import pytest

from echoloom.ass_style import AssStyle, build_ass
from echoloom.subtitles import build_project_ass, stamps_to_timed_lines

LINES = ["夜色穿过旧街灯", "影子替我沉默", "让风把名字吹散"]
STREAM = "夜色穿过旧街灯影子替我沉默让风把名字吹散"


def stamps_even():
    out = []
    t = 10.0
    for ch in STREAM:
        out.append({"text": ch, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.3
    return out


def test_stamps_to_timed_lines_maps_all_lines():
    timed = stamps_to_timed_lines(stamps_even(), LINES, STREAM)
    assert [x["text"] for x in timed] == LINES
    assert timed[0]["start"] == pytest.approx(10.0, abs=0.01)
    assert timed[0]["chars"][0]["ch"] == "夜"
    # 单调且覆盖到最后一个字
    assert timed[-1]["end"] > 10.0 + 0.3 * (len(STREAM) - 2)
    for a, b in zip(timed, timed[1:]):
        assert b["start"] >= a["start"]


def test_stamps_partial_coverage_extends_tail():
    stamps = stamps_even()[:12]  # 只覆盖前 12 个字
    timed = stamps_to_timed_lines(stamps, LINES, STREAM)
    assert len(timed) == 3
    # 尾部行仍有合理时间（顺延）
    assert timed[2]["start"] > timed[1]["start"]
    assert all(c["start"] >= 0 for c in timed[2]["chars"])


def test_stamps_empty_returns_empty():
    assert stamps_to_timed_lines([], LINES, STREAM) == []


def test_build_project_ass_intro_and_title():
    style = AssStyle()
    timed = stamps_to_timed_lines(stamps_even(), LINES, STREAM)
    for x in timed:  # 人声 10s 才开始
        x["start"] += 4
        x["end"] += 4
        for c in x["chars"]:
            c["start"] += 4
            c["end"] += 4
    ass = build_project_ass(style, timed, title="雨夜霓虹下的告白",
                            play_res_x=1344, play_res_y=768)
    # 标题卡事件（Title 样式，顶部居中）
    assert "EchoLoomTitle" in ass
    dlg = [l for l in ass.splitlines() if l.startswith("Dialogue: 1")]
    assert any("雨夜霓虹下的告白" in l for l in dlg)
    # 前奏 ♪ 指示（首句 14s 开始 > 3.5s 阈值）
    assert any("♪ ♪ ♪" in l for l in dlg)
    # 第一句歌词不在 0 秒渲染
    lyric_first = [l for l in ass.splitlines() if l.startswith("Dialogue: 0")][0]
    assert not lyric_first.startswith("Dialogue: 0,0:00:00")


def test_build_ass_with_extra_events_keeps_karaoke():
    style = AssStyle(mode="char")
    lines = [{"start": 20.0, "end": 22.0, "text": "两句",
              "chars": [{"ch": "两", "start": 20.0, "end": 20.5},
                        {"ch": "句", "start": 20.5, "end": 21.0}]}]
    ass = build_ass(style, lines, extra_events=[
        {"start": 1.0, "end": 5.0, "text": "♪ ♪ ♪", "style": "EchoLoom", "fade_ms": 500}])
    assert "♪ ♪ ♪" in ass
    assert "\\k50" in ass
