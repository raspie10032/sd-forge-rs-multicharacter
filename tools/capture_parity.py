#!/usr/bin/env python3
"""Launch local Forge and capture the first RS model call for offline replay.

Usage: python capture_parity.py --capture /absolute/path/call.pt --forge /path/to/forge -- [Forge flags]
This opt-in diagnostic saves model weights and prompt tensors locally. It never
changes the installed Forge source or adds a network endpoint.
"""
import argparse
import os
from pathlib import Path
import runpy
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--capture', type=Path, required=True)
parser.add_argument('--forge', type=Path, required=True)
args, flags = parser.parse_known_args()
target, forge_dir = args.capture.resolve(), args.forge.resolve()
if target.exists():
    parser.error(f'Capture already exists: {target}')
sys.path[:0] = [str(forge_dir), str(Path(__file__).resolve().parents[1])]
sys.argv = [str(forge_dir/'launch.py'), *(flags[1:] if flags[:1] == ['--'] else flags)]
os.chdir(forge_dir)

import torch  # noqa: E402
from rs_forge_mc.runtime import AnimaRuntime  # noqa: E402

original = AnimaRuntime.__call__
captured = False


def cpu(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {k: cpu(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [cpu(v) for v in value]
    return value


def call(self, apply_model, inputs):
    global captured
    if captured:
        return original(self, apply_model, inputs)
    captured = True
    root = apply_model.__self__
    model = root.diffusion_model
    block = model.blocks[0]
    kw = dict(in_channels=model.in_channels, out_channels=model.out_channels,
              patch_spatial=model.patch_spatial, patch_temporal=model.patch_temporal,
              model_channels=block.self_attn.q_proj.in_features,
              crossattn_emb_channels=block.cross_attn.k_proj.in_features,
              adaln_lora_dim=block.adaln_modulation_mlp[1].out_features,
              num_blocks=len(model.blocks), num_heads=block.self_attn.n_heads)
    data = dict(config=self.config.to_json(), contexts=cpu(self.contexts),
                inputs=cpu(inputs), model_kwargs=kw,
                computation_dtype=str(root.computation_dtype),
                multiplier=root.predictor.multiplier,
                rope_factors={axis: getattr(model.pos_embedder, axis+'_ntk_factor')
                              for axis in ('h', 'w', 't')},
                buffers=cpu(dict(model.named_buffers())),
                state=cpu(model.state_dict()),
                plans={name: dict(paths=plan.paths, factors=[dict(up=cpu(f.up), down=cpu(f.down),
                        alpha=f.scale*f.down.shape[0]) for f in plan.factors])
                       for name, plan in self.plans.items()})
    result = original(self, apply_model, inputs)
    data['output'] = cpu(result)
    target.parent.mkdir(parents=True, exist_ok=True)
    torch.save(data, target)
    print(f'RS parity capture saved: {target}', flush=True)
    return result


AnimaRuntime.__call__ = call
runpy.run_path(str(forge_dir/'launch.py'), run_name='__main__')
