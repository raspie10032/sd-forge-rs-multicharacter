# SPDX-License-Identifier: GPL-3.0-only
"""Forge lifecycle and independent model-family text conditioning."""

from contextlib import nullcontext
from dataclasses import replace

import torch

from .runtime import RUNTIME_LOCK, text_tensor
from .native_runtime import NativeRuntime, model_family


def conditioning_tensor(value):
    if isinstance(value, dict):
        value = value.get("crossattn", value.get("c_crossattn"))
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError("Use one image per batch for RS regional generation.")
        value = value[0]
    if isinstance(value, torch.Tensor) and value.ndim == 2:
        value = value.unsqueeze(0)
    if isinstance(value, torch.Tensor) and value.ndim == 4 and value.shape[1] > 1:
        # Forge Krea keeps Qwen layer and token axes separate; the shared
        # routing engine packs the layer stack into each token's features.
        value = value.flatten(2)
    return text_tensor(value)


def encode(p, text, width, height, scope=None, image=None):
    from modules.prompt_parser import SdConditioning

    with scope or nullcontext():
        prompts = SdConditioning(
            [text],
            width=width,
            height=height,
            distilled_cfg_scale=getattr(p, "distilled_cfg_scale", None),
        )
        if image is None:
            value = p.sd_model.get_learned_conditioning(prompts)
        else:
            from backend import memory_management

            memory_management.load_model_gpu(p.sd_model.forge_objects.clip.patcher)
            # The reference/pose pixels already follow the RS preparation;
            # avoid Forge's global reference state and second VAE encode.
            value = p.sd_model.text_processing_engine_qwen(prompts, images=[image])
    return conditioning_tensor(value).detach().cpu()


def validate(unet):
    family = model_family(unet)
    if unet.controlnet_linked_list is not None:
        raise ValueError("Disable external ControlNet while RS routing is enabled.")
    options = unet.model_options
    if options.get("model_function_wrapper"):
        raise ValueError("Another extension already wraps this model.")
    if any(
        options.get("transformer_options", {}).get(k)
        for k in ("optimized_attention_override", "patches_replace")
    ):
        raise ValueError("Another extension already replaces this model’s attention.")
    if family == "Anima":
        from backend.nn.anima import SelfCrossAttention

        if getattr(SelfCrossAttention.forward, "_couple", False):
            raise ValueError("Disable Forge Couple while using RS routing.")
    return family


def install(p, config, x):
    from .lora import load_plans
    from .references import prepare

    original = p.sd_model.forge_objects.unet
    family = validate(original)
    ratio = p.sd_model.forge_objects.vae.downscale_ratio
    down_h, down_w = ratio[-2:] if isinstance(ratio, tuple) else (ratio, ratio)
    height, width = int(x.shape[-2]) * down_h, int(x.shape[-1]) * down_w
    pipe = config.to_pipe()
    if config.features.get("syntax") == "NovelAI":
        from .shared.prompt_syntax import to_comfyui, parse_naiv4

        pipe = replace(
            pipe,
            characters=tuple(replace(c, prompt=to_comfyui(parse_naiv4(c.prompt))) for c in pipe.characters),
        )
    with RUNTIME_LOCK:
        model_plans, text_plans = load_plans(original, p.sd_model.forge_objects.clip, pipe.regions)
        contexts = []
        for c in pipe.regions:
            plan = text_plans.get(c.lora_name)
            scope = (
                plan.applied(p.sd_model.forge_objects.clip.cond_stage_model, c.lora_clip_strength)
                if plan
                else None
            )
            contexts.append(encode(p, c.prompt, width, height, scope))
        runtime = NativeRuntime(config, contexts, model_plans, family, pipe, (width, height))
        if runtime.pose:
            parts = [encode(p, t, width, height) for t in runtime.part_captions]
            if family == "Anima":
                runtime.routing.contexts = (*runtime.contexts, *parts)
            else:
                runtime.routing.conditions += [(c, {}) for c in parts]
        patched = original.clone()
        if config.features.get("progressive", {}).get("start_scale", 1.0) < 1.0:
            dm = original.model.diffusion_model
            patch = getattr(dm, "patch_spatial", getattr(dm, "patch", getattr(dm, "patch_size", 1)))
            ratio = p.sd_model.forge_objects.vae.downscale_ratio
            down_h, down_w = ratio[-2:] if isinstance(ratio, tuple) else (ratio, ratio)
            patched.model_options.setdefault("transformer_options", {})["rs_resolution_separation"] = {
                "final_grid": [height // down_h // patch, width // down_w // patch],
                "final_latent_grid": [height // down_h, width // down_w],
            }
        prepare(runtime, patched, p, width, height)
        from .learned_pose import prepare as prepare_pose

        prepare_pose(runtime, patched, p, width, height)
        if family == "Krea2":
            images = getattr(runtime, "krea_reference_pixels", {})
            if runtime.pose_runtime:
                image = runtime.pose_runtime["pixels"]
                common = encode(p, p.all_prompts[0], width, height, image=image)
                runtime.routing.pose_runtime["common_context"] = common
            if images:
                contexts = []
                for index, character in enumerate(pipe.regions):
                    plan = text_plans.get(character.lora_name)
                    scope = (
                        plan.applied(
                            p.sd_model.forge_objects.clip.cond_stage_model, character.lora_clip_strength
                        )
                        if plan
                        else None
                    )
                    contexts.append(encode(p, character.prompt, width, height, scope, images.get(index)))
                runtime.routing.conditions = [(c, {}) for c in contexts]
        runtime.install(patched)
        for plan in model_plans.values():
            patched.add_extra_torch_module_during_sampling(plan)
    return patched, runtime
