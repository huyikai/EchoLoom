"""流水线集成测试：LLM/ComfyUI/Demucs/FaceFusion/ASR/ffmpeg 全部用替身，
验证关卡编排、版本落盘、时间轴数学与产物结构。"""
import json
from pathlib import Path

import pytest

from echoloom.config import Settings
from echoloom.pipeline import Pipeline
from echoloom.state import ProjectStatus, new_project

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
    "singer_desc": "A young Chinese female singer with short black hair in a silver jacket",
    "caption": (
        "Global Metadata: dreamy city-pop, 100 BPM, about 3 minutes. Warm studio ambience.\n\n"
        "Vocal Details: Young Mandarin female vocal, fully sung, clear tone, no rap.\n\n"
        "Arrangement: Electric piano, soft drums, warm bass. No over-compression. 48kHz hi-fi fidelity."
    ),
    "shots": [
        {"id": 1, "type": "scene", "section": "[Intro]", "lyric": "", "duration": 5.0,
         "prompt": "Slow aerial drift over night city streets, neon reflections, cinematic.",
         "transition": "cut"},
        {"id": 2, "type": "singer", "section": "[Verse]", "lyric": "夜色穿过旧街灯", "duration": 5.0,
         "prompt": "Medium shot, the singer stands under a streetlamp, slow dolly in.",
         "transition": "cut"},
        {"id": 3, "type": "scene", "section": "[Verse]", "lyric": "影子替我沉默", "duration": 5.0,
         "prompt": "Low angle tracking of long shadows on wet asphalt, steady camera.",
         "transition": "cut"},
        {"id": 4, "type": "singer", "section": "[Chorus]", "lyric": "让风把名字吹散", "duration": 5.0,
         "prompt": "Close-up, the singer sings the chorus under flickering lamplight.",
         "transition": "cut"},
        {"id": 5, "type": "scene", "section": "[Outro]", "lyric": "天亮以前到家", "duration": 4.0,
         "prompt": "Doorway silhouette at dawn, very slow pull back, gentle grain.",
         "transition": "cut"},
    ],
}


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, temperature=0.8):
        self.calls += 1
        if "顶级中文流行歌词作者" in messages[0]["content"]:
            return LYRICS
        return json.dumps(STORYBOARD, ensure_ascii=False)


