#!/usr/bin/env python
"""CPU smoke against real Neo classes, randomly initialized tiny Anima only.

Usage: python tools/validate_native.py /path/to/forge-neo [--cpu]
No checkpoint, text encoder, VAE, or full WebUI generation is tested here.
"""
from pathlib import Path
import copy
from dataclasses import replace
import json
import sys
from types import SimpleNamespace

forge_directory = Path(sys.argv[1]).resolve()
report_path = Path(sys.argv[sys.argv.index('--report')+1]) if '--report' in sys.argv else None
sys.path[:0] = [str(forge_directory), str(Path(__file__).resolve().parents[1])]
sys.argv = [sys.argv[0], '--cpu']

import torch  # noqa: E402
from backend.args import dynamic_args  # noqa: E402
from backend.modules.k_model import KModel  # noqa: E402
from backend.modules.k_prediction import PredictionDiscreteFlow  # noqa: E402
from backend.nn.anima import Anima  # noqa: E402
from backend.patcher.unet import UnetPatcher  # noqa: E402
from backend.operations import using_forge_operations  # noqa: E402
from modules_forge.packages.comfy.weight_adapter.lora import LoRAAdapter  # noqa: E402
from rs_forge_mc.config import Character, Config  # noqa: E402
from rs_forge_mc.lora import LoraPlan  # noqa: E402
from rs_forge_mc.runtime import install  # noqa: E402

torch.manual_seed(20261107)
torch.set_num_threads(2)
dynamic_args.ops = 'PyTorch'
with using_forge_operations(device=torch.device('cpu'),dtype=torch.float32):
    model = Anima(in_channels=4,out_channels=4,patch_spatial=2,patch_temporal=1,
                  model_channels=48,crossattn_emb_channels=24,adaln_lora_dim=16,num_blocks=2,num_heads=2)
with torch.no_grad():
    for parameter in model.parameters():
        if parameter.ndim == 1:
            parameter.fill_(1.)
        else:
            parameter.normal_(std=.05)
model.storage_dtype = model.computation_dtype = torch.float32
root = KModel(model,None,SimpleNamespace(memory_usage_factor=1.),
              PredictionDiscreteFlow(SimpleNamespace(sampling_settings={})))
unet = UnetPatcher(root,torch.device('cpu'),torch.device('cpu'))
config = Config((Character(prompt='left', x=.25,lora='synthetic-a'),
                 Character(prompt='right', x=.75,lora='synthetic-b',strength=.7)))
config = replace(config, settings=replace(config.settings,lora_mode='precision'))
contexts = [torch.randn(1,5,24),torch.randn(1,7,24)]
paths = [name for name,layer in root.named_modules() if
         name.startswith('diffusion_model.blocks.0.') and
         name.endswith(('cross_attn.q_proj','cross_attn.k_proj','mlp.layer1')) and
         isinstance(layer,torch.nn.Linear)]
assert len(paths)==3
plans = {}
for name in ['synthetic-a','synthetic-b']:
    patches = {}
    for path in paths:
        layer = root.get_submodule(path)
        up,down = torch.randn(layer.out_features,2)*.1,torch.randn(2,layer.in_features)*.1
        patches[path+'.weight'] = LoRAAdapter(set(),(up,down,2.,None,None,None))
    plans[name] = LoraPlan(root,patches)
weights_before = {k:v.clone() for k,v in root.state_dict().items()}
x,t = torch.randn(2,4,1,16,16),torch.tensor([.9,.9])
base_context = torch.randn(2,6,24)
sigmas = torch.tensor([.9,.6,.3,0.])
conditions = {'c_crossattn':base_context,'transformer_options':{'sampling_sigmas':sigmas,'sigmas':t}}
args = {'input':x,'timestep':t,'c':conditions,'cond_or_uncond':[0,1]}
report = {'backend':'native Forge Neo Anima + KModel + UnetPatcher, CPU, random tiny weights',
          'checkpoint_generation':False,'lora_layers':paths}
with torch.inference_mode():
    baseline = root.apply_model(x,t,**conditions)
    patched,runtime = install(unet,config,contexts,plans)
    assert 'model_function_wrapper' not in unet.model_options
    assert len(patched.extra_model_patchers_during_sampling)==2
    out = patched.model_options['model_function_wrapper'](root.apply_model,args)
    assert out.shape == baseline.shape and torch.isfinite(out).all()
    assert not torch.equal(out,baseline)
    report['regional_max_delta'] = float((out-baseline).abs().max())
    assert runtime.audit['prediction_passes']==2
    # A different latent shape exercises Hires/img2img grid recalculation.
    bigger = copy.copy(args)
    bigger['input']=torch.randn(2,4,1,24,32)
    bigger_out = runtime(root.apply_model,bigger)
    assert bigger_out.shape == bigger['input'].shape
    # Native attention and every checkpoint tensor return exactly to baseline.
    assert all('torch_attention_op' not in block.cross_attn.__dict__ and
               'torch_attention_op' not in block.self_attn.__dict__ for block in model.blocks)
    assert all(torch.equal(v,weights_before[k]) for k,v in root.state_dict().items())
    assert not any(layer._forward_hooks for layer in root.modules())
    torch.testing.assert_close(root.apply_model(x,t,**conditions),baseline,rtol=0,atol=0)
    report['restoration_exact']=True
    normal_config = replace(config,settings=replace(config.settings,lora_mode='normal'))
    normal_patched,normal_runtime = install(unet,normal_config,contexts,plans)
    normal_out = normal_patched.model_options['model_function_wrapper'](root.apply_model,args)
    assert normal_runtime.audit['effective_lora_mode']=='normal'
    assert normal_runtime.audit['prediction_passes']==1
    assert torch.isfinite(normal_out).all() and not torch.equal(normal_out,baseline)
    assert not any(layer._forward_hooks for layer in root.modules())
    assert all(torch.equal(v,weights_before[k]) for k,v in root.state_dict().items())
    report['normal_audit']=normal_runtime.audit
    report['audit']=runtime.audit
    # Deliberate failure must remove installed ops and LoRA hooks, too.
    original_forward = model.forward
    def fail(*args,**kwargs):
        raise RuntimeError('deliberate native failure')
    model.forward = fail
    try:
        normal_runtime(root.apply_model,args)
        raise AssertionError('Failure did not propagate')
    except RuntimeError as error:
        assert 'deliberate native failure' in str(error)
    finally:
        model.forward = original_forward
    assert all('torch_attention_op' not in block.cross_attn.__dict__ for block in model.blocks)
    assert not any(layer._forward_hooks for layer in root.modules())
    report['failure_restoration']=True
if report_path is not None:
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
