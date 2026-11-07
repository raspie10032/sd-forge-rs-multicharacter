import dataclasses
import json
from types import SimpleNamespace
from xml.etree import ElementTree

import gradio as gr

from rs_forge_mc.config import Character, Config, defaults
from rs_forge_mc.preview import preview


def test_preview_output_ratio_and_empty_or_disabled_prompts():
    for width, height in [(1024, 1024), (768, 512), (512, 768)]:
        root = ElementTree.fromstring(preview(defaults(), 'i2i', width, height))
        assert root.attrib['data-region-mode'] == 'xy'
        assert root.find('svg').attrib['viewBox'] == f'0 0 {width} {height}'
        assert len(root.findall('.//g')) == 2
    config = dataclasses.replace(defaults(), characters=tuple(
        dataclasses.replace(c, enabled=False) for c in defaults().characters))
    assert not ElementTree.fromstring(preview(config)).findall('.//g')


def test_preview_renders_pose_support_instead_of_point_partition():
    scene = {'version': 1, 'width': 256, 'height': 256, 'mask_mode': 'full',
             'camera': {'position': [0,1.15,4.1], 'target': [0,.9,0], 'fov': 38},
             'people': [{'id': 1, 'position': [0,0,0], 'rotation': [0,0,0],
                         'scale': 1., 'bulk': 1., 'joints': {}}]}
    config = Config((Character(prompt=''),), pose3d_json=json.dumps(scene))
    root = ElementTree.fromstring(preview(config, width=256, height=256))
    assert root.attrib['data-region-mode'] == 'pose'
    cells = root.findall('.//rect')
    # One point would cover the full canvas. A projected silhouette does not.
    assert 0 < sum(float(r.attrib['width']) * float(r.attrib['height']) for r in cells) < 256**2 * .5
    assert root.find('.//g').attrib['data-rs-slot'] == '0'


def test_real_gradio_build_preserves_generation_and_restore_argument_order():
    from rs_forge_mc.ui import build
    with gr.Blocks():
        script = SimpleNamespace(rs_dimensions={'width': gr.Slider(64,4096,value=768),
                                                 'height': gr.Slider(64,4096,value=512)})
        components = build(script, False)
    assert len(components) == len(script.infotext_fields) == 108
    assert components[-2].elem_id == 'rs_mc_scene_t2i'
    assert components[-1].value == 'precision'
