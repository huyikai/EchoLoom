"""全局配置：.env / 环境变量 > 默认值。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    zhipu_api_key: str = ""
    llm_model: str = "glm-4.6"

    comfyui_url: str = "http://127.0.0.1:8188"
    facefusion_root: str = "D:/develop/facefusion"
    qwen3_asr_dir: str = "D:/develop/vrs-runtime/models/qwen3-asr"
    qwen3_aligner_dir: str = "D:/develop/vrs-runtime/models/qwen3-forcedaligner"
    ffmpeg_bin: str = "ffmpeg"

    host: str = "127.0.0.1"
    port: int = 8199

    default_song_sec: int = 180
    fps: int = 24
    width: int = 1344
    height: int = 768
    language: str = "zh"
    portrait_candidates: int = 3

    @property
    def output_root(self) -> Path:
        return ROOT / "output"


@lru_cache
def get_settings() -> Settings:
    return Settings()
