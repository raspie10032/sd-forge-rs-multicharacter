# SPDX-License-Identifier: GPL-3.0-only
"""Forge adapter for the original shared_lora single-forward algorithm.

Image hidden states share one diffusion evaluation. Image LoRA deltas use
spatial strengths; own caption K/V use full own strengths. Common/negative
caption K/V use the spatial mean. This is not equivalent to Precision.
"""

from contextlib import contextmanager
import re

import torch
import torch.nn.functional as F


class SharedLoraUnsupported(ValueError):
    pass


def layer_role(path):
    path = path.removeprefix("diffusion_model.")
    if re.fullmatch(r"blocks\.\d+\.cross_attn\.[kv]_proj", path):
        return "text"
    if re.fullmatch(
        r"blocks\.\d+\.(self_attn\.(q_proj|k_proj|v_proj|output_proj)|cross_attn\.(q_proj|output_proj)|mlp\.layer[12])",
        path,
    ):
        return "image"
    raise SharedLoraUnsupported(f"Shared regional LoRA does not support layer {path!r}.")


class SharedLora:
    def __init__(self, plans, characters):
        self.plans = plans
        self.characters = characters
        # Classify every layer before installing anything. Only capability
        # errors allow Precision fallback; execution errors propagate.
        self.roles = {path: layer_role(path) for plan in plans.values() for path in plan.paths}
        if any(not hasattr(plan, "factors") for plan in plans.values()):
            raise SharedLoraUnsupported("Extended adapter formats require independent Precision predictions.")

    @contextmanager
    def installed(self, root, masks, grid, lengths):
        weighted = {}
        for key, mask in masks:
            if key is not None:
                weighted[key[0]] = weighted.get(key[0], torch.zeros_like(mask)) + mask * key[1]
        handles = []
        try:
            for name, plan in self.plans.items():
                spatial = F.interpolate(
                    weighted.get(name, torch.zeros_like(masks[0][1]))[None, None], grid, mode="area"
                )[0, 0]
                strengths = [c.lora_strength if c.lora_name == name else 0.0 for c in self.characters]
                for path, factors in zip(plan.paths, plan.factors):
                    role = self.roles[path]
                    layer = root.get_submodule(path)

                    def regional_delta(
                        module,
                        inputs,
                        output,
                        role=role,
                        spatial=spatial,
                        strengths=strengths,
                        factors=factors,
                    ):
                        x = inputs[0]
                        if role == "image":
                            if tuple(x.shape[1:-1]) not in ((grid[0] * grid[1],), (1, *grid)):
                                raise ValueError(f"Unexpected Anima image-token shape: {tuple(x.shape)}.")
                        elif x.ndim != 3 or x.shape[1] != sum(lengths):
                            raise ValueError("Unexpected Anima caption-token shape.")
                        # ComfyUI casts the resized mask before its spatial
                        # mean. Mean-then-cast changes BF16 caption K/V.
                        typed = spatial.to(output)
                        weights = (
                            typed.flatten()
                            if role == "image"
                            else torch.cat(
                                [
                                    typed.mean().expand(lengths[0]),
                                    *[
                                        typed.new_full((length,), strength)
                                        for length, strength in zip(lengths[1:], strengths)
                                    ],
                                ]
                            )
                        )
                        multiplier = weights.reshape((1, *x.shape[1:-1], 1))
                        return output + factors.delta(x, output) * multiplier

                    handles.append(layer.register_forward_hook(regional_delta))
            yield
        finally:
            for handle in reversed(handles):
                handle.remove()
