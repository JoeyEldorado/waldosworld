// Waldo's World YouTube monitor — run via run_typescript (Vibe CLI).
// Steps: (1) fetch latest videos, (2) compare against persisted state,
// (3) create a Gmail draft if a newer video exists, (4) persist state.
// Set the file `.force-draft` next to state.json to force a draft on a run.

async function main() {
  const DIR = '/home/jds9/waldos-world-workflow/local-cli';
  const STATE_PATH = DIR + '/state.json';
  const FLAG_PATH = DIR + '/.force-draft';
  const RECIPIENT = 'joey.eldorado@gmail.com';

  // ---- Step 1: fetch latest videos from the channel feed ----
  const res = await tools.file_system.bash({
    command: 'python3 ' + DIR + '/workflow/fetch_videos.py',
    timeout_seconds: 60,
  });
  if (res.returncode !== 0) {
    return { ok: false, step: 'fetch', error: (res.stderr || res.stdout).slice(0, 800) };
  }
  const videos: Array<{ videoId: string; title: string; published: string; link: string }> =
    JSON.parse(res.stdout.trim().split('\n').pop()!);
  if (!videos.length) return { ok: false, step: 'parse', error: 'no videos parsed' };
  const newest = videos[0];

  // ---- Step 2: load persisted state and compare ----
  let state: any = { lastVideoId: null, lastPublished: null, seen: [], lastCheckAt: null };
  try {
    const f = await tools.file_system.read_file({ path: STATE_PATH });
    state = JSON.parse(f.content);
  } catch {
    /* first run: no state yet */
  }
  let forced = false;
  try {
    await tools.file_system.read_file({ path: FLAG_PATH });
    forced = true;
  } catch {
    /* no force flag */
  }

  const isFirstRun = !state.lastPublished;
  const newVideos = isFirstRun
    ? []
    : videos.filter((v) => v.published > state.lastPublished && !(state.seen || []).includes(v.videoId));
  const notifyList = newVideos.length > 0 ? newVideos : forced ? [newest] : [];
  const shouldNotify = notifyList.length > 0;

  // ---- Step 3: create Gmail draft if a newer video was found ----
  let draft: unknown = null;
  if (shouldNotify) {
    const lines = notifyList
      .map((v) => '- ' + v.title + '\n  Published: ' + v.published + '\n  Link: ' + v.link)
      .join('\n');
    const body =
      'New video' + (notifyList.length > 1 ? 's' : '') + " on Waldo's World:\n\n" + lines + '\n';
    draft = await tools.connector_gmail.create_draft({
      to: [RECIPIENT],
      subject: "New video on Waldo's World",
      body,
    });
  }

  // ---- Step 4: persist state between runs ----
  state.lastVideoId = newest.videoId;
  state.lastPublished = newest.published;
  state.seen = [newest.videoId, ...((state.seen || []) as string[]).filter((id) => id !== newest.videoId)].slice(0, 50);
  state.lastCheckAt = new Date().toISOString();
  await tools.file_system.write_file({ path: STATE_PATH, content: JSON.stringify(state, null, 2) });

  return {
    ok: true,
    firstRun: isFirstRun,
    latest: newest,
    newVideosFound: newVideos.length,
    notified: shouldNotify,
    draft,
    lastCheckAt: state.lastCheckAt,
  };
}
