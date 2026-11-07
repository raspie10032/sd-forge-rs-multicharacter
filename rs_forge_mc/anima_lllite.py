# SPDX-License-Identifier: GPL-3.0-only
# Adapted from ComfyUI comfy/ldm/anima/lllite.py.
import re

import torch
from torch import nn
import torch.nn.functional as F

from .host import compat as comfy


MODULE_PATTERN = re.compile(r"lllite_dit_blocks_(\d+)_(self_attn_[qkv]_proj|cross_attn_q_proj|mlp_layer1)$")


def _group_norm(channels, device=None, dtype=None, operations=None):
    groups = 8
    while groups > 1 and channels % groups != 0:
        groups //= 2
    return operations.GroupNorm(groups, channels, device=device, dtype=dtype)


class AnimaLLLiteResBlock(nn.Module):
    def __init__(self, channels, device=None, dtype=None, operations=None):
        super().__init__()
        self.norm1 = _group_norm(channels, device=device, dtype=dtype, operations=operations)
        self.conv1 = operations.Conv2d(
            channels, channels, kernel_size=3, padding=1, device=device, dtype=dtype
        )
        self.norm2 = _group_norm(channels, device=device, dtype=dtype, operations=operations)
        self.conv2 = operations.Conv2d(
            channels, channels, kernel_size=3, padding=1, device=device, dtype=dtype
        )

    def forward(self, x):
        h = self.conv1(F.silu(self.norm1(x)))
        h = self.conv2(F.silu(self.norm2(h)))
        return x + h


class AnimaLLLiteASPP(nn.Module):
    def __init__(self, channels, dilations, device=None, dtype=None, operations=None):
        super().__init__()
        branches = []
        for dilation in dilations:
            if dilation == 1:
                conv = operations.Conv2d(channels, channels, kernel_size=1, device=device, dtype=dtype)
            else:
                conv = operations.Conv2d(
                    channels,
                    channels,
                    kernel_size=3,
                    padding=dilation,
                    dilation=dilation,
                    device=device,
                    dtype=dtype,
                )
            branches.append(
                nn.Sequential(
                    conv, _group_norm(channels, device=device, dtype=dtype, operations=operations), nn.SiLU()
                )
            )
        self.branches = nn.ModuleList(branches)
        self.global_pool = nn.AdaptiveAvgPool2d(1)
        self.global_conv = nn.Sequential(
            operations.Conv2d(channels, channels, kernel_size=1, device=device, dtype=dtype),
            _group_norm(channels, device=device, dtype=dtype, operations=operations),
            nn.SiLU(),
        )
        self.proj = nn.Sequential(
            operations.Conv2d(
                channels * (len(dilations) + 1), channels, kernel_size=1, device=device, dtype=dtype
            ),
            _group_norm(channels, device=device, dtype=dtype, operations=operations),
            nn.SiLU(),
        )

    def forward(self, x):
        height, width = x.shape[-2:]
        outputs = [branch(x) for branch in self.branches]
        pooled = self.global_conv(self.global_pool(x))
        outputs.append(F.interpolate(pooled, size=(height, width), mode="bilinear", align_corners=False))
        return self.proj(torch.cat(outputs, dim=1))


class AnimaLLLiteConditioning(nn.Module):
    def __init__(
        self,
        cond_in_channels,
        cond_dim,
        cond_emb_dim,
        cond_resblocks,
        aspp_dilations,
        device=None,
        dtype=None,
        operations=None,
    ):
        super().__init__()
        half_dim = cond_dim // 2
        self.conv1 = operations.Conv2d(
            cond_in_channels, half_dim, kernel_size=4, stride=4, device=device, dtype=dtype
        )
        self.norm1 = _group_norm(half_dim, device=device, dtype=dtype, operations=operations)
        self.conv2 = operations.Conv2d(
            half_dim, half_dim, kernel_size=3, padding=1, device=device, dtype=dtype
        )
        self.norm2 = _group_norm(half_dim, device=device, dtype=dtype, operations=operations)
        self.conv3 = operations.Conv2d(
            half_dim, cond_dim, kernel_size=4, stride=4, device=device, dtype=dtype
        )
        self.norm3 = _group_norm(cond_dim, device=device, dtype=dtype, operations=operations)
        self.resblocks = nn.ModuleList(
            [
                AnimaLLLiteResBlock(cond_dim, device=device, dtype=dtype, operations=operations)
                for _ in range(cond_resblocks)
            ]
        )
        self.aspp = (
            AnimaLLLiteASPP(cond_dim, aspp_dilations, device=device, dtype=dtype, operations=operations)
            if aspp_dilations
            else None
        )
        self.proj = operations.Conv2d(cond_dim, cond_emb_dim, kernel_size=1, device=device, dtype=dtype)
        self.out_norm = operations.LayerNorm(cond_emb_dim, device=device, dtype=dtype)

    def forward(self, x):
        x = F.silu(self.norm1(self.conv1(x)))
        x = F.silu(self.norm2(self.conv2(x)))
        x = F.silu(self.norm3(self.conv3(x)))
        for block in self.resblocks:
            x = block(x)
        if self.aspp is not None:
            x = self.aspp(x)
        x = self.proj(x).flatten(2).transpose(1, 2).contiguous()
        return self.out_norm(x)


