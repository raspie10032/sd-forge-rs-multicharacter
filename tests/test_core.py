import dataclasses
import json

import pytest
import torch

from rs_forge_mc.config import Character, Config, Settings, defaults, from_ui, to_ui
from rs_forge_mc.geometry import groups_for, membership, prediction_masks
from rs_forge_mc.routing import route_cross, sdpa
from rs_forge_mc.runtime import attention_ops, schedule_values
from rs_forge_mc.shared.characters import CharacterPipe
from rs_forge_mc.shared.layout import effective_centers


def test_ui_and_preset_roundtrip():
    config = Config(
        (
            Character(prompt="girl", x=0.25, lora="local", strength=0.8, clip_strength=0.2),
            Character(prompt="boy", x=0.75),
        )
    )
    restored = from_ui(to_ui(Config.from_json(config.to_json())))
    assert restored.active == config.active
    assert restored.settings == config.settings
    assert from_ui(to_ui(defaults())) == defaults()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    "x,y,width,height", [(0.05, 0.5, 0.45, 0.9), (0, 0, 1, 1), (1, 1, 0.45, 0.9), (0.5, 0.5, 0.01, 0.01)]
)
def test_ui_boxes_fit_edges_preserving_size_and_disabled_slots(enabled, x, y, width, height):
    values = to_ui(defaults())
    values[5:12] = [enabled, "edge", x, y, "Box", width, height]
    values[16] = "other"
    config = from_ui(values)
    c = config.characters[0]
    assert c.enabled == enabled
    assert c.box[2] - c.box[0] == pytest.approx(width)
    assert c.box[3] - c.box[1] == pytest.approx(height)
    assert all(0 <= n <= 1 for n in c.box)
    assert from_ui(to_ui(config)) == config
    # The same original builder used by generation must accept the result.
    assert config.to_pipe().characters


def test_original_immutable_pipe_and_separate_lora_strengths():
    config = Config((Character(prompt="girl", lora="my-lora", strength=0.8, clip_strength=0.3),))
    pipe = config.to_pipe()
    assert isinstance(pipe, CharacterPipe)
    assert pipe.characters[0].lora_strength == 0.8
    assert pipe.characters[0].lora_clip_strength == 0.3
    with pytest.raises(dataclasses.FrozenInstanceError):
        pipe.characters = ()


def test_original_duplicate_centers_spread():
    config = Config((Character(prompt="a"), Character(prompt="b")))
    pipe = config.to_pipe()
    assert effective_centers(pipe.characters)[0] == ((0.25, 0.5), (0.75, 0.5))
    masks = membership(pipe.characters, 8, 8, "cpu")
    assert masks[0, :, :4].all() and masks[1, :, 4:].all()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_presets_rejected(value):
    with pytest.raises(ValueError):
        Config.from_json('{"version":1,"characters":[{"x":' + value + "}]}")


def test_boxes_overlap_and_prediction_partition():
    config = Config(
        (
            Character(prompt="a", x=0.35, box=(0.1, 0.1, 0.6, 0.9), lora="a"),
            Character(prompt="b", x=0.65, box=(0.4, 0.1, 0.9, 0.9), lora="b"),
        )
    )
    chars = config.to_pipe().characters
    weights = prediction_masks(chars, 16, 16, "cpu")
    torch.testing.assert_close(sum(w for _, w in weights), torch.ones(16, 16))
    groups = groups_for(membership(chars, 16, 16, "cpu"))
    assert any(members == (0, 1) for members, _ in groups.cells)
    assert len(groups.background) > 0


def test_point_excludes_box_coverage():
    config = Config((Character(prompt="point", x=0.2), Character(prompt="box", x=0.75, box=(0.5, 0, 1, 1))))
    masks = membership(config.to_pipe().characters, 8, 8, "cpu")
    assert masks[1, :, 4:].all()
    assert not masks[0, :, 4:].any()


