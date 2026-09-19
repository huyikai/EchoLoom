"""ComfyUI API 格式工作流构建器。

三份 ground truth 来源（本机已跑通）：
- music3:  D:/develop/baoshu-gospel/wf_music3.json（180s 成曲）
- z_image: D:/develop/comfyui/workflows/z_image_turbo_8step_api.json
- h3_i2v:  D:/develop/studebaker-gospel/gen_i2v.py（4 段动态镜头）
"""
from __future__ import annotations

import math


def frames_for(sec: float, fps: int = 24) -> int:
    """H3 视频帧数：≥5 且为 5 的倍数（模型约束）。"""
    n = max(5, round(sec * fps))
    return n + (5 - n % 5 if n % 5 else 0)


def music3_workflow(caption: str, lyrics: str, *, seed: int = 0, max_duration: float = 180.0,
                    steps: int = 30, cfg: float = 1.7, top_k: int = 50,
                    prefix: str = "echoloom/music") -> dict:
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "minimax_music3_dit_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "minimax_music3_text_encoder_pruned_int8_convrot.safetensors",
                         "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_music3_dav.safetensors"}},
        "4": {"class_type": "MiniMaxMusic3TextEncode",
              "inputs": {"clip": ["2", 0], "caption": caption, "lyrics": lyrics,
                         "seed": seed, "max_duration": float(max_duration),
                         "cfg_scale": cfg, "top_k": top_k}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyMiniMaxMusic3LatentAudio",
              "inputs": {"seconds": ["4", 1], "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecodeAudioTiled",
              "inputs": {"samples": ["7", 0], "vae": ["3", 0], "tile_size": 1536, "overlap": 64}},
        "9": {"class_type": "SaveAudioAdvanced",
              "inputs": {"audio": ["8", 0], "filename_prefix": prefix, "format": "flac"}},
    }


def zimage_workflow(prompt: str, *, negative: str = "", width: int = 1344, height: int = 768,
                    seed: int = 42, steps: int = 8, shift: float = 3.0,
                    prefix: str = "echoloom/zimage") -> dict:
    return {
        "3": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler",
                         "scheduler": "simple", "denoise": 1.0,
                         "model": ["66", 0], "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["58", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["38", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "37": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "qwen_image", "device": "cpu"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "z_image_turbo_ae.safetensors"}},
        "58": {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "60": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
        "66": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": shift, "model": ["37", 0]}},
    }


def h3_r2v_workflow(image_name: str, audio_name: str, motion_prompt: str, *, seed: int = 0,
                    frames: int = 120, width: int = 1344, height: int = 768,
                    prefix: str = "echoloom/h3r2v") -> dict:
    """Ref2VA 声画同步：参考图(歌手形象) + 真实音频段 → 跟唱视频（studebaker 已验证）。

    帧数约束与 i2v 不同：本机验证为 17 的倍数（gen_r2v.py frames_for）。
    """
    if frames % 17:
        frames += 17 - frames % 17
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                         "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                         "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
        "7": {"class_type": "MiniMaxH3ReferenceToVideo",
              "inputs": {"clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0],
                         "prompt": motion_prompt, "width": width, "height": height,
                         "length": frames, "ref_image_size": "match",
                         "ref_images.ref_image_0": ["5", 0],
                         "ref_audios.ref_audio_0": ["6", 0]}},
        "8": {"class_type": "BasicScheduler",
              "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["7", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["11", 0], "guider": ["10", 0], "sampler": ["9", 0],
                          "sigmas": ["8", 0], "latent_image": ["7", 1]}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": 24,
                                                       "audio": ["14", 0], "bit_depth": 8}},
        "16": {"class_type": "SaveVideo",
               "inputs": {"video": ["15", 0], "filename_prefix": prefix,
                          "format": "auto", "codec": "auto"}},
    }


def h3_r2v_workflow_locked(image_name: str, audio_name: str, motion_prompt: str, *, seed: int = 0,
                           frames: int = 119, width: int = 1344, height: int = 768,
                           prefix: str = "echoloom/h3r2v2") -> dict:
    """锁定构图版：ref_image_size=max（studebaker 实测口型有效的配方）。"""
    wf = h3_r2v_workflow(image_name, audio_name, motion_prompt, seed=seed, frames=frames,
                         width=width, height=height, prefix=prefix)
    wf["7"]["inputs"]["ref_image_size"] = "max"
    return wf


def h3_i2v_workflow(image_name: str, motion_prompt: str, *, seed: int = 0,
                    frames: int = 120, width: int = 1344, height: int = 768,
                    prefix: str = "echoloom/h3i2v") -> dict:
    if frames % 5:
        raise ValueError(f"frames 必须是 5 的倍数，得到 {frames}")
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                         "weight_dtype": "default"}},
        "2": {"class_type": "MiniMaxH3TurboLoRA",
              "inputs": {"model": ["1", 0], "lora_name": "minimax_h3_turbo_v4_step600_ema.safetensors",
                         "strength": 1.0, "low_vram": True}},
        "3": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                         "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "7": {"class_type": "MiniMaxH3ImageToVideo",
              "inputs": {"clip": ["3", 0], "vae": ["4", 0], "prompt": motion_prompt,
                         "width": width, "height": height, "length": frames,
                         "first_frame": ["6", 0]}},
        "8": {"class_type": "BasicScheduler",
              "inputs": {"model": ["2", 0], "scheduler": "simple", "steps": 6, "denoise": 1.0}},
        "9": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["7", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["11", 0], "guider": ["10", 0], "sampler": ["9", 0],
                          "sigmas": ["8", 0], "latent_image": ["7", 1]}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}},
        "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["5", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": 24,
                                                       "audio": ["14", 0], "bit_depth": 8}},
        "16": {"class_type": "SaveVideo",
               "inputs": {"video": ["15", 0], "filename_prefix": prefix,
                          "format": "auto", "codec": "auto"}},
    }
