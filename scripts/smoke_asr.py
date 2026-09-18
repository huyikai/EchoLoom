#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ASR 冒烟：对 output/smoke 的音乐/人声转写 + 字级时间戳。

python scripts/smoke_asr.py [音频路径] [歌词热词文件]
默认 output/smoke/smoke_music_00001.flac
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from echoloom.asr import transcribe_wav  # noqa: E402
from echoloom.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    audio = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output/smoke/smoke_music_00001.flac"
    if not audio.exists():
        print(f"音频不存在: {audio}")
        return 1
    hotwords = None
    if len(sys.argv) > 2:
        hotwords = Path(sys.argv[2]).read_text(encoding="utf-8")[:400]
    print(f"transcribing {audio.name} ...", flush=True)
    result = transcribe_wav(
        audio,
        asr_dir=s.qwen3_asr_dir,
        aligner_dir=s.qwen3_aligner_dir,
        language=s.language,
        hotwords=hotwords,
    )
    out = ROOT / "output/smoke/asr_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"language={result['language']} duration={result['duration']}s words={len(result['words'])}")
    print("TEXT:", result["text"][:200])
    print("first words:", result["words"][:6])
    print(f"saved -> {out}")
    return 0 if result["words"] else 2


if __name__ == "__main__":
    sys.exit(main())
