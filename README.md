# EchoLoom 🎬

开源本地 AI MV 流水线：一句话主题 → 歌词 → 作曲（MiniMax Music3）→ 分镜 → 歌手肖像（Z-Image）
→ 图生视频（MiniMax H3）→ 对口型（FaceFusion）→ karaoke 字幕（Qwen3-ASR 字级对齐 + ASS）
→ 母带 + 合成（ffmpeg）→ 完整 MV。

全流程本地算力（RTX 5070 Ti 16GB 验证），LLM 步骤用智谱 GLM 线上 API。

> 开发中，README 将在交付时补全。
