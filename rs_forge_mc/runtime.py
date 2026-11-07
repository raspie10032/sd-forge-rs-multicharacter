# SPDX-License-Identifier: GPL-3.0-only
"""Forge Neo adapter: cloned patcher, scoped native Anima attention operations."""
from contextlib import contextmanager, nullcontext
import math
import threading

import torch

from .anima_math import comfy_math
from .geometry import groups_for, membership, prediction_masks
from .routing import (character_value_gain, hold_decay_spatial_separation, route_cross,
                      sdpa, sigma_progress, stepped_common_weight)

RUNTIME_LOCK = threading.RLock()


def text_tensor(value):
    if not isinstance(value, torch.Tensor):
        raise ValueError("Anima conditioning must be a tensor.")
    if value.ndim == 4 and value.shape[1] == 1:
        value = value[:, 0]
    if value.ndim != 3 or value.shape[1] < 1:
        raise ValueError(f"Unexpected Anima text conditioning shape: {tuple(value.shape)}.")
    return value


def schedule_values(sigma, sigmas, settings):
    # Terminal zero is not an evaluation. Neo exposes the actual pass schedule,
    # including the shortened img2img/Hires schedule, in sampling_sigmas.
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in sigmas):
        raise ValueError("Anima sampler sigmas must be finite and nonnegative.")
    evaluations = [float(v) for v in sigmas if float(v) > 0]
    if not evaluations or any(not math.isfinite(v) for v in evaluations):
        raise ValueError("Anima sampling requires finite positive evaluation sigmas.")
    if any(a <= b for a, b in zip(evaluations, evaluations[1:])):
        raise ValueError("RS MultiCharacter requires a strictly descending sampler schedule.")
    if len(evaluations) == 1:
        return settings.common_prior, settings.character_gain, settings.separation
    else:
        progress = sigma_progress(float(sigma), evaluations)
    prior = stepped_common_weight(progress, len(evaluations), settings.common_prior, .2, .1)
    separation = hold_decay_spatial_separation(progress, len(evaluations), settings.separation,
                                              min(settings.hold_steps, len(evaluations)), settings.decay)
    return prior, character_value_gain(progress, settings.character_gain), separation


@contextmanager
def attention_ops(model, cross, spatial):
    """Modify only called instances and restore attributes exactly, also on errors."""
    saved = []
    try:
        for block in model.blocks:
            for name, op in (("cross_attn", cross), ("self_attn", spatial)):
                if op is None:
                    continue
                module = getattr(block, name)
                present = "torch_attention_op" in module.__dict__
                previous = module.__dict__.get("torch_attention_op")
                saved.append((module, present, previous))
                module.torch_attention_op = op
        yield
    finally:
        for module, present, previous in reversed(saved):
            if present:
                module.torch_attention_op = previous
            else:
                module.__dict__.pop("torch_attention_op", None)


def validate_model(unet):
    from backend.nn.anima import Anima, SelfCrossAttention
    model = unet.model.diffusion_model
    if not isinstance(model, Anima):
        raise ValueError("RS MultiCharacter alpha supports Forge Neo Anima models only.")
    if getattr(SelfCrossAttention.forward, "_couple", False):
        raise ValueError("Disable Forge Couple before enabling RS MultiCharacter.")
    if "model_function_wrapper" in unet.model_options:
        raise ValueError("Another extension already wraps this model. Disable it for RS MultiCharacter.")
    options = unet.model_options.get("transformer_options", {})
    if any(options.get(key) for key in ("optimized_attention_override", "patches", "patches_replace")):
        raise ValueError("Another extension already patches attention. Disable it for RS MultiCharacter.")
    if unet.controlnet_linked_list is not None:
        raise ValueError("ControlNet with RS MultiCharacter is not supported in this alpha.")
    for block in model.blocks:
        for module in (block.cross_attn, block.self_attn):
            if "torch_attention_op" in module.__dict__ or "forward" in module.__dict__:
                raise ValueError("Anima attention already has an instance patch.")


