# SPDX-License-Identifier: GPL-3.0-only
"""Versioned feature state and original RS pipe transformations."""

import base64
from dataclasses import replace
import json
import re

import numpy as np

from .config import number
from .shared.region_mask import RegionMask


def mask_from_record(data):
    if not isinstance(data, dict) or set(data) != {"width", "height", "bits"}:
        raise ValueError("Mask needs width, height and packed base64 bits.")
    w, h = data["width"], data["height"]
    if any(type(v) is not int or not 8 <= v <= 4096 for v in (w, h)):
        raise ValueError("Mask dimensions must be 8–4096.")
    try:
        bits = base64.b64decode(data["bits"], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid mask encoding.") from error
    if len(bits) != (w * h + 7) // 8:
        raise ValueError("Mask byte count does not match its dimensions.")
    if not np.unpackbits(np.frombuffer(bits, np.uint8))[: w * h].any():
        raise ValueError("Mask is empty. Paint or upload a nonempty region.")
    return RegionMask(w, h, bits)


def mask_record(mask):
    a = np.asarray(mask, dtype=bool)
    return dict(width=a.shape[1], height=a.shape[0], bits=base64.b64encode(np.packbits(a).tobytes()).decode())


def validate_features(data):
    if not isinstance(data, dict) or set(data) - {
        "slots",
        "interaction",
        "camera",
        "pose",
        "openpose",
        "progressive",
        "detailer",
        "reference",
        "syntax",
        "layout_method",
        "schedule",
    }:
        raise ValueError("Unrecognized advanced feature settings.")
    # Force a detached, JSON-only snapshot. This also rejects nonfinite numbers.
    data = json.loads(json.dumps(data, allow_nan=False))
    slots = data.get("slots", {})
    if not isinstance(slots, dict) or any(k not in {str(i) for i in range(1, 11)} for k in slots):
        raise ValueError("Feature slots must be numbered 1–10.")
    for slot, row in slots.items():
        if not isinstance(row, dict) or set(row) - {
            "mask",
            "kind",
            "text",
            "reference",
            "reference_strength",
            "body_part_strength",
            "body_parts",
            "reference_resolution",
            "mask_margin",
            "mask_offset_x",
            "mask_offset_y",
            "mask_scale",
        }:
            raise ValueError(f"Invalid advanced fields for slot {slot}.")
        if row.get("kind", "character") not in ("character", "text"):
            raise ValueError("Slot kind must be character or text.")
        if not isinstance(row.get("text", ""), str) or len(row.get("text", "")) > 16000:
            raise ValueError("Literal text is too large.")
        if row.get("mask") is not None:
            mask_from_record(row["mask"])
        for key, default, low, high in (
            ("mask_margin", 0, 0, 128),
            ("mask_offset_x", 0, -1, 1),
            ("mask_offset_y", 0, -1, 1),
            ("mask_scale", 1, 0.05, 4),
        ):
            number(row.get(key, default), low, high, key)
        if int(row.get("mask_margin", 0)) != row.get("mask_margin", 0):
            raise ValueError("Mask margin must be whole pixels.")
        from .shared.reference_image import validate_reference_size

        validate_reference_size(row.get("reference_resolution", 384))
        if row.get("reference") is not None and not re.fullmatch(r"[a-f0-9]{64}", row["reference"]):
            raise ValueError("Reference must be an uploaded image asset ID.")
        number(row.get("reference_strength", 1.0), 0, 2, "Reference strength")
        number(row.get("body_part_strength", 0.0), 0, 0.8, "Body part strength")
        if "body_parts" in row:
            parts = row["body_parts"]
            if not isinstance(parts, list) or len(parts) > 6:
                raise ValueError("Use at most six body-part masks per character.")
            for part in parts:
                if set(part) != {"name", "mask"} or not isinstance(part["name"], str):
                    raise ValueError("Each body part needs a name and mask.")
                RegionMask.from_record(part["mask"])
    schedule = data.get("schedule", {})
    if not isinstance(schedule, dict) or set(schedule) - {"common_boost", "region_feather"}:
        raise ValueError("Invalid advanced schedule fields.")
    number(schedule.get("common_boost", 0.1), 0, 1, "Common boost")
    number(schedule.get("region_feather", 0.04), 0, 0.25, "Region feather")
    from .shared.interaction import interaction_settings

    if data.get("interaction") is not None:
        data["interaction"] = interaction_settings(data["interaction"])
    camera = data.get("camera", {})
    if camera:
        from .shared.camera_control import RSCameraControl

        allowed = {
            "enabled",
            "azimuth",
            "elevation",
            "distance",
            "roll",
            "strength",
            "weighting",
            "scope",
            "random_mode",
            "random_seed",
            "layout_sync",
            "canvas_aspect",
        }
        if not isinstance(camera, dict) or set(camera) - allowed:
            raise ValueError("Invalid camera fields.")
        RSCameraControl().apply(**camera, base_prompt="validation")
    progressive = data.get("progressive", {})
    if progressive:
        number(progressive.get("start_scale", 1.0), 0.5, 1.0, "Progressive start scale")
        if set(progressive) - {"start_scale"}:
            raise ValueError("Invalid progressive settings.")
    pose = data.get("pose", {})
    if pose:
        if (
            not isinstance(pose, dict)
            or set(pose) - {"mode", "strength", "start", "end"}
            or pose.get("mode", "masks_only") not in ("auto", "masks_only")
        ):
            raise ValueError("Invalid 3D pose controls.")
        number(pose.get("strength", 1.0), 0, 2, "Pose strength")
        start = number(pose.get("start", 0.0), 0, 1, "Pose start")
        end = number(pose.get("end", 1.0), 0, 1, "Pose end")
        if end <= start:
            raise ValueError("Pose end must follow start.")
    if data.get("syntax", "ComfyUI") not in ("ComfyUI", "NovelAI"):
        raise ValueError("Unknown prompt syntax.")
    if data.get("layout_method", "regional") not in ("regional", "moss_native", "auto"):
        raise ValueError("Unknown layout method.")
    ref = data.get("reference", {})
    if ref:
        if not isinstance(ref, dict) or set(ref) - {
            "method",
            "guidance",
            "correction",
            "reference_scale",
            "cache",
            "adapter_strength",
        }:
            raise ValueError("Invalid reference settings.")
        if ref.get("method", "reference_frame") not in (
            "reference_frame",
            "asymmetric_v2",
            "role_kv",
            "legacy",
        ):
            raise ValueError("Invalid reference method.")
        number(ref.get("guidance", 4.5), 0, 20, "Reference guidance")
        number(ref.get("adapter_strength", 1.0), 0, 2, "Reference adapter strength")
        number(ref.get("reference_scale", 1.0), 0.25, 1.0, "Reference scale")
        if ref.get("correction", "apg") not in ("apg", "rescale", "none"):
            raise ValueError("Unknown reference correction.")
    if data.get("detailer"):
        from .detail import validate_settings

        validate_settings(data["detailer"])
    return data


def apply_features(pipe, config):
    """Apply masks/parts/text before the original shared camera transformation."""
    from .shared.characters import TextRegion

    features = dict(config.features)
    if (
        config.pose3d_json
        and not features.get("openpose")
        and any(row.get("body_part_strength", 0) > 0 for row in features.get("slots", {}).values())
    ):
        from .shared.pose3d import read_scene
        from .scene_parts import scene_pose

        scene = read_scene(config.pose3d_json)
        features["openpose"] = scene_pose(scene)
        entries = {
            p["id"]: row
            for p, row in zip(sorted(scene["people"], key=lambda p: p["id"]), features["openpose"]["people"])
        }
        features["openpose"]["people"] = [
            entries.get(i, {"pose_keypoints_2d": [0] * 54})
            for i, c in enumerate(config.characters, 1)
            if c.active and features.get("slots", {}).get(str(i), {}).get("kind") != "text"
        ]
    characters, texts = [], []
    active = [(i, c) for i, c in enumerate(config.characters, 1) if c.active]
    for (number_, c), region in zip(active, pipe.characters):
        row = features.get("slots", {}).get(str(number_), {})
        if row.get("mask"):
            from .shared.region_mask import prepare_mask

            region = replace(
                region,
                region_mask=prepare_mask(
                    mask_from_record(row["mask"]).tensor(),
                    threshold=0.5,
                    margin=int(row.get("mask_margin", 0)),
                    offset_x=row.get("mask_offset_x", 0),
                    offset_y=row.get("mask_offset_y", 0),
                    scale=row.get("mask_scale", 1),
                ),
            )
        if row.get("body_parts"):
            region = replace(
                region,
                body_parts=tuple((p["name"], RegionMask.from_record(p["mask"])) for p in row["body_parts"]),
                body_part_strength=row.get("body_part_strength", 0),
            )
        if row.get("kind") == "text":
            if c.box is None or not row.get("text", "").strip():
                raise ValueError(f"Text slot {number_} needs Box placement and literal text.")
            texts.append(TextRegion(region.prompt, x=c.x, y=c.y, bbox=c.box, text=row["text"]))
        else:
            characters.append(region)
    pipe = replace(
        pipe,
        characters=tuple(characters),
        text_regions=tuple(texts),
        interaction_json=json.dumps(features["interaction"]) if features.get("interaction") else None,
        syntax=features.get("syntax", "ComfyUI"),
    )
    if features.get("openpose"):
        from .shared.pose_parts import compile_semantic_parts
        from .shared.region_mask import prepare_mask

        parts, whole, _ = compile_semantic_parts(features["openpose"], len(characters))
        chars = []
        for i, c in enumerate(pipe.characters):
            source_number = [
                n for n, old in active if features.get("slots", {}).get(str(n), {}).get("kind") != "text"
            ][i]
            strength = features.get("slots", {}).get(str(source_number), {}).get("body_part_strength", 0.0)
            chars.append(
                replace(
                    c,
                    region_mask=c.region_mask or whole[i],
                    body_parts=tuple(
                        (p["name"], prepare_mask(p["mask"], margin=0)) for p in parts if p["owner"] == i
                    ),
                    body_part_strength=strength,
                )
            )
        pipe = replace(pipe, characters=tuple(chars))
    camera = features.get("camera", {})
    if camera.get("enabled"):
        from .shared.camera_control import RSCameraControl

        # The common prompt is appended in the Forge process hook. Here the
        # same original function transforms character captions and geometry.
        pipe = RSCameraControl().apply(**camera, base_prompt=pipe.prompt or "", building_pipe=pipe)["result"][
            0
        ]
    return pipe


def part_plan(pipe):
    active = [(i, c) for i, c in enumerate(pipe.characters) if c.body_parts and c.body_part_strength > 0]
    if not active:
        return None, []
    if pipe.text_regions or len({c.body_part_strength for _, c in active}) != 1:
        raise ValueError("Body parts require character-only slots and one shared strength.")
    parts = [dict(owner=i, name=name, mask=mask.tensor()) for i, c in active for name, mask in c.body_parts]
    captions = list(dict.fromkeys(p["name"] for p in parts))
    return dict(
        strength=active[0][1].body_part_strength,
        parts=parts,
        bank_ids=[captions.index(p["name"]) for p in parts],
    ), captions
