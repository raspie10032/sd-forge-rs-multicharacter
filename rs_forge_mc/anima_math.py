# SPDX-License-Identifier: GPL-3.0-only
"""Execution-scoped ComfyUI Anima math on Forge's existing model layers.

Forge rounds RoPE frequencies to fp16 and fuses AdaLN's multiply/add. Both
change BF16 predictions. Keep ComfyUI's frequency precision and operation order
without replacing weights or changing Forge when this extension is disabled.
"""

from contextlib import contextmanager
from types import MethodType

import torch


def position_forward(self, x, device):
    _, frames, height, width, _ = x.shape
    # Match ComfyUI's buffer dtype; Forge unconditionally converts to fp16.
    spatial = self.dim_spatial_range.to(device=device)
    temporal = self.dim_temporal_range.to(device=device)
    seq = torch.arange(max(frames, height, width), device=device, dtype=torch.float32)
    pieces = []
    for size, axis, factor in (
        (frames, temporal, self.t_ntk_factor),
        (height, spatial, self.h_ntk_factor),
        (width, spatial, self.w_ntk_factor),
    ):
        angle = torch.outer(seq[:size], 1.0 / ((10000.0 * factor) ** axis))
        pieces.append(torch.stack((angle.cos(), -angle.sin(), angle.sin(), angle.cos()), dim=-1))
    t, h, w = pieces
    rotations = torch.cat(
        (
            t[:, None, None].expand(-1, height, width, -1, -1),
            h[None, :, None].expand(frames, -1, width, -1, -1),
            w[None, None].expand(frames, height, -1, -1, -1),
        ),
        dim=-2,
    )
    return rotations.reshape(frames * height * width, -1, 2, 2).float()


def block_forward(
    self,
    x,
    emb,
    context,
    rope_emb_L_1_1_D=None,
    adaln_lora_B_T_3D=None,
    extra_per_block_pos_emb=None,
    transformer_options=None,
):
    options = {} if transformer_options is None else transformer_options
    residual_dtype, compute_dtype = x.dtype, emb.dtype
    if extra_per_block_pos_emb is not None:
        x = x + extra_per_block_pos_emb
    modulation = [
        (layer(emb) + adaln_lora_B_T_3D).chunk(3, dim=-1)
        for layer in (
            self.adaln_modulation_self_attn,
            self.adaln_modulation_cross_attn,
            self.adaln_modulation_mlp,
        )
    ]
    for index, (norm, layer) in enumerate(
        (
            (self.layer_norm_self_attn, self.self_attn),
            (self.layer_norm_cross_attn, self.cross_attn),
            (self.layer_norm_mlp, self.mlp),
        )
    ):
        shift, scale, gate = (v[:, :, None, None] for v in modulation[index])
        # Do not fuse: ComfyUI rounds the multiplication before adding shift.
        normalized = (norm(x) * (1 + scale) + shift).to(compute_dtype)
        if index < 2:
            output = layer(
                normalized.flatten(1, 3),
                None if index == 0 else context,
                rope_emb=rope_emb_L_1_1_D,
                transformer_options=options,
            ).reshape_as(x)
        else:
            output = layer(normalized)
        x = torch.addcmul(x, gate.to(residual_dtype), output.to(residual_dtype))
    return x


def final_forward(self, x, emb, adaln_lora_B_T_3D=None):
    shift, scale = (self.adaln_modulation(emb) + adaln_lora_B_T_3D[:, :, : 2 * self.hidden_size]).chunk(
        2, dim=-1
    )
    x = self.layer_norm(x) * (1 + scale[:, :, None, None]) + shift[:, :, None, None]
    return self.linear(x)


@contextmanager
def comfy_math(model):
    saved = []
    flags = []
    try:
        for block in (*model.blocks, model.final_layer):
            flags.append((block, "use_adaln_lora" in block.__dict__, block.__dict__.get("use_adaln_lora")))
            block.use_adaln_lora = True
        for module, forward in (
            (model.pos_embedder, position_forward),
            (model.final_layer, final_forward),
            *((block, block_forward) for block in model.blocks),
        ):
            saved.append((module, "forward" in module.__dict__, module.__dict__.get("forward")))
            module.forward = MethodType(forward, module)
        yield
    finally:
        for block, present, value in reversed(flags):
            if present:
                block.use_adaln_lora = value
            else:
                block.__dict__.pop("use_adaln_lora", None)
        for module, present, original in reversed(saved):
            if present:
                module.forward = original
            else:
                module.__dict__.pop("forward", None)
