import pytest

from echoloom.prompts import (
    PromptFormatError,
    build_lyrics_messages,
    build_storyboard_messages,
    parse_json_response,
    split_lyrics_sections,
    validate_lyrics,
    validate_storyboard,
)

GOOD_LYRICS = """[Intro]
[Instrumental]

[Verse]
夜色穿过旧街灯
影子替我沉默
风把昨天的名字
轻轻吹进人海

[Chorus]
让风把名字吹散
吹散也不回头
路灯一盏一盏灭
心事一句一句收

[Outro]
天亮以前到家
"""


def test_validate_lyrics_ok_and_sections():
    cleaned = validate_lyrics(GOOD_LYRICS)
    sections = split_lyrics_sections(cleaned)
    tags = [s["tag"] for s in sections]
    assert tags == ["Intro", "Instrumental", "Verse", "Chorus", "Outro"]
    assert sections[3]["lines"] == ["让风把名字吹散", "吹散也不回头", "路灯一盏一盏灭", "心事一句一句收"]


@pytest.mark.parametrize("bad", [
    "",
    "没有标签的歌词" * 10,
    "[Intro]\n[Verse]\n只有两句\n[Outro]\n没有副歌啦啦啦啦啦啦啦啦",
    "[Intro]\n[Chorus]\n短\n",
])
def test_validate_lyrics_rejects(bad):
    with pytest.raises(PromptFormatError):
        validate_lyrics(bad)


def test_validate_lyrics_strips_code_fence():
    fenced = "```markdown\n[Verse]\n" + "长句" * 30 + "\n[Chorus]\n" + "副歌" * 20 + "\n```"
    assert validate_lyrics(fenced).startswith("[Verse]")


def test_lyrics_messages_mention_target_and_tags():
    msgs = build_lyrics_messages("都市夜归人", target_sec=180)
    assert msgs[0]["role"] == "system"
    assert "180" in msgs[0]["content"]
    assert "[Chorus]" in msgs[0]["content"]
    assert "都市夜归人" in msgs[1]["content"]


STORYBOARD = {
    "singer_desc": "A young Chinese female singer with short black hair, wearing a silver jacket",
    "caption": "Global Metadata: dreamy synth-pop, 100 BPM, about 3 minutes.\n\nVocal Details: Female Mandarin vocal, fully sung.\n\nArrangement: Warm synths, soft drums. No over-compression, preserve live dynamics. 48kHz hi-fi fidelity.",
    "shots": [
        {"id": i, "type": "singer" if i % 2 else "scene", "section": "[Chorus]",
         "lyric": "让风把名字吹散", "prompt": f"Slow dolly forward, shot {i}, cinematic light, steady camera.",
         "duration": 5.0, "transition": "cut"}
        for i in range(1, 31)
    ],
}


def test_parse_json_response_variants():
    assert parse_json_response('{"a": 1}') == {"a": 1}
    assert parse_json_response('好的：```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('杂文 {"a": {"b": [1,2]}} 结尾') == {"a": {"b": [1, 2]}}
    with pytest.raises(PromptFormatError):
        parse_json_response("完全没有 json")
    with pytest.raises(PromptFormatError):
        parse_json_response("{broken json")


def test_validate_storyboard_ok():
    obj = validate_storyboard(STORYBOARD, target_sec=150)
    assert obj["singer_desc"].startswith("A young")


def test_validate_storyboard_rejections():
    import copy

    for mutate in (
        lambda o: o.pop("caption"),
        lambda o: o.update(caption="没有官方前缀的 caption"),
        lambda o: o.update(shots=o["shots"][:2]),
        lambda o: o["shots"][0].update(type="weird"),
        lambda o: o["shots"][0].update(duration=60),
        lambda o: o["shots"][0].update(prompt="短"),
        lambda o: o.update(shots=[{**s, "type": "scene"} for s in o["shots"]]),
        lambda o: o.update(shots=[{**s, "duration": 2.5} for s in o["shots"]]),
    ):
        bad = copy.deepcopy(STORYBOARD)
        mutate(bad)
        with pytest.raises(PromptFormatError):
            validate_storyboard(bad, target_sec=150)


def test_storyboard_messages_contract():
    msgs = build_storyboard_messages(GOOD_LYRICS, "a singer", target_sec=100)
    sys_text = msgs[0]["content"]
    assert '"singer_desc"' in sys_text and "Global Metadata:" in sys_text
    assert "[Chorus]" in sys_text  # 歌词分段简报注入
