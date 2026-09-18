import re

import pytest

from echoloom.ass_style import AssStyle, ass_color, ass_time, build_ass, style_line
from echoloom.align import align_lines

# ---------------------------------------------------------------- ASS 样式


def test_ass_color_bgr():
    assert ass_color("#FF8800") == "&H0000 88FF".replace(" ", "")
    assert ass_color("#000000") == "&H00000000"
    assert ass_color("#FFFFFF", alpha=0x80) == "&H80FFFFFF"


def test_ass_time_format():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(61.234) == "0:01:01.23"
    assert ass_time(3661.5) == "1:01:01.50"
    assert ass_time(-3) == "0:00:00.00"


def test_style_line_contains_fields():
    style = AssStyle()
    line = style_line(style)
    assert line.startswith("Style: EchoLoom,Microsoft YaHei,60,")
    assert len(line.split(",")) == 18  # Style 名 + 23 字段格式中我们输出的 18 项
    # primary #00E5FF → BGR FFE500；secondary #F2F2F2 → F2F2F2
    assert "&H00FFE500" in line
    assert "&H00F2F2F2" in line


def test_build_ass_karaoke_chars():
    style = AssStyle(mode="char", fade_ms=100)
    lines = [{
        "start": 1.0, "end": 3.0, "text": "让风把名字吹散",
        "chars": [{"ch": c, "start": 1.0 + i * 0.4, "end": 1.4 + i * 0.4}
                  for i, c in enumerate("让风把名字吹散")],
    }]
    ass = build_ass(style, lines, play_res_x=1344, play_res_y=768)
    assert "[Script Info]" in ass and "PlayResX: 1344" in ass
    assert "Format: Layer, Start, End" in ass
    dlg = [l for l in ass.splitlines() if l.startswith("Dialogue:")][0]
    assert dlg.startswith("Dialogue: 0,0:00:01.00,0:00:03.00,EchoLoom")
    assert r"\fad(100,100)" in dlg
    ks = re.findall(r"\\k(\d+)", dlg)
    assert len(ks) == 7
    assert all(int(k) == 40 for k in ks)  # 0.4s = 40cs
    # 展开文本无标记后应为原句
    plain = re.sub(r"\{[^}]*\}", "", dlg.split(",", 9)[-1])
    assert plain == "让风把名字吹散"


def test_build_ass_line_mode():
    style = AssStyle(mode="line", fade_ms=0)
    lines = [{"start": 2.0, "end": 4.5, "text": "两秒半一行", "chars": None}]
    dlg = [l for l in build_ass(style, lines).splitlines() if l.startswith("Dialogue:")][0]
    assert r"\k250" in dlg
    assert "fad" not in dlg


def test_karaoke_total_matches_line_duration():
    style = AssStyle(mode="char")
    text = "五字一行啊"  # 5 字
    chars = [{"ch": c, "start": 0.5 + i * 0.3, "end": 0.8 + i * 0.3} for i, c in enumerate(text)]
    lines = [{"start": 0.5, "end": 2.0, "text": text, "chars": chars}]
    dlg = [l for l in build_ass(style, lines).splitlines() if l.startswith("Dialogue:")][0]
    ks = sum(int(k) for k in re.findall(r"\\k(\d+)", dlg))
    assert ks == 150  # 5 × 0.3s


# ---------------------------------------------------------------- 对齐


WORDS = [  # 「让风把名字吹散 吹散也不回头」的模拟 ASR 词
    {"word": "让", "start": 10.0, "end": 10.3},
    {"word": "风", "start": 10.3, "end": 10.6},
    {"word": "把", "start": 10.6, "end": 10.9},
    {"word": "名字", "start": 10.9, "end": 11.5},
    {"word": "吹散", "start": 11.5, "end": 12.1},
    {"word": "也不", "start": 13.0, "end": 13.4},
    {"word": "回头", "start": 13.4, "end": 14.0},
]


def test_align_exact_match():
    lines = ["让风把名字吹散", "吹散也不回头"]
    out = align_lines(lines, WORDS, total_sec=20.0)
    assert len(out) == 2
    l1, l2 = out
    assert l1["start"] == pytest.approx(10.0, abs=0.05)
    assert l1["chars"][0]["ch"] == "让"
    assert l1["chars"][0]["start"] == pytest.approx(10.0, abs=0.05)
    assert l2["start"] == pytest.approx(12.1, abs=0.35)  # 「吹散」重复词落到第二处
    assert l2["end"] <= 20.0
    # 字时间单调
    for line in out:
        ts = [c["start"] for c in line["chars"]]
        assert ts == sorted(ts)


def test_align_with_misheard_char_interpolates():
    lines = ["让风把名字吹散"]
    noisy = [dict(w) for w in WORDS[:5]]
    noisy[3] = {"word": "明字", "start": 10.9, "end": 11.5}  # ASR 听错一个字
    out = align_lines(lines, noisy)
    assert len(out) == 1
    starts = [c["start"] for c in out[0]["chars"]]
    assert starts == sorted(starts)
    assert out[0]["chars"][0]["start"] == pytest.approx(10.0, abs=0.05)


def test_align_total_mismatch_falls_back_proportional():
    lines = ["完全不同的两行词", "跟语音毫无关系"]
    out = align_lines(lines, WORDS, total_sec=24.0)
    assert len(out) == 2
    assert out[0]["start"] == pytest.approx(0.0, abs=0.5)
    assert out[-1]["end"] == pytest.approx(24.0, abs=0.5)


def test_align_skips_empty_lines():
    out = align_lines(["", "让风把名字吹散", ""], WORDS)
    assert len(out) == 1
