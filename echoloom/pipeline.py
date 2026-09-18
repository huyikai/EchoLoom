"""EchoLoom 流水线编排：四关卡产物生成 + 最终合成。

阶段方法只依赖 (state, project_dir)，产物按版本落盘，状态由调用方持久化。
LLM/Comfy/Demucs/FaceFusion 全部可注入替身（测试用）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .align import align_lines
from .asr import transcribe_wav
from .ass_style import AssStyle, build_ass
from .audio import master_audio, separate_vocals
from .comfy import ComfyClient, OutFile
from .config import Settings
from .llm import ZhipuClient
from .mv import (
    burn_cmd,
    build_clip,
    has_nvenc,
    probe_sec,
    run,
    xfade_concat_cmd,
)
from .prompts import (
    PromptFormatError,
    build_lyrics_messages,
    build_storyboard_messages,
    parse_json_response,
    validate_lyrics,
    validate_storyboard,
)
from .state import ProjectState, ProjectStatus
from .workflows import frames_for, h3_i2v_workflow, music3_workflow, zimage_workflow

Progress = Callable[[str, str, float], None]

ROOT_VENV_PY = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe"


def noop_progress(stage: str, msg: str, pct: float) -> None:  # pragma: no cover
    pass


class Pipeline:
    def __init__(self, settings: Settings, llm: ZhipuClient, comfy: ComfyClient,
                 progress: Progress = noop_progress):
        self.s = settings
        self.llm = llm
        self.comfy = comfy
        self.progress = progress
        self._nvenc: bool | None = None

    # ---- 基础 ---------------------------------------------------------------
    def _dir(self, project_dir: Path, *parts: str) -> Path:
        d = project_dir.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def nvenc(self) -> bool:
        if self._nvenc is None:
            self._nvenc = has_nvenc(self.s.ffmpeg_bin)
        return self._nvenc

    def _llm_retry(self, messages: list[dict[str, str]], validator: Callable[[Any], Any],
                   *, attempts: int = 3, temperature: float = 0.8) -> Any:
        last: Exception | None = None
        for _ in range(attempts):
            raw = self.llm.chat(messages, temperature=temperature)
            try:
                return validator(raw)
            except PromptFormatError as e:
                last = e
        raise PromptFormatError(f"LLM 输出 {attempts} 次均不合规: {last}")

    # ---- 关卡 A：歌词 ----------------------------------------------------------
    def make_lyrics(self, state: ProjectState, project_dir: Path) -> str:
        self.progress("lyrics", "生成歌词…", 0.02)
        msgs = build_lyrics_messages(state.theme, language=state.language,
                                     target_sec=state.target_sec)
        lyrics = self._llm_retry(msgs, validate_lyrics)
        vdir = self._dir(project_dir, "lyrics")
        version = state.submit("lyrics", lyrics)
        (vdir / f"v{version.id}.txt").write_text(lyrics, encoding="utf-8")
        self.progress("lyrics", f"歌词 v{version.id} 完成", 0.08)
        return lyrics

    # ---- 关卡 B：分镜脚本 --------------------------------------------------------
    def make_storyboard(self, state: ProjectState, project_dir: Path) -> dict[str, Any]:
        lyrics = state.gates["lyrics"].approved_payload
        if not lyrics:
            raise ValueError("歌词关卡未确认")
        self.progress("storyboard", "生成分镜脚本与 Music3 caption…", 0.10)
        msgs = build_storyboard_messages(lyrics, "", target_sec=state.target_sec)
        sb = self._llm_retry(msgs, lambda t: validate_storyboard(
            parse_json_response(t), target_sec=state.target_sec), temperature=0.6)
        vdir = self._dir(project_dir, "storyboard")
        version = state.submit("storyboard", sb)
        (vdir / f"v{version.id}.json").write_text(
            json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
        self.progress("storyboard", f"分镜 v{version.id}: {len(sb['shots'])} 镜", 0.15)
        return sb

    # ---- 关卡 C：歌手肖像 --------------------------------------------------------
    def make_portraits(self, state: ProjectState, project_dir: Path) -> list[str]:
        sb = state.gates["storyboard"].approved_payload
        if not sb:
            raise ValueError("分镜关卡未确认")
        desc = sb["singer_desc"]
        self.progress("portrait", "生成歌手肖像候选…", 0.18)
        vdir = self._dir(project_dir, "portraits")
        n = self.s.portrait_candidates
        files: list[str] = []
        for i in range(n):
            wf = zimage_workflow(
                f"character sheet, {desc}, upper body portrait, looking at camera, "
                "clean dark background, cinematic studio lighting, highly detailed",
                width=768, height=1024, seed=state.seed + i * 101,
                prefix=f"echoloom/{state.id}/portrait",
            )
            outs: list[OutFile] = self.comfy.run(wf, poll=2.0, timeout=900)
            dest = self.comfy.fetch(outs[0], vdir / f"candidate_{i + 1}.png")
            files.append(dest.name)
            self.progress("portrait", f"候选 {i + 1}/{n}", 0.18 + 0.04 * (i + 1) / n)
        version = state.submit("portrait", files)
        self.progress("portrait", f"肖像 v{version.id}: {len(files)} 候选", 0.24)
        return files

    # ---- 关卡 D：整曲 ----------------------------------------------------------
    def make_song(self, state: ProjectState, project_dir: Path) -> Path:
        sb = state.gates["storyboard"].approved_payload
        lyrics = state.gates["lyrics"].approved_payload
        if not sb or not lyrics:
            raise ValueError("歌词/分镜关卡未确认")
        self.progress("audio", f"Music3 作曲（目标 {state.target_sec}s，约 5-15 分钟）…", 0.26)
        wf = music3_workflow(sb["caption"], lyrics, seed=state.seed,
                             max_duration=float(state.target_sec),
                             prefix=f"echoloom/{state.id}/music")
        outs = self.comfy.run(wf, poll=5.0, timeout=7200,
                              on_poll=lambda t, q: self.progress(
                                  "audio", f"Music3 生成中 {t:.0f}s", 0.26))
        vdir = self._dir(project_dir, "audio")
        dest = vdir / f"song_v{len(state.gates['audio'].versions) + 1}.flac"
        self.comfy.fetch(outs[0], dest)
        dur = probe_sec(self.s.ffmpeg_bin, dest) if self.s.ffmpeg_bin else 0.0
        version = state.submit("audio", dest.name, note=f"{dur:.1f}s")
        self.progress("audio", f"整曲 v{version.id} 完成（实测 {dur:.1f}s）", 0.32)
        return dest

    # ---- 最终合成 ---------------------------------------------------------------
    def compose_final(self, state: ProjectState, project_dir: Path) -> Path:
        sb = state.gates["storyboard"].approved_payload
        lyrics = state.gates["lyrics"].approved_payload
        audio_name = state.gates["audio"].approved_payload
        song = self._dir(project_dir, "audio") / audio_name if audio_name else None
        if not sb or not lyrics or not song or not song.exists():
            raise ValueError("四关卡未全部确认")
        state.status = ProjectStatus.composing

        shots: list[dict[str, Any]] = sb["shots"]
        song_dur = probe_sec(self.s.ffmpeg_bin, song)
        xfade_t = 0.5

        # 1) 时间轴：分镜总长 → 等比缩放到实际歌曲时长
        sb_total = sum(float(s["duration"]) for s in shots)
        scale = song_dur / sb_total
        durs = [float(s["duration"]) * scale for s in shots]
        self.progress("compose", f"时间轴: {len(shots)} 镜 × 缩放 {scale:.3f} = {song_dur:.1f}s", 0.34)

        # 2) 关键帧：scene 用 Z-Image，singer 用已选肖像
        kf_dir = self._dir(project_dir, "shots", "keyframes")
        portraits = self._dir(project_dir, "portraits")
        chosen_portrait = self._chosen_portrait(state, portraits)
        keyframes: list[Path] = []
        for i, shot in enumerate(shots):
            if shot["type"] == "singer":
                keyframes.append(chosen_portrait)
                continue
            prompt = (
                f"{shot['prompt']}. Consistent character: {sb['singer_desc']}. "
                "Cinematic film still, no text, no watermark."
            )
            wf = zimage_workflow(prompt, width=self.s.width, height=self.s.height,
                                 seed=state.seed + i * 7,
                                 prefix=f"echoloom/{state.id}/kf")
            outs = self.comfy.run(wf, poll=2.0, timeout=900)
            dest = self.comfy.fetch(outs[0], kf_dir / f"shot_{i + 1:02d}.png")
            keyframes.append(dest)
            self.progress("compose", f"关键帧 {i + 1}/{len(shots)}", 0.34 + 0.10 * (i + 1) / len(shots))

        # 3) i2v 逐镜（singer 镜头用肖像出动态底版）
        clip_dir = self._dir(project_dir, "shots", "clips")
        clips: list[Path] = []
        for i, (shot, kf) in enumerate(zip(shots, keyframes)):
            up = self.comfy.upload_image(kf)
            motion = self._motion_prompt(shot, sb)
            wf = h3_i2v_workflow(up, motion, seed=state.seed + i * 13,
                                 frames=frames_for(durs[i], self.s.fps),
                                 width=self.s.width, height=self.s.height,
                                 prefix=f"echoloom/{state.id}/i2v")
            outs = self.comfy.run(wf, poll=5.0, timeout=7200)
            dest = clip_dir / f"shot_{i + 1:02d}.mp4"
            self.comfy.fetch(outs[0], dest)
            clips.append(dest)
            self.progress("compose", f"图生视频 {i + 1}/{len(shots)}", 0.44 + 0.26 * (i + 1) / len(shots))

        # 4) 分轨 + 母带
        self.progress("compose", "Demucs 分轨…", 0.72)
        stems = separate_vocals(str(ROOT_VENV_PY), song, self._dir(project_dir, "stems"))
        self.progress("compose", "母带 loudnorm…", 0.76)
        master, _ = master_audio(self.s.ffmpeg_bin, song,
                                 self._dir(project_dir, "final") / "master.flac")

        # 5) 歌手镜头对口型（用 vocals 分轨）
        lipsync_dir = self._dir(project_dir, "shots", "lipsync")
        for i, (shot, clip) in enumerate(zip(shots, clips)):
            if shot["type"] != "singer":
                continue
            from .lipsync import run_lip_sync
            out = lipsync_dir / f"shot_{i + 1:02d}.mp4"
            run_lip_sync(stems["vocals"], clip, out, settings=self.s)
            clips[i] = out
            self.progress("compose", f"对口型 {i + 1} 完成", 0.80)

        # 6) ASS：ASR 字级时间戳 + 歌词对齐
        self.progress("compose", "ASR 字级对齐…", 0.84)
        asr = transcribe_wav(stems["vocals"], asr_dir=self.s.qwen3_asr_dir,
                             aligner_dir=self.s.qwen3_aligner_dir,
                             language=state.language,
                             hotwords=lyrics.replace("\n", " ")[:400])
        lines = [ln for ln in lyrics.replace("\r\n", "\n").split("\n") if ln.strip()
                 and not ln.strip().startswith("[")]
        timed = align_lines(lines, asr["words"], total_sec=song_dur)
        style = AssStyle(**(state.ass_style or {}))
        ass_path = self._dir(project_dir, "ass") / "final.ass"
        ass_path.write_text(
            build_ass(style, timed, play_res_x=self.s.width, play_res_y=self.s.height,
                      title=state.title), encoding="utf-8")
        (self._dir(project_dir, "ass") / "timed.json").write_text(
            json.dumps(timed, ensure_ascii=False, indent=1), encoding="utf-8")

        # 7) 镜头装配 + xfade + 烧字
        self.progress("compose", "装配时间线…", 0.88)
        workdir = self._dir(project_dir, "final", "segs")
        padded = [d + xfade_t for d in durs[:-1]] + [durs[-1]]
        segs: list[Path] = []
        for i, (clip, d) in enumerate(zip(clips, padded)):
            segs.append(build_clip(clip, workdir / f"seg_{i:02d}.mp4", dur=d,
                                   w=self.s.width, h=self.s.height, fps=self.s.fps,
                                   nvenc=self.nvenc))
        body = workdir / "body.mp4"
        run(xfade_concat_cmd(segs, body, durs=padded, t=xfade_t, nvenc=self.nvenc))
        self.progress("compose", "烧字幕合成成片…", 0.94)
        final = self._dir(project_dir, "final") / "mv.mp4"
        run(burn_cmd(self.s.ffmpeg_bin, body, master, final, ass_path=ass_path,
                     title=state.title, total=song_dur, w=self.s.width, h=self.s.height,
                     nvenc=self.nvenc))
        self.progress("compose", f"成片完成 {final}", 1.0)
        return final

    # ---- 内部 -----------------------------------------------------------------
    def _chosen_portrait(self, state: ProjectState, portraits_dir: Path) -> Path:
        payload = state.gates["portrait"].approved_payload or []
        # UI 允许从候选中挑一张：payload 可以是 ["candidate_1.png"] 或 ["candidate_2.png"]
        name = payload[0] if payload else "candidate_1.png"
        return portraits_dir / name

    def _motion_prompt(self, shot: dict[str, Any], sb: dict[str, Any]) -> str:
        if shot["type"] == "singer":
            return (
                f"{shot['prompt']} The singer sings passionately with expressive mouth movement, "
                "steady camera, cinematic."
            )
        return f"{shot['prompt']}"
