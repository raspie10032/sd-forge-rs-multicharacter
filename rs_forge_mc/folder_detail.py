# SPDX-License-Identifier: GPL-3.0-only
"""Explicit local-folder correction through the same detected-region detailer."""

import json
from pathlib import Path
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from .config import Config, INFOTEXT_KEY, number


def run(raw):
    from modules import processing, shared, sd_models
    from modules.call_queue import queue_lock
    from .detail import run as correct
    from .host import check_interrupted
    from . import __version__

    data = json.loads(raw)
    config = Config.from_json(json.dumps(data["config"]))
    config.validate_generation()
    source = Path(data["source"]).expanduser().resolve(strict=True)
    output = Path(data["output"]).expanduser().resolve()
    if not source.is_dir() or source == output:
        raise ValueError("Choose an input folder and a different output folder.")
    files = sorted(
        p
        for p in source.iterdir()
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg")
    )
    if not 1 <= len(files) <= 512:
        raise ValueError("Choose a folder containing 1–512 images.")
    if not config.features.get("detailer", {}).get("enabled"):
        raise ValueError("Enable and configure the local detailer first.")
    seed = int(number(data.get("seed", 0), -1, 2**53 - 1, "Seed"))
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    with queue_lock:
        # Folder correction can be the first action after startup or unload.
        # Standard process_images() loads this before touching forge_objects.
        model, _ = sd_models.forge_model_reload()
        if not hasattr(model, "forge_objects"):
            raise ValueError("Select a checkpoint, encoder and VAE before folder correction.")
        shared.state.begin("RS folder detailer")
        p = processing.StableDiffusionProcessingTxt2Img(
            sd_model=model,
            prompt=str(data.get("prompt", "")),
            negative_prompt=str(data.get("negative", "")),
            seed=seed,
            sampler_name=str(data.get("sampler", "Euler a")),
            scheduler=str(data.get("scheduler", "SGM Uniform")),
        )
        try:
            processing.fix_seed(p)
            for index, path in enumerate(files):
                check_interrupted()
                target = output / (path.name + ".rs-detail.png")
                if target.exists():
                    raise ValueError(f"Output already exists: {target.name}")
                with Image.open(path) as im:
                    image = im.convert("RGB")
                p.all_seeds = [int(p.seed) + index]
                edited, rows = correct(image, p, config)
                meta = PngInfo()
                # Record the correction's settings, without assigning the
                # source image's generation settings to the corrected result.
                meta.add_text(
                    "parameters",
                    f"{p.prompt}\nNegative prompt: {p.negative_prompt}\n"
                    f"Seed: {p.all_seeds[0]}, Size: {edited.width}x{edited.height}, "
                    f"{INFOTEXT_KEY}: {json.dumps(config.to_json(), ensure_ascii=True)}",
                )
                meta.add_text(
                    "RS detailer",
                    json.dumps(
                        dict(
                            version=__version__,
                            config=json.loads(config.to_json()),
                            source=path.name,
                            seed=p.all_seeds[0],
                            report=rows,
                        ),
                        ensure_ascii=True,
                    ),
                )
                with target.open("xb") as stream:
                    edited.save(stream, format="PNG", pnginfo=meta)
                reports.append(dict(file=target.name, regions=rows))
        finally:
            p.close()
            shared.state.end()
    return dict(output=str(output), images=reports)
