#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E2E 驱动：对指定项目走完四关卡+合成。开发代理充当确认人。

python scripts/e2e_walk.py <project_id> [--timeout 7200]
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8199"


def req(path, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


def main():
    pid = sys.argv[1]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 7200.0
    t0 = time.time()
    for gate, prev in [("lyrics", None), ("storyboard", "lyrics"), ("portrait", "storyboard"),
                       ("audio", "portrait")]:
        while True:
            p = req(f"/api/projects/{pid}")
            if p["error"]:
                print(f"❌ 项目错误: {p['error'][:300]}", flush=True)
                return 3
            if p["gates"][gate]["versions"]:
                break
            print(f"[{time.time()-t0:5.0f}s] 等待 {gate} 生成…", flush=True)
            time.sleep(10)
        ver = p["gates"][gate]["versions"][-1]["id"]
        p = req(f"/api/projects/{pid}/gates/{gate}/approve", "POST", {"version": ver})
        print(f"[{time.time()-t0:5.0f}s] ✓ 确认 {gate} v{ver}", flush=True)
        if gate == "audio":
            print(f"    音频: {p['gates']['audio']['versions'][-1].get('note')}", flush=True)

    p = req(f"/api/projects/{pid}/compose", "POST", {})
    print(f"[{time.time()-t0:5.0f}s] ▶ 合成已提交", flush=True)
    while time.time() - t0 < timeout:
        p = req(f"/api/projects/{pid}")
        if p.get("final"):
            print(f"🎬 成片: {p['final']}  (总耗时 {(time.time()-t0)/60:.1f} 分钟)", flush=True)
            return 0
        if p.get("error"):
            print(f"❌ 合成失败: {p['error'][:400]}", flush=True)
            return 3
        time.sleep(15)
    print("超时", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
