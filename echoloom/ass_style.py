"""ASS 字幕：样式参数 → [V4+ Styles]，歌词字级时间 → karaoke \\k 逐字高亮。"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

STYLE_NAME = "EchoLoom"

PRESETS: dict[str, dict[str, Any]] = {
    "night_neon": {
        "font_name": "Microsoft YaHei", "font_size": 60, "primary": "#00E5FF",
        "secondary": "#F2F2F2", "outline_color": "#101018", "outline": 2, "shadow": 1,
    },
    "minimal_white": {
        "font_name": "Microsoft YaHei", "font_size": 56, "primary": "#FFFFFF",
        "secondary": "#9AA0A6", "outline_color": "#000000", "outline": 2, "shadow": 0,
    },
    "stage_outline": {
        "font_name": "Microsoft YaHei", "font_size": 64, "primary": "#FFD54A",
        "secondary": "#FFFFFF", "outline_color": "#331100", "outline": 3, "shadow": 2,
    },
}


class AssStyle(BaseModel):
    font_name: str = "Microsoft YaHei"
    font_size: int = 60
    bold: bool = True
    primary: str = "#00E5FF"       # 已唱高亮色（karaoke \k 切到 primary）
    secondary: str = "#F2F2F2"     # 未唱颜色
    outline_color: str = "#101018"
    outline: float = 2
    shadow: float = 1
    alignment: int = 2             # 2=底部居中
    margin_l: int = 60
    margin_r: int = 60
    margin_v: int = 50
    mode: str = Field(default="char", pattern="^(char|line)$")
    fade_ms: int = 150

    @classmethod
    def from_preset(cls, name: str, **overrides: Any) -> "AssStyle":
        data = dict(PRESETS.get(name, PRESETS["night_neon"]))
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB → &HAABBGGRR（ASS 是 BGR + 前置 alpha）。"""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
    if not m:
        raise ValueError(f"非法颜色: {hex_color}")
    r, g, b = m.group(1)[0:2], m.group(1)[2:4], m.group(1)[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(sec: float) -> str:
    """秒 → H:MM:SS.CC（厘秒）。"""
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360_000)
    mnt, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{mnt:02d}:{s:02d}.{cs:02d}"


def style_line(style: AssStyle) -> str:
    """完整 23 字段 ASS V4+ Style 行（字段顺序见 build_ass 的 Format 行，不可乱序）。"""
    return (
        f"Style: {STYLE_NAME},{style.font_name},{style.font_size},"
        f"{ass_color(style.primary)},{ass_color(style.secondary)},"
        f"{ass_color(style.outline_color)},{ass_color('#000000', 0x80)},"
        f"{style.bold:d},0,0,0,100,100,0,0,1,{style.outline:g},{style.shadow:g},"
        f"{style.alignment},{style.margin_l},{style.margin_r},{style.margin_v},1"
    )


def build_ass(style: AssStyle, timed_lines: list[dict[str, Any]], *,
              play_res_x: int = 1344, play_res_y: int = 768, title: str = "EchoLoom") -> str:
    """timed_lines: [{start, end, chars: [{ch, start, end}] | None, text}]"""
    header = (
        "[Script Info]\n"
        f"Title: {title}\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line(style)}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    for line in timed_lines:
        text = _karaoke_text(style, line)
        fade = ""
        if style.fade_ms > 0:
            fade = rf"{{\fad({style.fade_ms},{style.fade_ms})}}"
        events.append(
            f"Dialogue: 0,{ass_time(line['start'])},{ass_time(line['end'])},{STYLE_NAME},,"
            f"0,0,0,,{fade}{text}"
        )
    return header + "\n".join(events) + "\n"


def _karaoke_text(style: AssStyle, line: dict[str, Any]) -> str:
    if style.mode == "line" or not line.get("chars"):
        dur = max(1, int(round((line["end"] - line["start"]) * 100)))
        return rf"{{\k{dur}}}{line['text']}"
    parts: list[str] = []
    for ch in line["chars"]:
        dur = max(1, int(round((ch["end"] - ch["start"]) * 100)))
        parts.append(rf"{{\k{dur}}}{ch['ch']}")
    return "".join(parts)
