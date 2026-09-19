#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""口型返工：修复"整条人声轨从 0 秒对口型"的切片 bug，并做 wav2lip(修复版) vs H3 Ref2VA 的 A/B 对比。

  python scripts/rework_lipsync.py <project_id> ab [shot_count]     # 抽样对比+指标
  python scripts/rework_lipsync.py <project_id> apply wav2lip|r2v   # 全量应用+重装配
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from echoloom.align import align_lines  # noqa: E402  ( noqa )
from echoloom.ass_style import AssStyle  # noqa: E402
from echoloom.comfy import ComfyClient  # noqa: E402
from echoloom.config import get_settings  # noqa: E402
from echoloom.lipsync import run_lip_sync  # noqa: E402
from echoloom.mv import (  # noqa: E402
    build_clip,
    burn_cmd,
    has_nvenc,
    probe_sec,
    run,
    xfade_concat_cmd,
    xfade_offsets,
)
from echoloom.state import ProjectState  # noqa: E402
from echoloom.workflows import h3_r2v_workflow  # noqa: E402

FPS = 24


def timeline(state: ProjectState, d: Path):
    """复现 compose_final 的时间轴数学。"""
    sb = state.gates["storyboard"].approved_payload
    song = d / "audio" / state.gates["audio"].approved_payload
    s = get_settings()
    song_dur = probe_sec(s.ffprobe_bin, song)
    xfade_t = 0.5
    shots = sb["shots"]
    sb_total = sum(float(x["duration"]) for x in shots)
    scale = song_dur / sb_total
    durs = [float(x["duration"]) * scale for x in shots]
    padded = [x + xfade_t for x in durs[:-1]] + [durs[-1]]
    offsets = [0.0] + xfade_offsets(padded, xfade_t)
    return sb, song, song_dur, xfade_t, shots, durs, padded, offsets


def vocals_slice(vocals: Path, dest: Path, a0: float, a1: float) -> Path:
    s = get_settings()
    run([s.ffmpeg_bin, "-y", "-v", "error", "-i", str(vocals),
         "-ss", f"{a0:.3f}", "-to", f"{a1:.3f}", "-ac", "1", "-ar", "16000", str(dest)])
    return dest


def lipsync_metric(video: Path, audio: Path) -> float:
    """嘴部运动能量与响度包络的 Pearson 相关（越高口型同步越好）。"""
    s = get_settings()
    raw = subprocess.run(
        [s.ffmpeg_bin, "-v", "error", "-i", str(video), "-f", "rawvideo",
         "-pix_fmt", "gray", "-"], capture_output=True, timeout=300).stdout
    frame = numpy.frombuffer(raw, dtype=numpy.uint8)
    n_frames = len(raw) // (1344 * 768)
    if n_frames < 8:
        return float("nan")
    g = frame[: n_frames * 1344 * 768].reshape(n_frames, 768, 1344)
    mouth = g[:, int(768 * 0.52):int(768 * 0.82), int(1344 * 0.32):int(1344 * 0.68)]
    energy = numpy.abs(numpy.diff(mouth.astype(numpy.float32).mean(axis=(1, 2))))
    araw = subprocess.run(
        [s.ffmpeg_bin, "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1",
         "-ar", "16000", "-"], capture_output=True, timeout=120).stdout
    a = numpy.frombuffer(araw, dtype=numpy.int16).astype(numpy.float32) / 32768.0
    blocks = numpy.array_split(a, n_frames)
    loud = numpy.array([numpy.sqrt(numpy.mean(b ** 2)) if len(b) else 0.0 for b in blocks])[: n_frames - 1]
    if loud.std() < 1e-6 or energy.std() < 1e-6:
        return 0.0
    return float(numpy.corrcoef(energy, loud)[0, 1])


def make_wav2lip(vocals: Path, shot_clip: Path, a0: float, a1: float, dest: Path, tmp: Path) -> Path:
    s = get_settings()
    sl = vocals_slice(vocals, tmp / f"{dest.stem}_slice.wav", a0, a1)
    return run_lip_sync(sl, shot_clip, dest, settings=s)


def make_r2v(client: ComfyClient, portrait_land: Path, vocals: Path, dest: Path,
             a0: float, a1: float, tmp: Path, seed: int, state_id: str) -> Path:
    s = get_settings()
    sl = vocals_slice(vocals, tmp / f"{dest.stem}_slice.wav", a0, a1)
    up_img = client.upload_image(portrait_land)
    up_aud = client.upload_image(sl)  # /upload/image 也接受音频文件
    dur = a1 - a0
    frames = max(17, round(dur * FPS))
    frames += 17 - frames % 17
    wf = h3_r2v_workflow(
        up_img, up_aud,
        "The singer sings this exact audio passage to camera with expressive mouth movements "
        "precisely synchronized to the Mandarin song audio, subtle gestures on the beat, "
        "steady camera, cinematic stage lighting.",
        seed=seed, frames=frames, prefix=f"echoloom/{state_id}/r2v")
    outs = client.run(wf, poll=5.0, timeout=7200)
    return client.fetch(outs[0], dest)


