# SPDX-License-Identifier: GPL-3.0-only
"""Explicit Forge services for shared RS code. Never registers fake Comfy modules."""

import hashlib
import math
import os
from pathlib import Path
from types import SimpleNamespace

import torch
import torch.nn.functional as F


def models_dir():
    from modules import paths

    return Path(paths.models_path)


def model_roots():
    from modules import shared

    roots = [models_dir()]
    roots += [
        Path(p).expanduser()
        for p in str(getattr(shared.opts, "rs_mc_model_roots", "")).split(os.pathsep)
        if p
    ]
    return roots


class Folders:
    @property
    def models_dir(self):
        return str(models_dir())

    @property
    def folder_names_and_paths(self):
        return {p.name: None for root in model_roots() for p in root.iterdir() if p.is_dir()}

    def get_folder_paths(self, name):
        return [
            str(root / ("ultralytics/" + name if name in ("bbox", "segm") else name))
            for root in model_roots()
            if (root / ("ultralytics/" + name if name in ("bbox", "segm") else name)).exists()
        ]

    def get_full_path(self, name, file):
        for root in self.get_folder_paths(name):
            p = (Path(root) / file).resolve()
            if p.is_relative_to(Path(root).resolve()) and p.is_file():
                return str(p)
        return None

    def get_full_path_or_raise(self, name, file):
        p = self.get_full_path(name, file)
        if not p:
            raise FileNotFoundError(f"Missing local {name}: {file}")
        return p

    def get_filename_list(self, name):
        return sorted(
            {
                str(p.relative_to(root))
                for root in map(Path, self.get_folder_paths(name))
                for p in root.rglob("*")
                if p.is_file()
            }
        )

    def get_input_directory(self):
        p = models_dir() / "rs_mc" / "assets"
        p.mkdir(parents=True, exist_ok=True)
        return str(p)


folders = Folders()


def load_torch_file(path, safe_load=True, **kwargs):
    if str(path).endswith(".safetensors"):
        from safetensors.torch import load_file

        return load_file(str(path), device="cpu")
    return torch.load(path, map_location="cpu", weights_only=True)


def pad_to_patch_size(x, patch_size):
    padding = []
    for size, patch in zip(reversed(x.shape[-len(patch_size) :]), reversed(patch_size)):
        padding.extend((0, (-size) % patch))
    return F.pad(x, padding, mode="replicate") if any(padding) else x


def repeat_to_batch_size(x, n):
    return x.repeat(math.ceil(n / x.shape[0]), *([1] * (x.ndim - 1)))[:n]


