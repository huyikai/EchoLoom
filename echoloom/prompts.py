"""LLM 提示词构建与输出解析。格式规范见 docs/prompt-formats.md。

所有 system prompt 的核心规则从规范派生；解析器对 LLM 输出做结构校验，
不符合即抛 PromptFormatError（由调用方重试）。
"""
from __future__ import annotations

import json
import re
from typing import Any

MUSIC_TAGS = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Outro")
CAPTION_PREFIXES = ("Global Metadata:", "Vocal Details:", "Arrangement:")

_SHOT_TYPES = ("singer", "scene")


class PromptFormatError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 歌词
# ---------------------------------------------------------------------------

def build_lyrics_messages(theme: str, *, language: str = "zh", target_sec: int = 180,
                          extra_hint: str = "") -> list[dict[str, str]]:
    system = (
        "你是顶级中文流行歌词作者。只输出歌词本身，不要任何解释、不要 Markdown 代码块。\n"
        "歌词必须用分段标签结构，可用标签：[Intro] [Verse] [Pre-Chorus] [Chorus] [Bridge] [Outro]，"
        "标签独占一行。器乐段写 [Intro] 后跟一行 [Instrumental]。\n"
        f"目标时长约 {target_sec} 秒（按中文流行 95-110BPM 估算句数：副歌约 8-12 行，主歌约 8-16 行）。\n"
        "结构建议：Intro(器乐) → Verse → Pre-Chorus → Chorus → Verse → Chorus → Bridge → Chorus → Outro。\n"
        "副歌重复必须完整重复写出，禁止写『重复』之类的占位。\n"
        "句子口语化、可唱、有记忆点；口吻词（啊/哟/——）可用于增强演唱语气。"
    )
    user = f"歌曲主题：{theme}\n{extra_hint}\n请写出完整歌词。"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validate_lyrics(text: str) -> str:
    """校验分段标签结构；不合格抛 PromptFormatError。返回清洗后的文本。"""
    if not text or not text.strip():
        raise PromptFormatError("歌词为空")
    cleaned = text.replace("\r\n", "\n").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", cleaned).strip()
    tags = re.findall(r"^\[([^\[\]]+)\]\s*$", cleaned, flags=re.M)
    if not tags:
        raise PromptFormatError("歌词缺少 [Tag] 分段标签")
    if "Chorus" not in tags:
        raise PromptFormatError("歌词缺少 [Chorus] 段")
    bad = [t for t in tags if not any(t.startswith(m) for m in MUSIC_TAGS) and t != "Instrumental"]
    if bad:
        raise PromptFormatError(f"未知分段标签: {bad}")
    body = re.sub(r"^\[[^\[\]]+\]\s*$", "", cleaned, flags=re.M).strip()
    if len(re.sub(r"\s", "", body)) < 40:
        raise PromptFormatError("歌词正文太短")
    return cleaned


def split_lyrics_sections(lyrics: str) -> list[dict[str, Any]]:
    """按标签切段：[{tag, lines:[...]}, ...]；无标签前导文本归入 (none)。"""
    sections: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in lyrics.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^\[([^\[\]]+)\]\s*$", line.strip())
        if m:
            cur = {"tag": m.group(1).strip(), "lines": []}
            sections.append(cur)
        elif cur is not None:
            if line.strip():
                cur["lines"].append(line.strip())
        elif line.strip():
            sections.append({"tag": "(none)", "lines": [line.strip()]})
    return sections


# ---------------------------------------------------------------------------
# 分镜脚本
# ---------------------------------------------------------------------------

class Shot(dict):
    """分镜条目就是 dict，schema 校验用 validate_storyboard。"""


