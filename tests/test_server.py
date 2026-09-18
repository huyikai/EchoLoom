"""FastAPI 契约测试：假管线注入，跑完整关卡-合成 API 流。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.app import app  # noqa: E402

LYRICS = """[Intro]
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

STORYBOARD = {
    "singer_desc": "A young Chinese female singer in a silver jacket",
    "caption": ("Global Metadata: city-pop, 100 BPM, about 30 seconds.\n\n"
                "Vocal Details: Mandarin female vocal, fully sung.\n\n"
                "Arrangement: Piano, soft drums. No over-compression. 48kHz hi-fi fidelity."),
    "shots": [
        {"id": 1, "type": "scene", "section": "[Intro]", "lyric": "", "duration": 5.0,
         "prompt": "Slow drift over night city, neon reflections, cinematic.", "transition": "cut"},
        {"id": 2, "type": "singer", "section": "[Verse]", "lyric": "夜色穿过旧街灯", "duration": 6.0,
         "prompt": "Medium shot of the singer under a streetlamp, slow dolly in.", "transition": "cut"},
        {"id": 3, "type": "singer", "section": "[Chorus]", "lyric": "让风把名字吹散", "duration": 6.0,
         "prompt": "Close-up of the singer singing the chorus, steady camera.", "transition": "cut"},
        {"id": 4, "type": "scene", "section": "[Outro]", "lyric": "天亮以前到家", "duration": 7.0,
         "prompt": "Doorway silhouette at dawn, slow pull back.", "transition": "cut"},
    ],
}  # 总 24s


class FakePipe:
    """与 Pipeline 同接口的即时假件，产物落盘满足视图层。"""

    def __init__(self, settings, pid_progress=None):
        pass

    def _vdir(self, d, name):
        sub = d / name
        sub.mkdir(parents=True, exist_ok=True)
        return sub

    def make_lyrics(self, state, d):
        v = state.submit("lyrics", LYRICS)
        (self._vdir(d, "lyrics") / f"v{v.id}.txt").write_text(LYRICS, encoding="utf-8")
        return LYRICS

    def make_storyboard(self, state, d):
        v = state.submit("storyboard", STORYBOARD)
        (self._vdir(d, "storyboard") / f"v{v.id}.json").write_text("{}", encoding="utf-8")
        return STORYBOARD

    def make_portraits(self, state, d):
        p = self._vdir(d, "portraits")
        for i in range(1, 3):
            (p / f"candidate_{i}.png").write_bytes(b"png")
        v = state.submit("portrait", ["candidate_1.png", "candidate_2.png"])
        return v.payload

    def make_song(self, state, d):
        f = self._vdir(d, "audio") / f"song_v{len(state.gates['audio'].versions) + 1}.flac"
        f.write_bytes(b"fLaC")
        state.submit("audio", f.name, note="30.0s")
        return f

    def compose_final(self, state, d):
        final = self._vdir(d, "final") / "mv.mp4"
        final.write_bytes(b"mp4")
        from echoloom.state import ProjectStatus
        state.status = ProjectStatus.done
        return final


@pytest.fixture
def client(tmp_path, monkeypatch):
    import echoloom.config as C
    import server.app as S

    s = C.Settings(zhipuai_api_key="fake") if False else None
    # Settings 用 pydantic-settings，直接构造并替换 output_root 不可行（property），
    # 改为 monkeypatch Store 的输出根：把 store 指向 tmp_path
    monkeypatch.setattr(S, "build_pipeline", lambda settings, pid: FakePipe(settings))

    c = TestClient(app)
    with c:  # 触发 startup
        # startup 已用真实 output_root 建了 store；把它重定向到 tmp_path
        real_dir = S.store.dir

        def fake_dir(pid):
            d = tmp_path / pid
            d.mkdir(parents=True, exist_ok=True)
            return d

        monkeypatch.setattr(S.store, "dir", fake_dir)
        yield c


def wait_done(client, pid, timeout=5.0):
    import time
    for _ in range(int(timeout / 0.05)):
        st = client.get(f"/api/projects/{pid}").json()
        if st["gates"]["audio"]["versions"] or st["status"] != "gathering":
            if st["error"]:
                return st
        if st["gates"]["lyrics"]["versions"]:
            return st
        time.sleep(0.05)
    return client.get(f"/api/projects/{pid}").json()


