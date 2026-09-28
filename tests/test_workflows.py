import json

import pytest

from echoloom.workflows import (  # noqa: F401
    frames_for,
    h3_i2v_workflow,
    music3_workflow,
    qwen_image_workflow,
)


def test_frames_for_multiple_of_five():
    assert frames_for(0.1) == 5
    assert frames_for(5.0) == 120
    assert frames_for(5.1) == 125
    assert frames_for(3.0) == 75
    for s in (1, 2, 4.7, 5, 6.3, 8):
        assert frames_for(s) % 5 == 0


def test_music3_graph_matches_ground_truth():
    wf = music3_workflow("Global Metadata: pop, 100 BPM", "[Verse]\n测试", seed=7, max_duration=180)
    assert wf["1"]["inputs"]["unet_name"] == "minimax_music3_dit_int8_convrot.safetensors"
    assert wf["2"]["inputs"]["clip_name"].startswith("minimax_music3_text_encoder")
    assert wf["4"]["class_type"] == "MiniMaxMusic3TextEncode"
    assert wf["4"]["inputs"]["max_duration"] == 180.0
    assert wf["6"]["inputs"]["seconds"] == ["4", 1]  # latent 秒数跟随 TextEncode
    assert wf["5"]["class_type"] == "ConditioningZeroOut"
    k = wf["7"]["inputs"]
    assert (k["steps"], k["cfg"], k["sampler_name"], k["scheduler"]) == (30, 1.7, "euler", "simple")
    assert wf["8"]["inputs"]["tile_size"] == 1536
    assert wf["9"]["inputs"]["format"] == "flac"


def test_qwen_image_graph_matches_template():
    wf = qwen_image_workflow("a singer portrait", width=768, height=1024, seed=42)
    assert wf["1"]["inputs"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert wf["2"]["class_type"] == "QwenImage21Cache"
    assert wf["3"]["inputs"] ["type"] == "qwen_image"
    assert wf["3"]["inputs"]["clip_name"] == "qwen3vl_8b_int8_convrot.safetensors"
    assert wf["4"]["class_type"] == "TextEncodeQwenImage21"
    assert wf["4"]["inputs"]["negative_prompt"] == ""
    # TextEncodeQwenImage21 输出 [positive, negative, latent] → KSampler 正负条件
    assert wf["6"]["inputs"]["positive"] == ["4", 0]
    assert wf["6"]["inputs"]["negative"] == ["4", 1]
    assert wf["6"]["inputs"]["steps"] == 25 and wf["6"]["inputs"]["cfg"] == 1.0
    assert wf["6"]["inputs"]["sampler_name"] == "euler" and wf["6"]["inputs"]["scheduler"] == "simple"
    assert wf["7"]["inputs"]["vae_name"] == "qwen_image_2.1_vae_bf16.safetensors"
    assert wf["5"]["inputs"]["width"] == 768
    assert wf["9"]["inputs"]["filename_prefix"].startswith("echoloom/")
    # 不再引用任何 Z-Image 权重
    blob = json.dumps(wf)
    assert "z_image" not in blob and "AuraFlow" not in blob


def test_h3_i2v_graph():
    wf = h3_i2v_workflow("portrait.png", "Slow dolly forward, cinematic.", seed=99, frames=120)
    assert wf["7"]["class_type"] == "MiniMaxH3ImageToVideo"
    assert wf["7"]["inputs"]["length"] == 120
    assert (wf["7"]["inputs"]["width"], wf["7"]["inputs"]["height"]) == (1344, 768)
    assert wf["2"]["inputs"]["lora_name"] == "minimax_h3_turbo_v4_step600_ema.safetensors"
    assert wf["8"]["inputs"]["steps"] == 6
    assert wf["9"]["class_type"] == "MiniMaxH3TurboSampler"
    assert wf["16"]["inputs"]["filename_prefix"].startswith("echoloom/")
    # 双 VAE：视频 fp16 + 音频 fp32
    assert wf["4"]["inputs"]["vae_name"].endswith("video_vae_fp16.safetensors")
    assert wf["5"]["inputs"]["vae_name"].endswith("audio_vae_fp32.safetensors")


def test_h3_frames_validation():
    with pytest.raises(ValueError):
        h3_i2v_workflow("a.png", "p", frames=121)
