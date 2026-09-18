#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FaceFusion lip_syncer 冒烟：歌手肖像图 → 3s 视频 → 对口型（会首跑下载 ~500MB 模型）。
python scripts/smoke_lipsync.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from echoloom.config import get_settings  # noqa: E402
from echoloom.lipsync import run_lip_sync  # noqa: E402

SMOKE = ROOT / "output" / "smoke"


def main() -> int:
    s = get_settings()
    SMOKE.mkdir(parents=True, exist_ok=True)
    img = SMOKE / "smoke_t2i_00001_.png"
    if not img.exists():
        print("先跑 python scripts/smoke_comfy.py t2i 生成肖像")
        return 1
    # 肖像 → 3s 24fps 视频；另出 3s 正弦音频作为对口型源（真实流程用 Demucs vocals 分轨）
    target = SMOKE / "lipsync_target.mp4"
    audio = SMOKE / "lipsync_audio.wav"
    subprocess.run(
        [s.ffmpeg_bin, "-y", "-v", "error", "-loop", "1", "-framerate", "24", "-i", str(img),
         "-vf", "scale=768:1024", "-t", "3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(target)],
        check=True)
    subprocess.run(
        [s.ffmpeg_bin, "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-c:a", "pcm_s16le", str(audio)],
        check=True)
    print(f"target video: {target}", flush=True)

    out = SMOKE / "lipsync_out.mp4"
    run_lip_sync(audio, target, out, settings=s, timeout=1800)
    print(f"OK -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
