"""FastAPI 服务：项目/关卡/重生成/合成/SSE 进度/字幕样式预览/产物托管。

前端（web/dist 构建产物）由本服务直接托管，单进程单命令启动。
"""
from __future__ import annotations

import base64
import json
import tempfile
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from echoloom.ass_style import AssStyle, build_ass
from echoloom.comfy import ComfyClient
from echoloom.config import ROOT, Settings, get_settings
from echoloom.llm import ZhipuClient
from echoloom.mv import run as ff_run
from echoloom.pipeline import Pipeline
from echoloom.state import GATES, GateName, ProjectState, ProjectStatus, new_project

app = FastAPI(title="EchoLoom", version="0.1.0")


# ---------------------------------------------------------------------------
# 存储 & 任务队列
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, settings: Settings):
        self.s = settings
        self.projects: dict[str, ProjectState] = {}
        self.events: dict[str, deque] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)  # GPU 任务全局串行
        self._load_existing()

    def _load_existing(self) -> None:
        for st in sorted(self.s.output_root.glob("*/state.json")):
            try:
                p = ProjectState.load(st)
                self.projects[p.id] = p
                self.events[p.id] = deque(maxlen=500)
            except Exception:
                continue

    def dir(self, pid: str) -> Path:
        d = self.s.output_root / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get(self, pid: str) -> ProjectState:
        p = self.projects.get(pid)
        if not p:
            raise HTTPException(404, f"项目不存在: {pid}")
        return p

    def create(self, **kw) -> ProjectState:
        p = new_project(**kw)
        with self.lock:
            self.projects[p.id] = p
            self.events[p.id] = deque(maxlen=500)
        p.save(self.dir(p.id) / "state.json")
        return p

    def save(self, p: ProjectState) -> None:
        p.save(self.dir(p.id) / "state.json")

    def emit(self, pid: str, stage: str, msg: str, pct: float) -> None:
        ev = self.events.get(pid)
        if ev is not None:
            ev.append({"stage": stage, "msg": msg, "pct": pct, "ts": threading.get_ident() and _now()})

    def submit_job(self, pid: str, fn) -> None:
        p = self.get(pid)
        if p.status == ProjectStatus.composing:
            raise HTTPException(409, "正在合成中")

        def wrapped():
            try:
                p.error = ""
                self.save(p)
                fn()
                p.error = ""
                self.save(p)
            except Exception as e:  # 严格模式：失败落状态，前端可见
                if p.status == ProjectStatus.composing:
                    p.status = ProjectStatus.gathering
                p.error = f"{type(e).__name__}: {e}"
                self.emit(pid, "error", p.error, 1.0)
                self.save(p)

        self.pool.submit(wrapped)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


store: Store = None  # type: ignore  (startup 初始化)


def build_pipeline(s: Settings, pid: str) -> Pipeline:
    return Pipeline(
        s,
        ZhipuClient(s.zhipuai_api_key, model=s.llm_model),
        ComfyClient(s.comfyui_url),
        progress=lambda stage, msg, pct: store.emit(pid, stage, msg, pct),
    )


@app.on_event("startup")
def _startup() -> None:
    global store
    store = Store(get_settings())


# ---------------------------------------------------------------------------
# 视图模型
# ---------------------------------------------------------------------------

def gate_view(p: ProjectState, pid: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for g in GATES:
        gs = p.gates[g]
        versions = []
        for v in gs.versions:
            item: dict[str, Any] = {
                "id": v.id, "note": v.note, "created_at": v.created_at,
            }
            if g == "lyrics":
                item["text"] = v.payload
            elif g == "storyboard":
                item["storyboard"] = v.payload
            elif g == "portrait":
                item["images"] = [f"/files/{pid}/portraits/{name}" for name in v.payload]
            elif g == "audio":
                item["url"] = f"/files/{pid}/audio/{v.payload}"
                item["name"] = v.payload
            versions.append(item)
        out[g] = {"versions": versions, "approved_version": gs.approved_version}
    return out


def project_view(p: ProjectState) -> dict[str, Any]:
    pid = p.id
    final = store.dir(pid) / "final" / "mv.mp4"
    return {
        "id": pid, "title": p.title, "theme": p.theme, "status": p.status.value,
        "target_sec": p.target_sec, "seed": p.seed, "auto_approve": p.auto_approve,
        "language": p.language,
        "gates": gate_view(p, pid),
        "ass_style": p.ass_style or AssStyle().model_dump(),
        "final": f"/files/{pid}/final/mv.mp4" if final.exists() else None,
        "master": f"/files/{pid}/final/master.flac" if (store.dir(pid) / "final" / "master.flac").exists() else None,
        "error": p.error,
        "created_at": p.created_at,
    }


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class CreateReq(BaseModel):
    theme: str = ""
    lyrics_text: str = ""
    title: str = ""
    target_sec: int = 180
    seed: Optional[int] = None
    language: str = "zh"
    auto_approve: bool = False


class ApproveReq(BaseModel):
    version: Optional[int] = None


class EditTextReq(BaseModel):
    text: str


class StyleReq(BaseModel):
    style: dict[str, Any]


class ComposeReq(BaseModel):
    style: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "projects": len(store.projects)}


