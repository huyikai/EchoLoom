import pytest

from echoloom.mv import (
    burn_cmd,
    master_pass2_cmd,
    parse_loudnorm_measures,
    plan_durations,
    trim_clip_cmd,
    xfade_concat_cmd,
    xfade_filter,
    xfade_offsets,
)


def test_plan_durations_pads_for_xfade():
    durs = [10.0, 8.0, 6.0]
    assert plan_durations(durs, 0.5) == [10.5, 8.5, 6.0]
    assert plan_durations([5.0], 0.5) == [5.0]
    # 拼接后总时长守恒
    padded = plan_durations(durs, 0.5)
    assert sum(padded) - 0.5 * (len(padded) - 1) == pytest.approx(sum(durs))


def test_xfade_offsets_math():
    # durs=[5,5,5], t=1: 接缝1 offset=4, 组合长9, 接缝2 offset=8, 总长13=15-2
    assert xfade_offsets([5, 5, 5], 1.0) == [4.0, 8.0]


def test_xfade_filter_two_and_three():
    f2 = xfade_filter(2, [5, 5], 0.5)
    assert f2 == "[0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.5[v]"
    f3 = xfade_filter(3, [5.5, 5.5, 5.0], 0.5)
    assert "[vx1]" in f3 and "offset=5.0" in f3 and f3.endswith("[v]")


def test_xfade_concat_cmd_structure():
    cmd = xfade_concat_cmd([f"{i}.mp4" for i in range(2)], "out.mp4", durs=[5, 5], t=0.5)
    assert cmd[0] == "ffmpeg" and cmd.count("-i") == 2
    assert "-filter_complex" in cmd and "-map" in cmd
    assert "h264_nvenc" in cmd


def test_trim_clip_cmd():
    cmd = trim_clip_cmd("a.mp4", "s.mp4", dur=5.0, w=1344, h=768, fps=24)
    joined = " ".join(cmd)
    assert "-vf" in cmd
    assert "scale=1344:768" in joined and "fps=24" in joined
    assert "-an" in cmd and "h264_nvenc" in joined


LOUDNORM_LOG = """
[Parsed_loudnorm_0 @ xxx] 
{
	"input_i" : "-18.02",
	"input_tp" : "-2.04",
	"input_lra" : "6.50",
	"input_thresh" : "-28.55",
	"output_i" : "-14.05",
	"output_tp" : "-1.51",
	"output_lra" : "6.50",
	"output_thresh" : "-24.53",
	"normalization_type" : "linear",
	"target_offset" : "-0.13"
}
"""


def test_parse_loudnorm_measures():
    m = parse_loudnorm_measures(LOUDNORM_LOG)
    assert m["input_i"] == pytest.approx(-18.02)
    assert m["input_tp"] == pytest.approx(-2.04)
    cmd = master_pass2_cmd("ffmpeg", "song.flac", "master.flac", m)
    assert "measured_I=-18.02" in " ".join(cmd)
    assert "linear=true" in " ".join(cmd) and "48000" in cmd


def test_burn_cmd_escapes_windows_path():
    ass = "D:/develop/EchoLoom/output/x/final.ass"
    cmd = burn_cmd("ffmpeg", "v.mp4", "a.flac", "out.mp4", ass_path=ass,
                   title="夜行", total=180.0, w=1344, h=768)
    joined = " ".join(cmd)
    assert "D\\:/develop/EchoLoom/output/x/final.ass" in joined
    assert "subtitles=" in joined and "fade=t=out:st=177.6" in joined
    assert "夜行" in joined and "-shortest" in cmd


def test_burn_cmd_without_ass_and_title():
    cmd = burn_cmd("ffmpeg", "v.mp4", "a.flac", "out.mp4", ass_path=None,
                   title=None, total=60.0, w=1344, h=768)
    joined = " ".join(cmd)
    assert "subtitles" not in joined and "drawtext" not in joined
