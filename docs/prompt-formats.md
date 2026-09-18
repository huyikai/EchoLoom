# EchoLoom 官方提示词格式规范

> 本文是 LLM 生成 prompt 的**权威依据**（`echoloom/prompts.py` 的 system prompt 由本文派生，
> `tests/test_prompts.py` 断言输出符合本文格式）。
> 格式来源：本机已跑通的 ground truth（`baoshu-gospel/wf_music3.json` 生成过 180s 成曲、
> `studebaker-gospel/PROMPTS.md` + `gen_i2v.py` 生成过 4 段 H3 动态镜头）＋ ComfyUI 官方文档。

---

## 一、MiniMax Music3 — 结构化 caption（英文）

caption 为**英文**，固定三段结构，段与段之间空行，段首用固定前缀：

```
Global Metadata: <风格定位, 演出形态, BPM, 拍号, 调性, 目标时长(about N minutes/specific seconds), 空间感/混响/立体声>

Vocal Details: <是否全程演唱(never spoken), 人数与声部, 每个声部的性别/年龄/音色/气质, 语言与咬字,
副歌和声安排, 现场氛围(观众掌声等), 真人质感声明(no robotic AI voice, no spoken word, no rap, no narration)>

Arrangement: <主奏乐器逐项, 各段落动态安排(verse restrained / chorus explode / outro ritardando),
no over-compression, preserve live dynamics, 48kHz hi-fi fidelity>
```

规则：
1. **全部英文**；中文歌也在 Vocal Details 里写 `singing in Mandarin with clear articulation`。
2. 三段前缀逐字固定：`Global Metadata: ` / `Vocal Details: ` / `Arrangement: `。
3. 时长写在 Global Metadata 里（`about 3 minutes`）；真正控制时长用节点参数 `max_duration`。
4. 结尾固定声明：`No over-compression, preserve live dynamics. 48kHz hi-fi fidelity.`

### 歌词（lyrics 输入，中文）

用**分段标签**结构，标签行独立成行，段内歌词按乐句空行分组：

```
[Intro]
[Instrumental]

[Verse]
<乐句>
<乐句>

[Pre-Chorus]
...

[Chorus]
...

[Verse]
...

[Chorus]
...

[Outro]
<收尾句>
```

规则：标签用 `[Intro]` `[Verse]` `[Pre-Chorus]` `[Chorus]` `[Bridge]` `[Outro]`（可加 `[Instrumental]`、
`[间奏]` 等中文备注标签——ground truth 中 `[Intro 器乐]` 亦有效，但 MVP 统一用英文标准标签）；
副歌重复要**完整重复写出**（不要写"重复副歌"）；口吻/语气词保留（增强演唱语气）。

### 节点参数（本机 8188 实测 schema）

| 参数 | 默认 | 说明 |
|---|---|---|
| `max_duration` | 120 | **实测上限 360s**；180s 中文歌默认值；模型可能提前结束 |
| `cfg_scale` | 1.5 | ground truth 用 1.7 |
| `top_k` | 50 | — |
| `seed` | 0 | 固定可复现 |
| 采样 | KSampler: euler/simple, **steps 30**, cfg 1.7, denoise 1.0 | ground truth |
| 负条件 | `ConditioningZeroOut(positive)` | ground truth |
| latent | `EmptyMiniMaxMusic3LatentAudio(seconds=["TextEncode",1])` | 秒数引用 TextEncode 输出的第二槽 |
| 解码 | `VAEDecodeAudioTiled(tile_size=1536, overlap=64)` | ground truth |
| 保存 | `SaveAudioAdvanced(format="flac")` | — |

---

## 二、MiniMax H3 — 图生视频提示词（英文）

分镜画面 prompt 为**英文**，写法（ground truth 四段例句的共性）：

```
<镜头运动 Slow dolly forward / Handheld push-in / Slow lateral tracking / Very slow pull-back>
<主体与动作描述，具体到人物姿态、道具、环境反应>
<氛围与光效 dust drifting in the light beam, golden stage lights flare>
<风格收尾 Cinematic, solemn, steady camera. / slight camera shake / shallow depth of field / gentle film grain>
```

规则：
1. 一条镜头一个**连贯动作**，时长 ~5s（可被镜头运动动词约束：slow/steady）。
2. 人物外貌要**逐字复用歌手形象描述**（跨镜头一致性）。
3. 不写对话/歌词内容（H3 会生成同步音频，但 MV 合成时音轨用母带，视频 `-an` 静音铺底）。
4. `MiniMaxH3ImageToVideo` 参数：`width=1344, height=768`，`length=帧数`（24fps，
   **必须是 5 的倍数**，`n=max(5, round(sec*24))` 向上取整到 5）；`first_frame=LoadImage`。
5. 加速：`MiniMaxH3TurboLoRA(strength=1.0, low_vram=True)` + `BasicScheduler(simple, steps=6)` +
   `MiniMaxH3TurboSampler`（4~6 步快速出片）。

## 三、Z-Image Turbo — 文生图提示词

- 正向：英文，电影感摄影描述（主体+场景+光线+镜头+质感），歌手肖像要含
  `character sheet`/多角度描述；负向可空串。
- 参数：`KSampler(steps=8, cfg=1.0, euler/simple, denoise=1.0)` + `ModelSamplingAuraFlow(shift=3.0)`；
  CLIP `qwen_3_4b.safetensors (type=qwen_image, device=cpu)`；latent `EmptySD3LatentImage`。
- 分辨率：肖像 768×1024 竖版；分镜 1344×768 横版（与 H3 输出一致，避免二次缩放）。

## 四、FaceFusion 对口型输入

- 源音频 = **人声分轨**（Demucs vocals，不是母带）——口型只需对上人声。
- 目标视频 = 歌手镜头的 H3 动态底版；输出替换口型后回写时间轴。
- 模型 `wav2lip_gan_96`（默认），权重首跑自动下载 ~500MB。
