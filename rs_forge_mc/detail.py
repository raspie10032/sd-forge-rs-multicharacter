# SPDX-License-Identifier: GPL-3.0-only
"""Original conservative matching/mask repair with Forge's masked img2img."""

from contextlib import nullcontext
from types import SimpleNamespace
import copy

import numpy as np
from PIL import Image
import torch

from .config import number
from .host import folders, models_dir, check_interrupted


def validate_settings(d):
    fields = {
        "enabled",
        "segm",
        "bbox",
        "sam",
        "tagger",
        "denoise",
        "size",
        "steps",
        "cfg",
        "min_score",
        "min_margin",
        "max_regions",
        "threshold",
        "crop_factor",
        "dilation",
        "feather",
        "fill_holes",
        "closing",
    }
    if not isinstance(d, dict) or set(d) - fields:
        raise ValueError("Unknown detailer settings.")
    for k, default, lo, hi in [
        ("denoise", 0.25, 0.01, 1),
        ("size", 768, 128, 2048),
        ("steps", 20, 1, 100),
        ("cfg", 4, 0, 30),
        ("min_score", 0.25, 0, 1),
        ("min_margin", 0.08, 0, 1),
        ("max_regions", 10, 1, 64),
        ("threshold", 0.3, 0.01, 1),
        ("crop_factor", 3, 1, 8),
        ("dilation", 8, 0, 128),
        ("feather", 8, 0, 64),
    ]:
        number(d.get(k, default), lo, hi, "Detailer " + k)
    for k in ("enabled", "fill_holes", "closing"):
        if k in d and type(d[k]) is not bool:
            raise ValueError(k + " must be a boolean.")
    for k in ("segm", "bbox", "sam", "tagger"):
        if k in d and not isinstance(d[k], str):
            raise ValueError(k + " must be a model name.")
    return d


def detector_files():
    from .shared.detection_models import CATALOG

    result = {k: ["OFF"] for k in ("segm", "bbox", "sam")}
    for k in ("segm", "bbox"):
        installed = [
            n for n in folders.get_filename_list("ultralytics") if n.startswith(k + "/") and n.endswith(".pt")
        ]
        result[k] += sorted(set(installed) | {n for n in CATALOG if n.startswith(k + "/")})
    result["sam"] += folders.get_filename_list("sams")
    return result


class Detector:
    def __init__(self, name):
        from ultralytics import YOLO
        from .shared.detection_models import ensure_detection_model
        from .shared.tagger_progress import TaggerProgress

        path = folders.get_full_path("ultralytics", name)
        if not path:
            path = ensure_detection_model(name, TaggerProgress())
        self.model = YOLO(str(path))
        self.segm = name.startswith("segm/")

    def detect(self, image, threshold, dilation, crop_factor, **kwargs):
        im = Image.fromarray((image[0].cpu().numpy() * 255).astype(np.uint8))
        w, h = im.size
        result = self.model.predict(im, conf=threshold, device="cpu", verbose=False)[0]
        segments = []
        if result.boxes is None:
            return (h, w), segments
        for index, box in enumerate(result.boxes.xyxy.cpu().tolist()):
            x0, y0, x1, y1 = tuple(max(0, round(v)) for v in box)
            x1 = min(w, x1)
            y1 = min(h, y1)
            if x1 - x0 < 10 or y1 - y0 < 10:
                continue
            mask = np.ones((y1 - y0, x1 - x0), np.float32)
            if self.segm:
                if result.masks is None:
                    raise ValueError("SEGM model returned no masks.")
                full = np.asarray(
                    Image.fromarray(result.masks.data[index].cpu().numpy()).resize(
                        (w, h), Image.Resampling.BILINEAR
                    )
                )
                mask = full[y0:y1, x0:x1]
            segments.append(
                SimpleNamespace(bbox=(x0, y0, x1, y1), crop_region=(x0, y0, x1, y1), cropped_mask=mask)
            )
        return (h, w), segments


