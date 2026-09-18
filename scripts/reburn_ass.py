#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重烧字幕：重跑 ASR 对齐 + ASS 生成 + 烧字（复用已有 body/master，不重跑生成阶段）。

python scripts/reburn_ass.py <project_id>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from echoloom.align import align_lines  # noqa: E402
from echoloom.asr import transcribe_wav  # noqa: E402
from echoloom.ass_style import AssStyle, build_ass  # noqa: E402
from echoloom.config import get_settings  # noqa: E402
from echoloom.mv import burn_cmd, has_nvenc, probe_sec, run  # noqa: E402
from echoloom.state import ProjectState  # noqa: E402


def main() -> int:
    pid = sys.argv[1]
    s = get_settings()
    d = s.output_root / pid
    state = ProjectState.load(d / "state.json")

    lyrics = state.gates["lyrics"].approved_payload
    song = d / "audio" / state.gates["audio"].approved_payload
    vocals = next((d / "stems" / "htdemucs").glob("*/vocals.wav"))
    body = d / "final" / "segs" / "body.mp4"
    master = d / "final" / "master.flac"
    assert lyrics and song.exists() and vocals.exists() and body.exists() and master.exists()

    song_dur = probe_sec(s.ffprobe_bin, song)
    print(f"transcribing {vocals.name} ...", flush=True)
    asr = transcribe_wav(vocals, asr_dir=s.qwen3_asr_dir, aligner_dir=s.qwen3_aligner_dir,
                         language=state.language, hotwords=lyrics.replace("\n", " ")[:400])
    lines = [ln for ln in lyrics.replace("\r\n", "\n").split("\n")
             if ln.strip() and not ln.strip().startswith("[")]
    timed = align_lines(lines, asr["words"], total_sec=song_dur)
    style = AssStyle(**(state.ass_style or {}))
    ass_path = d / "ass" / "final.ass"
    ass_path.write_text(build_ass(style, timed, play_res_x=s.width, play_res_y=s.height,
                                  title=state.title), encoding="utf-8")
    (d / "ass" / "timed.json").write_text(json.dumps(timed, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"ASS ok: {len(timed)} 行", flush=True)

    final = d / "final" / "mv.mp4"
    run(burn_cmd(s.ffmpeg_bin, body, master, final, ass_path=ass_path, title=state.title,
                 total=song_dur, w=s.width, h=s.height, nvenc=has_nvenc(s.ffmpeg_bin)))
    print(f"OK reburn: {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
