"""Waldo's World YouTube monitor.

Fetches the latest videos of https://www.youtube.com/@WaldosWorld from the
channel RSS feed, compares them against the newest previously seen video
persisted between runs (a Mistral Files object, or a local file when
WALDOS_STATE_FILE is set for local dev/tests), and creates a Gmail draft
addressed to the channel owner when a newer video is found. Otherwise it does
nothing. Scheduled daily at 09:00 Europe/Helsinki via a workflow schedule.
"""

import base64
import json
import os
import xml.etree.ElementTree as ET
from datetime import timedelta

import mistralai.workflows as workflows
from pydantic import BaseModel

CHANNEL_ID = "UC6xNwCtnpXrWdFzDqn3lupg"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
STATE_FILE_NAME = "waldos-world-monitor-state.json"
GMAIL_RECIPIENT = "joey.eldorado@gmail.com"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"


class Video(BaseModel):
    video_id: str
    title: str
    published: str
    link: str


class MonitorInput(BaseModel):
    """Workflow input. `dry_run` computes everything but creates no draft;
    `force_draft` notifies about the newest video even if not new (testing)."""

    dry_run: bool = False
    force_draft: bool = False


class MonitorResult(BaseModel):
    checked_at: str
    latest: Video
    new_videos: list[Video]
    draft_id: str | None
    dry_run: bool


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"environment variable {name} is not set")
    return value


@workflows.activity(start_to_close_timeout=timedelta(seconds=60))
async def fetch_latest_videos() -> list[Video]:
    """Step 1: fetch the channel RSS feed and parse the latest videos."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}) as http:
        resp = await http.get(FEED_URL)
        resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"atom": ATOM, "yt": YT}
    videos: list[Video] = []
    for entry in root.findall("atom:entry", ns):
        vid = entry.find("yt:videoId", ns)
        title = entry.find("atom:title", ns)
        published = entry.find("atom:published", ns)
        link = entry.find("atom:link", ns)
        if vid is None or title is None or published is None or link is None:
            continue
        videos.append(
            Video(
                video_id=vid.text or "",
                title=(title.text or "").strip(),
                published=published.text or "",
                link=link.get("href") or "",
            )
        )
    videos.sort(key=lambda v: v.published, reverse=True)
    return videos


def _mistral_client():
    # The app's own client: on a managed deployment the platform mounts a
    # service-account token at MISTRAL_SA_TOKEN_PATH (MISTRAL_API_KEY is
    # reserved there); locally it falls back to MISTRAL_API_KEY.
    from utils.mistral import mistral_client

    return mistral_client()


@workflows.activity(start_to_close_timeout=timedelta(seconds=60))
async def load_state() -> dict:
    """Step 2a: read persisted state (last seen video) from Mistral Files, or
    from a local file when WALDOS_STATE_FILE is set (local dev and tests)."""
    local = os.environ.get("WALDOS_STATE_FILE", "").strip()
    if local:
        if os.path.exists(local):
            with open(local, encoding="utf-8") as fh:
                return json.load(fh)
        return {}
    client = _mistral_client()
    listed = client.files.list(search=STATE_FILE_NAME, source=["upload"])
    for f in listed.data or []:
        if f.file_name == STATE_FILE_NAME:
            content = client.files.download(file_id=f.id).content
            return json.loads(content.decode("utf-8"))
    return {}


@workflows.activity(start_to_close_timeout=timedelta(seconds=60), retry_policy_max_attempts=1)
async def save_state(state: dict) -> str:
    """Step 4: persist state between runs. Returns the update timestamp."""
    from datetime import UTC, datetime

    state = dict(state)
    state["updated_at"] = datetime.now(UTC).isoformat()
    payload = json.dumps(state).encode("utf-8")
    local = os.environ.get("WALDOS_STATE_FILE", "").strip()
    if local:
        with open(local, "w", encoding="utf-8") as fh:
            fh.write(payload.decode("utf-8"))
        return state["updated_at"]
    from mistralai.client.models.file import File

    client = _mistral_client()
    listed = client.files.list(search=STATE_FILE_NAME, source=["upload"])
    for f in listed.data or []:
        if f.file_name == STATE_FILE_NAME:
            client.files.delete(file_id=f.id)
    client.files.upload(file=File(file_name=STATE_FILE_NAME, content=payload), purpose="batch")
    return state["updated_at"]


@workflows.activity(start_to_close_timeout=timedelta(seconds=60), retry_policy_max_attempts=1)
async def create_gmail_draft(videos: list[Video]) -> str:
    """Step 3: create a Gmail draft via the Gmail REST API. Auth is OAuth for a
    private Gmail account: the GMAIL_OAUTH_REFRESH_TOKEN workspace secret (plus
    client id/secret) is exchanged here for a short-lived access token scoped to
    gmail.compose, acting as the account that granted consent. Returns draft ID."""
    import httpx

    token_request = {
        "grant_type": "refresh_token",
        "client_id": _env("GMAIL_OAUTH_CLIENT_ID"),
        "client_secret": _env("GMAIL_OAUTH_CLIENT_SECRET"),
        "refresh_token": _env("GMAIL_OAUTH_REFRESH_TOKEN"),
    }
    lines = ["New video" + ("s" if len(videos) > 1 else "") + " on Waldo's World:", ""]
    for v in videos:
        lines.append(f"- {v.title}")
        lines.append(f"  Published: {v.published}")
        lines.append(f"  Link: {v.link}")
    raw = (
        f"To: {GMAIL_RECIPIENT}\r\n"
        f"Subject: New video on Waldo's World\r\n"
        f"Content-Type: text/plain; charset=\"UTF-8\"\r\n"
        f"\r\n" + "\n".join(lines) + "\r\n"
    ).encode("utf-8")
    async with httpx.AsyncClient(timeout=30.0) as http:
        token_resp = await http.post(TOKEN_URL, data=token_request)
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        draft_resp = await http.post(
            GMAIL_DRAFTS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": {"raw": base64.urlsafe_b64encode(raw).decode("ascii")}},
        )
        draft_resp.raise_for_status()
        return draft_resp.json()["id"]


@workflows.workflow.define(
    name="waldos-world-monitor",
    workflow_display_name="Waldo's World YouTube monitor",
    workflow_description=(
        "Fetches the latest videos of youtube.com/@WaldosWorld, compares them with the "
        "newest previously seen video persisted between runs, and creates a Gmail draft "
        "with title, date and link when a newer video is found. Runs daily at 09:00 "
        "Europe/Helsinki via a workflow schedule."
    ),
)
class WaldosWorldMonitor:
    @workflows.workflow.entrypoint
    async def run(self, inp: MonitorInput) -> MonitorResult:
        videos = await fetch_latest_videos()
        if not videos:
            raise RuntimeError("no videos parsed from the channel feed")
        latest = videos[0]

        state = await load_state()
        last_published = state.get("last_published") or ""
        seen = set(state.get("seen") or [])
        new_videos = [v for v in videos if v.published > last_published and v.video_id not in seen]
        if inp.force_draft and not new_videos:
            new_videos = [latest]

        draft_id = None
        if new_videos and not inp.dry_run:
            draft_id = await create_gmail_draft(new_videos)

        seen.add(latest.video_id)
        for v in new_videos:
            seen.add(v.video_id)
        checked_at = await save_state(
            {
                "last_video_id": latest.video_id,
                "last_published": latest.published,
                "seen": sorted(seen)[-50:],
            }
        )
        return MonitorResult(
            checked_at=checked_at,
            latest=latest,
            new_videos=new_videos,
            draft_id=draft_id,
            dry_run=inp.dry_run,
        )