class AnimaLLLiteModule(nn.Module):
    def __init__(self, in_dim, cond_emb_dim, mlp_dim, device=None, dtype=None, operations=None):
        super().__init__()
        self.down = operations.Linear(in_dim, mlp_dim, device=device, dtype=dtype)
        self.mid = operations.Linear(mlp_dim + cond_emb_dim, mlp_dim, device=device, dtype=dtype)
        self.cond_to_film = operations.Linear(cond_emb_dim, 2 * mlp_dim, device=device, dtype=dtype)
        self.up = operations.Linear(mlp_dim, in_dim, device=device, dtype=dtype)
        self.depth_embed = nn.Parameter(
            torch.empty(cond_emb_dim, device=device, dtype=dtype), requires_grad=False
        )

    def forward(self, x, cond_emb, strength):
        original_shape = x.shape
        if x.ndim == 5:
            x = x.flatten(1, 3)

        if x.shape[0] != cond_emb.shape[0]:
            if x.shape[0] % cond_emb.shape[0] != 0:
                raise ValueError(
                    f"Anima LLLite batch mismatch: model input batch {x.shape[0]}, control batch {cond_emb.shape[0]}"
                )
            cond_emb = cond_emb.repeat(x.shape[0] // cond_emb.shape[0], 1, 1)
        if x.shape[1] != cond_emb.shape[1]:
            raise ValueError(
                f"Anima LLLite sequence mismatch: model input has {x.shape[1]} tokens, control has {cond_emb.shape[1]}"
            )

        cond_local = cond_emb + comfy.ops.cast_to_input(self.depth_embed, cond_emb)
        hidden = F.silu(self.down(x))
        gamma, beta = self.cond_to_film(cond_local).chunk(2, dim=-1)
        hidden = self.mid(torch.cat((cond_local, hidden), dim=-1))
        hidden = F.silu(hidden * (1 + gamma) + beta)
        x = x + self.up(hidden) * strength

        if len(original_shape) == 5:
            x = x.reshape(original_shape)
        return x


class AnimaLLLite(nn.Module):
    def __init__(self, state_dict, metadata, device=None, dtype=None, operations=None):
        super().__init__()
        metadata = metadata or {}
        version = metadata.get("lllite.version", "2")
        if version != "2":
            raise ValueError(
                f"Unsupported Anima LLLite version {version!r}; only named-key v2 checkpoints are supported"
            )

        module_names = sorted(
            {key.split(".", 1)[0] for key in state_dict if key.startswith("lllite_dit_blocks_")}
        )
        if not module_names:
            raise ValueError("Anima LLLite checkpoint has no lllite_dit_blocks_* modules")

        cond_in_channels = state_dict["lllite_conditioning1.conv1.weight"].shape[1]
        cond_dim = state_dict["lllite_conditioning1.conv3.weight"].shape[0]
        cond_emb_dim = state_dict["lllite_conditioning1.proj.weight"].shape[0]
        resblock_ids = {
            int(key.split(".")[2]) for key in state_dict if key.startswith("lllite_conditioning1.resblocks.")
        }
        cond_resblocks = max(resblock_ids) + 1 if resblock_ids else 0
        use_aspp = any(key.startswith("lllite_conditioning1.aspp.") for key in state_dict)
        dilation_string = metadata.get("lllite.aspp_dilations", "1,2,4,8")
        aspp_dilations = (
            tuple(int(value) for value in dilation_string.split(",") if value.strip()) if use_aspp else ()
        )

        self.cond_in_channels = cond_in_channels
        self.inpaint_masked_input = metadata.get("lllite.inpaint_masked_input", "false").lower() == "true"
        self.lllite_conditioning1 = AnimaLLLiteConditioning(
            cond_in_channels,
            cond_dim,
            cond_emb_dim,
            cond_resblocks,
            aspp_dilations,
            device=device,
            dtype=dtype,
            operations=operations,
        )

        self.module_names = set()
        self.block_count = 0
        self.model_dim = None
        for name in module_names:
            match = MODULE_PATTERN.fullmatch(name)
            if match is None:
                raise ValueError(f"Unsupported Anima LLLite module name: {name}")
            down_shape = state_dict[f"{name}.down.weight"].shape
            mlp_dim, in_dim = down_shape
            module_cond_dim = state_dict[f"{name}.cond_to_film.weight"].shape[1]
            if module_cond_dim != cond_emb_dim:
                raise ValueError(
                    f"Anima LLLite conditioning dimension mismatch in {name}: {module_cond_dim} != {cond_emb_dim}"
                )
            if self.model_dim is None:
                self.model_dim = in_dim
            elif self.model_dim != in_dim:
                raise ValueError(
                    f"Anima LLLite model dimension mismatch in {name}: {in_dim} != {self.model_dim}"
                )
            self.add_module(
                name,
                AnimaLLLiteModule(
                    in_dim, cond_emb_dim, mlp_dim, device=device, dtype=dtype, operations=operations
                ),
            )
            self.module_names.add(name)
            self.block_count = max(self.block_count, int(match.group(1)) + 1)

    def encode_conditioning(self, image):
        return self.lllite_conditioning1(image)

    def apply(self, x, cond_emb, block_index, target, strength):
        name = f"lllite_dit_blocks_{block_index}_{target}"
        if name not in self.module_names:
            return x
        return self.get_submodule(name)(x, cond_emb, strength)
