# SPDX-License-Identifier: GPL-3.0-only
"""Model-family pose controls with execution-scoped Forge hooks."""

from contextlib import contextmanager
import torch
from .host import verified_asset, load_torch_file, common_upscale, VAEView


def prepare(runtime, unet, p, width, height):
    settings = runtime.config.features.get("pose", {})
    if settings.get("mode", "masks_only") == "masks_only" or settings.get("strength", 1) == 0:
        return
    if not runtime.config.pose3d_json:
        raise ValueError("Learned pose needs a 3D scene.")
    if runtime.config.features.get("progressive", {}).get("start_scale", 1) < 1:
        raise ValueError("Learned pose requires full resolution, as in the original.")
    from .shared.pose3d import read_scene
    from .shared.pose_control_maps import control_maps

    scene = {**read_scene(runtime.config.pose3d_json), "width": width, "height": height}
    color, depth, skeleton = control_maps(scene)

    def image(a):
        return torch.from_numpy(a.copy()).float()[None] / 255.0

    predictor = unet.model.predictor
    plan = {
        "family": runtime.family,
        "strength": settings.get("strength", 1.0),
        "start_sigma": float(predictor.percent_to_sigma(settings.get("start", 0))),
        "end_sigma": float(predictor.percent_to_sigma(settings.get("end", 1))),
    }
    dm = unet.model.diffusion_model
    if runtime.family == "Anima":
        from .anima_lllite import AnimaLLLite

        path = verified_asset("anima_pose")
        weights = load_torch_file(path)
        from safetensors import safe_open

        with safe_open(path, framework="pt") as f:
            metadata = f.metadata()
        adapter = AnimaLLLite(weights, metadata, operations=torch.nn)
        if (
            adapter.block_count != len(dm.blocks)
            or adapter.model_dim != dm.blocks[0].self_attn.q_proj.in_features
        ):
            raise ValueError("The learned Anima pose weights require the matching 2B architecture.")
        plan.update(model=adapter, pixels=image(skeleton), cache={})
        unet.add_extra_torch_module_during_sampling(adapter, cast_to_unet_dtype=False)
    elif runtime.family in ("Krea2", "MOSS"):
        from backend.patcher.lora import load_lora, model_lora_keys_unet
        from .adapter_delta import WeightDeltaPlan

        weights = load_torch_file(verified_asset("krea_pose" if runtime.family == "Krea2" else "moss_pose"))
        if runtime.family == "MOSS":
            plan["embedder"] = {k: weights.pop(k) for k in ("video_embedder.weight", "video_embedder.bias")}
            weights = {
                (k if k.startswith("diffusion_model.") else "diffusion_model." + k): v
                for k, v in weights.items()
            }
        patches, remaining = load_lora(weights, model_lora_keys_unet(unet.model, {}))
        if remaining or not patches:
            raise ValueError("Pose adapter tensors do not match this model: " + str(list(remaining)[:3]))
        plan["lora"] = WeightDeltaPlan(unet.model, patches)
        vae = VAEView(p.sd_model.forge_objects.vae)
        if runtime.family == "MOSS":
            plan["control"] = torch.cat([vae.process(vae.encode(image(a))) for a in (color, depth)], 1)
        else:
            pixels = image(skeleton)
            h, w = pixels.shape[1:3]

            def fit(area, snap):
                scale = min(1.0, (area / (w * h)) ** 0.5)
                return common_upscale(
                    pixels.movedim(-1, 1),
                    max(snap, round(w * scale / snap) * snap),
                    max(snap, round(h * scale / snap) * snap),
                    "area",
                ).movedim(1, -1)

            plan["latent"] = vae.process(vae.encode(fit(1024**2, 16)))
            plan["pixels"] = fit(384**2, 1)
            runtime.routing.pose_runtime = plan
            runtime.routing.pose_start_sigma = plan["start_sigma"]
            runtime.routing.pose_end_sigma = plan["end_sigma"]
            runtime.routing.pose_kv = {}
    else:
        raise ValueError("The original learned 3D pose adapters support Anima, Krea2 and MOSS.")
    runtime.pose_runtime = plan
    runtime.audit["learned_pose"] = {
        k: v for k, v in plan.items() if k in ("family", "strength", "start_sigma", "end_sigma")
    }


@contextmanager
def scope(runtime, root, x, sigma):
    plan = runtime.pose_runtime
    if not plan or not plan["end_sigma"] <= float(sigma.max()) <= plan["start_sigma"]:
        yield
        return
    handles = []
    try:
        if plan["family"] == "Anima":
            dtype = root.diffusion_model.blocks[0].self_attn.q_proj.weight.dtype
            model = plan["model"].to(device=x.device, dtype=dtype)
            key = (tuple(x.shape[-2:]), str(x.device), dtype)
            if key not in plan["cache"]:
                pixels = (
                    common_upscale(
                        plan["pixels"].movedim(-1, 1), x.shape[-1] * 8, x.shape[-2] * 8, "bicubic", "center"
                    )
                    .clamp(0, 1)
                    .to(device=x.device, dtype=dtype)
                    * 2
                    - 1
                )
                if model.cond_in_channels == 4:
                    pixels = torch.cat((pixels, torch.ones_like(pixels[:, :1])), 1)
                plan["cache"][key] = model.encode_conditioning(pixels)
            cond = plan["cache"][key]
            for i, block in enumerate(root.diffusion_model.blocks):
                for target, path in (
                    ("self_attn_q_proj", "self_attn.q_proj"),
                    ("self_attn_k_proj", "self_attn.k_proj"),
                    ("self_attn_v_proj", "self_attn.v_proj"),
                    ("cross_attn_q_proj", "cross_attn.q_proj"),
                    ("mlp_layer1", "mlp.layer1"),
                ):

                    def hook(module, args, i=i, target=target):
                        return (model.apply(args[0], cond, i, target, plan["strength"]), *args[1:])

                    handles.append(block.get_submodule(path).register_forward_pre_hook(hook))
            yield
        else:
            if plan["family"] == "MOSS":
                embedder = root.diffusion_model.video_embedder

                def full(module, args, output):
                    target = args[0]
                    h, w = x.shape[-2:]
                    control = (
                        common_upscale(plan["control"].to(x), w, h, "bilinear").flatten(2).transpose(1, 2)
                    )
                    control = control.expand(target.shape[0], -1, -1)
                    return torch.nn.functional.linear(
                        torch.cat((target, control), -1),
                        plan["embedder"]["video_embedder.weight"].to(target),
                        plan["embedder"]["video_embedder.bias"].to(target),
                    )

                handles.append(embedder.register_forward_hook(full))
            with plan["lora"].applied(root, plan["strength"]):
                yield
    finally:
        for h in reversed(handles):
            h.remove()
