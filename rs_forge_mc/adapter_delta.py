# SPDX-License-Identifier: GPL-3.0-only
"""Native Forge adapter algebra, applied as an execution-scoped affine delta."""

from contextlib import contextmanager
import torch
import torch.nn.functional as F


class WeightDeltaPlan(torch.nn.Module):
    def __init__(self, root, patches):
        super().__init__()
        self.entries = {}
        self.paths = []
        supported = (
            torch.nn.Linear,
            torch.nn.Conv1d,
            torch.nn.Conv2d,
            torch.nn.Conv3d,
            torch.nn.LayerNorm,
            torch.nn.GroupNorm,
            torch.nn.RMSNorm,
        )
        for key, patch in patches.items():
            name, offset = key, None
            if isinstance(key, tuple):
                if len(key) not in (2, 3) or len(key) == 3 and key[2] is not None:
                    raise ValueError(f"Unsupported adapter function: {key}")
                name, offset = key[:2]
            path, _, parameter = name.rpartition(".")
            module = root.get_submodule(path)
            if parameter not in ("weight", "bias") or not isinstance(module, supported):
                raise ValueError(f"Unsupported regional adapter layer: {name}")
            tensor = getattr(module, parameter, None)
            if tensor is None:
                raise ValueError(f"Missing adapter parameter: {name}")
            row = self.entries.setdefault(path, {})
            row.setdefault(parameter, []).append((name, patch, offset))
        self.paths = list(self.entries)

    @contextmanager
    def applied(self, root, strength):
        from backend.patcher.lora import merge_lora_to_weight

        handles = []
        try:
            for path, patches in self.entries.items():
                module = root.get_submodule(path)

                def hook(layer, args, output, patches=patches):
                    x = args[0].to(device=output.device, dtype=torch.float32)
                    deltas = {}
                    for parameter, rows in patches.items():
                        original = getattr(layer, parameter).to(device=x.device)
                        if hasattr(original, "dequantize") and type(original) not in (
                            torch.Tensor,
                            torch.nn.Parameter,
                        ):
                            original = original.dequantize()
                        original = original.float()
                        updates = [(strength, patch, 1.0, offset, None) for _, patch, offset in rows]
                        changed = merge_lora_to_weight(
                            updates, original.clone(), rows[0][0], computation_dtype=torch.float32
                        )
                        deltas[parameter] = changed - original
                    dw, db = deltas.get("weight"), deltas.get("bias")
                    if isinstance(layer, torch.nn.Linear):
                        delta = F.linear(x, dw, db) if dw is not None else db
                    elif isinstance(layer, (torch.nn.Conv1d, torch.nn.Conv2d, torch.nn.Conv3d)):
                        delta = (
                            layer._conv_forward(x, dw, db)
                            if dw is not None
                            else db.reshape(1, -1, *([1] * (x.ndim - 2)))
                        )
                    else:
                        if isinstance(layer, torch.nn.LayerNorm):
                            normal = F.layer_norm(x, layer.normalized_shape, eps=layer.eps)
                        elif isinstance(layer, torch.nn.GroupNorm):
                            normal = F.group_norm(x, layer.num_groups, eps=layer.eps)
                        else:
                            normal = F.rms_norm(x, layer.normalized_shape, eps=layer.eps)
                        delta = 0
                        if dw is not None:
                            delta = (
                                normal * dw.reshape(1, -1, *([1] * (x.ndim - 2)))
                                if isinstance(layer, torch.nn.GroupNorm)
                                else normal * dw
                            )
                        if db is not None:
                            delta = (
                                delta + db.reshape(1, -1, *([1] * (x.ndim - 2)))
                                if isinstance(layer, torch.nn.GroupNorm)
                                else delta + db
                            )
                    return output + delta.to(output)

                handles.append(module.register_forward_hook(hook))
            yield
        finally:
            for h in reversed(handles):
                h.remove()
