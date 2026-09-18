"""项目状态机：四关卡（歌词/分镜/肖像/音频）+ 版本历史 + 确认锁存 + 自动放行。

关卡规则：
- 每次提交草稿/重生成追加新版本，历史版本不可变；
- approved_version 指向某个历史版本，重生成不改变它；
- 全部四关 approved 后才能 finalize；
- auto_approve=True 时提交即确认最新版（CLI/测试路径）。
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

GateName = Literal["lyrics", "storyboard", "portrait", "audio"]
GATES: tuple[GateName, ...] = ("lyrics", "storyboard", "portrait", "audio")


class Version(BaseModel):
    id: int
    payload: Any  # 歌词 str / storyboard dict / 肖像文件名列表 / 音频文件名
    note: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GateState(BaseModel):
    versions: list[Version] = Field(default_factory=list)
    approved_version: int | None = None

    def latest(self) -> Version | None:
        return self.versions[-1] if self.versions else None

    def approved(self) -> Version | None:
        if self.approved_version is None:
            return None
        for v in self.versions:
            if v.id == self.approved_version:
                return v
        return None

    @property
    def approved_payload(self) -> Any:
        v = self.approved()
        return v.payload if v else None


class ProjectStatus(str, Enum):
    draft = "draft"            # 创建，未产出歌词
    gathering = "gathering"    # 关卡收集中（0-4 关已确认）
    composing = "composing"    # 最终合成中
    done = "done"
    failed = "failed"


class ProjectState(BaseModel):
    id: str
    title: str
    theme: str = ""
    language: str = "zh"
    target_sec: int = 180
    seed: int = 0
    auto_approve: bool = False
    status: ProjectStatus = ProjectStatus.draft
    gates: dict[GateName, GateState] = Field(
        default_factory=lambda: {g: GateState() for g in GATES}
    )
    ass_style: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: str = ""

    # ---- 关卡操作 -----------------------------------------------------------
    def submit(self, gate: GateName, payload: Any, note: str = "") -> Version:
        gs = self.gates[gate]
        version = Version(id=len(gs.versions) + 1, payload=payload, note=note)
        gs.versions.append(version)
        if self.auto_approve:
            gs.approved_version = version.id
        self._touch_status()
        return version

    def approve(self, gate: GateName, version_id: int | None = None) -> Version:
        gs = self.gates[gate]
        target = version_id if version_id is not None else (gs.latest().id if gs.latest() else None)
        for v in gs.versions:
            if v.id == target:
                gs.approved_version = v.id
                self._touch_status()
                return v
        raise ValueError(f"{gate} v{target} 不存在")

    def edit(self, gate: GateName, payload: Any, note: str = "edited") -> Version:
        """编辑产生新版本（历史不可变）。"""
        return self.submit(gate, payload, note)

    def all_approved(self) -> bool:
        return all(self.gates[g].approved() is not None for g in GATES)

    def finalize(self) -> None:
        if not self.all_approved():
            missing = [g for g in GATES if self.gates[g].approved() is None]
            raise ValueError(f"关卡未全部确认: {missing}")
        self.status = ProjectStatus.composing

    # ---- 持久化 -------------------------------------------------------------
    def _touch_status(self) -> None:
        if self.status in (ProjectStatus.draft, ProjectStatus.gathering):
            self.status = ProjectStatus.gathering

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ProjectState":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def new_project(theme: str, *, language: str = "zh", target_sec: int = 180,
                seed: int | None = None, auto_approve: bool = False,
                title: str = "") -> ProjectState:
    return ProjectState(
        id=uuid.uuid4().hex[:12],
        title=title or theme[:24] or "untitled",
        theme=theme,
        language=language,
        target_sec=target_sec,
        seed=seed if seed is not None else int(time.time()) % 1_000_000,
        auto_approve=auto_approve,
    )
