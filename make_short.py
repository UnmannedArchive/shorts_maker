"""Make a short from your OWN story text — no Reddit needed.

Usage:
    .venv/bin/python make_short.py                      # reads story.txt
    .venv/bin/python make_short.py path/to/story.txt    # reads a specific file
    .venv/bin/python make_short.py story.txt en_us_006  # optional TikTok voice seed

Output: assets/<story-filename>.mp4
"""

import os
import sys
from pathlib import Path

import certifi
import yaml

# local patch: macOS python.org builds ship without CA certs, so model downloads
# via urllib/torchaudio fail with CERTIFICATE_VERIFY_FAILED. Point SSL at the
# certifi CA bundle already in the venv (full certificate verification stays on).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from ShortsMaker import MoviepyCreateVideo, ShortsMaker

SETUP_FILE = "setup.yml"


def main() -> None:
    story_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("story.txt")
    voice = sys.argv[2] if len(sys.argv) > 2 else None  # None -> random TikTok voice

    if not story_file.exists():
        raise SystemExit(f"Story file not found: {story_file}\nCreate it, paste your story, rerun.")

    script = story_file.read_text(encoding="utf-8").strip()
    if not script:
        raise SystemExit(f"{story_file} is empty — paste your story into it and rerun.")

    with open(SETUP_FILE) as f:
        cfg = yaml.safe_load(f)
    cache = cfg["cache_dir"]
    audio_file = f"{cache}/{cfg['audio']['output_audio_file']}"
    script_file = f"{cache}/{cfg['audio']['output_script_file']}"
    output_path = f"assets/{story_file.stem}.mp4"

    print(f"Story: {story_file}  ({len(script.split())} words)")

    maker = ShortsMaker(SETUP_FILE)

    print("Generating narration (TikTok TTS)...")
    if not maker.generate_audio(
        source_txt=script,
        output_audio=audio_file,
        output_script_file=script_file,
        seed=voice,
    ):
        maker.quit()
        raise SystemExit("TTS failed — check the log output above.")

    print("Transcribing for word-level captions (WhisperX)...")
    maker.generate_audio_transcript(
        source_audio_file=audio_file,
        source_text_file=script_file,
    )
    maker.quit()

    print("Rendering video (this is the slow part)...")
    create_video = MoviepyCreateVideo(config_file=SETUP_FILE)
    create_video(output_path=output_path)
    create_video.quit()

    print(f"\nDone -> {output_path}")


if __name__ == "__main__":
    main()
