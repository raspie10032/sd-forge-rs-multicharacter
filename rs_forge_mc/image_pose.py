# SPDX-License-Identifier: GPL-3.0-only
"""Single-person SAM 3D Body inference using Forge device management."""

import gc
import numpy as np
import torch
from .runtime import RUNTIME_LOCK
from .host import load_torch_file, check_interrupted


def estimate(image, character_number=1, base_scene=""):
    from backend import memory_management
    from .shared.pose_estimator import prepare_model, import_pose
    from .shared.pose3d import read_scene

    if base_scene:
        scene = read_scene(base_scene)
        if scene["version"] != 2 or not any(p["id"] == character_number for p in scene["people"]):
            raise ValueError("Select an existing MHR character first.")
    from .vendor_sam3d.model.model import SAM3DBody
    from .vendor_sam3d.inference import run_batched_frames, image_to_uint8

    with RUNTIME_LOCK, torch.inference_mode():
        path = prepare_model()
        check_interrupted()
        memory_management.unload_all_models()
        weights = load_torch_file(path)
        weights = {
            k.replace(".layers.0.0.", ".layers.0."): v
            for k, v in weights.items()
            if k not in ("hand_cls_embed.weight", "hand_cls_embed.bias")
            and not k.startswith("face_landmarker.")
        }
        device = memory_management.get_torch_device()
        dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
        try:
            model = SAM3DBody(dtype=dtype, operations=torch.nn)
            model.load_state_dict(weights, strict=True, assign=True)
            del weights
            model = model.to(device=device).eval()
            model.backbone_dtype = dtype
            pixels = torch.from_numpy(np.asarray(image.convert("RGB")).copy()).float() / 255.0
            h, w = pixels.shape[:2]
            box = torch.tensor([[0.0, 0.0, float(w), float(h)]])
            with torch.autocast(device.type, dtype=dtype, enabled=device.type == "cuda"):
                rows = run_batched_frames(
                    model, [image_to_uint8(pixels)], [box], None, model.image_size, "body", crops_per_chunk=1
                )
            people = rows[0]
            if len(people) != 1 or "pred_global_rots" not in people[0]:
                raise ValueError("Use a clear single-person crop.")
            scene, pose = import_pose(
                people[0]["pred_global_rots"],
                base_scene,
                character_number,
                prediction=people[0],
                image_size=(h, w),
            )
            return {"scene": scene, "pose": pose}
        finally:
            if "model" in locals():
                del model
            gc.collect()
            memory_management.soft_empty_cache()
