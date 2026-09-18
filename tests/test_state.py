import pytest

from echoloom.state import GateName, ProjectState, new_project


def test_submit_and_auto_approve():
    p = new_project("测试主题", auto_approve=True)
    assert p.status.value == "draft"
    p.submit("lyrics", "[Verse]\n测试")
    assert p.gates["lyrics"].approved_version == 1
    assert p.status.value == "gathering"
    assert p.all_approved() is False


def test_manual_approve_and_versions_immutable():
    p = new_project("测试")
    p.submit("lyrics", "v1 内容")
    p.submit("lyrics", "v2 内容")
    gs = p.gates["lyrics"]
    assert [v.id for v in gs.versions] == [1, 2]
    assert gs.approved_version is None

    p.approve("lyrics", 1)
    assert gs.approved_payload == "v1 内容"

    # 重生成不动已确认版本
    p.submit("lyrics", "v3 内容")
    assert gs.approved_payload == "v1 内容"

    # 编辑也产生新版本
    p.edit("lyrics", "改过的词")
    assert len(gs.versions) == 4 and gs.approved_payload == "v1 内容"

    # 换成确认 v4
    v = p.approve("lyrics", 4)
    assert v.payload == "改过的词"


def test_approve_nonexistent_version_raises():
    p = new_project("测试")
    with pytest.raises(ValueError):
        p.approve("lyrics", 99)
    p.submit("lyrics", "x")
    with pytest.raises(ValueError):
        p.approve("lyrics", 2)


def test_finalize_requires_all_gates():
    p = new_project("测试", auto_approve=True)
    p.submit("lyrics", "词")
    p.submit("storyboard", {"shots": []})
    p.submit("portrait", ["a.png"])
    with pytest.raises(ValueError) as e:
        p.finalize()
    assert "audio" in str(e.value)

    p.submit("audio", "song.flac")
    p.finalize()
    assert p.status.value == "composing"


def test_composing_then_done_flow():
    p = new_project("测试", auto_approve=True)
    for gate, payload in [("lyrics", "词"), ("storyboard", {}), ("portrait", ["p"]), ("audio", "a.flac")]:
        p.submit(gate, payload)
    p.finalize()
    # composing 状态下 submit 不应回退状态
    p.submit("lyrics", "新词")
    assert p.status.value == "composing"


def test_persistence_roundtrip(tmp_path):
    p = new_project("持久化", auto_approve=True, seed=42)
    p.submit("lyrics", "词")
    path = tmp_path / "proj" / "state.json"
    p.save(path)
    q = ProjectState.load(path)
    assert q.id == p.id
    assert q.seed == 42
    assert q.gates["lyrics"].approved_payload == "词"
