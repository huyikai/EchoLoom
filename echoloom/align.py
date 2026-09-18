"""歌词 × ASR 字级时间对齐。

思路：把歌词文本与 ASR 词序列各自摊平成字符流，用 difflib.SequenceMatcher 找匹配块，
匹配字符取所在 ASR 词的时间；未匹配字符在左右邻接锚点间线性插值。
相似度过低（<0.45）时退化为按行均匀铺满整曲（保底可唱）。
"""
from __future__ import annotations

import difflib
import re
from typing import Any

_PUNCT = re.compile(r"""[，。！？、；：""''（）\s,.!?;:()'"—…·-]""")


def _norm_char(c: str) -> str:
    return c.lower() if c.isascii() else c


def words_to_stream(words: list[dict[str, Any]]) -> tuple[str, list[tuple[int, int, float, float]]]:
    """ASR 词序列 → (文本流, [(start_off, end_off, t_start, t_end), ...])，offset 为字符下标。"""
    text = ""
    spans: list[tuple[int, int, float, float]] = []
    for w in words:
        wt = str(w.get("word") or "")
        if not wt:
            continue
        st = float(w.get("start") or 0.0)
        en = float(w.get("end") or st)
        spans.append((len(text), len(text) + len(wt), st, en))
        text += wt
    return text, spans


def _time_at(offset: int, text: str, spans: list[tuple[int, int, float, float]]) -> float:
    for s, e, st, en in spans:
        if s <= offset < e and e > s:
            return st + (en - st) * (offset - s) / (e - s)
    return -1.0


