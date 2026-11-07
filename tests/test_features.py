import base64
from dataclasses import replace
import json

import numpy as np
import pytest

from rs_forge_mc.config import Character, Config, Settings
from rs_forge_mc.features import mask_from_record, mask_record
from rs_forge_mc.preview import preview
from rs_forge_mc.ui import from_ui, to_ui


def test_mixed_mask_and_text_slots_survive_ui_and_json_restoration():
    mask = np.zeros((32, 48), dtype=bool)
    mask[3:29, 2:21] = True
    config = Config(
        (
            Character(prompt="red hair", x=0.2),
            Character(prompt="a chalk sign", x=0.775, y=0.4, box=(0.6, 0.2, 0.95, 0.6)),
        ),
        Settings(common_prior=0.5),
        features={
            "slots": {"1": {"mask": mask_record(mask)}, "2": {"kind": "text", "text": "CAFE"}},
            "interaction": {"preset": "delay6"},
            "progressive": {"start_scale": 0.5},
        },
    )
    restored = Config.from_json(config.to_json())
    form = from_ui(to_ui(restored))
    assert form.features == config.features
    assert form.characters[:2] == config.characters
    pipe = restored.to_pipe()
    assert len(pipe.characters) == len(pipe.text_regions) == 1
    assert pipe.characters[0].region_mask.packed == base64.b64decode(mask_record(mask)["bits"])
    assert pipe.text_regions[0].text == "CAFE"
    assert json.loads(pipe.interaction_json)["preset"] == "delay6"
    assert "<svg" in preview(restored, width=768, height=512)


@pytest.mark.parametrize(
    "change", [{"bits": "x"}, {"width": 4}, {"height": True}, {"bits": base64.b64encode(bytes(8)).decode()}]
)
def test_malformed_or_empty_masks_are_rejected(change):
    record = mask_record(np.ones((8, 8), dtype=bool))
    with pytest.raises(ValueError):
        mask_from_record({**record, **change})


def test_default_advanced_settings_preserve_pipe_and_old_presets():
    base = Config((Character(prompt="left", x=0.25), Character(prompt="right", x=0.75)))
    legacy = json.loads(base.to_json())
    legacy.pop("features")
    assert Config.from_json(json.dumps(legacy)).to_pipe() == base.to_pipe()
    assert replace(base, features={"progressive": {"start_scale": 1}}).to_pipe() == base.to_pipe()
    text = replace(base, features={"slots": {"1": {"kind": "text", "text": "NO BOX"}}})
    with pytest.raises(ValueError, match="Box"):
        text.to_pipe()


def test_mask_position_and_margin_use_original_transform_before_camera():
    from rs_forge_mc.shared.region_mask import prepare_mask

    mask = np.zeros((48, 64), dtype=bool)
    mask[12:30, 12:28] = True
    config = Config(
        (Character(prompt="red hair"),),
        features={
            "slots": {
                "1": {
                    "mask": mask_record(mask),
                    "mask_margin": 3,
                    "mask_offset_x": 0.2,
                    "mask_offset_y": -0.1,
                    "mask_scale": 1.3,
                }
            }
        },
    )
    expected = prepare_mask(
        mask_from_record(mask_record(mask)).tensor(),
        threshold=0.5,
        margin=3,
        offset_x=0.2,
        offset_y=-0.1,
        scale=1.3,
    )
    actual = Config.from_json(config.to_json()).to_pipe().characters[0].region_mask
    assert actual == expected
    assert actual.center[0] > mask_from_record(mask_record(mask)).center[0]


def test_moss_native_layout_is_selected_and_uses_literal_text_boxes():
    from rs_forge_mc.layout import resolve, native_prompt

    config = Config(
        (Character(prompt="a red sign", box=(0.1, 0.2, 0.9, 0.8)),),
        features={"layout_method": "moss_native", "slots": {"1": {"kind": "text", "text": "CAFE"}}},
    )
    assert resolve(config, "MOSS") == "moss_native"
    layout = json.loads(native_prompt(config, "an outdoor cafe", 768, 512))
    assert layout["summary"]["caption"] == "an outdoor cafe"
    assert layout["items"][0]["text"] == "CAFE"
    with pytest.raises(ValueError, match="requires MOSS"):
        resolve(config, "Anima")
    with pytest.raises(ValueError, match="boxes or masks"):
        native_prompt(
            replace(config, characters=(Character(prompt="a red sign"),), features={}), "cafe", 768, 512
        )