class FakeComfyClient:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs = 0
        self.uploaded: list[str] = []

    def health(self):
        return {"system": {"comfyui_version": "fake"}}

    def upload_image(self, path):
        self.uploaded.append(str(path))
        return path.name

    def run(self, wf, **kw):
        self.runs += 1
        from echoloom.comfy import OutFile
        types = [v["class_type"] for v in wf.values()]
        if "SaveImage" in types:
            out = OutFile(filename=f"img_{self.runs:03d}_00001_.png", subfolder="", type="output", kind="image")
            payload, suffix = b"\x89PNG fake", ".png"
        elif "SaveAudioAdvanced" in types:
            out = OutFile(filename=f"song_{self.runs:03d}_00001.flac", subfolder="", type="output", kind="audio")
            payload, suffix = b"fLaC fake", ".flac"
        else:
            assert "SaveVideo" in types, types
            out = OutFile(filename=f"vid_{self.runs:03d}_00001_.mp4", subfolder="", type="output", kind="video")
            payload, suffix = b"mp4 fake", ".mp4"
        (self.root / out.filename).write_bytes(payload)
        return [out]

    def fetch(self, f, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((self.root / f.filename).read_bytes())
        return dest


@pytest.fixture
def env(tmp_path, monkeypatch):
    import echoloom.pipeline as P

    settings = Settings(zhipu_api_key="fake", ffmpeg_bin="ffmpeg", portrait_candidates=2)

    def fake_probe(ff, f):
        return 180.0

    def fake_run(cmd):
        out = Path(cmd[-1])
        if out.suffix in (".mp4", ".flac"):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"enc")
        return None

    def fake_build_clip(src, dest, *, dur, w, h, fps, nvenc=True):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"seg")
        return dest

    def fake_xfade(files, dest, *, durs, t, transition="fade", nvenc=True):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"body")
        return dest

    def fake_burn(ff, video, audio, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"final")
        return dest

    def fake_stems(py, song, out_dir, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        vocals = out_dir / "htdemucs" / song.stem / "vocals.wav"
        vocals.parent.mkdir(parents=True, exist_ok=True)
        vocals.write_bytes(b"wav")
        (vocals.parent / "no_vocals.wav").write_bytes(b"wav")
        return {"vocals": vocals, "no_vocals": vocals.parent / "no_vocals.wav", "other": {}}

    def fake_master(ff, song, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"master")
        return dest, {"input_i": -18.0, "input_tp": -2.0, "input_lra": 6.0, "input_thresh": -28.0}

    def fake_asr(wav, **kw):
        words = [{"word": w, "start": 30.0 + i * 0.4, "end": 30.3 + i * 0.4}
                 for i, w in enumerate("夜色穿过旧街灯影子替我沉默让风把名字吹散")]
        return {"engine": "fake", "language": "zh", "duration": 180.0,
                "text": "".join(w["word"] for w in words), "words": words}

    def fake_lipsync(audio, video, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(video.read_bytes())
        return dest

    monkeypatch.setattr(P, "probe_sec", fake_probe)
    monkeypatch.setattr(P, "run", fake_run)
    monkeypatch.setattr(P, "build_clip", fake_build_clip)
    monkeypatch.setattr(P, "xfade_concat_cmd",
                        lambda *a, **k: ["true", str(a[-1])])  # a=(segs, body)
    monkeypatch.setattr(P, "burn_cmd",
                        lambda *a, **k: ["true", str(a[3])])  # a=(ff, video, audio, dest)
    monkeypatch.setattr(P, "separate_vocals", fake_stems)
    monkeypatch.setattr(P, "master_audio", fake_master)
    monkeypatch.setattr(P, "transcribe_wav", fake_asr)
    import echoloom.lipsync as L
    monkeypatch.setattr(L, "run_lip_sync", fake_lipsync)
    # pipeline.compose_final 里是局部 import，直接改 pipeline 命名空间引用即可
    monkeypatch.setattr(P, "has_nvenc", lambda ff="ffmpeg": True)

    proj = tmp_path / "proj"
    proj.mkdir()
    # target_sec=30 与测试分镜总时长(24s)同量级，满足 ≥80% 校验
    state = new_project("都市夜归人", auto_approve=True, seed=7, target_sec=30)
    pipe = Pipeline(settings, FakeLLM(), FakeComfyClient(tmp_path / "comfyout"),
                    progress=lambda s, m, p: None)
    return pipe, state, proj


def test_full_pipeline_with_fakes(env):
    pipe, state, proj = env
    assert state.status == ProjectStatus.draft

    lyrics = pipe.make_lyrics(state, proj)
    assert state.gates["lyrics"].approved_payload == lyrics
    assert (proj / "lyrics" / "v1.txt").exists()

    sb = pipe.make_storyboard(state, proj)
    assert sb["singer_desc"] == STORYBOARD["singer_desc"]
    assert (proj / "storyboard" / "v1.json").exists()

    files = pipe.make_portraits(state, proj)
    assert len(files) == 2
    assert all((proj / "portraits" / f).exists() for f in files)

    song = pipe.make_song(state, proj)
    assert song.exists() and song.suffix == ".flac"
    assert state.all_approved()

    final = pipe.compose_final(state, proj)
    assert final.exists() and final.name == "mv.mp4"
    assert state.status == ProjectStatus.composing

    # 产物结构
    assert (proj / "stems" / "htdemucs" / song.stem / "vocals.wav").exists()
    assert (proj / "final" / "master.flac").exists()
    ass = proj / "ass" / "final.ass"
    assert ass.exists()
    text = ass.read_text(encoding="utf-8")
    assert "[Script Info]" in text and "Dialogue:" in text
    # 关键帧：scene 3 张（singer 用肖像不生成）
    kfs = list((proj / "shots" / "keyframes").glob("*.png"))
    assert len(kfs) == 3
    # i2v：5 个镜头全部生成
    clips = list((proj / "shots" / "clips").glob("*.mp4"))
    assert len(clips) == 5
    # singer 镜头经过对口型
    lips = list((proj / "shots" / "lipsync").glob("*.mp4"))
    assert len(lips) == 2


def test_pipeline_gate_order_enforced(env):
    pipe, state, proj = env
    state.auto_approve = False
    with pytest.raises(ValueError):
        pipe.make_storyboard(state, proj)  # 歌词关卡未确认
    pipe.make_lyrics(state, proj)
    with pytest.raises(ValueError):
        pipe.make_storyboard(state, proj)  # 歌词已产出但仍未确认
    state.auto_approve = True
    state.approve("lyrics", 1)  # 补确认前面手动模式留下的歌词
    sb = pipe.make_storyboard(state, proj)  # 提交即确认
    assert state.gates["storyboard"].approved_payload == sb
    with pytest.raises(ValueError):
        pipe.compose_final(state, proj)  # 肖像/音频未确认


def test_pipeline_regenerate_creates_new_version(env):
    pipe, state, proj = env
    pipe.make_lyrics(state, proj)
    # 关掉自动放行模拟重生成
    state.auto_approve = False
    pipe.make_lyrics(state, proj)
    gs = state.gates["lyrics"]
    assert len(gs.versions) == 2
    assert gs.approved_version == 1  # 重生成不动已确认版本
