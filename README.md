# EchoLoom 🎬

**开源本地 AI MV 流水线** —— 一句话主题，在你的显卡上织出一支完整 MV：

```mermaid
主题 ─▶ ①歌词(智谱GLM) ─▶ ②分镜脚本 ─▶ ③歌手肖像(Z-Image) ─▶ ④整曲(MiniMax Music3)
                     └─────────── 全部确认 ───────────┘
                                  ▼
   分镜图(Z-Image) → 图生视频(MiniMax H3) → 对口型(FaceFusion) → 分轨(Demucs)
   → 母带(loudnorm) → karaoke 字幕(Qwen3-ASR 字级对齐 + ASS) → 合成烧字(ffmpeg) → mv.mp4
```

- **四个人工确认关卡**：歌词 / 分镜脚本 / 歌手肖像 / 整曲，每关可查看、编辑、换版本重生成、确认放行；
  全部确认后一键合成。也支持「自动放行」全自动直出。
- **karaoke 字幕**：Qwen3-ASR + ForcedAligner 字级时间戳，逐字 `\k` 高亮，样式（字体/字号/颜色/描边/
  逐字逐行/边距）在 UI 实时预览，合成时由 libass 烧录。
- **全程本地算力**（开发验证环境：RTX 5070 Ti 16GB / 32GB RAM），LLM 步骤用智谱 GLM 线上 API。

## 快速开始

```powershell
# 1) 环境（Python 3.12 + Node 18+）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[pipeline,server,facefusion,dev]" -i https://mirrors.aliyun.com/pypi/simple/
cd web && npm install --registry=https://registry.npmmirror.com && npm run build && cd ..

# 2) 配置 .env（参考下文），FaceFusion 首跑自动下载 lip 模型(~200MB)

# 3) 一键启动（自动拉起 ComfyUI + Web 工作台）
.\scripts\start_all.ps1
# 浏览器打开 http://127.0.0.1:8199
```

CLI 直出（跳过人工确认）：

```bash
python -m echoloom run --theme "深夜城市里独行的旅人" --target-sec 180
```

### .env

```ini
ZHIPUAI_API_KEY=你的智谱key        # https://open.bigmodel.cn
COMFYUI_URL=http://127.0.0.1:8188
FACEFUSION_ROOT=D:/develop/facefusion
QWEN3_ASR_DIR=D:/develop/vrs-runtime/models/qwen3-asr
QWEN3_ALIGNER_DIR=D:/develop/vrs-runtime/models/qwen3-forcedaligner
DEFAULT_SONG_SEC=180
```

## 引擎与模型

| 环节 | 引擎 | 模型 / 说明 |
|---|---|---|
| 写词/分镜/caption | 智谱 GLM | `glm-4.6`，输出严格遵循 [官方提示词格式](docs/prompt-formats.md) |
| 文生音乐 | MiniMax **Music3**（ComfyUI 原生节点） | INT8 三件套，实测 `max_duration` 上限 360s，默认 180s |
| 文生图 | Z-Image Turbo | 8 步蒸馏，肖像 768×1024 / 分镜 1344×768 |
| 图生视频 | MiniMax **H3** i2v | Turbo LoRA 6 步，~5s/镜头，24fps，帧数 5 的倍数 |
| 对口型 | H3 Ref2VA 声画同步（主）/ FaceFusion lip_syncer（备） | r2v_locked 配方：锁定构图 prompt + `ref_image_size=max` + 44.1k 立体声切片，Mandarin 口型原生生成；wav2lip_gan_96 仅作快速备选（96px 贴回，中文口型贴合差）。edtalk_256 实测推理过慢弃用 |
| 分轨 | Demucs | htdemucs，vocals / no_vocals |
| 歌词时间戳 | Qwen3-ASR-1.7B + ForcedAligner-0.6B | 字级对齐，difflib 匹配 + 线性插值兜底 |
| 母带 | ffmpeg loudnorm 两遍 | -14 LUFS / TP -1.5 / 48kHz |
| 合成 | ffmpeg | 分镜时长等比缩放到曲长 → xfade 0.5s → ASS 烧字 → NVENC |

ComfyUI 任务经 8188 API 串行提交；ASR/Demucs/FaceFusion 与 ComfyUI 错峰使用显存。

## 测试

```bash
.venv\Scripts\python.exe -m pytest tests -q          # 49 个单元/契约/集成测试
python -m echoloom smoke t2i|music|i2v|asr|lipsync   # 分引擎真机冒烟（需 ComfyUI）
python scripts/e2e_walk.py <project_id>              # API 驱动走完四关卡+合成
```

TDD 覆盖：状态机（关卡锁/版本历史/自动放行）、提示词格式校验（对齐官方规范）、
ASS `\k` 时间轴数学、歌词-ASR 对齐（精确/误听/兜底三档）、ffmpeg 命令快照、
xfade 偏移数学、ComfyUI 工作流图结构、FastAPI 契约（TestClient）。

## 项目结构

```
echoloom/   pipeline 核心（llm/comfy/workflows/asr/align/ass_style/audio/lipsync/mv/pipeline/state）
server/     FastAPI：关卡 API + SSE 进度 + 字幕实时预览 + 产物托管
web/        React+Vite+TS 前端（暗色录音棚设计系统）
scripts/    start_all.ps1 / smoke_* / e2e_walk.py
docs/       prompt-formats.md（官方提示词规范）/ ui-iterations/
```

## 设计说明

- 前端为手写 CSS 设计系统（`web/src/styles.css` 设计令牌），未用组件库模板，
  舞台琥珀单强调色 + 暗色录音棚质感；每轮视觉迭代截图存档于 `docs/ui-iterations/`。
- 人工确认关卡是**产品功能**：服务端 `state.json` 持久化 + 版本不可变（重生成不动已确认版本），
  重启可续作；关卡确认后自动串链下一阶段。

## 路线图

- [ ] >3 分钟歌曲（Music3 AR 续写 `comfy/ldm/minimax_music/ar.py`）
- [ ] 竖屏模板（抖音 9:16）
- [ ] 歌手镜头备选路径：~~H3 Ref2VA 声画同步生成~~（已落地为默认口型方案，见上表）
- [ ] FaceFusion wav2lip 快速备选的质量增强（超分嘴部区域）
- [ ] ACE-Step 备选音乐引擎（本机权重已就位）
- [ ] SCAIL 舞蹈复刻镜头、声音克隆

## 致谢

[ComfyUI](https://github.com/comfyanonymous/ComfyUI) · [MiniMax H3/Music3 开放权重](https://huggingface.co/Comfy-Org) ·
[Z-Image](https://huggingface.co/Tongyi-MAI) · [FaceFusion](https://github.com/facefusion/facefusion) ·
[Demucs](https://github.com/adefossez/demucs) · [Qwen3-ASR](https://huggingface.co/Qwen) ·
[智谱开放平台](https://open.bigmodel.cn)。ASR 推理实现参考了本机
video-remake-studio 项目的工程实践（transformers 5.x + numpy 传参）。

## License

MIT（各引擎模型遵循其原始许可证，Music3/kim_vocal_2 等注意非商用条款）
