# Waldo's World YouTube Monitor

Monitors https://www.youtube.com/@WaldosWorld/videos and emails you (as a Gmail draft)
when a new video appears.

## How it works

1. **Fetch** — pulls the channel RSS feed
   (`https://www.youtube.com/feeds/videos.xml?channel_id=UC6xNwCtnpXrWdFzDqn3lupg`)
   via `workflow/fetch_videos.py` and parses out each video's `videoId`, `title`,
   `published` (ISO 8601) and `link`.
2. **Compare** — reads `state.json` (persisted between runs) and selects videos with
   `published` newer than `state.lastPublished` whose `videoId` is not in `state.seen`.
3. **Notify** — if any are found, creates a Gmail draft to `joey.eldorado@gmail.com`
   with subject `New video on Waldo's World` and a body listing title, date and link.
   Otherwise does nothing.
4. **Persist** — writes the newest `videoId`/`published`, the seen-ID list and the
   check timestamp back to `state.json`.

On the very first run there is no previous state, so the current newest video is stored
as the baseline and no draft is sent. Touch `.force-draft` to force a draft on a run
(useful for testing).

## Files

- `workflow/monitor.ts` — the workflow program (run with `run_typescript`; defines `main()`)
- `workflow/fetch_videos.py` — step 1, feed fetcher/parser (used by `monitor.ts`)
- `state.json` — persisted state, created on first run
- `studio/workflow.json` — portable workflow manifest (steps + schedule) for import into Mistral Studio

## Schedule

Registered with the Vibe cron scheduler as `0 9 * * *` (host timezone is Europe/Helsinki,
so this fires daily at 09:00 Helsinki time, DST-aware). The scheduled prompt reads
`workflow/monitor.ts` and executes it via `run_typescript`.

## Manual run

Read `workflow/monitor.ts` and execute its code with `run_typescript`. The returned JSON
reports `newVideosFound`, `notified`, and the created draft.