def main() -> int:
    pid = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "ab"
    s = get_settings()
    d = s.output_root / pid
    state = ProjectState.load(d / "state.json")
    sb, song, song_dur, xfade_t, shots, durs, padded, offsets = timeline(state, d)
    stems = next((d / "stems" / "htdemucs").glob("*/vocals.wav"))
    portraits = d / "portraits"
    chosen = (state.gates["portrait"].approved_payload or ["candidate_1.png"])[0]
    portrait = portraits / chosen
    clips_dir = d / "shots" / "clips"
    singer_idx = [i for i, x in enumerate(shots) if x["type"] == "singer"]
    print(f"project {pid}: {len(shots)} shots, {len(singer_idx)} singer shots, song {song_dur:.1f}s")

    if mode == "ab":
        sample = singer_idx[: min(2, len(singer_idx))]
        client = ComfyClient(s.comfyui_url)
        tmp = d / "shots" / "ab"
        tmp.mkdir(parents=True, exist_ok=True)
        report = {}
        for i in sample:
            a0, a1 = max(0.0, offsets[i] - 0.25), min(song_dur, offsets[i] + durs[i] + 0.25)
            src = clips_dir / f"shot_{i + 1:02d}.mp4"
            old = src  # 旧版（错位）的 lipsync 结果
            w = make_wav2lip(stems, src, a0, a1, tmp / f"shot_{i + 1:02d}_w.mp4", tmp)
            r = make_r2v(client, portrait, stems, tmp / f"shot_{i + 1:02d}_r.mp4",
                         a0, a1, tmp, state.seed + i * 31, pid)
            m_old = lipsync_metric(old, tmp / f"shot_{i + 1:02d}_w_slice.wav")
            m_w = lipsync_metric(w, tmp / f"shot_{i + 1:02d}_w_slice.wav")
            m_r = lipsync_metric(r, tmp / f"shot_{i + 1:02d}_r_slice.wav")
            report[i] = {"old": m_old, "wav2lip_fixed": m_w, "r2v": m_r}
            print(f"shot#{i + 1}: old={m_old:.3f} wav2lip_fixed={m_w:.3f} r2v={m_r:.3f}", flush=True)
        (d / "shots" / "ab" / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("A/B 报告 ->", d / "shots" / "ab" / "report.json")
        return 0

    if mode == "apply":
        method = sys.argv[3] if len(sys.argv) > 3 else "wav2lip"
        client = ComfyClient(s.comfyui_url)
        tmp = d / "shots" / "ab"
        tmp.mkdir(parents=True, exist_ok=True)
        out_dir = d / "shots" / "lipsync_v2"
        out_dir.mkdir(parents=True, exist_ok=True)
        kf_dir = d / "shots" / "keyframes"
        for n, i in enumerate(singer_idx):
            a0, a1 = max(0.0, offsets[i] - 0.25), min(song_dur, offsets[i] + durs[i] + 0.25)
            src = clips_dir / f"shot_{i + 1:02d}.mp4"
            dest = out_dir / f"shot_{i + 1:02d}.mp4"
            t0 = time.time()
            if method == "r2v":
                land = kf_dir / f"portrait_land_{i + 1:02d}.png"
                if not land.exists():
                    land = portrait
                make_r2v(client, land, stems, dest, a0, a1, tmp, state.seed + i * 31, pid)
            else:
                make_wav2lip(stems, src, a0, a1, dest, tmp)
            print(f"[{n + 1}/{len(singer_idx)}] shot#{i + 1} {method} {time.time() - t0:.0f}s", flush=True)

        # 用新镜头重装配：singer 用 lipsync_v2，其余沿用原 clips；重新裁剪+xfade+烧字
        clips = []
        for i, x in enumerate(shots):
            src = (out_dir / f"shot_{i + 1:02d}.mp4") if x["type"] == "singer" else (clips_dir / f"shot_{i + 1:02d}.mp4")
            clips.append(src)
        workdir = d / "final" / "segs_v2"
        workdir.mkdir(parents=True, exist_ok=True)
        nvenc = has_nvenc(s.ffmpeg_bin)
        segs = []
        for i, (clip, dur) in enumerate(zip(clips, padded)):
            segs.append(build_clip(clip, workdir / f"seg_{i:02d}.mp4", dur=dur,
                                   w=s.width, h=s.height, fps=FPS, nvenc=nvenc))
        body = workdir / "body.mp4"
        run(xfade_concat_cmd(segs, body, durs=padded, t=xfade_t, nvenc=nvenc))
        ass_path = d / "ass" / "final.ass"
        master = d / "final" / "master.flac"
        final = d / "final" / "mv_v2.mp4"
        run(burn_cmd(s.ffmpeg_bin, body, master, final, ass_path=ass_path,
                     title=state.title, total=song_dur, w=s.width, h=s.height, nvenc=nvenc))
        print(f"✅ v2 成片: {final}")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
