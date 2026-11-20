#!/usr/bin/env python3
"""Step 1 of the Waldo's World monitor: fetch the channel RSS feed and print
the latest videos as JSON (videoId, title, published, link), newest first."""
import html
import json
import re
import subprocess
import sys

CHANNEL_ID = "UC6xNwCtnpXrWdFzDqn3lupg"  # @WaldosWorld
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"


def main() -> None:
    proc = subprocess.run(
        ["curl", "-s", "-m", "15", "-A", "Mozilla/5.0", FEED_URL],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        print("fetch failed", file=sys.stderr)
        sys.exit(1)
    xml = proc.stdout
    entries = re.findall(r"<entry>.*?</entry>", xml, re.S)
    videos = []
    for e in entries:
        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", e)
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        pub = re.search(r"<published>([^<]+)</published>", e)
        link = re.search(r'<link rel="alternate" href="([^"]+)"', e)
        if all([vid, title, pub, link]):
            videos.append(
                {
                    "videoId": vid.group(1),
                    "title": html.unescape(title.group(1)).strip(),
                    "published": pub.group(1),
                    "link": link.group(1),
                }
            )
    videos.sort(key=lambda v: v["published"], reverse=True)
    json.dump(videos, sys.stdout)


if __name__ == "__main__":
    main()