def test_routing_matches_dense_reference_and_keeps_negative_native():
    torch.manual_seed(42)
    chars = Config((Character(prompt="a", x=0.25), Character(prompt="b", x=0.75))).to_pipe().characters
    groups = groups_for(membership(chars, 2, 4, "cpu"))
    q, k, v = torch.randn(2, 8, 2, 4), torch.randn(2, 6, 2, 4), torch.randn(2, 6, 2, 4)
    out = route_cross(q, k, v, groups, [2, 1, 3], [0, 1], weights=(0.3, 1.0), character_gain=1.7)
    expected = torch.empty_like(out)
    for members, indices in groups.cells:
        if not members:
            continue
        slot = members[0]
        keep = [0, 1] + ([2] if slot == 0 else [3, 4, 5])
        scaled = v[0:1, keep].clone()
        scaled[:, 2:] *= 1.7
        bias = torch.tensor([0.3 / 2, 0.3 / 2] + [1.0 / (len(keep) - 2)] * (len(keep) - 2)).log()[None, :]
        expected[0:1, indices] = sdpa(q[0:1, indices], k[0:1, keep], scaled, bias)
    expected[1:2] = sdpa(q[1:2], k[1:2, :2], v[1:2, :2])
    torch.testing.assert_close(out, expected)


def test_schedule_uses_actual_sigma_not_forward_count():
    settings = Settings(common_prior=0.05, character_gain=1.7)
    sigmas = list(range(30, 0, -1)) + [0]
    first = schedule_values(30, sigmas, settings)
    fourth = schedule_values(27, sigmas, settings)
    assert first == (0.05, 1.7, 0.9)
    assert fourth[0] == pytest.approx(0.35)
    assert fourth[2] == pytest.approx(0.7)
    assert schedule_values(30, sigmas, settings) == first
    assert schedule_values(1, sigmas, settings) == (1.0, 1.0, 0.0)
    assert schedule_values(30, sigmas, defaults().settings) == (0.05, 1.7, 0.9)


def test_legacy_schedule_restores_exactly_and_comfy_reset_preserves_characters():
    from rs_forge_mc.ui import reset_schedule, restore_value

    legacy = Config(
        (
            Character(prompt="red", x=0.225, box=(0, 0.05, 0.45, 0.95), lora="a"),
            Character(prompt="blue", x=0.75, lora="b"),
        ),
        Settings(common_prior=0.05, character_gain=1.7, lora_mode="normal"),
    )
    params = {"RS MultiCharacter": legacy.to_json()}
    values = to_ui(legacy)
    assert [restore_value(i, params) for i in range(5)] == values[:5]
    values[:5] = reset_schedule()
    reset = from_ui(values)
    assert reset.active == legacy.active
    assert reset.settings == Settings(lora_mode="normal")


def test_attention_restores_after_failure():
    class Attention:
        pass

    class Block:
        cross_attn = Attention()
        self_attn = Attention()

    class Model:
        blocks = [Block()]

    model = Model()
    assert "torch_attention_op" not in model.blocks[0].cross_attn.__dict__
    with pytest.raises(RuntimeError):
        with attention_ops(model, lambda: 1, lambda: 2):
            raise RuntimeError("interrupted")
    assert "torch_attention_op" not in model.blocks[0].cross_attn.__dict__
    assert "torch_attention_op" not in model.blocks[0].self_attn.__dict__


def test_pose_scene_preserves_character_numbers():
    from rs_forge_mc.pose import preview_payload

    scene = {
        "version": 1,
        "width": 256,
        "height": 256,
        "mask_mode": "full",
        "camera": {"position": [0, 1.15, 4.1], "target": [0, 0.9, 0], "fov": 38},
        "people": [
            {"id": 2, "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": 1.0, "bulk": 1.0, "joints": {}}
        ],
    }
    config = Config(
        (Character(prompt="a", x=0.25), Character(prompt="b", x=0.75)), pose3d_json=json.dumps(scene)
    )
    pipe = config.to_pipe()
    assert pipe.characters[0].region_mask is None
    assert pipe.characters[1].region_mask is not None
    assert preview_payload(scene)["masks"][0]["number"] == 2
    restored = Config.from_json(config.to_json())
    assert restored.pose3d_json == config.pose3d_json