def common_upscale(x, w, h, mode, crop="disabled"):
    if crop == "center":
        ih, iw = x.shape[-2:]
        aspect = w / h
        if iw / ih > aspect:
            nw = round(ih * aspect)
            x = x[..., (iw - nw) // 2 : (iw + nw) // 2]
        elif iw / ih < aspect:
            nh = round(iw / aspect)
            x = x[..., (ih - nh) // 2 : (ih + nh) // 2, :]
    if mode == "lanczos":
        import numpy as np
        from PIL import Image

        images = x.movedim(1, -1).detach().cpu().numpy()
        resized = [
            np.asarray(
                Image.fromarray(np.clip(255 * a, 0, 255).astype(np.uint8)).resize(
                    (w, h), Image.Resampling.LANCZOS
                )
            ).copy()
            for a in images
        ]
        return (torch.from_numpy(np.stack(resized)).movedim(-1, 1) / 255.0).to(x)
    return F.interpolate(
        x, size=(h, w), mode=mode, **({"align_corners": False} if mode in ("bilinear", "bicubic") else {})
    )


class VAEView:
    """RS helpers consume raw VAE latents; Forge denoising uses process_in."""

    def __init__(self, vae):
        self.vae = vae

    def encode(self, pixels):
        return self.vae.encode(pixels)

    def process(self, latent):
        return self.vae.first_stage_model.process_in(latent)


def check_interrupted():
    from modules import shared

    if shared.state.interrupted or shared.state.skipped:
        from modules import sd_samplers_common

        raise sd_samplers_common.InterruptedException


def optimized_attention_masked(q, k, v, heads, mask=None, **kwargs):
    from backend.attention import attention_function

    return attention_function(q, k, v, heads, mask=mask, **kwargs)


class LazyNamespace:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module(self.module), name)


class Management:
    def __getattr__(self, name):
        if name in ("throw_exception_if_processing_interrupted",):
            return check_interrupted
        from backend import memory_management as m

        aliases = {
            "get_torch_device": "get_torch_device",
            "load_models_gpu": "load_models_gpu",
            "soft_empty_cache": "soft_empty_cache",
            "unet_offload_device": "unet_offload_device",
            "free_memory": "free_memory",
        }
        return getattr(m, aliases.get(name, name))


class ProgressBar:
    def __init__(self, total):
        self.total = total

    def update(self, amount):
        check_interrupted()


utils = SimpleNamespace(
    ProgressBar=ProgressBar,
    load_torch_file=load_torch_file,
    pad_to_patch_size=pad_to_patch_size,
    repeat_to_batch_size=repeat_to_batch_size,
    common_upscale=common_upscale,
    weight_dtype=lambda s: next(v.dtype for v in s.values() if v.is_floating_point()),
)
# Pure math helpers share Forge's native implementations.
compat = SimpleNamespace(
    utils=utils,
    model_management=Management(),
    ldm=SimpleNamespace(common_dit=SimpleNamespace(pad_to_patch_size=pad_to_patch_size)),
    ops=SimpleNamespace(
        manual_cast=torch.nn,
        disable_weight_init=torch.nn,
        cast_to_input=lambda value, x: value.to(device=x.device, dtype=x.dtype),
    ),
)


def hf_hub_download(*args, tqdm_class=None, **kwargs):
    """Keep Forge's installed Hub version; progress is optional on older Hub."""
    import inspect
    from huggingface_hub import hf_hub_download as download

    if tqdm_class is not None and "tqdm_class" in inspect.signature(download).parameters:
        kwargs["tqdm_class"] = tqdm_class
    check_interrupted()
    result = download(*args, **kwargs)
    check_interrupted()
    return result


def verified_asset(name):
    """Original pinned catalog and verifier, with Forge's model directories."""
    from .shared.reference_assets import CATALOG, _check_adapter
    from .shared.tagger_progress import TaggerProgress

    spec = CATALOG[name]
    progress = TaggerProgress()
    candidates = []
    for root in model_roots():
        candidates.extend(
            [
                root / spec["folder"] / "rs_reference" / spec["subdir"] / spec["file"],
                root / spec["folder"] / spec["file"],
            ]
        )
        for folder in (
            root / spec["folder"],
            root / "ipadapter",
            root / "loras",
            root / "clip_vision",
            root / "siglip2",
        ):
            if folder.exists():
                candidates.extend(folder.rglob(Path(spec["file"]).name))
    found = next((p for p in candidates if p.is_file()), None)
    if found is None:
        target = models_dir() / spec["folder"] / "rs_reference" / spec["subdir"]
        found = Path(
            hf_hub_download(
                repo_id=spec["repo"],
                revision=spec["revision"],
                filename=spec["file"],
                local_dir=target,
                tqdm_class=progress.download_bar(spec["file"]),
            )
        )
    if spec.get("sha256"):
        _check_adapter(found, progress, name) if name in (
            "anima_frame",
            "anima29_frame",
            "anima_frame_v2",
            "anima_role_kv",
            "krea_pose",
            "moss_pose",
            "anima_pose",
        ) else check_digest(found, spec["sha256"])
    return found


def check_digest(path, expected):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        while b := f.read(8 * 1024 * 1024):
            check_interrupted()
            digest.update(b)
    if digest.hexdigest() != expected:
        raise ValueError(f"Asset checksum mismatch: {Path(path).name}")
    return path
