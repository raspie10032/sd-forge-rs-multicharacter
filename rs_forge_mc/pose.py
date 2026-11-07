# SPDX-License-Identifier: GPL-3.0-only
"""Same scene -> numbered mask -> BuildPipe path as the ComfyUI extension."""
import json

import numpy as np

from .shared.character_builder import update_slot
from .shared.pose3d import read_scene, rasterize
from .shared.region_mask import RegionMask


def scene_masks(raw, max_side=512):
    scene = read_scene(raw)
    full, visible = rasterize(scene, max_side=max_side)
    return scene, full if scene['mask_mode'] == 'full' else visible


def preview_payload(raw):
    scene, masks = scene_masks(raw, 192)
    records = []
    for person, mask in zip(scene['people'], masks):
        yy, xx = np.nonzero(mask)
        if not len(xx):
            raise ValueError(f"Character {person['id']}: no silhouette on the canvas.")
        records.append(dict(number=person['id'], width=mask.shape[1], height=mask.shape[0],
                            data=mask.astype(np.uint8).reshape(-1).tolist(),
                            center=[float((xx+.5).mean()/mask.shape[1]), float((yy+.5).mean()/mask.shape[0])]))
    return dict(canvas_width=scene['width'], canvas_height=scene['height'], masks=records, scene=scene)


def apply_pose_masks(pipe, raw):
    scene, masks = scene_masks(raw)
    slots = {slot.number: slot for slot in pipe.slots}
    for person, mask in zip(scene['people'], masks):
        number = person['id']
        if number not in slots or not slots[number].enabled:
            continue
        region = RegionMask(mask.shape[1], mask.shape[0], np.packbits(mask.reshape(-1)).tobytes())
        pipe = update_slot(pipe, number, region_mask=region)
    return pipe


def default_json():
    from .shared.mhr import default_scene
    return json.dumps(default_scene())
