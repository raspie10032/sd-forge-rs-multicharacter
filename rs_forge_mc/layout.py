# SPDX-License-Identifier: GPL-3.0-only
"""Choose the original MOSS layout path before Forge encodes the prompt."""

from dataclasses import replace
from .shared.layout import moss_layout_prompt


def resolve(config, family):
    method = config.features.get("layout_method", "auto")
    learned = config.features.get("pose", {}).get("mode", "masks_only") == "auto"
    if method == "auto":
        method = "moss_native" if family == "MOSS" and learned else "regional"
    if method == "moss_native":
        if family != "MOSS":
            raise ValueError("MOSS native layout requires MOSS-Image; choose regional for this model.")
        if config.features.get("syntax", "ComfyUI") != "ComfyUI":
            raise ValueError("MOSS native layout uses literal captions and ComfyUI syntax.")
        if any(c.lora != "None" and c.clip_strength for c in config.active):
            raise ValueError("MOSS native layout uses one encoding; set character CLIP LoRA strength to 0.")
        if any(r.get("reference") for r in config.features.get("slots", {}).values()):
            raise ValueError("Image references require regional layout.")
    return method


def native_prompt(config, prompt, width, height):
    return moss_layout_prompt(replace(config.to_pipe(), prompt=prompt), width, height)