@app.post("/api/projects")
def create_project(req: CreateReq) -> dict:
    if not req.theme and not req.lyrics_text:
        raise HTTPException(400, "theme 或 lyrics_text 至少一个")
    p = store.create(
        theme=req.theme, title=req.title, language=req.language,
        target_sec=req.target_sec, seed=req.seed, auto_approve=req.auto_approve,
    )
    store.save(p)

    def job():
        pipe = build_pipeline(store.s, p.id)
        if req.lyrics_text:
            text = req.lyrics_text.strip()
            v = p.submit("lyrics", text, note="user")
            (store.dir(p.id) / "lyrics").mkdir(exist_ok=True)
            (store.dir(p.id) / "lyrics" / f"v{v.id}.txt").write_text(text, encoding="utf-8")
        else:
            pipe.make_lyrics(p, store.dir(p.id))

    store.submit_job(p.id, job)
    return project_view(p)


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [project_view(p) for p in
            sorted(store.projects.values(), key=lambda x: x.created_at, reverse=True)]


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return project_view(store.get(pid))


def _require_gate_editable(p: ProjectState, gate: GateName) -> None:
    if p.status not in (ProjectStatus.draft, ProjectStatus.gathering):
        raise HTTPException(409, f"状态 {p.status.value} 下不可修改关卡")


NEXT_GATE: dict[GateName, GateName] = {
    "lyrics": "storyboard", "storyboard": "portrait", "portrait": "audio",
}


@app.post("/api/projects/{pid}/gates/{gate}/approve")
def approve_gate(pid: str, gate: GateName, req: ApproveReq) -> dict:
    p = store.get(pid)
    if gate not in GATES:
        raise HTTPException(404, gate)
    try:
        p.approve(gate, req.version)
    except ValueError as e:
        raise HTTPException(400, str(e))
    p.error = ""
    store.save(p)
    # 自动串链：确认后下一关未产出则自动开始
    if gate in NEXT_GATE:
        nxt = NEXT_GATE[gate]
        if not p.gates[nxt].versions and p.status in (ProjectStatus.draft, ProjectStatus.gathering):
            stages = {
                "storyboard": lambda pipe: pipe.make_storyboard(p, store.dir(pid)),
                "portrait": lambda pipe: pipe.make_portraits(p, store.dir(pid)),
                "audio": lambda pipe: pipe.make_song(p, store.dir(pid)),
            }
            store.submit_job(pid, lambda: stages[nxt](build_pipeline(store.s, pid)))
    return project_view(p)


@app.post("/api/projects/{pid}/gates/{gate}/regenerate")
def regenerate_gate(pid: str, gate: GateName) -> dict:
    p = store.get(pid)
    _require_gate_editable(p, gate)
    stages = {
        "lyrics": lambda pipe: pipe.make_lyrics(p, store.dir(pid)),
        "storyboard": lambda pipe: pipe.make_storyboard(p, store.dir(pid)),
        "portrait": lambda pipe: pipe.make_portraits(p, store.dir(pid)),
        "audio": lambda pipe: pipe.make_song(p, store.dir(pid)),
    }
    if gate not in stages:
        raise HTTPException(404, gate)
    store.submit_job(pid, lambda: stages[gate](build_pipeline(store.s, pid)))
    return project_view(p)


