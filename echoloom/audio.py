"""人声分离（Demucs）与母带（loudnorm 两遍）。"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .mv import FfmpegError, master_pass1_cmd, master_pass2_cmd, parse_loudnorm_measures, run

DEMUCS_MODEL = "htdemucs"


def separate_vocals(python: str, song: Path, out_dir: Path, *,
                    model: str = DEMUCS_MODEL, two_stems: bool = True,
                    timeout: float = 3600.0) -> dict[str, Path]:
    """Demucs 分轨。two_stems=True 只出 vocals/no vocals；False 出全部 4 轨。

    子进程隔离，规避 torchaudio 新旧 API 兼容问题。
    返回 {"vocals": path, "no_vocals": path, "other": {stem: path}}。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [python, "-m", "demucs", "-n", model, "-o", str(out_dir)]
    if two_stems:
        cmd.append("--two-stems=vocals")
    cmd.append(str(song))
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if p.returncode != 0:
        raise FfmpegError(f"demucs 失败: {(p.stderr or p.stdout)[-1200:]}")
    # demucs 输出结构: <out_dir>/<model>/<song_stem_name>/*.wav
    stem_dir = next((out_dir / model).glob(f"*{song.stem}*"))
    result: dict[str, Path] = {"other": {}}
    for wav in sorted(stem_dir.glob("*.wav")):
        name = wav.stem.lower()
        if name == "vocals":
            result["vocals"] = wav
        elif name in ("no_vocals", "accompaniment", "no_vocals.wav"):
            result["no_vocals"] = wav
        else:
            result["other"][name] = wav
    if "vocals" not in result:
        raise FfmpegError(f"demucs 输出缺少 vocals: {list(stem_dir.glob('*.wav'))}")
    return result


def master_audio(ff: str, song: Path, dest: Path) -> tuple[Path, dict[str, float]]:
    """两遍 loudnorm → -14 LUFS / TP -1.5 / LRA 11，48kHz flac。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    p1 = subprocess.run(master_pass1_cmd(ff, song), capture_output=True,
                        text=True, encoding="utf-8", errors="replace", timeout=1800)
    if p1.returncode != 0:
        raise FfmpegError(f"loudnorm 测量失败: {p1.stderr[-500:]}")
    measures = parse_loudnorm_measures(p1.stderr)
    run(master_pass2_cmd(ff, song, dest, measures))
    return dest, measures