class AnimaRuntime:
    def __init__(self, config, contexts, plans=None):
        config.validate_generation()
        self.config = config
        self.pipe = config.to_pipe()
        self.characters = self.pipe.regions
        self.contexts = tuple(text_tensor(c).detach().cpu() for c in contexts)
        if len(self.contexts) != len(self.characters) or any(c.shape[0] != 1 for c in self.contexts):
            raise ValueError("Expected one independently encoded caption for each active character.")
        self.plans = plans or {}
        self.audit = {"model_calls": 0, "prediction_passes": 0, "restored_calls": 0, "grids": []}
        self.shared_lora = None
        self.audit["requested_lora_mode"] = config.settings.lora_mode
        self.audit["effective_lora_mode"] = "precision" if plans else "none"
        if plans and config.settings.lora_mode == "normal":
            from .shared_lora import SharedLora, SharedLoraUnsupported
            try:
                self.shared_lora = SharedLora(plans, self.characters)
            except SharedLoraUnsupported as error:
                self.audit["lora_fallback_reason"] = str(error)
            else:
                self.audit["effective_lora_mode"] = "normal"
        self._schedule_source = None
        self._schedule = None
        self._grid_key = None
        self._groups = None
        self._prediction_weights = None

    def __call__(self, apply_model, args):
        from backend.args import dynamic_args
        if dynamic_args.ref_latents:
            raise ValueError("Disable Anima image references for RS MultiCharacter alpha.")
        with RUNTIME_LOCK:
            return self._forward(apply_model, args)

    def _forward(self, apply_model, args):
        model = apply_model.__self__.diffusion_model
        from backend.nn.anima import SelfCrossAttention
        if getattr(SelfCrossAttention.forward, "_couple", False):
            raise ValueError("Forge Couple and RS MultiCharacter cannot run together.")
        x, t, conditions = args["input"], args["timestep"], dict(args["c"])
        options = dict(conditions.get("transformer_options", {}))
        kinds = args.get("cond_or_uncond") or options.get("cond_or_uncond")
        if not kinds or any(kind not in (0, 1) for kind in kinds) or x.shape[0] % len(kinds):
            raise ValueError("Invalid Forge CFG batch layout.")
        if x.ndim != 5 or x.shape[2] != 1 or model.patch_temporal != 1:
            raise ValueError("RS MultiCharacter supports Anima single-frame images only.")
        if conditions.get("control") is not None or conditions.get("control_model") is not None:
            raise ValueError("ControlNet is unsupported with RS MultiCharacter alpha.")
        batch_size = x.shape[0] // len(kinds)
        row_kinds = [kind for kind in kinds for _ in range(batch_size)]
        height = math.ceil(x.shape[-2] / model.patch_spatial)
        width = math.ceil(x.shape[-1] / model.patch_spatial)
        grid_key = (tuple(x.shape[-2:]), x.device)
        if grid_key != self._grid_key:
            self._groups = groups_for(membership(self.characters, height, width, x.device, x.shape[-2:]))
            if self.plans:
                self._prediction_weights = prediction_masks(self.characters, x.shape[-2], x.shape[-1], x.device)
            self._grid_key = grid_key
            self.audit["grids"].append([height, width])
        groups = self._groups
        source = options.get("sampling_sigmas")
        if source is None:
            raise ValueError("Forge Neo did not supply sampling_sigmas; use a supported K-diffusion sampler.")
        if source is not self._schedule_source:
            self._schedule = source.detach().cpu().tolist() if isinstance(source, torch.Tensor) else list(source)
            self._schedule_source = source
        # Values come from sigma, not transformed Anima timesteps or a forward counter.
        sigma = options.get("sigmas", t).flatten()
        if not torch.allclose(sigma, sigma[:1].expand_as(sigma)):
            raise ValueError("A CFG batch must share the same sampling sigma.")
        prior, gain, separation = schedule_values(float(sigma[0]), self._schedule, self.config.settings)
        base = text_tensor(conditions["c_crossattn"])
        if base.shape[0] != x.shape[0]:
            raise ValueError("Anima text and image batch sizes do not match.")
        character_contexts = [torch.cat([c.to(base).expand(batch_size, -1, -1) if kind == 0 else
                                         base.new_zeros((batch_size, c.shape[1], c.shape[2]))
                                         for kind in kinds]) for c in self.contexts]
        if any(c.shape[-1] != base.shape[-1] for c in character_contexts):
            raise ValueError("Character text dimensions do not match the loaded Anima model.")
        lengths = [base.shape[1]] + [c.shape[1] for c in character_contexts]
        conditions["c_crossattn"] = torch.cat([base, *character_contexts], dim=1)
        conditions["transformer_options"] = options

        def cross(q, k, v, transformer_options=None):
            if q.shape[1] != height * width:
                raise ValueError("Unexpected Anima token grid (reference/tiling extension active?).")
            return route_cross(q, k, v, groups, lengths, row_kinds,
                               weights=(prior, 1.), character_gain=gain)

        # Keep the S×S bias limited to small query chunks to bound peak memory.
        # A chunk reads all image keys, so this preserves full self-attention.
        def spatial(q, k, v, transformer_options=None):
            if q.shape[1] != height * width:
                raise ValueError("Unexpected Anima self-attention grid.")
            result = q.new_empty((q.shape[0], q.shape[1], q.shape[2] * q.shape[3]))
            for start in range(0, q.shape[1], 256):
                stop = min(start + 256, q.shape[1])
                bias = q.new_full((stop-start, k.shape[1]), math.log1p(-separation))
                for group in groups:
                    rows = group[(group >= start) & (group < stop)] - start
                    bias[rows[:, None], group] = 0
                background = groups.background
                bias[:, background] = 0
                rows = background[(background >= start) & (background < stop)] - start
                bias[rows, :] = 0
                result[:, start:stop] = sdpa(q[:, start:stop], k, v, bias)
            return result

        self.audit["model_calls"] += 1
        self.audit["last_schedule"] = {"common_prior": prior, "character_gain": gain, "separation": separation}
        try:
            with comfy_math(model), attention_ops(model, cross, spatial):
                if not self.plans:
                    self.audit["prediction_passes"] += 1
                    return apply_model(x, t, **conditions)
                if self.shared_lora is not None:
                    with self.shared_lora.installed(apply_model.__self__, self._prediction_weights,
                                                    (height, width), lengths):
                        self.audit["prediction_passes"] += 1
                        return apply_model(x, t, **conditions)
                result = torch.zeros_like(x, dtype=torch.float32)
                for key, weight in self._prediction_weights:
                    plan = self.plans[key[0]] if key is not None else None
                    context = plan.applied(apply_model.__self__, key[1]) if plan is not None else nullcontext()
                    with context:
                        prediction = apply_model(x, t, **conditions)
                    result.add_(prediction.float() * weight[None, None, None])
                    self.audit["prediction_passes"] += 1
                return result
        finally:
            self.audit["restored_calls"] += 1


def install(unet, config, contexts, plans=None):
    validate_model(unet)
    patched = unet.clone()
    runtime = AnimaRuntime(config, contexts, plans)
    patched.set_model_unet_function_wrapper(runtime)
    # Factor buffers enter Forge's model accounting/offload path with the UNet.
    for plan in runtime.plans.values():
        if plan.paths:
            patched.add_extra_torch_module_during_sampling(plan, cast_to_unet_dtype=False)
    return patched, runtime
