"""Local web UI for ClipForge / shorts_maker.

Runs entirely on your machine. Open http://localhost:5000 in a browser, paste a
story, pick a voice, click "Generate Video". It runs the same make_short.py
pipeline (no Reddit) and shows the finished MP4 right in the page.

Start with:  .venv/bin/python web_app.py
"""

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

# TikTok voices supported by the TTS backend (mirrors ShortsMaker/utils/get_tts.py)
VOICES = [
    ("en_us_001", "US Female 1"),
    ("en_us_002", "US Female 2"),
    ("en_us_006", "US Male 1"),
    ("en_us_010", "US Male 2"),
    ("en_uk_001", "UK Male 1"),
    ("en_uk_003", "UK Male 2"),
    ("en_au_002", "AU Male"),
    ("en_female_emotional", "Peaceful"),
]

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
app = Flask(__name__)

# single-job-at-a-time state (CPU rendering is heavy; don't run two at once)
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _run_job(job_id: str, story: str, voice: str) -> None:
    job = _jobs[job_id]
    story_file = ROOT / f"web_{job_id}.txt"
    story_file.write_text(story, encoding="utf-8")
    log_path = Path(f"/tmp/clipforge_web_{job_id}.log")
    job["log_path"] = str(log_path)
    job["output"] = f"web_{job_id}.mp4"

    env = dict(os.environ)
    env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"

    cmd = [sys.executable, str(ROOT / "make_short.py"), str(story_file)]
    if voice:
        cmd.append(voice)

    job["status"] = "running"
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)

    out = ASSETS / job["output"]
    if proc.returncode == 0 and out.exists():
        job["status"] = "done"
    else:
        job["status"] = "error"
    job["returncode"] = proc.returncode


def _log_tail(path: str, n: int = 14) -> str:
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return ""
    # strip ANSI colour codes and the noisy ffmpeg progress carriage-return spam
    clean = []
    for ln in lines:
        ln = ln.replace("\x1b[32m", "").replace("\x1b[31m", "").replace("\x1b[33m", "")
        ln = ln.replace("\x1b[36m", "").replace("\x1b[0m", "").replace("\x1b[1m", "")
        if ln.strip().startswith("size=") or ln.strip().startswith("frame="):
            continue
        clean.append(ln)
    return "\n".join(clean[-n:])


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClipForge — Make a Short</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         background:#0d1117; color:#e6edf3; display:flex; justify-content:center; }
  .wrap { width:100%; max-width:720px; padding:32px 20px 60px; }
  h1 { font-size:26px; margin:0 0 4px; }
  .sub { color:#8b949e; margin:0 0 24px; font-size:14px; }
  label { display:block; font-weight:600; margin:18px 0 6px; font-size:14px; }
  textarea, select { width:100%; background:#161b22; color:#e6edf3; border:1px solid #30363d;
         border-radius:10px; padding:12px 14px; font-size:15px; }
  textarea { min-height:170px; resize:vertical; }
  button { margin-top:20px; width:100%; padding:13px; font-size:16px; font-weight:600;
         color:#fff; background:#238636; border:0; border-radius:10px; cursor:pointer; }
  button:disabled { background:#30363d; color:#8b949e; cursor:not-allowed; }
  #status { margin-top:24px; }
  .badge { display:inline-block; padding:3px 10px; border-radius:20px; font-size:13px; font-weight:600; }
  .running { background:#1f6feb33; color:#79c0ff; }
  .done { background:#23863633; color:#7ee787; }
  .error { background:#da363333; color:#ff7b72; }
  pre { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:12px;
        font-size:12px; overflow:auto; max-height:240px; white-space:pre-wrap; color:#9da7b3; }
  video { width:100%; border-radius:12px; margin-top:16px; background:#000; }
  a.dl { color:#79c0ff; }
</style></head>
<body><div class="wrap">
  <h1>🎬 ClipForge</h1>
  <p class="sub">Paste a story, pick a voice, generate a short. Runs locally on your Mac.</p>

  <label for="story">Your story</label>
  <textarea id="story" placeholder="Paste or type the story to narrate..."></textarea>

  <label for="voice">Voice</label>
  <select id="voice">__VOICES__</select>

  <button id="go" onclick="generate()">Generate Video</button>

  <div id="status"></div>
</div>
<script>
let poll = null;
async function generate() {
  const story = document.getElementById('story').value.trim();
  if (!story) { alert('Please enter a story first.'); return; }
  const voice = document.getElementById('voice').value;
  document.getElementById('go').disabled = true;
  const r = await fetch('/generate', {method:'POST', headers:{'Content-Type':'application/json'},
                                       body: JSON.stringify({story, voice})});
  const j = await r.json();
  if (j.error) { alert(j.error); document.getElementById('go').disabled = false; return; }
  watch(j.job);
}
function watch(job) {
  if (poll) clearInterval(poll);
  poll = setInterval(async () => {
    const r = await fetch('/status/' + job);
    const s = await r.json();
    let html = '<span class="badge ' + s.status + '">' + s.status.toUpperCase() + '</span>';
    if (s.status === 'running') html += ' &nbsp;rendering — this takes a few minutes…';
    if (s.log) html += '<pre>' + s.log.replace(/</g,'&lt;') + '</pre>';
    if (s.status === 'done') {
      clearInterval(poll);
      document.getElementById('go').disabled = false;
      html += '<video controls autoplay src="/video/' + job + '"></video>';
      html += '<p><a class="dl" href="/video/' + job + '" download>⬇ Download MP4</a></p>';
    }
    if (s.status === 'error') {
      clearInterval(poll);
      document.getElementById('go').disabled = false;
      html += '<p style="color:#ff7b72">Render failed — see log above.</p>';
    }
    document.getElementById('status').innerHTML = html;
  }, 2500);
}
</script>
</body></html>"""


@app.route("/")
def index() -> Response:
    opts = "".join(f'<option value="{v}">{label}</option>' for v, label in VOICES)
    return Response(PAGE.replace("__VOICES__", opts), mimetype="text/html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)
    story = (data.get("story") or "").strip()
    voice = data.get("voice") or ""
    if not story:
        return jsonify(error="Story is empty."), 400
    with _lock:
        if any(j["status"] == "running" for j in _jobs.values()):
            return jsonify(error="A video is already rendering. Please wait for it to finish."), 409
        job_id = uuid.uuid4().hex[:10]
        _jobs[job_id] = {"status": "queued", "created": time.time()}
    threading.Thread(target=_run_job, args=(job_id, story, voice), daemon=True).start()
    return jsonify(job=job_id)


@app.route("/status/<job_id>")
def status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify(status=job["status"], log=_log_tail(job.get("log_path", "")))


@app.route("/video/<job_id>")
def video(job_id: str):
    job = _jobs.get(job_id)
    if not job or job.get("status") != "done":
        abort(404)
    return send_file(ASSETS / job["output"], mimetype="video/mp4")


if __name__ == "__main__":
    print("ClipForge web UI -> http://localhost:5050")
    app.run(host="127.0.0.1", port=5050, threaded=True)
