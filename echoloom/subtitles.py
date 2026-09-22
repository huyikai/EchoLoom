"""字幕构建：歌词强制对齐（KTV 标准做法）+ 标题/前奏指示事件。

对齐思路：歌词文本已知，无需 ASR 识别——用 Qwen3-ForcedAligner 把确认后的歌词
直接强制对齐到人声分轨，得到每字精确时间戳（单调、全覆盖，不会把后半段撒到视频外）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .align import _PUNCT  # 复用标点定义

_FALLBACK_STEP = 0.3  # 无锚字符的兜底步长（秒）


def force_align_lyrics(
    vocals_wav: Path,
    lyrics: str,
    *,
    asr_dir: str | Path,  # noqa: ARG001  (保留参数位：与 transcribe 路径对齐)
    aligner_dir: str | Path,
    language: str = "zh",
    device: str = "auto",
) -> list[dict[str, Any]]:
    """歌词 → timed_lines（每行 {start,end,text,chars:[{ch,start,end}]}）。

    内部用 Qwen3-ForcedAligner 对「歌词全文」做强制对齐；音频超过 240s 分块，
    歌词按块时长比例切分对齐后再拼回。
    """
    import gc

    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor

    from .asr import _audio_chunks, _cublas_available, load_wav_16k

    use_cuda = device == "cuda" or (device == "auto" and torch.cuda.is_available() and _cublas_available())
    dev = "cuda:0" if use_cuda else "cpu"
    dtype = torch.bfloat16 if use_cuda else torch.float32

    audio, sr = load_wav_16k(vocals_wav)
    lines = [ln for ln in lyrics.replace("\r\n", "\n").split("\n") if ln.strip() and not ln.strip().startswith("[")]
    streams: list[str] = []
    stream_full = "".join(c for ln in lines for c in ln if not _PUNCT.match(c))
    total_dur = len(audio) / sr
    chunks = list(_audio_chunks(audio, sr))
    if len(chunks) <= 1:
        streams.append(stream_full)
    else:
        acc = 0.0
        for offset, chunk in chunks:
            dur = len(chunk) / sr
            lo = int(len(stream_full) * acc / total_dur)
            hi = int(len(stream_full) * (acc + dur) / total_dur)
            streams.append(stream_full[lo:hi])
            acc += dur

    stamps: list[dict[str, Any]] = []
    aligner_model = aligner_processor = None
    try:
        aligner_processor = AutoProcessor.from_pretrained(str(aligner_dir), trust_remote_code=False)
        aligner_model = AutoModelForTokenClassification.from_pretrained(
            str(aligner_dir), dtype=dtype, device_map=dev)
        aligner_model.eval()

        for (offset, _chunk), text in zip(chunks, streams):
            if not text:
                continue
            inputs, word_lists = aligner_processor.prepare_forced_aligner_inputs(
                audio=_chunk, transcript=text, language=language)
            inputs = inputs.to(next(aligner_model.parameters()).device,
                               next(aligner_model.parameters()).dtype)
            with torch.inference_mode():
                logits = aligner_model(**inputs).logits
            part = aligner_processor.decode_forced_alignment(
                logits=logits, input_ids=inputs["input_ids"],
                word_lists=word_lists,
                timestamp_token_id=aligner_model.config.timestamp_token_id)[0]
            for item in part:
                text_out = str(item.get("text") or "")
                if not text_out:
                    continue
                stamps.append({
                    "text": text_out,
                    "start": round(float(item.get("start_time") or 0) + offset, 3),
                    "end": round(float(item.get("end_time") or 0) + offset, 3),
                })
    finally:
        del aligner_model, aligner_processor
        gc.collect()
        if use_cuda:
            torch.cuda.empty_cache()

    stamps = _repair_stamps(stamps, audio_dur=len(audio) / sr)
    return stamps_to_timed_lines(stamps, lines, stream_full)


def build_project_ass(style: Any, timed_lines: list[dict[str, Any]], *, title: str,
                      play_res_x: int = 1344, play_res_y: int = 768,
                      intro_min_sec: float = 3.5) -> str:
    """组装完整 ASS：标题卡（替换 drawtext）+ KTV 前奏 ♪ 指示 + karaoke 歌词。"""
    from .ass_style import STYLE_NAME, build_ass

    first_vocal = timed_lines[0]["start"] if timed_lines else 0.0
    extra: list[dict[str, Any]] = []
    if title:
        extra.append({"start": 0.2, "end": max(4.0, min(6.5, first_vocal)),
                      "text": title, "style": f"{STYLE_NAME}Title", "fade_ms": 700})
    if first_vocal > intro_min_sec:
        extra.append({"start": 0.8, "end": max(1.6, first_vocal - 0.4),
                      "text": "♪ ♪ ♪", "style": STYLE_NAME, "fade_ms": 500})
    return build_ass(style, timed_lines, play_res_x=play_res_x, play_res_y=play_res_y,
                     title=title, extra_events=extra)


def _repair_stamps(stamps: list[dict[str, Any]], audio_dur: float) -> list[dict[str, Any]]:
    """修复 ForcedAligner 解码的边界怪癖：

    - 首个字符戳被锚到音频开头（前奏即有声音/泄漏），与其余戳拉开大 gap → 拉回第二戳前；
    - 尾戳外推超出音频时长 → 钳回曲长内；
    - 非单调戳 → 拉平到前一戳之后。
    """
    if len(stamps) < 3:
        return stamps
    st = [dict(x) for x in stamps]
    # 首戳异常：与第二戳 gap 过大且落在开头
    if st[0]["start"] < 5.0 and st[1]["start"] - st[0]["end"] > 2.5:
        st[0]["start"] = max(0.0, st[1]["start"] - 0.32)
        st[0]["end"] = st[1]["start"]
    # 尾戳异常：超出音频
    if st[-1]["end"] > audio_dur + 0.3:
        prev_end = st[-2]["end"] if len(st) > 2 else max(0.0, audio_dur - 0.8)
        st[-1]["start"] = min(st[-1]["start"], max(prev_end + 0.05, audio_dur - 0.45))
        st[-1]["end"] = audio_dur - 0.05
        if st[-1]["end"] <= st[-1]["start"]:
            st[-1]["start"] = max(prev_end + 0.05, audio_dur - 0.45)
            st[-1]["end"] = audio_dur - 0.05
    # 单调化
    for i in range(1, len(st)):
        if st[i]["start"] < st[i - 1]["end"]:
            st[i]["start"] = st[i - 1]["end"]
        if st[i]["end"] <= st[i]["start"]:
            st[i]["end"] = st[i]["start"] + 0.12
    # 全局钳制
    for x in st:
        x["start"] = min(max(0.0, x["start"]), max(0.0, audio_dur - 0.12))
        x["end"] = min(max(x["end"], x["start"] + 0.08), audio_dur)
    return st


def stamps_to_timed_lines(stamps: list[dict[str, Any]], lines: list[str],
                          stream: str, *, max_sec: float | None = None) -> list[dict[str, Any]]:
    """对齐器输出（按流顺序的字符块时间）→ 按歌词行重组的 timed_lines。

    尾部未覆盖的字符按前字符时长顺延；整段无结果时按行均匀铺满兜底。
    """
    per_line_chars: list[list[str]] = []
    pos = 0
    for ln in lines:
        chars = [c for c in ln if not _PUNCT.match(c)]
        per_line_chars.append(chars)
        pos += len(chars)

    n = len(stream)
    char_time: list[float] = [-1.0] * n
    cursor = 0
    for st in stamps:
        text = "".join(c for c in st["text"] if not _PUNCT.match(c) and c.strip())
        for _ch in text:
            if cursor >= n:
                break
            char_time[cursor] = float(st["start"])
            cursor += 1

    if not any(t >= 0 for t in char_time):
        return []

    out: list[dict[str, Any]] = []
    idx = 0
    prev_end = 0.0
    for ln, chars in zip(lines, per_line_chars):
        if not chars:
            continue
        times = char_time[idx : idx + len(chars)]
        idx += len(chars)
        known = [t for t in times if t >= 0]
        start = known[0] if known else prev_end
        last = known[-1] if known else start + 0.3 * len(chars)
        step = (last - start) / len(times) if len(times) > 1 else 0.4
        timed = []
        for j, (ch, t) in enumerate(zip(chars, times)):
            cs = t if t >= 0 else start + step * j
            ce = times[j + 1] if j + 1 < len(times) and times[j + 1] >= 0 else cs + max(0.08, step)
            timed.append({"ch": ch, "start": round(cs, 3), "end": round(ce, 3)})
        end = timed[-1]["end"] + 0.35
        out.append({"start": round(start, 3), "end": round(end, 3), "text": ln, "chars": timed})
        prev_end = out[-1]["end"]
    # 防交叉
    for prev, cur in zip(out, out[1:]):
        if cur["start"] < prev["end"]:
            prev["end"] = round(cur["start"], 3)
            for tc in prev["chars"]:
                tc["end"] = min(tc["end"], prev["end"])
    return out
