#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重烧字幕：歌词强制对齐 + ASS(标题卡/前奏♪/karaoke) + 烧字（复用已有 body/master）。

python scripts/reburn_ass.py <project_id>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from echoloom.ass_style import AssStyle  # noqa: E402
from echoloom.config import get_settings  # noqa: E402
from echoloom.mv import burn_cmd, has_nvenc, probe_sec, run  # noqa: E402
from echoloom.state import ProjectState  # noqa: E402
from echoloom.subtitles import build_project_ass, force_align_lyrics  # noqa: E402


def main() -> int:
    pid = sys.argv[1]
    s = get_settings()
    d = s.output_root / pid
    state = ProjectState.load(d / "state.json")

    lyrics = state.gates["lyrics"].approved_payload
    song = d / "audio" / state.gates["audio"].approved_payload
    vocals = next((d / "stems" / "htdemucs").glob("*/vocals.wav"))
    body = d / "final" / "segs_v2" / "body.mp4"
    if not body.exists():
        body = d / "final" / "segs" / "body.mp4"
    master = d / "final" / "master.flac"
    assert lyrics and song.exists() and vocals.exists() and body.exists() and master.exists()

    song_dur = probe_sec(s.ffprobe_bin, song)
    print(f"force-aligning lyrics against {vocals.name} ...", flush=True)
    timed = force_align_lyrics(vocals, lyrics,
                               asr_dir=s.qwen3_asr_dir, aligner_dir=s.qwen3_aligner_dir,
                               language=state.language)
    print(f"aligned lines: {len(timed)} | first: {timed[0]['start']:.1f}s last-end: {timed[-1]['end']:.1f}s",
          flush=True)
    style = AssStyle(**(state.ass_style or {}))
    ass_path = d / "ass" / "final.ass"
    ass_path.write_text(
        build_project_ass(style, timed, title=state.title,
                          play_res_x=s.width, play_res_y=s.height), encoding="utf-8")
    import json
    (d / "ass" / "timed.json").write_text(
        json.dumps(timed, ensure_ascii=False, indent=1), encoding="utf-8")

    final = d / "final" / "mv_v2.mp4"
    run(burn_cmd(s.ffmpeg_bin, body, master, final, ass_path=ass_path,
                 title=None, total=song_dur, w=s.width, h=s.height,
                 nvenc=has_nvenc(s.ffmpeg_bin)))
    print(f"OK reburn: {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
