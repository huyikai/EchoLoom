"""Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B 本地推理（移植自 video-remake-studio/src/vrs/asr.py，
针对本机 D:/develop/vrs-runtime/models 权重与 transformers 5.x）。

注意：传 numpy 给 processor，不要传 wav 路径（transformers 5 在 Windows 会走 torchcodec 直接炸）。
"""
from __future__ import annotations

import gc
import os
import re
import wave
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "zh"
_MAX_CHUNK_SEC = 240.0

_SPACE = re.compile(r"\s+")
_REPEAT_CHAR = re.compile(r"(.)\1{5,}")
_REPEAT_PAREN = re.compile(r"[)）]{4,}")
_PUNCT_END = "。！？!?，,、；;．."


def looks_like_hallucination(text: str) -> bool:
    """静音/片尾/复读时的典型垃圾转写。"""
    t = (text or "").strip()
    if not t:
        return True
    if _REPEAT_PAREN.search(t) or _REPEAT_CHAR.search(t):
        return True
    compact = _SPACE.sub("", t)
    if len(compact) >= 8 and len(set(compact)) <= 2:
        return True
    if len(compact) >= 24:
        for size in range(8, 21):
            if len(compact) < size * 3:
                break
            if compact.count(compact[:size]) >= 3:
                return True
    cjk = sum(1 for ch in t if "一" <= ch <= "\u9fff")
    latin = sum(1 for ch in t if ch.isascii() and ch.isalpha())
    if latin >= 10 and cjk < 3:
        return True
    return False


def _cublas_available() -> bool:
    try:
        import torch

        lib = Path(torch.__file__).resolve().parent / "lib"
        if (lib / "cublas64_12.dll").is_file() or (lib / "cublas64_13.dll").is_file():
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
            return True
    except Exception:
        pass
    return False


def load_wav_16k(path: Path) -> tuple[Any, int]:
    """任意音频 → 16k mono float32 numpy（经 ffmpeg 转 wav 再读）。"""
    import numpy as np
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp_path)],
        check=True, capture_output=True,
    )
    try:
        with wave.open(str(tmp_path), "rb") as handle:
            sr = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        tmp_path.unlink(missing_ok=True)
    return data, sr


def _audio_chunks(audio: Any, sr: int, *, max_sec: float = _MAX_CHUNK_SEC):
    max_n = int(max_sec * sr)
    if len(audio) <= max_n:
        yield 0.0, audio
        return
    hop = int((max_sec - 0.4) * sr)
    start = 0
    while start < len(audio):
        end = min(len(audio), start + max_n)
        yield start / sr, audio[start:end]
        if end >= len(audio):
            break
        start += hop


def transcribe_wav(
    wav: Path,
    *,
    asr_dir: str | Path,
    aligner_dir: str | Path,
    language: str = DEFAULT_LANGUAGE,
    hotwords: str | None = None,
    device: str = "auto",
) -> dict[str, Any]:
    """转写 + 字级时间戳。返回 {text, words:[{word,start,end}], language, duration}。"""
    import torch
    from transformers import AutoModelForMultimodalLM, AutoModelForTokenClassification, AutoProcessor

    use_cuda = device == "cuda" or (device == "auto" and torch.cuda.is_available() and _cublas_available())
    dev = "cuda:0" if use_cuda else "cpu"
    dtype = torch.bfloat16 if use_cuda else torch.float32
    prompt = (hotwords or "").strip()[:400] or None

    audio, sr = load_wav_16k(wav)
    duration = round(len(audio) / max(sr, 1), 3)

    texts: list[str] = []
    words: list[dict[str, Any]] = []
    detected = language
    asr_model = asr_processor = aligner_model = aligner_processor = None
    try:
        asr_processor = AutoProcessor.from_pretrained(str(asr_dir), trust_remote_code=False)
        asr_model = AutoModelForMultimodalLM.from_pretrained(
            str(asr_dir), dtype=dtype, device_map=dev)
        asr_model.eval()
        aligner_processor = AutoProcessor.from_pretrained(str(aligner_dir), trust_remote_code=False)
        aligner_model = AutoModelForTokenClassification.from_pretrained(
            str(aligner_dir), dtype=dtype, device_map=dev)
        aligner_model.eval()

        for offset, chunk in _audio_chunks(audio, sr):
            inputs = asr_processor.apply_transcription_request(
                audio=chunk, sampling_rate=sr, language=language, prompt=prompt)
            inputs = inputs.to(next(asr_model.parameters()).device,
                               next(asr_model.parameters()).dtype)
            with torch.inference_mode():
                out_ids = asr_model.generate(**inputs, max_new_tokens=1024)
            gen_ids = out_ids[:, inputs["input_ids"].shape[1]:]
            parsed = asr_processor.decode(gen_ids, return_format="parsed")[0]
            text = str((parsed or {}).get("transcription") or "").strip()
            if parsed and parsed.get("language"):
                detected = str(parsed["language"])
            if not text or looks_like_hallucination(text):
                continue
            texts.append(text)
            a_in, word_lists = aligner_processor.prepare_forced_aligner_inputs(
                audio=chunk, transcript=text, language=detected or language)
            a_in = a_in.to(next(aligner_model.parameters()).device,
                           next(aligner_model.parameters()).dtype)
            with torch.inference_mode():
                logits = aligner_model(**a_in).logits
            stamps = aligner_processor.decode_forced_alignment(
                logits=logits, input_ids=a_in["input_ids"], word_lists=word_lists,
                timestamp_token_id=aligner_model.config.timestamp_token_id)[0]
            for item in stamps:
                words.append({
                    "word": str(item.get("text") or ""),
                    "start": round(float(item.get("start_time") or 0) + offset, 3),
                    "end": round(float(item.get("end_time") or 0) + offset, 3),
                })
    finally:
        del asr_model, asr_processor, aligner_model, aligner_processor
        gc.collect()
        if use_cuda:
            torch.cuda.empty_cache()

    return {
        "engine": "qwen3-asr",
        "language": detected,
        "duration": duration,
        "text": "".join(texts).strip(),
        "words": words,
    }
