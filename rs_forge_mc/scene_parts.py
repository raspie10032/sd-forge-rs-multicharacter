# SPDX-License-Identifier: GPL-3.0-only
"""Project actual MHR joints through the existing 3D camera for semantic masks."""

import numpy as np
from .shared import pose3d


def scene_pose(scene):
    names = [
        "head",
        "neck",
        "right_shoulder",
        "right_elbow",
        "right_wrist",
        "left_shoulder",
        "left_elbow",
        "left_wrist",
        "right_hip",
        "right_knee",
        "right_ankle",
        "left_hip",
        "left_knee",
        "left_ankle",
        None,
        None,
        None,
        None,
    ]
    from .shared.mhr import mannequin as mhr

    people = []
    factor = min(1.0, 2048 / max(scene["width"], scene["height"]))
    width, height = round(scene["width"] * factor), round(scene["height"] * factor)
    for person in sorted(scene["people"], key=lambda p: p["id"]):
        _, _, joints = (mhr if scene["version"] == 2 else pose3d.mannequin)(person)
        points = []
        for name in names:
            if name not in joints:
                points.extend((0, 0, 0))
                continue
            x, y, z = pose3d.project(np.array([joints[name]]), scene["camera"], width, height)[0]
            points.extend((float(x), float(y), 1.0 if z >= 0.05 else 0.0))
        people.append(dict(pose_keypoints_2d=points))
    return dict(
        coordinate_space="pixels",
        canvas_width=width,
        canvas_height=height,
        pose_model="COCO_18",
        people=people,
    )
