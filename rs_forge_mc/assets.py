# SPDX-License-Identifier: GPL-3.0-only
"""Content-addressed local reference images and original metadata interchange."""

import hashlib
import io
import json
import re

from PIL import Image, ImageOps
from .host import models_dir
from .config import Config, Character, Settings


def read_image(raw):
    with Image.open(io.BytesIO(raw)) as im:
        if im.width * im.height > 24_000_000 or getattr(im, "n_frames", 1) != 1:
            raise ValueError("Use a single image up to 24 megapixels.")
        return ImageOps.exif_transpose(im).convert("RGB")


def save_image(raw):
    im = read_image(raw)
    im.thumbnail((2048, 2048))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    data = buf.getvalue()
    key = hashlib.sha256(data).hexdigest()
    path = models_dir() / "rs_mc/assets" / f"{key}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return {"asset": key, "width": im.width, "height": im.height}


def asset_path(key):
    if not isinstance(key, str) or not re.fullmatch("[0-9a-f]{64}", key):
        raise ValueError("Invalid reference asset ID.")
    path = models_dir() / "rs_mc/assets" / f"{key}.png"
    if not path.is_file():
        raise ValueError("This reference image is missing locally. Upload the original again: " + key[:12])
    return path


def import_record(raw, filename):
    from .shared.metadata import read_record, pipe_from_record

    if filename.lower().endswith(".json"):
        data = json.loads(raw)
        if "rs_forge_preset" in data:
            return json.loads(Config.from_json(json.dumps(data["rs_forge_preset"])).to_json())
        if data.get("version") == 1 and "characters" in data:
            return json.loads(Config.from_json(raw.decode()).to_json())
        record = data
    else:
        with Image.open(io.BytesIO(raw)) as image:
            params = image.info.get("parameters", "")
            if "RS MultiCharacter:" in params:
                from modules.infotext_utils import parse_generation_parameters

                return json.loads(
                    Config.from_json(parse_generation_parameters(params)["RS MultiCharacter"]).to_json()
                )
            record = read_record(image)
    pipe = pipe_from_record(record)
    chars = []
    features = {"syntax": pipe.syntax, "slots": {}}
    for i, c in enumerate(pipe.regions, 1):
        chars.append(
            Character(True, c.prompt, c.x, c.y, c.bbox, c.lora_name, c.lora_strength, c.lora_clip_strength)
        )
        row = {}
        if c.region_mask:
            import base64

            row["mask"] = dict(
                width=c.region_mask.width,
                height=c.region_mask.height,
                bits=base64.b64encode(c.region_mask.packed).decode(),
            )
        if hasattr(c, "text"):
            row.update(kind="text", text=c.text)
        if c.body_parts:
            row.update(
                body_parts=[dict(name=name, mask=mask.record()) for name, mask in c.body_parts],
                body_part_strength=c.body_part_strength,
            )
        features["slots"][str(i)] = row
    if pipe.interaction_json:
        features["interaction"] = json.loads(pipe.interaction_json)
    local = record.get("rs_multicharacter", {})
    old = local.get("settings", {})
    settings = Settings(
        common_prior=old.get("initial_common_prior", 0.05),
        character_gain=old.get("initial_character_gain", 1.7),
        separation=old.get("initial_spatial_separation", 0.9),
        hold_steps=old.get("boundary_hold_steps", 3),
        decay=old.get("boundary_decrement", 0.2),
        lora_mode=pipe.lora_application_mode,
    )
    features["schedule"] = dict(
        common_boost=old.get("common_after_step3_boost", 0.1), region_feather=old.get("region_feather", 0.04)
    )
    return json.loads(
        Config(tuple(chars), settings, pose3d_json=pipe.pose3d_json, features=features).to_json()
    )


def nai_record(config, prompt="", negative=""):
    from dataclasses import replace
    from .shared.metadata import pipe_record
    from .shared.prompt_syntax import parse_comfyui

    def to_naiv4(tags):
        return ", ".join(text if weight == 1 else f"{weight:g}::{text} ::" for text, weight in tags)

    pipe = config.to_pipe()
    def convert(text):
        return to_naiv4(parse_comfyui(text)) if pipe.syntax == "ComfyUI" else text

    exported = replace(
        pipe,
        prompt=convert(prompt),
        negative_prompt=convert(negative),
        characters=tuple(replace(c, prompt=convert(c.prompt)) for c in pipe.characters),
        syntax="NovelAI",
        character_syntax="NovelAI",
        lora_application_mode=config.settings.lora_mode,
    )
    return {**pipe_record(exported), "rs_forge_preset": json.loads(config.to_json())}