def run(image, p, config):
    from modules import processing, shared
    from .runtime import RUNTIME_LOCK
    from .shared.detector_bundle import DetectionBundle
    from .shared.detection import RepairedDetector, _detect, _context_crop
    from .shared.mask_repair import inside_alpha
    from .shared.detailer_matching import Match, match_characters, selected_prompts
    from .shared.wd_tagger import WDTagger
    from .lora import load_plans

    d = validate_settings(config.features["detailer"])
    pipe = config.to_pipe()
    chars = pipe.characters
    if not chars:
        raise ValueError("The detailer needs a character slot.")
    choices = detector_files()
    for k in ("segm", "bbox", "sam"):
        if d.get(k, "OFF") not in choices[k]:
            raise ValueError("Choose an available " + k + " model.")
    segm = Detector(d["segm"]) if d.get("segm", "OFF") != "OFF" else None
    bbox = Detector(d["bbox"]) if not segm and d.get("bbox", "OFF") != "OFF" else None
    if segm is None and bbox is None:
        raise ValueError("Select SEGM or BBOX for the detailer.")
    sam = None
    if not segm and d.get("sam", "OFF") != "OFF":
        from segment_anything import sam_model_registry

        name = d["sam"]
        kind = next((v for v in ("vit_h", "vit_l", "vit_b") if v in name), None)
        if not kind:
            raise ValueError("Use a SAM ViT-H/L/B checkpoint.")
        sam = sam_model_registry[kind](checkpoint=folders.get_full_path_or_raise("sams", name))
    repaired = RepairedDetector(
        DetectionBundle(segm, bbox, sam),
        closing=d.get("closing", True),
        fill_holes=d.get("fill_holes", True),
        dilation=int(d.get("dilation", 8)),
    )
    tensor = torch.from_numpy(np.asarray(image.convert("RGB")).copy()).float()[None] / 255.0
    regions = _detect(repaired, tensor, d.get("threshold", 0.3), 0, d.get("crop_factor", 3.0))
    regions.sort(key=lambda r: ((r.bbox[0] + r.bbox[2]) / 2, (r.bbox[1] + r.bbox[3]) / 2))
    regions = regions[: int(d.get("max_regions", 10))]
    tagger = None
    if len(chars) > 1:
        tagger = WDTagger(
            models_dir() / "rs_wd_tagger", device="cpu", model_name=d.get("tagger", "WD ViT v3")
        )
        scores = tagger.score([_context_crop(image, r.bbox, 2.0) for r in regions])
        matches = [
            match_characters(s, chars, d.get("min_score", 0.25), d.get("min_margin", 0.08)) for s in scores
        ]
    else:
        matches = [Match(0, 1.0, 1.0, "single_character") for _ in regions]
    result = image.copy()
    reports = []
    original_unet = p.sd_model.forge_objects.unet
    restore = getattr(p, "_rs_mc_restore", None)
    if restore and p.sd_model.forge_objects.unet is restore[1]:
        p.sd_model.forge_objects.unet = restore[0]
    original_unet = p.sd_model.forge_objects.unet
    saved_state = {
        k: copy.copy(v)
        for k, v in vars(shared.state).items()
        if k
        in (
            "job_count",
            "job_no",
            "sampling_step",
            "sampling_steps",
            "current_image",
            "current_latent",
            "textinfo",
        )
    }
    try:
        for i, (region, match) in enumerate(zip(regions, matches)):
            check_interrupted()
            report = dict(
                region=i,
                bbox=region.bbox,
                character=match.character_index,
                score=match.score,
                margin=match.margin,
                reason=match.reason,
                edited=False,
            )
            reports.append(report)
            if match.character_index is None:
                continue
            c = chars[match.character_index]
            box = region.crop_region
            crop = result.crop(box)
            mask = Image.fromarray((region.cropped_mask * 255).astype(np.uint8), "L")
            prompt, negative = selected_prompts(
                p.prompt if isinstance(p.prompt, str) else p.all_prompts[0],
                p.negative_prompt if isinstance(p.negative_prompt, str) else p.all_negative_prompts[0],
                chars,
                match,
            )
            size = int(d.get("size", 768))
            factor = min(size / min(crop.size), 1024 / max(crop.size))
            width, height = [max(64, round(v * factor / 16) * 16) for v in crop.size]
            mp, tp = load_plans(original_unet, p.sd_model.forge_objects.clip, [c])
            model_scope = (
                mp[c.lora_name].applied(original_unet.model, c.lora_strength)
                if c.lora_name in mp
                else nullcontext()
            )
            text_scope = (
                tp[c.lora_name].applied(p.sd_model.forge_objects.clip.cond_stage_model, c.lora_clip_strength)
                if c.lora_name in tp
                else nullcontext()
            )
            q = processing.StableDiffusionProcessingImg2Img(
                sd_model=p.sd_model,
                init_images=[crop],
                mask=mask,
                mask_blur=0,
                inpainting_fill=1,
                inpaint_full_res=False,
                denoising_strength=d.get("denoise", 0.25),
                width=width,
                height=height,
                prompt=prompt,
                negative_prompt=negative,
                sampler_name=p.sampler_name,
                scheduler=p.scheduler,
                steps=int(d.get("steps", 20)),
                cfg_scale=d.get("cfg", 4),
                seed=int(p.all_seeds[0]) + i,
                batch_size=1,
                n_iter=1,
                do_not_save_samples=True,
                do_not_save_grid=True,
            )
            q.scripts = None
            q._rs_mc_detail_pass = True
            try:
                with RUNTIME_LOCK, model_scope, text_scope:
                    edited = (
                        processing.process_images(q)
                        .images[-1]
                        .convert("RGB")
                        .resize(crop.size, Image.Resampling.LANCZOS)
                    )
            finally:
                q.close()
            alpha = Image.fromarray(
                np.round(inside_alpha(region.cropped_mask, int(d.get("feather", 8))) * 255).astype(np.uint8),
                "L",
            )
            result.paste(edited, box[:2], alpha)
            report["edited"] = True
    finally:
        p.sd_model.forge_objects.unet = original_unet
        for k, v in saved_state.items():
            setattr(shared.state, k, v)
    return result, reports
