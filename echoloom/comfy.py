"""ComfyUI HTTP 客户端（stdlib urllib，零三方依赖）。

协议：POST /prompt 提交 → 轮询 /history/{id} → /view 取件；图片先 /upload/image。
"""
from __future__ import annotations

import io
import json
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ComfyError(RuntimeError):
    pass


@dataclass
class OutFile:
    filename: str
    subfolder: str
    type: str
    kind: str  # image / audio / video

    @property
    def ext(self) -> str:
        return Path(self.filename).suffix.lstrip(".").lower()


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 120):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    # ---- HTTP ---------------------------------------------------------------
    def _req(self, path: str, data: bytes | None = None, headers: dict | None = None,
             method: str = "GET", timeout: int | None = None) -> Any:
        req = urllib.request.Request(
            self.base + path, data=data, headers=headers or {},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            body = r.read()
        ct = r.headers.get("Content-Type", "")
        if "json" in ct:
            return json.loads(body)
        return body

    # ---- API ----------------------------------------------------------------
    def health(self) -> dict:
        return self._req("/system_stats")

    def upload_image(self, path: Path) -> str:
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        body.write(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode()
        )
        body.write(path.read_bytes())
        body.write(f"\r\n--{boundary}--\r\n".encode())
        resp = self._req(
            "/upload/image", data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST", timeout=300,
        )
        return resp["name"]

    def submit(self, workflow: dict, client_id: str | None = None) -> str:
        payload = {"prompt": workflow, "client_id": client_id or str(uuid.uuid4())}
        resp = self._req(
            "/prompt", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        if resp.get("node_errors"):
            raise ComfyError(f"节点校验错误: {json.dumps(resp['node_errors'], ensure_ascii=False)[:2000]}")
        return resp["prompt_id"]

    def history(self, prompt_id: str) -> dict | None:
        h = self._req(f"/history/{prompt_id}")
        return h.get(prompt_id) if h else None

    def queue_size(self) -> int:
        q = self._req("/queue")
        return len(q.get("queue_running", [])) + len(q.get("queue_pending", []))

    def wait(
        self, prompt_id: str, *, poll: float = 3.0, timeout: float = 7200.0,
        on_poll: Callable[[float, int], None] | None = None,
    ) -> list[OutFile]:
        """阻塞至完成；返回产物文件列表。失败/超时抛 ComfyError。"""
        t0 = time.time()
        while True:
            h = self.history(prompt_id)
            if h:
                status = h.get("status", {})
                if status.get("completed") or status.get("status_str") == "success":
                    return collect_outputs(h)
                if status.get("status_str") == "error":
                    errs = {
                        nid: nd.get("error")
                        for nid, nd in (h.get("outputs") or {}).items()
                        if nd.get("error")
                    }
                    raise ComfyError(f"执行失败: {json.dumps(errs, ensure_ascii=False)[:2000]}")
            if on_poll:
                on_poll(time.time() - t0, self.queue_size())
            if time.time() - t0 > timeout:
                raise ComfyError(f"超时 {timeout:.0f}s: {prompt_id}")
            time.sleep(poll)

    def run(self, workflow: dict, *, poll: float = 3.0, timeout: float = 7200.0,
            on_poll: Callable[[float, int], None] | None = None) -> list[OutFile]:
        pid = self.submit(workflow)
        return self.wait(pid, poll=poll, timeout=timeout, on_poll=on_poll)

    def fetch(self, f: OutFile, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = self._req(
            f"/view?filename={urllib.request.quote(f.filename)}&subfolder={urllib.request.quote(f.subfolder)}&type={f.type}",
            timeout=600,
        )
        dest.write_bytes(data)
        return dest


def collect_outputs(history_entry: dict) -> list[OutFile]:
    out: list[OutFile] = []
    for node_out in (history_entry.get("outputs") or {}).values():
        for kind in ("images", "audio", "gifs", "videos"):
            for a in node_out.get(kind) or []:
                out.append(OutFile(
                    filename=a["filename"], subfolder=a.get("subfolder", ""),
                    type=a.get("type", "output"),
                    kind="video" if kind in ("gifs", "videos") else kind.rstrip("s"),
                ))
    return out
