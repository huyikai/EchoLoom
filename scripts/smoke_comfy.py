#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M1 冒烟：python scripts/smoke_comfy.py <t2i|music|i2v> [args...]

t2i   一张 Z-Image 测试图（~30s）
music 一段 Music3 冒烟曲（默认 30s，~1-3min）
i2v   一段 H3 图生视频（需要先 t2i，~2-4min）
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from echoloom.comfy import ComfyClient, ComfyError  # noqa: E402
from echoloom.workflows import (  # noqa: E402
    frames_for,
    h3_i2v_workflow,
    music3_workflow,
    zimage_workflow,
)

OUT = ROOT / "output" / "smoke"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "t2i"
    c = ComfyClient()
    stats = c.health()
    print(f"ComfyUI {stats['system']['comfyui_version']} up, queue={c.queue_size()}", flush=True)
    t0 = time.time()

    if stage == "t2i":
        wf = zimage_workflow(
            "cinematic portrait of a young woman standing in a sunlit courtyard, "
            "soft natural light, film photography, shallow depth of field, 85mm lens",
            width=768, height=1024, seed=42, prefix="echoloom_smoke/t2i",
        )
        files = c.run(wf, poll=2.0, timeout=600)
        for f in files:
            dest = c.fetch(f, OUT / f"smoke_{f.filename}")
            print(f"OK image -> {dest} ({time.time()-t0:.0f}s)", flush=True)
        return 0

    if stage == "music":
        sec = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
        caption = (
            "Global Metadata: Uplifting Mandarin city-pop, live band recording in a warm studio, "
            f"100 BPM, 4/4, C major, about {int(sec)} seconds. Not a dry studio take, gentle room ambience, wide stereo.\n\n"
            "Vocal Details: Every line fully SUNG, never spoken. Young Mandarin Chinese female vocal, "
            "clear bright tone, precise articulation, natural breaths, real human singing texture, "
            "no spoken word, no rap, no robotic AI voice.\n\n"
            "Arrangement: Electric piano foundation, soft drums, warm bass, synth pads, guitar licks in chorus. "
            "No over-compression, preserve live dynamics. 48kHz hi-fi fidelity."
        )
        lyrics = (
            "[Intro]\n[Instrumental]\n\n[Verse]\n夜色穿过旧街灯\n影子替我沉默\n\n"
            f"[Chorus]\n让风把名字吹散\n吹散也不回头\n\n[Outro]\n天亮以前到家\n"
        )
        wf = music3_workflow(caption, lyrics, seed=7, max_duration=sec,
                             prefix="echoloom_smoke/music")
        files = c.run(wf, poll=3.0, timeout=1800)
        for f in files:
            dest = c.fetch(f, OUT / f"smoke_{f.filename}")
            print(f"OK audio -> {dest} ({time.time()-t0:.0f}s)", flush=True)
        return 0

    if stage == "i2v":
        img = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT / "smoke_t2i_00001_.png"
        if not img.exists():
            print(f"先跑 t2i 生成 {img}", flush=True)
            return 1
        up = c.upload_image(img)
        print(f"uploaded -> {up}", flush=True)
        sec = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
        wf = h3_i2v_workflow(
            up, "Slow dolly forward, the young woman looks up and smiles gently, "
                "dust drifting in sunlight, cinematic, steady camera.",
            seed=11, frames=frames_for(sec), prefix="echoloom_smoke/i2v",
        )
        files = c.run(wf, poll=5.0, timeout=3600)
        for f in files:
            dest = c.fetch(f, OUT / f"smoke_{f.filename}")
            print(f"OK video -> {dest} ({time.time()-t0:.0f}s)", flush=True)
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ComfyError as e:
        print(f"COMFY ERROR: {e}", flush=True)
        sys.exit(3)
