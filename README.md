# waldos-world-workflow

Monitors the YouTube channel [@WaldosWorld](https://www.youtube.com/@WaldosWorld/videos)
and creates a Gmail draft for the owner when a new video appears.

Two implementations live here:

- `apps/worker/` — the **Mistral Workflows** app (the one deployed to Studio / console.mistral.ai).
  `apps/worker/src/worker/workflows/waldos_world_monitor.py` defines the `waldos-world-monitor`
  workflow: fetch channel RSS feed → compare with persisted state → create Gmail draft if a
  newer video exists → persist state. Tests: `apps/worker/tests/test_waldos_world_monitor.py`
  (local no-infra mode: `python -m pytest tests/test_waldos_world_monitor.py` from `apps/worker`).
- `local-cli/` — the standalone Vibe-CLI version (RSS fetch + `state.json` + `connector_gmail`
  draft + a 09:00 Europe/Helsinki cron loop), kept for reference.

## Studio workflow: how it works

| Step | Where | What |
|---|---|---|
| 1. Fetch | activity `fetch_latest_videos` | GET `https://www.youtube.com/feeds/videos.xml?channel_id=UC6xNwCtnpXrWdFzDqn3lupg` (the real channel ID behind `@WaldosWorld`), parse entries → `{video_id, title, published, link}` |
| 2. Compare | activity `load_state` + entrypoint | state persisted as a Mistral **File** named `waldos-world-monitor-state.json` (`last_video_id`, `last_published`, `seen[]`); new = `published > last_published` and not seen |
| 3. Notify | activity `create_gmail_draft` | Gmail REST API, service-account JWT (workspace secret `gmail_service_account_json`, domain-wide delegation as `joey.eldorado@gmail.com`, scope `gmail.compose`), subject `New video on Waldo's World` with title/date/link |
| 4. Persist | activity `save_state` | rewrites the state File; runs even on `dry_run` (used to seed the baseline) |

Input: `{"dry_run": bool = false, "force_draft": bool = false}` — `dry_run` computes everything
but creates no draft (run once with `{"dry_run": true}` right after deployment to seed the
baseline so the schedule only fires on genuinely new videos).

## Deploy (managed deployment)

1. Push this repo to GitHub (branch + PR per team convention).
2. In console.mistral.ai → **Secrets**, create workspace secrets:
   - `mistral_api_key` — a Mistral API key value (worker calls the Mistral Files API for state).
   - Gmail auth for a **private** Gmail account uses OAuth, not a service account
     (domain-wide delegation needs Workspace). Create a Google Cloud OAuth client
     (Desktop app type, Gmail API enabled), run the one-time consent flow as
     `joey.eldorado@gmail.com` with scope `gmail.compose` and `access_type=offline`
     to get a refresh token, then store three secrets:
     `gmail_oauth_client_id`, `gmail_oauth_client_secret`, `gmail_oauth_refresh_token`.
     The workflow activity exchanges the refresh token for a short-lived access token
     and calls the Gmail REST API — no user present needed, so schedules work.
3. Deploy via the Mistral MCP server (`deploy_workflow_deployment`):
   `github_url=<repo>`, `revision=<pushed commit SHA>`, `deployment_name="waldos-world-monitor"`,
   `build_directory="."`, `dockerfile_path="deploy/docker/Dockerfile.worker"`,
   `secrets=[{secret_name: "mistral_api_key", env_var_name: "MISTRAL_API_KEY"},
             {secret_name: "gmail_oauth_client_id", env_var_name: "GMAIL_OAUTH_CLIENT_ID"},
             {secret_name: "gmail_oauth_client_secret", env_var_name: "GMAIL_OAUTH_CLIENT_SECRET"},
             {secret_name: "gmail_oauth_refresh_token", env_var_name: "GMAIL_OAUTH_REFRESH_TOKEN"}]`.
4. `wait_workflow_deployment_ready` until the revision serves, then `execute_workflow` once with
   `{"dry_run": true}` to verify and seed state.
5. `create_workflow_schedule`: `workflow_identifier="waldos-world-monitor"`,
   `schedule={input: {}, calendars: [{hour: [{start: 9}], minute: [{start: 0}]}],
   time_zone_name: "Europe/Helsinki"}` — daily 09:00 Helsinki.

The workflow then appears in console.mistral.ai → **Workflows** and the schedule in its
schedules list; executions run on the managed deployment.
