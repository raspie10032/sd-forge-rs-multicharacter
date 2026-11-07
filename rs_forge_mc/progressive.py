# SPDX-License-Identifier: GPL-3.0-only
"""Original three-stage resize/noise policy, scoped to one Forge sampler."""

import torch
import math
from functools import wraps
from .shared.progressive import resolution_plan, resize_lanczos, resize_mask


def install(p, config):
    p._rs_mc_progressive = config.features["progressive"]


def attach(p):
    settings = getattr(p, "_rs_mc_progressive", None)
    sampler = getattr(p, "sampler", None)
    if not settings or not sampler or getattr(p, "_rs_mc_sampler_restore", None):
        return
    original = sampler.func

    @wraps(original)
    def progressive(model, x, *args, **kwargs):
        if settings["start_scale"] >= 1:
            return original(model, x, *args, **kwargs)
        sigmas = kwargs.get("sigmas", kwargs.get("sigma_sched"))
        if sigmas is None:
            raise ValueError("Progressive sampling needs an explicit sigma schedule.")
        target = tuple(x.shape[-2:])
        steps = len(sigmas) - 1
        plan = resolution_plan(target[1] * 8, target[0] * 8, steps, settings["start_scale"])
        predictor = p.sd_model.forge_objects.unet.model.predictor
        seed = int(p.all_seeds[0])
        generator = torch.Generator(device=x.device).manual_seed(seed ^ 0x5EED1234)
        ancestral = torch.Generator(device=x.device).manual_seed((seed + (x.device.type == "cpu")) % 2**64)
        callback = kwargs.get("callback")
        last = None
        report = []
        for index, stage in enumerate(plan):
            start, end = stage["start"], stage["end"]
            grid = (stage["height"] // 8, stage["width"] // 8)
            if index == 0:
                source = getattr(model, "init_latent", None)
                if getattr(model, "mask", None) is not None:
                    raise ValueError(
                        "Use progressive resolution for txt2img or ordinary img2img; masked inpainting needs a fixed grid."
                    )
                initial = (
                    resize_mask(source, grid).to(x)
                    if source is not None
                    else x.new_zeros((*x.shape[:-2], *grid))
                )
                noise = torch.randn(
                    initial.shape,
                    device="cpu",
                    dtype=x.dtype,
                    generator=torch.Generator(device="cpu").manual_seed(seed),
                ).to(x)
                maximum = float(predictor.sigma_max)
                maximum_noise = (
                    math.isclose(maximum, float(sigmas[0]), rel_tol=1e-5) or float(sigmas[0]) > maximum
                )
                x = predictor.noise_scaling(sigmas[0], noise, initial, max_denoise=maximum_noise)
            elif x.shape[-2:] != grid:
                if last is None:
                    raise ValueError("Sampler did not report a clean prediction before expansion.")
                clean = resize_lanczos(last, grid)
                fresh = torch.randn(clean.shape, device=x.device, dtype=x.dtype, generator=generator)
                x = predictor.noise_scaling(sigmas[start], fresh, clean)

            def observe(data):
                nonlocal last
                last = data["denoised"].detach()
                if callback:
                    callback({**data, "i": start + data["i"]})

            options = {**kwargs, "sigmas": sigmas[start : end + 1], "callback": observe}
            options["extra_args"] = {**kwargs.get("extra_args", {}), "seed": (seed + index * 10000) % 2**64}
            for name, value in list(options["extra_args"].items()):
                if (
                    isinstance(value, torch.Tensor)
                    and value.ndim in (4, 5)
                    and tuple(value.shape[-2:]) == target
                ):
                    options["extra_args"][name] = resize_mask(value, grid)
            if "euler_ancestral" in original.__name__:
                options["noise_sampler"] = lambda _a, _b: torch.randn(
                    x.shape, device=x.device, dtype=x.dtype, generator=ancestral
                )
            last = None
            x = original(model, x, *args, **options)
            report.append({**stage, "latent_grid": list(grid)})
            if not torch.isfinite(x).all():
                raise ValueError("Nonfinite progressive latent.")
        p.extra_generation_params["RS progressive stages"] = str(report)
        return x

    sampler.func = progressive

    def restore():
        sampler.func = original
        p.__dict__.pop("_rs_mc_progressive", None)
        p.__dict__.pop("_rs_mc_sampler_restore", None)

    p._rs_mc_sampler_restore = restore
