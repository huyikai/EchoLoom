"""FaceFusion lip_syncer headless 调用。

FaceFusion 3.x 纯 onnxruntime；跑在 EchoLoom venv（安装 facefusion extra），
运行时把 torch 的 CUDA DLL 目录注入 PATH 供 onnxruntime-gpu 找到 cuDNN。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import ROOT, Settings
from .mv import FfmpegError


def facefusion_python(settings: Settings) -> Path:
    return ROOT / ".venv" / "Scripts" / "python.exe"


def lip_sync_cmd(source_audio: Path, target_video: Path, dest: Path, *,
                 settings: Settings, model: str = "wav2lip_gan_96") -> tuple[list[str], dict[str, str]]:
    """返回 (命令, 环境变量覆盖)。"""
    ff_root = Path(settings.facefusion_root)
    py = facefusion_python(settings)
    cmd = [
        str(py), str(ff_root / "facefusion.py"), "headless-run",
        "--processors", "lip_syncer",
        "--lip-syncer-model", model,
        "--source-paths", str(source_audio),   # 本 fork: source 复数 / target、output 单数
        "--target-path", str(target_video),
        "--output-path", str(dest),
        "--execution-providers", "cuda",
        "--log-level", "warn",
    ]
    env = os.environ.copy()
    # onnxruntime-gpu 需要的 CUDA/cuDNN DLL 在 torch 包里
    for extra in ("torch\\lib",):
        d = ROOT / ".venv" / "Lib" / "site-packages" / extra
        if d.is_dir():
            env["PATH"] = str(d) + os.pathsep + env.get("PATH", "")
    return cmd, env


def run_lip_sync(source_audio: Path, target_video: Path, dest: Path, *,
                 settings: Settings, model: str = "wav2lip_gan_96",
                 timeout: float = 3600.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd, env = lip_sync_cmd(source_audio, target_video, dest, settings=settings, model=model)
    p = subprocess.run(cmd, env=env, cwd=str(settings.facefusion_root),  # FF 用相对路径解析 processors/模型
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if p.returncode != 0 or not dest.exists():
        raise FfmpegError(
            f"lip_syncer 失败 (rc={p.returncode}):\n{(p.stdout + p.stderr)[-1500:]}")
    return dest
