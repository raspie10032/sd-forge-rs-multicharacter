#!/usr/bin/env python3
"""Compare actual ComfyUI routing/model/LoRA math with the Forge adapter.

No downloads or servers. Tiny CPU models are random; --capture instead replays
real tensors and weights exported by tools/capture_parity.py from a local Forge.
"""
import argparse
from contextlib import contextmanager, ExitStack
from dataclasses import replace
from functools import partial
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

import torch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--comfy', type=Path, required=True)
parser.add_argument('--original', type=Path, required=True)
parser.add_argument('--forge', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--capture', type=Path)
parser.add_argument('--device', default='cpu')
parser.add_argument('--allow-live-output-drift', action='store_true',
                    help='Report, without asserting, a saved output from a different GPU/kernel. '
                         'The same-device ComfyUI versus Forge comparison remains strict.')
args = parser.parse_args()
sys.path[:0] = [str(args.comfy), str(args.forge), str(Path(__file__).resolve().parents[1])]
sys.argv = [sys.argv[0], '--cpu']
import comfy.ops  # noqa: E402
from comfy.ldm.cosmos.predict2 import MiniTrainDIT  # noqa: E402
from comfy.weight_adapter.lora import LoRAAdapter as ComfyLoRA  # noqa: E402
from backend.nn.anima import Anima  # noqa: E402
from backend.operations import using_forge_operations  # noqa: E402
from modules_forge.packages.comfy.weight_adapter.lora import LoRAAdapter  # noqa: E402
from rs_forge_mc.config import Config, Character, Settings  # noqa: E402
from rs_forge_mc.lora import LoraPlan  # noqa: E402
from rs_forge_mc.runtime import text_tensor  # noqa: E402
from rs_forge_mc.native_runtime import NativeRuntime  # noqa: E402


def AnimaRuntime(config, contexts, plans, x):
    return NativeRuntime(config, contexts, plans, "Anima", size=(x.shape[-1] * 8, x.shape[-2] * 8))

package = ModuleType('rs_comfy_reference')
package.__path__ = [str(args.original)]
sys.modules[package.__name__] = package
Engine = importlib.import_module(package.__name__+'.engine').AnimaRouting
Layout = importlib.import_module(package.__name__+'.layout')
Grouped = importlib.import_module(package.__name__+'.regional_lora').grouped_masks
Shared = importlib.import_module(package.__name__+'.shared_lora')

torch.set_num_threads(2)
torch.manual_seed(20261107)


class Root(torch.nn.Module):
    def __init__(self, model, multiplier=1.):
        super().__init__()
        self.diffusion_model = model
        self.multiplier = multiplier

    def apply_model(self, x, t, c_crossattn, **kw):
        dtype = next(self.parameters()).dtype
        result = self.diffusion_model(x.to(dtype), t.float()*self.multiplier, c_crossattn.to(dtype), **kw).float()
        return x - result * t.reshape(-1, 1, 1, 1, 1)


class Executor:
    def __init__(self, model):
        self.class_obj = model

    def __call__(self, *a, **kw):
        return self.class_obj(*a, **kw)


def metrics(a, b):
    a, b = a.float(), b.float()
    rmse = (a-b).square().mean().sqrt()
    return dict(max_abs=float((a-b).abs().max()), rmse=float(rmse),
                relative_rmse=float(rmse/a.square().mean().sqrt()))


def adapters_for(plans, dtype, device):
    return {name: [(path.removeprefix('diffusion_model.'),
                   ComfyLoRA(set(), (f.up.to(device=device, dtype=dtype),
                                     f.down.to(device=device, dtype=dtype),
                                     f.scale*f.down.shape[0], None, None, None)))
                  for path, f in zip(plan.paths, plan.factors)] for name, plan in plans.items()}


@contextmanager
def reference_lora(model, entries, strength=1.):
    saved = []
    try:
        for path, adapter in entries:
            layer = model.get_submodule(path)
            saved.append((layer, 'forward' in layer.__dict__, layer.__dict__.get('forward')))
            original = layer.forward
            adapter.multiplier = strength
            def forward(x, *a, original=original, adapter=adapter, **kw):
                base = original(x, *a, **kw)
                return base + adapter.h(x, base)
            layer.forward = forward
        yield
    finally:
        for layer, present, original in reversed(saved):
            if present:
                layer.forward = original
            else:
                layer.__dict__.pop('forward', None)


def reference(model, config, contexts, plans, x, t, base, sigmas, kinds, multiplier=1.):
    chars = config.to_pipe().regions
    centers, _ = Layout.effective_centers(chars)
    masks = Layout.character_masks(chars, centers, x.shape[-1]*8, x.shape[-2]*8, .04)
    hooks = [(c.lora_name, c.lora_strength) if c.lora_name != 'None' and c.lora_strength else None for c in chars]
    grouped = Grouped(hooks, masks, chars) if plans else [(None, torch.ones_like(masks[0]))]
    s = config.settings
    router = Engine([], masks, 'character_first', {}, base.shape[1],
                    initial_common_prior=s.common_prior, initial_character_gain=s.character_gain,
                    initial_spatial_separation=s.separation, late_spatial_separation=0.,
                    common_weight_schedule='step_3x0.2', spatial_separation_schedule='hold_decay',
                    boundary_hold_steps=min(s.hold_steps, len(sigmas)-1), boundary_decrement=s.decay,
                    common_after_step3_boost=.1, boxes=tuple(c.bbox is not None or c.region_mask is not None for c in chars))
    router.contexts = contexts
    router.sigmas = sigmas[:-1].tolist()
    router.audit.update(forwards=[], cross_calls=0, self_calls=0, restored_forwards=0)
    adapters = adapters_for(plans, base.dtype, x.device)
    output, counts = torch.zeros_like(x), torch.ones_like(x)*1e-37
    with ExitStack() as stack:
        if plans and s.lora_mode == 'normal':
            shared = Shared.SharedRegionalLora.__new__(Shared.SharedRegionalLora)
            shared.mask_cache = {}
            shared.audit = dict(base_layer_calls=0, adapter_calls=0)
            layer_adapters = {}
            for name, entries in adapters.items():
                mask = sum((mask * key[1] for key, mask in grouped if key and key[0] == name), torch.zeros_like(masks[0]))
                strengths = [c.lora_strength if c.lora_name == name else 0. for c in chars]
                for path, adapter in entries:
                    adapter.multiplier = 1.
                    layer_adapters.setdefault(path, []).append((adapter, mask, strengths))
            for path, entries in layer_adapters.items():
                layer = model.get_submodule(path)
                original = layer.forward
                layer.forward = partial(shared.layer_forward, original, entries, Shared.layer_role(path),
                                        (x.shape[-2]//2, x.shape[-1]//2), [base.shape[1], *[c.shape[1] for c in contexts]])
                stack.callback(layer.__dict__.pop, 'forward')
            grouped = [(None, torch.ones_like(masks[0]))]
        for key, mask in grouped:
            scope = reference_lora(model, adapters[key[0]], key[1]) if key else ExitStack()
            with scope:
                result = router.forward(Executor(model), x.to(base.dtype), t*multiplier, base,
                                        transformer_options=dict(cond_or_uncond=kinds, sigmas=t))
            prediction = x - result.float()*t.reshape(-1, 1, 1, 1, 1)
            weight = mask.to(x)[None, None, None]
            output += prediction * weight
            counts += weight
    return output/counts


def tiny():
    kw = dict(in_channels=4, out_channels=4, patch_spatial=2, patch_temporal=1,
              model_channels=48, crossattn_emb_channels=24, adaln_lora_dim=16, num_blocks=2, num_heads=2)
    comfy_core = MiniTrainDIT(max_img_h=240, max_img_w=240, max_frames=128, use_adaln_lora=True,
                        pos_emb_cls='rope3d', operations=comfy.ops.disable_weight_init, **kw)
    with using_forge_operations(device=torch.device('cpu'), dtype=torch.float32):
        forge = Anima(**kw)
    for p in forge.parameters():
        torch.nn.init.ones_(p) if p.ndim == 1 else torch.nn.init.normal_(p, std=.05)
    comfy_core.load_state_dict(forge.state_dict())
    root = Root(forge)
    plans = {}
    for name in ('a', 'b'):
        patches = {}
        for path in ('diffusion_model.blocks.0.cross_attn.q_proj',
                     'diffusion_model.blocks.0.cross_attn.k_proj', 'diffusion_model.blocks.0.mlp.layer1'):
            layer = root.get_submodule(path)
            patches[path+'.weight'] = LoRAAdapter(set(), (torch.randn(layer.out_features, 3)*.1,
                                                         torch.randn(3, layer.in_features)*.1, 2., None, None, None))
        plans[name] = LoraPlan(root, patches)
    x, base = torch.randn(2, 4, 1, 16, 24), torch.randn(2, 6, 24)
    contexts = [torch.randn(1, 5, 24), torch.randn(1, 7, 24)]
    sigmas = torch.cat((torch.linspace(.99, .1, 9), torch.zeros(1)))
    layouts = [Config((Character(prompt='a', x=.27, y=.38, lora='a', strength=.63),
                       Character(prompt='b', x=.74, y=.63, lora='b', strength=.79))),
               Config((Character(prompt='a', x=.35, box=(.1,.1,.6,.9), lora='a', strength=.63),
                       Character(prompt='b', x=.65, box=(.4,.1,.9,.9), lora='b', strength=.79))),
               Config((Character(prompt='a', x=.2, lora='a', strength=.63),
                       Character(prompt='b', x=.75, box=(.5,0,1,1), lora='a', strength=.79)))]
    rows = []
    with torch.inference_mode():
        for dtype in (torch.float32, torch.bfloat16):
            comfy_core.to(dtype)
            forge.to(dtype)
            for layout, config in enumerate(layouts):
                for mode in ('precision', 'normal'):
                    config = replace(config, settings=Settings(lora_mode=mode))
                    runtime = AnimaRuntime(config, contexts, plans, x)
                    for index in (0, 3, 8):
                        t = sigmas[index].expand(2)
                        c = dict(c_crossattn=base.to(dtype), transformer_options=dict(sigmas=t, sampling_sigmas=sigmas))
                        a = reference(comfy_core, config, [v.to(dtype) for v in contexts], plans, x, t, base.to(dtype), sigmas, [0, 1])
                        b = runtime(root.apply_model, dict(input=x, timestep=t, c=c, cond_or_uncond=[0, 1]))
                        row = dict(dtype=str(dtype), layout=layout, mode=mode, step=index, **metrics(a,b))
                        rows.append(row)
                        print(json.dumps(row), flush=True)
                        torch.testing.assert_close(a,b,rtol=2e-6,atol=2e-6)
    return dict(kind='tiny actual ComfyUI and Forge model classes; original routing and LoRA algebra', cases=rows)


def replay():
    data = torch.load(args.capture, map_location='cpu', weights_only=True)
    device = torch.device(args.device)
    dtype = getattr(torch, data['computation_dtype'].removeprefix('torch.'))
    kw = data['model_kwargs']
    # The live Anima loader uses 4x spatial RoPE extrapolation. Constructor
    # defaults are 1x and do not describe a loaded checkpoint.
    from comfy.model_detection import detect_unet_config
    detected = detect_unet_config(data['state'], '')
    kw = {**kw, **{key: value for key, value in detected.items()
                   if key in ('rope_h_extrapolation_ratio', 'rope_w_extrapolation_ratio',
                              'rope_t_extrapolation_ratio')}}
    comfy_core = MiniTrainDIT(max_img_h=240, max_img_w=240, max_frames=128, use_adaln_lora=True,
                             pos_emb_cls='rope3d', operations=comfy.ops.disable_weight_init, **kw)
    with using_forge_operations(device=torch.device('cpu'), dtype=dtype):
        forge = Anima(**kw)
    state = {k: v for k, v in data['state'].items() if not k.startswith('llm_adapter.')}
    comfy_core.load_state_dict(state, assign=True)
    forge.load_state_dict(state, assign=True)
    # Nonpersistent position buffers are intentionally absent from state_dict.
    # Replay their exact runtime dtype instead of an accidental model.to(dtype).
    for model in (comfy_core, forge):
        for axis, factor in data.get('rope_factors', {}).items():
            setattr(model.pos_embedder, axis+'_ntk_factor', factor)
        for path, value in data['buffers'].items():
            if path.startswith('llm_adapter.'):
                continue
            parent, _, name = path.rpartition('.')
            setattr(model.get_submodule(parent), name, value.clone())
    config = Config.from_json(data['config'])
    root = Root(forge, data['multiplier'])
    plans = {}
    for name, plan in data['plans'].items():
        plans[name] = LoraPlan(root, {path+'.weight': LoRAAdapter(set(),
            (f['up'], f['down'], f['alpha'], None, None, None))
            for path, f in zip(plan['paths'], plan['factors'])})
    inputs = data['inputs']
    x, t = inputs['input'].to(device), inputs['timestep'].to(device)
    base = text_tensor(inputs['c']['c_crossattn']).to(device=device, dtype=dtype)
    sigmas = inputs['c']['transformer_options']['sampling_sigmas'].to(device)
    contexts = [v.to(device=device, dtype=dtype) for v in data['contexts']]
    c = dict(c_crossattn=base, transformer_options=dict(sigmas=t, sampling_sigmas=sigmas))
    kinds = inputs['cond_or_uncond']
    rows = []
    with torch.inference_mode():
        for mode in ('precision', 'normal'):
            cfg = replace(config, settings=replace(config.settings, lora_mode=mode))
            comfy_core.to(device)
            a = reference(comfy_core, cfg, contexts, plans, x, t, base, sigmas, kinds, data['multiplier'])
            comfy_core.cpu()
            torch.cuda.empty_cache() if device.type == 'cuda' else None
            forge.to(device)
            b = AnimaRuntime(cfg, data['contexts'], plans, x)(root.apply_model,
                dict(input=x, timestep=t, c=c, cond_or_uncond=kinds))
            row = dict(mode=mode, **metrics(a,b))
            if mode == config.settings.lora_mode:
                row['live_forge_vs_replay'] = metrics(data['output'].to(device),b)
                if not args.allow_live_output_drift:
                    torch.testing.assert_close(data['output'].to(device), b, rtol=2e-6, atol=2e-6)
            rows.append(row)
            print(json.dumps(row), flush=True)
            torch.testing.assert_close(a,b,rtol=2e-6,atol=2e-6)
            forge.cpu()
            torch.cuda.empty_cache() if device.type == 'cuda' else None
    return dict(kind='actual live Forge inputs and trained Anima weights replayed through original ComfyUI routing/LoRA',
                capture=str(args.capture), dtype=str(dtype), device=str(device),
                latent_shape=list(x.shape), text_shapes=[list(base.shape), *[list(c.shape) for c in contexts]],
                multiplier=data['multiplier'], cases=rows,
                live_output_strict=not args.allow_live_output_drift,
                limits='Diffusion/region/LoRA parity with identical encoded text, latent, sigma and weights. Does not establish independent tokenization, RNG, sampler or VAE parity. Saved live-output drift is diagnostic when explicitly allowed for a different GPU/kernel.')


if __name__ == '__main__':
    report = replay() if args.capture else tiny()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(cases=len(report['cases']), max_abs=max(r['max_abs'] for r in report['cases']))))
