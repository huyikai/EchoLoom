"""ffmpeg 合成构建器：纯函数造命令（可快照测试），run_* 负责执行。

时间轴数学：xfade 每个接缝吃掉 t 秒，所以除最后一个镜头外每个镜头多生成 t 秒素材
（plan_durations），保证拼接后总时长等于歌曲时长。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class FfmpegError(RuntimeError):
    pass


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise FfmpegError(f"命令失败 ({p.returncode}): {' '.join(cmd[:6])}...\n{p.stderr[-1500:]}")
    return p


# ---------------------------------------------------------------------------
# 探测
# ---------------------------------------------------------------------------

def probe_sec(ffprobe: str, file: Path) -> float:
    p = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise FfmpegError(f"ffprobe 失败: {p.stderr[:300]}")
    return float(json.loads(p.stdout)["format"]["duration"])


# ---------------------------------------------------------------------------
# 镜头级
# ---------------------------------------------------------------------------

def enc_args(nvenc: bool = True) -> list[str]:
    return (["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"] if nvenc
            else ["-c:v", "libx264", "-preset", "medium", "-crf", "20"])


def trim_clip_cmd(src: Path, dest: Path, *, dur: float, w: int, h: int, fps: int,
                  nvenc: bool = True) -> list[str]:
    return [
        "ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", f"{dur:.3f}",
        "-vf", f"scale={w}:{h}:flags=lanczos,fps={fps},format=yuv420p",
        *enc_args(nvenc), "-an", str(dest),
    ]


def still_zoom_cmd(still: Path, dest: Path, *, dur: float, w: int, h: int, fps: int,
                   nvenc: bool = True) -> list[str]:
    n = int(round(dur * fps))
    return [
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(fps), "-i", str(still),
        "-vf", f"scale={w}:{h},zoompan=z='1+0.0004*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
               f"d={n}:s={w}x{h}:fps={fps},format=yuv420p",
        "-frames:v", str(n), *enc_args(nvenc), "-an", str(dest),
    ]


def concat_cmd(files: list[Path], dest: Path, listfile: Path) -> list[str]:
    listfile.parent.mkdir(parents=True, exist_ok=True)
    listfile.write_text(
        "\n".join(f"file '{f.as_posix()}'" for f in files), encoding="utf-8"
    )
    return ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(dest)]


# ---------------------------------------------------------------------------
# xfade 时间轴
# ---------------------------------------------------------------------------

def plan_durations(section_durs: list[float], xfade_t: float) -> list[float]:
    """歌曲段落时长 → 每镜头素材时长（除最后一个外 +xfade_t 补偿）。"""
    if len(section_durs) <= 1:
        return list(section_durs)
    return [d + xfade_t for d in section_durs[:-1]] + [section_durs[-1]]


def xfade_offsets(durs: list[float], t: float) -> list[float]:
    """每个接缝的 xfade offset（相对累积时间线）。"""
    offsets: list[float] = []
    acc = durs[0] if durs else 0.0
    for d in durs[1:]:
        acc -= t
        offsets.append(round(acc, 3))
        acc += d
    return offsets


def xfade_filter(n: int, durs: list[float], t: float, transition: str = "fade") -> str:
    """n 个输入的 xfade filter_complex。"""
    if n < 2:
        return "[0:v]copy[v]"
    offsets = xfade_offsets(durs, t)
    chains: list[str] = []
    for i in range(n - 1):
        in_a = f"[{i}:v]" if i == 0 else f"[vx{i}]"
        in_b = f"[{i + 1}:v]"
        out = "[v]" if i == n - 2 else f"[vx{i + 1}]"
        chains.append(
            f"{in_a}{in_b}xfade=transition={transition}:duration={t}:offset={offsets[i]}{out}"
        )
    return ";".join(chains)


def xfade_concat_cmd(files: list[Path], dest: Path, *, durs: list[float], t: float,
                     transition: str = "fade", nvenc: bool = True) -> list[str]:
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in files:
        cmd += ["-i", str(f)]
    cmd += ["-filter_complex", xfade_filter(len(files), durs, t, transition), "-map", "[v]"]
    cmd += enc_args(nvenc) + ["-an", str(dest)]
    return cmd


# ---------------------------------------------------------------------------
# 母带 / 烧字合成
# ---------------------------------------------------------------------------

def master_pass1_cmd(ff: str, src: Path) -> list[str]:
    return ["ffmpeg", "-y", "-v", "info", "-i", str(src),
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]


def parse_loudnorm_measures(log: str) -> dict[str, float]:
    start = log.rfind("{")
    end = log.rfind("}")
    if start == -1 or end == -1:
        raise FfmpegError("loudnorm 输出中找不到测量 JSON")
    data = json.loads(log[start : end + 1])
    return {k: float(v) for k, v in data.items()
            if k in ("input_i", "input_tp", "input_lra", "input_thresh")
            and v not in ("", "-inf", "inf")}


def master_pass2_cmd(ff: str, src: Path, dest: Path, m: dict[str, float]) -> list[str]:
    af = (
        f"loudnorm=I=-14:TP=-1.5:LRA=11:"
        f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
        "linear=true"
    )
    return ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af,
            "-ar", "48000", "-c:a", "flac", str(dest)]


def _escape_path(p: Path | str) -> str:
    return Path(p).as_posix().replace(":", "\\:")


def burn_cmd(ff: str, video: Path, audio: Path, dest: Path, *, ass_path: Path | None,
             title: str | None = None, total: float, w: int, h: int,
             nvenc: bool = True) -> list[str]:
    vf: list[str] = []
    if title:
        size = max(40, int(h * 0.08))
        vf.append(
            f"drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':text='{title}':fontsize={size}:"
            "fontcolor=white:borderw=2:x=(w-text_w)/2:y=h*0.30:"
            "alpha='if(lt(t,0.8),t/0.8,if(lt(t,4.5),1,max(0,(6.5-t)/2)))'"
        )
    if ass_path is not None:
        vf.append(f"subtitles=filename='{_escape_path(ass_path)}'")
    vf.append(f"fade=t=out:st={max(0.0, total - 2.4)}:d=2.4")
    return [
        "ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio),
        "-vf", ",".join(vf),
        *enc_args(nvenc), "-c:a", "aac", "-b:a", "256k",
        "-af", f"afade=t=out:st={max(0.0, total - 3.0)}:d=3.0",
        "-shortest", str(dest),
    ]


# ---------------------------------------------------------------------------
# 执行封装
# ---------------------------------------------------------------------------

def has_nvenc(ff: str = "ffmpeg") -> bool:
    try:
        p = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        return "h264_nvenc" in p.stdout
    except Exception:
        return False


def build_clip(src: Path, dest: Path, *, dur: float, w: int, h: int, fps: int,
               nvenc: bool = True) -> Path:
    """视频镜头裁剪；src 不存在或不可解码时退化为静图缓推。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(trim_clip_cmd(src, dest, dur=dur, w=w, h=h, fps=fps, nvenc=nvenc))
        return dest
    except FfmpegError:
        run(still_zoom_cmd(src, dest, dur=dur, w=w, h=h, fps=fps, nvenc=nvenc))
        return dest


def assemble_timeline(clips: list[Path], durs: list[float], workdir: Path, dest: Path, *,
                      xfade_t: float, transition: str = "fade", nvenc: bool = True) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    if xfade_t > 0 and len(clips) > 1:
        run(xfade_concat_cmd(clips, dest, durs=durs, t=xfade_t, transition=transition, nvenc=nvenc))
    else:
        run(concat_cmd(clips, dest, workdir / "concat.txt"))
    return dest
