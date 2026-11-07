# SPDX-License-Identifier: GPL-3.0-only
"""Per-generation reference preparation and original numbered guidance algebra."""

from types import SimpleNamespace

import numpy as np
from PIL import Image
import torch

from .assets import asset_path
from .host import verified_asset, VAEView


def sources(runtime):
    rows = runtime.config.features.get("slots", {})
    ids = [
        i
        for i, c in enumerate(runtime.config.characters, 1)
        if c.active and rows.get(str(i), {}).get("kind") != "text"
    ]
    result = []
    for slot, i in enumerate(ids):
        row = rows.get(str(i), {})
        if row.get("reference") and row.get("reference_strength", 1) > 0:
            with Image.open(asset_path(row["reference"])) as im:
                im = im.convert("RGB")
            from .shared.image_reference import ImageReference
            from .shared.reference_image import prepare_reference

            resolution = row.get("reference_resolution", 384)
            fitted, _ = prepare_reference(im, resolution, square_padding=False)
            result.append(
                (
                    slot,
                    ImageReference(
                        fitted.tobytes(), fitted.size, resolution, row.get("reference_strength", 1), i
                    ),
                )
            )
    return result


def prepare(runtime, unet, p, width, height):
    from .shared.native_reference import attach_native_references

    if runtime.family != "Anima":
        attach_native_references(
            runtime.routing,
            SimpleNamespace(model_options={}, model=SimpleNamespace(process_latent_in=lambda x: x)),
        )
    from .native_runtime import KreaView

    runtime.routing.reference_dm = (
        KreaView(unet.model.diffusion_model) if runtime.family == "Krea2" else unet.model.diffusion_model
    )
    refs = sources(runtime)
    if not refs:
        return
    if runtime.config.features.get("pose", {}).get("mode", "masks_only") != "masks_only":
        raise ValueError("Use references or learned pose, one at a time (same as the original).")
    vae = VAEView(p.sd_model.forge_objects.vae)
    if runtime.family == "Anima":
        settings = runtime.config.features.get("reference", {})
        method = settings.get("method", "reference_frame")
        if method in ("reference_frame", "asymmetric_v2") and (
            settings.get("adapter_strength", 1.0) == 0 or settings.get("guidance", 4.5) == 0
        ):
            return
        if method == "role_kv":
            from .shared.anima_role_kv import encode_role_references, RoleKVRuntime
            from .shared.image_reference import RoleKVImageReference

            refs = [(i, RoleKVImageReference(**r.__dict__)) for i, r in refs]
            if (
                runtime.pose
                or runtime.config.features.get("interaction", {}).get("preset", "baseline") != "baseline"
            ):
                raise ValueError("Role K/V requires baseline interaction and body-part strength 0.")
            if runtime.plans and runtime.config.settings.lora_mode != "normal":
                raise ValueError("Role K/V with character LoRAs requires Normal mode, as in ComfyUI.")
            latents = encode_role_references(refs, vae, vae.process)
            runtime.routing.role_kv_runtime = RoleKVRuntime(
                refs, latents, verified_asset("anima_role_kv"), runtime.routing, runtime.audit
            )
            runtime.routing.mode = "weighted_static"
            runtime.routing.initial_spatial_separation = runtime.routing.late_spatial_separation = 0.0
            return
        if method == "legacy":
            prepare_legacy(runtime, refs)
            return
        from .shared.anima_ref_frame import ReferencePlan, FrameRuntime, encode_reference
        from .shared.anima_ref_v2 import AsymmetricRuntime

        blocks = len(unet.model.diffusion_model.blocks)
        key = (
            "anima_frame_v2"
            if method == "asymmetric_v2"
            else "anima29_frame"
            if blocks == 40
            else "anima_frame"
        )
        if blocks not in (28, 40) or method == "asymmetric_v2" and blocks != 28:
            raise ValueError("Choose a supported Anima reference adapter (2B/2.9B; v2 is 2B only).")
        if method == "asymmetric_v2" and runtime.plans:
            raise ValueError("Asymmetric v2 with character LoRAs is not validated in the original.")
        plan = ReferencePlan(
            None,
            str(verified_asset(key)),
            settings.get("adapter_strength", 1.0),
            settings.get("guidance", 4.5),
            settings.get("correction", "apg"),
            settings.get("cache", False),
            reference_scale=settings.get("reference_scale", 1.0),
            backend="v2" if method == "asymmetric_v2" else "pilot",
        )
        rw, rh = [max(16, round(v * plan.reference_scale / 16) * 16) for v in (width, height)]
        encoded = [
            vae.process(
                encode_reference(
                    torch.from_numpy(np.asarray(r.image()).copy()).float()[None] / 255.0, vae, rw, rh
                )
            )
            for _, r in refs
        ]
        reference = torch.cat([v.unsqueeze(2) if v.ndim == 4 else v for v in encoded], 2)
        runtime.reference = (AsymmetricRuntime if method == "asymmetric_v2" else FrameRuntime)(
            plan,
            reference,
            runtime.audit,
            cache_allowed=not runtime.plans,
            slots=[i for i, _ in refs],
            strengths=[r.strength for _, r in refs],
            masks=runtime.masks,
        )
        runtime.reference_values = {}
        if runtime.config.features.get("progressive", {}).get("start_scale", 1) < 1:
            from .shared.anima_ref_frame import prepare_reference_latents

            first, stages, audit = prepare_reference_latents(
                plan,
                refs,
                vae,
                width,
                height,
                p.steps,
                runtime.config.features["progressive"]["start_scale"],
                follow=True,
            )
            runtime.reference.reference = vae.process(first)
            runtime.reference.stage_references = {grid: vae.process(value) for grid, value in stages.items()}
            runtime.reference.audit.update(audit)
        # CFG=1 must retain its negative branch for reference guidance.
        unet.model_options["disable_cfg1_optimization"] = True
        unet.set_model_sampler_cfg_function(runtime.reference_cfg, disable_cfg1_optimization=True)
    elif runtime.family in ("SDXL", "SD1.5"):
        from backend.patcher.clipvision import load
        from .shared.sd_reference import SDReferenceRuntime

        encoder = load(str(verified_asset("sd_encoder")))
        rows = []
        for i, r in refs:
            from .shared.reference_image import prepare_reference

            square, geometry = prepare_reference(r.image(), r.resolution, square_padding=True)
            px = torch.from_numpy(np.asarray(square).copy()).float()[None] / 255.0
            features = encoder.encode_image(px).penultimate_hidden_states.cpu()
            null = encoder.encode_image(torch.zeros_like(px)).penultimate_hidden_states.cpu()
            rows.append(
                dict(
                    slot=i, source=r.source, strength=r.strength, geometry=geometry, features=(features, null)
                )
            )
        runtime.routing.reference = SDReferenceRuntime((runtime.family, rows, "PLUS"), runtime.audit)
    else:
        rows = []
        runtime.krea_reference_pixels = {}
        for i, r in refs:
            from .shared.reference_image import prepare_reference

            im, geometry = prepare_reference(r.image(), r.resolution, square_padding=runtime.family == "MOSS")
            if runtime.family != "MOSS":
                im = im.resize(tuple(max(16, v // 16 * 16) for v in im.size), Image.Resampling.LANCZOS)
            px = torch.from_numpy(np.asarray(im).copy()).float()[None] / 255.0
            latent = vae.process(vae.encode(px)).cpu()
            if runtime.family == "Krea2":
                runtime.krea_reference_pixels[i] = px
            rows.append(
                dict(
                    slot=i, source=r.source, strength=r.strength, geometry=geometry, latent=latent, pixels=px
                )
            )
        if runtime.family in ("Krea2", "MOSS"):
            from backend.patcher.lora import load_lora, model_lora_keys_unet
            from .host import load_torch_file

            weights = load_torch_file(
                verified_asset("krea_edit" if runtime.family == "Krea2" else "moss_edit")
            )
            patches, remaining = load_lora(weights, model_lora_keys_unet(unet.model, {}))
            if remaining:
                raise ValueError("Reference adapter contains unmatched weights: " + str(list(remaining)[:3]))
            unet.add_patches(patches)
        from .shared.native_reference import attach_native_references

        attach_native_references(
            runtime.routing,
            SimpleNamespace(
                model_options={"rs_native_reference": rows},
                model=SimpleNamespace(process_latent_in=lambda x: x),
            ),
        )


def prepare_legacy(runtime, refs):
    from transformers import AutoModel, AutoImageProcessor
    from .shared.anima_reference import AnimaReferenceRuntime, ReferenceCondition
    from .host import load_torch_file

    config = verified_asset("anima_config")
    verified_asset("anima_preprocessor_config")
    weights = verified_asset("anima_model")
    encoder = AutoModel.from_config(
        __import__("transformers").AutoConfig.from_pretrained(config.parent, local_files_only=True)
    )
    encoder.load_state_dict(load_torch_file(weights), strict=True)
    encoder.eval()
    processor = AutoImageProcessor.from_pretrained(config.parent, local_files_only=True)
    conditions = []
    for i, r in refs:
        with torch.inference_mode():
            features = encoder.get_image_features(**processor(images=r.image(), return_tensors="pt"))
        conditions.append(ReferenceCondition(i, features, r.strength, r.source, list(r.size)))
    runtime.legacy_reference = AnimaReferenceRuntime(
        (conditions, "native"), runtime.masks, runtime.boxes, runtime.audit
    )
