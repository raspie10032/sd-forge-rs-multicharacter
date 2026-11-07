# SPDX-License-Identifier: GPL-3.0-only
"""Factor-only, execution-local LoRA. Checkpoint tensors are never replaced."""

from contextlib import contextmanager
import math

import torch
import torch.nn.functional as F


class Factors(torch.nn.Module):
    def __init__(self, up, down, alpha):
        super().__init__()
        self.register_buffer("up", up.detach().cpu())
        self.register_buffer("down", down.detach().cpu())
        self.scale = 1.0 if alpha is None else float(alpha) / down.shape[0]

    def delta(self, x, output, strength=1.0):
        # Text encoding runs before sampling_prepare moves auxiliary models.
        # Sampling factors are already managed by Forge's auxiliary patcher.
        up = self.up.to(device=output.device, dtype=output.dtype)
        down = self.down.to(device=output.device, dtype=output.dtype)
        return F.linear(F.linear(x.to(down.dtype), down), up) * (self.scale * strength)


class LoraPlan(torch.nn.Module):
    def __init__(self, root, patches):
        super().__init__()
        from modules_forge.packages.comfy.weight_adapter.lora import LoRAAdapter

        self.paths = []
        self.factors = torch.nn.ModuleList()
        # Validate the whole LoRA before installing any hooks. Partial adapters
        # (DoRA, LoHa, LoKr, convolution, diff/set patches) must not silently run.
        for key, adapter in patches.items():
            if not isinstance(key, str) or not key.endswith(".weight") or type(adapter) is not LoRAAdapter:
                raise ValueError(f"Regional LoRA needs plain linear LoRA weights: {key!r}.")
            if len(adapter.weights) != 6 or any(v is not None for v in adapter.weights[3:]):
                raise ValueError(f"Extended LoRA/DoRA is unsupported: {key}.")
            up, down, alpha = adapter.weights[:3]
            if any(
                not isinstance(t, torch.Tensor) or t.ndim != 2 or not t.is_floating_point()
                for t in (up, down)
            ):
                raise ValueError(f"Only floating-point linear LoRA factors are supported: {key}.")
            if (
                up.shape[1] != down.shape[0]
                or down.shape[0] == 0
                or alpha is not None
                and (not isinstance(alpha, (int, float)) or not math.isfinite(alpha))
            ):
                raise ValueError(f"Invalid LoRA factor shape/alpha: {key}.")
            if not bool(torch.isfinite(up).all() and torch.isfinite(down).all()):
                raise ValueError(f"LoRA contains nonfinite factors: {key}.")
            path = key[: -len(".weight")]
            layer = root.get_submodule(path)
            weight = getattr(layer, "weight", None)
            if (
                weight is None
                or tuple(weight.shape) != (up.shape[0], down.shape[1])
                or not hasattr(layer, "in_features")
                or not hasattr(layer, "out_features")
            ):
                raise ValueError(f"LoRA does not match a linear layer: {key}.")
            self.paths.append(path)
            self.factors.append(Factors(up, down, alpha))

    @contextmanager
    def applied(self, root, strength):
        handles = []
        try:
            for path, factors in zip(self.paths, self.factors):
                layer = root.get_submodule(path)

                def add_delta(module, inputs, output, factors=factors):
                    return output + factors.delta(inputs[0], output, strength)

                handles.append(layer.register_forward_hook(add_delta))
            yield
        finally:
            for handle in reversed(handles):
                handle.remove()


def available_loras():
    import networks

    return ["None"] + sorted(networks.available_networks)


def resolve_lora(name):
    import networks

    entry = networks.available_networks.get(name)
    if entry is None:
        networks.list_available_networks()
        entry = networks.available_networks.get(name)
    if entry is None:
        raise ValueError(f"Character LoRA {name!r} is missing. Refresh Forge's LoRA list.")
    # Names come from Forge's registry. Presets cannot supply arbitrary paths.
    return entry.filename


def load_plans(unet, clip, characters):
    import networks
    from backend.patcher.lora import load_lora, model_lora_keys_clip, model_lora_keys_unet
    from backend.utils import load_torch_file

    model_plans, text_plans = {}, {}
    if not any(c.lora_name != "None" and (c.lora_strength or c.lora_clip_strength) for c in characters):
        return model_plans, text_plans
    model_keys = model_lora_keys_unet(unet.model, {})
    text_keys = model_lora_keys_clip(clip.cond_stage_model, {})
    for character in characters:
        name = character.lora_name
        if (
            name == "None"
            or not (character.lora_strength or character.lora_clip_strength)
            or name in model_plans
        ):
            continue
        state = load_torch_file(resolve_lora(name), safe_load=True)
        if not state:
            raise ValueError(f"Empty character LoRA: {name}.")
        from .shared.adapter_formats import load_additional_adapters, validate_file_format

        validate_file_format(state)
        state = {
            k.replace("lora_unet__", "lora_unet_", 1) if k.startswith("lora_unet__") else k: v
            for k, v in state.items()
        }
        if type(unet.model.diffusion_model).__name__ == "Anima" and not networks.process_anima(
            state, len(unet.model.diffusion_model.blocks)
        ):
            raise ValueError(f"Anima LoRA block mapping failed: {name}.")
        model_extra = load_additional_adapters(state, model_keys)
        text_extra = load_additional_adapters(state, text_keys)
        for adapter in list(model_extra.values()) + list(text_extra.values()):
            for key in adapter.loaded_keys:
                state.pop(key, None)
        model_patches, remaining = load_lora(state, model_keys)
        text_patches, remaining = load_lora(remaining, text_keys)
        model_patches.update(model_extra)
        text_patches.update(text_extra)
        if remaining or not (model_patches or text_patches):
            examples = ", ".join(list(remaining)[:3])
            raise ValueError(f"Character LoRA {name!r} has unsupported/unmatched tensors: {examples}.")
        from .adapter_delta import WeightDeltaPlan

        def plan(root, patches):
            try:
                return LoraPlan(root, patches)
            except ValueError:
                return WeightDeltaPlan(root, patches)

        model_plans[name] = plan(unet.model, model_patches)
        text_plans[name] = plan(clip.cond_stage_model, text_patches)
    return model_plans, text_plans