def align_lines(lines: list[str], asr_words: list[dict[str, Any]], *,
                total_sec: float | None = None) -> list[dict[str, Any]]:
    """歌词行列表 → timed_lines。每行 {start, end, text, chars:[{ch,start,end}]}。

    顺序游标匹配：逐行在 ASR 字符流的剩余区间里找最佳匹配块（保证时间轴单调，
    重复的副歌各归各的出现位置），匹配不上的行走插值兜底。
    """
    lyric_lines: list[list[str]] = []
    lyric_stream = ""
    line_spans: list[tuple[int, int]] = []
    for ln in lines:
        chars = [c for c in ln if not _PUNCT.match(c)]
        line_spans.append((len(lyric_stream), len(lyric_stream) + len(chars)))
        lyric_lines.append(chars)
        lyric_stream += "".join(chars)

    asr_text, asr_spans = words_to_stream(asr_words)
    a = "".join(_norm_char(c) for c in lyric_stream)
    b = "".join(_norm_char(c) for c in asr_text)

    lyric_time = [-1.0] * len(lyric_stream)

    if a and b:
        cursor = 0
        sm = difflib.SequenceMatcher(None, a, b)
        # 全局相似度过低时仍尝试逐行匹配（逐行容错性更好）
        for (s0, s1) in line_spans:
            seg = a[s0:s1]
            if not seg:
                continue
            best_pos, best_ratio = -1, 0.0
            span = max(len(seg) // 2, 4)
            start = cursor
            while start <= len(b):
                window = b[start : start + len(seg) + span]
                if not window:
                    break
                r = difflib.SequenceMatcher(None, seg, window).ratio()
                if r > best_ratio:
                    best_ratio, best_pos = r, start
                if r > 0.92:
                    break
                start += max(1, len(seg) // 4)
            if best_pos >= 0 and best_ratio >= 0.55:
                for k in range(len(seg)):
                    t = _time_at(best_pos + k, asr_text, asr_spans)
                    if t >= 0:
                        lyric_time[s0 + k] = t
                cursor = best_pos + len(seg)  # 单调前进：重复段落下次从其后找

    _interpolate(lyric_time)
    if total_sec and (not lyric_time or max(lyric_time) <= 0):
        return _proportional(lines, total_sec)

    return _assemble(lines, lyric_lines, line_spans, lyric_time, asr_spans, asr_text, total_sec)


def _interpolate(times: list[float]) -> None:
    n = len(times)
    anchors = [(i, t) for i, t in enumerate(times) if t >= 0]
    if not anchors:
        return
    first_i, first_t = anchors[0]
    for i in range(first_i):
        times[i] = max(0.0, first_t - (first_i - i) * 0.18)
    last_i, last_t = anchors[-1]
    for i in range(last_i + 1, n):
        times[i] = last_t + (i - last_i) * 0.18
    for (i0, t0), (i1, t1) in zip(anchors, anchors[1:]):
        if i1 - i0 <= 1:
            continue
        step = (t1 - t0) / (i1 - i0)
        for k in range(1, i1 - i0):
            times[i0 + k] = t0 + step * k


def _assemble(lines: list[str], lyric_lines: list[list[str]], line_spans: list[tuple[int, int]],
              lyric_time: list[float], asr_spans: list[tuple[int, int, float, float]],
              asr_text: str, total_sec: float | None) -> list[dict[str, Any]]:
    max_t = total_sec or max((en for _, _, _, en in asr_spans), default=0.0) or 60.0
    out: list[dict[str, Any]] = []
    for text, chars, (s0, s1) in zip(lines, lyric_lines, line_spans):
        if s1 == s0:
            continue
        char_times = lyric_time[s0:s1]
        start = char_times[0]
        end_guess = char_times[-1]
        # 行尾：用最后一个字符时长估计；并保证最短可读时长
        tail = max(0.35, (end_guess - start) / len(char_times)) if len(char_times) > 1 else 0.6
        end = max(start + 0.9, min(max_t, end_guess + tail))
        # 行间防重叠由时间单调性保证；chars 时间也做一次夹逼
        timed_chars = []
        for ch, t in zip([c for c in text if not _PUNCT.match(c)], char_times):
            timed_chars.append({"ch": ch, "start": round(t, 3), "end": 0.0})
        for i, tc in enumerate(timed_chars):
            nxt = timed_chars[i + 1]["start"] if i + 1 < len(timed_chars) else end
            tc["end"] = round(min(max_t, max(nxt, tc["start"] + 0.05)), 3)
        out.append({
            "start": round(start, 3), "end": round(end, 3),
            "text": text, "chars": timed_chars,
        })
    # 行首尾裁剪防交叉
    for prev, cur in zip(out, out[1:]):
        if cur["start"] < prev["end"]:
            mid = (prev["end"] + cur["start"]) / 2
            prev["end"] = round(mid, 3)
            cur["start"] = round(mid, 3)
            for tc in prev["chars"]:
                tc["end"] = min(tc["end"], prev["end"])
            for tc in cur["chars"]:
                tc["start"] = max(tc["start"], cur["start"])
    # 最短可读时长（最终钳制，允许与下一行首轻微重叠——karaoke 有淡入淡出）
    for i, line in enumerate(out):
        if line["end"] - line["start"] < 0.85:
            new_end = line["start"] + 0.85
            if i + 1 < len(out) and new_end > out[i + 1]["start"]:
                new_end = out[i + 1]["start"]
            line["end"] = round(max(line["end"], new_end), 3)
    return out


def _proportional(lines: list[str], total_sec: float) -> list[dict[str, Any]]:
    valid = [ln for ln in lines if ln.strip()]
    n = max(1, len(valid))
    out = []
    for i, ln in enumerate(valid):
        start = total_sec * i / n
        end = total_sec * (i + 1) / n
        chars = [c for c in ln if not _PUNCT.match(c)]
        timed = []
        m = len(chars)
        for j, ch in enumerate(chars):
            cs = start + (end - start) * j / m
            ce = start + (end - start) * (j + 1) / m
            timed.append({"ch": ch, "start": round(cs, 3), "end": round(ce, 3)})
        out.append({"start": round(start, 3), "end": round(end, 3), "text": ln, "chars": timed})
    return out