@app.put("/api/projects/{pid}/gates/lyrics")
def edit_lyrics(pid: str, req: EditTextReq) -> dict:
    p = store.get(pid)
    _require_gate_editable(p, "lyrics")
    from echoloom.prompts import validate_lyrics
    try:
        text = validate_lyrics(req.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    v = p.edit("lyrics", text)
    (store.dir(pid) / "lyrics").mkdir(exist_ok=True)
    (store.dir(pid) / "lyrics" / f"v{v.id}.txt").write_text(text, encoding="utf-8")
    store.save(p)
    return project_view(p)


@app.put("/api/projects/{pid}/gates/storyboard")
def edit_storyboard(pid: str, req: dict[str, Any]) -> dict:
    p = store.get(pid)
    _require_gate_editable(p, "storyboard")
    v = p.edit("storyboard", req, note="edited")
    (store.dir(pid) / "storyboard").mkdir(exist_ok=True)
    (store.dir(pid) / "storyboard" / f"v{v.id}.json").write_text(
        json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    store.save(p)
    return project_view(p)


@app.put("/api/projects/{pid}/gates/portrait")
def edit_portrait(pid: str, req: dict[str, Any]) -> dict:
    """重排/编辑肖像候选：payload 为文件名列表，第一张将作为歌手形象。"""
    p = store.get(pid)
    _require_gate_editable(p, "portrait")
    files = req.get("images") or []
    if not files:
        raise HTTPException(400, "images 不能为空")
    known = {v for gs in p.gates["portrait"].versions for v in (gs.payload or [])}
    # 允许传 URL 或文件名，统一按 basename 归一
    normalized = [Path(f).name for f in files]
    unknown = [f for f in normalized if f not in known]
    if unknown:
        raise HTTPException(400, f"未知文件: {unknown}")
    v = p.edit("portrait", normalized, note="picked")
    store.save(p)
    return project_view(p)


@app.put("/api/projects/{pid}/style")
def put_style(pid: str, req: StyleReq) -> dict:
    p = store.get(pid)
    try:
        AssStyle(**req.style)  # 校验
    except Exception as e:
        raise HTTPException(400, f"样式非法: {e}")
    p.ass_style = req.style
    store.save(p)
    return project_view(p)


@app.post("/api/projects/{pid}/compose")
def compose(pid: str, req: ComposeReq) -> dict:
    p = store.get(pid)
    if not p.all_approved():
        raise HTTPException(409, "关卡未全部确认")
    if req.style:
        p.ass_style = req.style
    store.save(p)

    def job():
        pipe = build_pipeline(store.s, pid)
        final = pipe.compose_final(p, store.dir(pid))
        from echoloom.state import ProjectStatus as PS
        p.status = PS.done
        p.error = ""

    store.submit_job(pid, job)
    return project_view(p)


@app.get("/api/projects/{pid}/events")
async def events(pid: str, probe: bool = False) -> StreamingResponse:
    import asyncio
    import time as _time

    store.get(pid)

    async def gen():
        idx = 0
        end_pushes = 0
        started = _time.monotonic()
        while True:
            items = list(store.events.get(pid))
            while idx < len(items):
                yield f"data: {json.dumps(items[idx], ensure_ascii=False)}\n\n"
                idx += 1
            p = store.projects.get(pid)
            terminal = p and (p.status == ProjectStatus.done or p.error)
            if terminal:
                end_pushes += 1
                if end_pushes > 3:
                    yield f'data: {json.dumps({"stage": "end", "msg": p.status.value, "pct": 1.0})}\n\n'
                    return
            if _time.monotonic() - started > 1800:  # 半小时兜底断开
                yield f'data: {json.dumps({"stage": "timeout", "msg": "stream closed", "pct": 1.0})}\n\n'
                return
            yield ": ping\n\n"  # 心跳，保持连接可探测
            if probe:
                return
            await asyncio.sleep(0.6)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.post("/api/projects/{pid}/ass-preview")
def ass_preview(pid: str, req: StyleReq) -> dict:
    """用项目里最近的一张图 + 样例歌词即时渲染字幕样式预览。"""
    p = store.get(pid)
    try:
        style = AssStyle(**req.style)
    except Exception as e:
        raise HTTPException(400, f"样式非法: {e}")

    d = store.dir(pid)
    img = None
    for cand in sorted((d / "shots" / "keyframes").glob("*.png")) + sorted((d / "portraits").glob("*.png")):
        img = cand
    if img is None:
        img = _gradient_placeholder(d)

    sample = [
        {"start": 1.0, "end": 4.2, "text": "让风把名字吹散",
         "chars": [{"ch": c, "start": 1.0 + i * 0.4, "end": 1.4 + i * 0.4}
                   for i, c in enumerate("让风把名字吹散")]},
        {"start": 4.6, "end": 7.8, "text": "吹散也不回头",
         "chars": [{"ch": c, "start": 4.6 + i * 0.4, "end": 5.0 + i * 0.4}
                   for i, c in enumerate("吹散也不回头")]},
    ]
    ass_path = d / "ass" / "preview.ass"
    ass_path.parent.mkdir(exist_ok=True)
    ass_path.write_text(build_ass(style, sample, title=p.title), encoding="utf-8")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out = Path(tmp.name)
    ff_run([store.s.ffmpeg_bin, "-y", "-v", "error", "-i", str(img),
            "-vf", f"subtitles=filename='{ass_path.as_posix().replace(':', chr(92) + ':')}'",
            "-frames:v", "1", str(out)])
    b64 = base64.b64encode(out.read_bytes()).decode()
    out.unlink(missing_ok=True)
    return {"image": f"data:image/png;base64,{b64}"}


def _gradient_placeholder(d: Path) -> Path:
    out = d / "ass" / "placeholder.png"
    out.parent.mkdir(exist_ok=True)
    if not out.exists():
        ff_run([store.s.ffmpeg_bin, "-y", "-v", "error",
                "-f", "lavfi", "-i", "gradients=s=1344x768:c0=0x1a1f36:c1=0x0b0d16",
                "-frames:v", "1", str(out)])
    return out


# ---------------------------------------------------------------------------
# 静态产物 & 前端
# ---------------------------------------------------------------------------

@app.get("/files/{pid}/{path:path}")
def files(pid: str, path: str) -> FileResponse:
    d = store.dir(pid).resolve()
    target = (d / path).resolve()
    if not str(target).startswith(str(d)) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


_web_dist = ROOT / "web" / "dist"
if _web_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_web_dist), html=True), name="web")
else:
    @app.get("/")
    def index() -> JSONResponse:
        return JSONResponse({"app": "EchoLoom", "hint": "web/dist 未构建，前端开发模式请用 vite dev server"})
