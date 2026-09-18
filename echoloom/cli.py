"""EchoLoom 命令行。

  python -m echoloom run --theme "..."   一键全自动出片（关卡自动放行）
  python -m echoloom serve               启动 Web 工作台 (localhost:8199)
  python -m echoloom smoke t2i|music|i2v|asr|lipsync   分引擎冒烟
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _run(args: argparse.Namespace) -> int:
    from echoloom.comfy import ComfyClient
    from echoloom.config import get_settings
    from echoloom.llm import ZhipuClient
    from echoloom.pipeline import Pipeline
    from echoloom.state import ProjectStatus, new_project

    s = get_settings()
    lyrics_text = Path(args.lyrics_file).read_text(encoding="utf-8") if args.lyrics_file else ""
    state = new_project(args.theme or "未命名", target_sec=args.target_sec,
                        seed=args.seed, auto_approve=True)
    proj_dir = s.output_root / state.id
    proj_dir.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, msg: str, pct: float) -> None:
        print(f"[{stage:<10}] {pct*100:5.1f}%  {msg}", flush=True)

    pipe = Pipeline(
        s,
        ZhipuClient(s.zhipuai_api_key, model=s.llm_model),
        ComfyClient(s.comfyui_url),
        progress=progress,
    )
    t0 = time.time()
    try:
        if lyrics_text:
            from echoloom.prompts import validate_lyrics
            state.submit("lyrics", validate_lyrics(lyrics_text), note="user")
        else:
            pipe.make_lyrics(state, proj_dir)
        pipe.make_storyboard(state, proj_dir)
        pipe.make_portraits(state, proj_dir)
        pipe.make_song(state, proj_dir)
        final = pipe.compose_final(state, proj_dir)
        state.status = ProjectStatus.done
        state.save(proj_dir / "state.json")
        print(f"\n✅ 成片: {final}  (总耗时 {(time.time()-t0)/60:.1f} 分钟)")
        return 0
    except Exception as e:
        state.error = f"{type(e).__name__}: {e}"
        state.save(proj_dir / "state.json")
        print(f"\n❌ 失败: {state.error}", file=sys.stderr)
        raise


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from echoloom.config import get_settings

    s = get_settings()
    uvicorn.run("server.app:app", host=args.host or s.host, port=args.port or s.port,
                log_level="info")
    return 0


def _smoke(args: argparse.Namespace) -> int:
    import subprocess

    script = {"t2i": ["scripts/smoke_comfy.py", "t2i"],
              "music": ["scripts/smoke_comfy.py", "music"],
              "i2v": ["scripts/smoke_comfy.py", "i2v"],
              "asr": ["scripts/smoke_asr.py"],
              "lipsync": ["scripts/smoke_lipsync.py"]}[args.stage]
    return subprocess.run([sys.executable, *script]).returncode


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="echoloom", description="本地 AI MV 流水线")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="全自动出片")
    r.add_argument("--theme", default="", help="歌曲主题（一句话）")
    r.add_argument("--lyrics-file", default="", help="已有歌词文本文件路径（跳过写词）")
    r.add_argument("--target-sec", type=int, default=180)
    r.add_argument("--seed", type=int, default=None)
    r.set_defaults(fn=_run)

    v = sub.add_parser("serve", help="启动 Web 工作台")
    v.add_argument("--host", default=None)
    v.add_argument("--port", type=int, default=None)
    v.set_defaults(fn=_serve)

    sm = sub.add_parser("smoke", help="分引擎冒烟测试")
    sm.add_argument("stage", choices=["t2i", "music", "i2v", "asr", "lipsync"])
    sm.set_defaults(fn=_smoke)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