def build_storyboard_messages(lyrics: str, singer_desc: str, *, target_sec: int = 180,
                              shot_sec: float = 5.0) -> list[dict[str, str]]:
    sections = split_lyrics_sections(lyrics)
    sec_brief = "\n".join(
        f"- [{s['tag']}] {' / '.join(s['lines'][:3])}{'…' if len(s['lines']) > 3 else ''}"
        for s in sections if s["tag"] != "(none)"
    )
    system = (
        "你是 MV 分镜导演。根据歌词输出 JSON 分镜脚本，**只输出 JSON**，不要任何其他文字。\n"
        "JSON 格式：\n"
        '{"singer_desc": "<歌手形象英文描述，50-80 词，外貌/服装/气质，将被逐字复用于所有歌手镜头>",\n'
        ' "caption": "<MiniMax Music3 英文结构化 caption，严格三段: Global Metadata: / Vocal Details: / Arrangement:>",\n'
        ' "shots": [{"id": 1, "type": "singer|scene", "section": "[Chorus]", "lyric": "该镜头覆盖的歌词首句",\n'
        '            "prompt": "<英文镜头提示词: 镜头运动+主体动作+光效氛围+风格收尾>",\n'
        '            "duration": 5.0, "transition": "cut|fade"}]}\n'
        "规则：\n"
        f"- 总时长约 {target_sec}s，每个镜头 duration 约 {shot_sec}s（4-8s），shots 数量 = ceil({target_sec}/{shot_sec}) 左右\n"
        "- type=singer 是歌手演唱镜头（对口型），type=scene 是氛围/叙事镜头；两者交替，副歌多用 singer\n"
        "- singer 镜头的 prompt 必须以歌手形象描述开头（复用 singer_desc 关键句）并写明 singing 表演状态\n"
        "- prompt 一律英文，一条镜头一个连贯动作，镜头运动用 slow/steady/handheld 等词\n"
        "- section 必须引用给定歌词段标签；lyric 用该段第一句中文\n"
        "歌词分段：\n" + sec_brief
    )
    user = f"歌手形象（已定，必须遵守）：{singer_desc}\n完整歌词：\n{lyrics}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_json_response(text: str) -> Any:
    """剥掉代码围栏/前后杂文，解析 JSON。"""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, flags=re.S)
    if m:
        t = m.group(1)
    else:
        start = t.find("{")
        end = t.rfind("}")
        if start == -1 or end == -1:
            raise PromptFormatError("响应中没有 JSON 对象")
        t = t[start : end + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise PromptFormatError(f"JSON 解析失败: {e}") from e


def validate_storyboard(obj: Any, *, target_sec: int = 180) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise PromptFormatError("分镜不是 JSON 对象")
    for key in ("singer_desc", "caption", "shots"):
        if key not in obj:
            raise PromptFormatError(f"分镜缺少字段 {key}")
    desc = str(obj["singer_desc"]).strip()
    caption = str(obj["caption"]).strip()
    for prefix in CAPTION_PREFIXES:
        if prefix not in caption:
            raise PromptFormatError(f"caption 缺少官方三段前缀 {prefix}")
    if not desc:
        raise PromptFormatError("singer_desc 为空")

    shots = obj["shots"]
    if not isinstance(shots, list) or len(shots) < 4:
        raise PromptFormatError("shots 太少")
    total = 0.0
    singer_shots = 0
    for i, s in enumerate(shots, 1):
        if not isinstance(s, dict):
            raise PromptFormatError(f"shot#{i} 不是对象")
        s.setdefault("id", i)
        if s.get("type") not in _SHOT_TYPES:
            raise PromptFormatError(f"shot#{i} type 非法: {s.get('type')}")
        if s["type"] == "singer":
            singer_shots += 1
        dur = float(s.get("duration") or 0)
        if not 2.0 <= dur <= 12.0:
            raise PromptFormatError(f"shot#{i} duration 越界: {dur}")
        prompt = str(s.get("prompt") or "").strip()
        if len(prompt) < 20:
            raise PromptFormatError(f"shot#{i} prompt 太短")
        total += dur
    if singer_shots < 2:
        raise PromptFormatError("歌手镜头不足 2 个")
    if total < target_sec * 0.8:
        raise PromptFormatError(f"分镜总时长 {total:.0f}s 低于目标的 80%")
    return obj
