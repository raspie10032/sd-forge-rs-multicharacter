from types import SimpleNamespace

import pytest
import torch

from rs_forge_mc.config import Character, Config, Settings
from rs_forge_mc.geometry import prediction_masks
from rs_forge_mc.lora import Factors
from rs_forge_mc.runtime import AnimaRuntime
from rs_forge_mc.shared_lora import SharedLora


@pytest.mark.parametrize("role", ["image", "text"])
def test_original_spatial_and_own_caption_policy(role):
    config = Config((Character(prompt="a", x=0.25, lora="a"), Character(prompt="b", x=0.75)))
    chars = config.to_pipe().characters
    layer = torch.nn.Linear(3, 3, bias=False)
    with torch.no_grad():
        layer.weight.zero_()
    path = "diffusion_model.blocks.0.cross_attn." + ("q_proj" if role == "image" else "k_proj")
    factors = Factors(torch.ones(3, 1), torch.ones(1, 3), 1.0)
    plans = {"a": SimpleNamespace(paths=[path], factors=[factors])}
    shared = SharedLora(plans, chars)
    masks = prediction_masks(chars, 16, 16, "cpu")
    root = SimpleNamespace(get_submodule=lambda name: layer)
    lengths = [2, 3, 4]
    x = torch.ones(2, 8 if role == "image" else sum(lengths), 3)
    with shared.installed(root, masks, (2, 4), lengths):
        out = layer(x)
    if role == "image":
        expected = torch.tensor([1, 11 / 12, 1 / 12, 0, 1, 11 / 12, 1 / 12, 0]) * 3.0
    else:
        expected = torch.tensor([0.5, 0.5, 1, 1, 1, 0, 0, 0, 0]) * 3.0
    torch.testing.assert_close(out, expected[None, :, None].expand_as(out))
    assert not layer._forward_hooks
    with pytest.raises(RuntimeError):
        with shared.installed(root, masks, (2, 4), lengths):
            raise RuntimeError("interrupted")
    assert not layer._forward_hooks


def test_known_unsupported_layer_selects_precision_before_install():
    config = Config((Character(prompt="a", lora="a"),), Settings(lora_mode="normal"))
    runtime = AnimaRuntime(
        config, [torch.zeros(1, 3, 4)], {"a": SimpleNamespace(paths=["diffusion_model.t_embedder.0"])}
    )
    assert runtime.audit["effective_lora_mode"] == "precision"
    assert "t_embedder" in runtime.audit["lora_fallback_reason"]
    assert runtime.shared_lora is None
    assert config.to_pipe().lora_application_mode == "normal"


def test_extended_adapter_selects_precision_before_sampling():
    from rs_forge_mc.shared_lora import SharedLoraUnsupported

    plan = SimpleNamespace(paths=["diffusion_model.blocks.0.cross_attn.q_proj"])
    with pytest.raises(SharedLoraUnsupported, match="Extended adapter"):
        SharedLora({"extended": plan}, ())