def test_health_and_create_flow(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]

    r = client.post("/api/projects", json={"theme": "都市夜归人", "target_sec": 30})
    assert r.status_code == 200
    p = r.json()
    assert p["theme"] == "都市夜归人" and p["status"] in ("draft", "gathering")
    pid = p["id"]

    st = wait_done(client, pid)
    assert st["gates"]["lyrics"]["versions"], "后台歌词任务应已产出"


def test_full_gate_flow_and_compose(client):
    pid = client.post("/api/projects", json={"theme": "测试", "target_sec": 30}).json()["id"]

    # 逐关推进：等后台任务完成后确认
    import time

    def has_version(gate):
        return client.get(f"/api/projects/{pid}").json()["gates"][gate]["versions"]

    for gate in ("lyrics", "storyboard", "portrait", "audio"):
        for _ in range(100):
            if has_version(gate):
                break
            time.sleep(0.05)
        r = client.post(f"/api/projects/{pid}/gates/{gate}/approve", json={})
        assert r.status_code == 200, r.text

    # 字幕样式
    r = client.put(f"/api/projects/{pid}/style",
                   json={"style": {"font_size": 72, "primary": "#FF0000"}})
    assert r.status_code == 200
    assert r.json()["ass_style"]["font_size"] == 72

    # 合成
    r = client.post(f"/api/projects/{pid}/compose", json={})
    assert r.status_code == 200
    for _ in range(100):
        st = client.get(f"/api/projects/{pid}").json()
        if st["final"]:
            break
        time.sleep(0.05)
    assert st["final"] == f"/files/{pid}/final/mv.mp4"
    assert st["status"] == "done"

    # 文件可取
    r = client.get(st["final"])
    assert r.status_code == 200


def test_edit_lyrics_creates_version_and_validates(client):
    pid = client.post("/api/projects", json={"theme": "编辑测试", "target_sec": 30}).json()["id"]
    wait_done(client, pid)

    r = client.put(f"/api/projects/{pid}/gates/lyrics",
                   json={"text": "没有标签的歌词内容" * 10})
    assert r.status_code == 400  # 校验拒绝

    # 先确认 v1，再编辑
    client.post(f"/api/projects/{pid}/gates/lyrics/approve", json={})
    good = LYRICS + "\n[Chorus]\n再来一行凑数\n凑够两行就行\n"
    r = client.put(f"/api/projects/{pid}/gates/lyrics", json={"text": good})
    assert r.status_code == 200
    st = r.json()
    assert len(st["gates"]["lyrics"]["versions"]) == 2
    assert st["gates"]["lyrics"]["approved_version"] == 1  # 编辑不动已确认版本

    # 确认新版本
    r = client.post(f"/api/projects/{pid}/gates/lyrics/approve", json={"version": 2})
    assert r.json()["gates"]["lyrics"]["approved_version"] == 2


def test_approve_errors(client):
    pid = client.post("/api/projects", json={"theme": "x", "target_sec": 30}).json()["id"]
    r = client.post(f"/api/projects/{pid}/gates/lyrics/approve", json={"version": 99})
    assert r.status_code == 400
    r = client.post(f"/api/projects/{pid}/gates/nope/approve", json={})
    assert r.status_code == 422 or r.status_code == 404

    # compose 未确认时 409
    r = client.post(f"/api/projects/{pid}/compose", json={})
    assert r.status_code == 409


def test_sse_streams_events(client):
    pid = client.post("/api/projects", json={"theme": "sse", "target_sec": 30}).json()["id"]
    # probe 模式：收到首个心跳即返回
    r = client.get(f"/api/projects/{pid}/events?probe=1")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "ping" in r.text


def test_ass_preview_renders_png(client):
    pid = client.post("/api/projects", json={"theme": "预览", "target_sec": 30}).json()["id"]
    r = client.post(f"/api/projects/{pid}/ass-preview",
                    json={"style": {"font_size": 64, "primary": "#FFD54A"}})
    assert r.status_code == 200
    img = r.json()["image"]
    assert img.startswith("data:image/png;base64,")
    import base64
    assert base64.b64decode(img.split(",")[1])[:8] == b"\x89PNG\r\n\x1a\n"
