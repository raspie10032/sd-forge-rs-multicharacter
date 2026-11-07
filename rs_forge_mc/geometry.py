# SPDX-License-Identifier: GPL-3.0-only
"""Original ComfyUI layout and token ownership, with a Forge tensor boundary."""

import torch

from .routing import BoxGroups, token_groups
from .shared.characters import Character
from .shared.layout import character_masks, effective_centers
from .shared.region_mask import explicit_region


def core_characters(characters):
    return tuple(
        c
        if isinstance(c, Character)
        else Character(
            c.prompt or "preview",
            x=c.x,
            y=c.y,
            bbox=c.box,
            lora_name=c.lora,
            lora_strength=c.strength,
            lora_clip_strength=c.clip_strength,
        )
        for c in characters
    )


def membership(characters, height, width, device, latent_shape=None):
    if height < 1 or width < 1 or not characters:
        raise ValueError("Invalid character grid.")
    characters = core_characters(characters)
    centers, _ = effective_centers(characters)
    # Original layout validates image dimensions. Resizing its latent masks also
    # handles small token grids used by smoke tests or later downsampling paths.
    source_h, source_w = latent_shape or (height * 2, width * 2)
    masks = character_masks(characters, centers, max(8, source_w) * 8, max(8, source_h) * 8, 0.04)
    flags = tuple(explicit_region(c) for c in characters)
    groups = token_groups(masks, height, width, device=device, boxes=flags if any(flags) else False)
    result = torch.zeros((len(characters), height * width), dtype=torch.bool, device=device)
    for i, indices in enumerate(groups):
        result[i, indices] = True
    return result.reshape(len(characters), height, width)


def groups_for(masks):
    members = masks.flatten(1)
    codes = (members.long() * (2 ** torch.arange(len(members), device=masks.device))[:, None]).sum(0)
    cells = [
        (tuple(i for i in range(len(members)) if code & (1 << i)), (codes == code).nonzero().flatten())
        for code in codes.unique().tolist()
    ]
    return BoxGroups([row.nonzero().flatten() for row in members], cells, (codes == 0).nonzero().flatten())


def lora_key(character):
    return (
        (character.lora_name, float(character.lora_strength))
        if character.lora_name != "None" and character.lora_strength != 0
        else None
    )


def prediction_masks(characters, height, width, device, feather=0.04):
    characters = core_characters(characters)
    centers, _ = effective_centers(characters)
    weights = character_masks(characters, centers, width * 8, height * 8, feather).to(device)
    # Preserve original regional_lora.grouped_masks fractional edge coverage.
    boxes = [i for i, c in enumerate(characters) if explicit_region(c)]
    points = [i for i, c in enumerate(characters) if not explicit_region(c)]
    if boxes and points:
        weights[points] *= 1 - weights[boxes].sum(0).clamp(0, 1)
    coverage = weights.sum(0)
    weights /= coverage.clamp_min(1.0)
    grouped = {None: (1 - coverage).clamp(0, 1)}
    for character, weight in zip(characters, weights):
        key = lora_key(character)
        grouped[key] = grouped.get(key, torch.zeros_like(weight)) + weight
    return [(key, weight) for key, weight in grouped.items() if bool(weight.any())]
