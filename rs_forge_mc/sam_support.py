# SPDX-License-Identifier: GPL-3.0-only
"""ComfyUI tensor math adapted to native PyTorch/Forge, no ComfyUI imports."""

import math
import torch
from torch import nn


def cast_to_input(value, x, **kwargs):
    return value.to(device=x.device, dtype=x.dtype, **kwargs)


def optimized_attention(q, k, v, heads, mask=None, **kwargs):
    from backend.attention import attention_function

    kwargs.pop("low_precision_attention", None)
    return attention_function(q, k, v, heads, mask=mask, **kwargs)


def optimized_attention_for_device(device, mask=False, **kwargs):
    return optimized_attention


def LayerNorm2d_op(operations):
    class LayerNorm2d(operations.LayerNorm):
        def forward(self, x):
            return super().forward(x.permute(0, 2, 3, 1)).permute(0, 3, 1, 2)

    return LayerNorm2d


class PositionEmbeddingRandom(nn.Module):
    """Fourier feature positional encoding with random gaussian projection."""

    def __init__(self, num_pos_feats=64, scale=None):
        super().__init__()
        self.register_buffer(
            "positional_encoding_gaussian_matrix", (scale or 1.0) * torch.randn(2, num_pos_feats)
        )

    def _encode(self, normalized_coords):
        """Map normalized [0,1] coordinates to fourier features via random projection. Computes in fp32."""
        orig_dtype = normalized_coords.dtype
        proj_matrix = self.positional_encoding_gaussian_matrix.to(
            device=normalized_coords.device, dtype=torch.float32
        )
        projected = 2 * math.pi * (2 * normalized_coords.float() - 1) @ proj_matrix
        return torch.cat([projected.sin(), projected.cos()], dim=-1).to(orig_dtype)

    def forward(self, size, device=None):
        h, w = size
        dev = device if device is not None else self.positional_encoding_gaussian_matrix.device
        ones = torch.ones((h, w), device=dev, dtype=torch.float32)
        norm_xy = torch.stack([(ones.cumsum(1) - 0.5) / w, (ones.cumsum(0) - 0.5) / h], dim=-1)
        return self._encode(norm_xy).permute(2, 0, 1).unsqueeze(0)

    def forward_with_coords(self, pixel_coords, image_size):
        norm = pixel_coords.clone()
        norm[:, :, 0] /= image_size[1]
        norm[:, :, 1] /= image_size[0]
        return self._encode(norm)


class LayerScale(torch.nn.Module):
    def __init__(self, dim, dtype, device, operations):
        super().__init__()
        self.lambda1 = torch.nn.Parameter(torch.empty(dim, device=device, dtype=dtype))

    def forward(self, x):
        return x * self.lambda1.to(device=x.device, dtype=x.dtype)
