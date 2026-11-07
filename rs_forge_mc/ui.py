# SPDX-License-Identifier: GPL-3.0-only
"""Gradio 4 UI and PNG/preset restoration, independent from the sampler."""
from html import escape

import gradio as gr

from .config import (Config, INFOTEXT_KEY, MAX_CHARACTERS, defaults, from_ui, to_ui)
from .preview import COLORS, preview


def launchers(config, ident):
    cards = []
    for i, c in enumerate(config.characters):
        cards.append(f'<button type="button" class="rs-mc-character-open" data-rs-slot="{i}" '
                     f'style="--rs-mc-accent:{COLORS[i]}"{ "" if c.enabled else " hidden"}>'
                     f'<strong>캐릭터 {i+1} (프롬프트 입력)</strong>'
                     '<span class="rs-mc-character-summary">눌러서 프롬프트 · LoRA 설정</span>'
                     '<span class="rs-mc-character-lora">LoRA 없음</span></button>')
    return (f'<div class="rs-mc-character-list" data-rs-target="{ident}">' + "".join(cards)
            + '<button type="button" class="rs-mc-character-add">+ 캐릭터 추가</button></div>')


def lora_choices(current=()):
    try:
        from .lora import available_loras
        choices = available_loras()
    except ImportError:
        choices = ["None"]
    return choices + [c for c in current if c not in choices]


def refresh_loras(*current):
    import networks
    networks.list_available_networks()
    choices = lora_choices(current)
    return [gr.update(choices=choices, value=c) for c in current]


def export_preset(*values):
    return from_ui(values).to_json(pretty=True)


def reset_schedule():
    # Change only the schedule. Keep prompts, regions, pose, LoRAs and mode.
    return to_ui(defaults())[:5]


def import_preset(text, ident="t2i", width=1024, height=1024):
    try:
        config = Config.from_json(text)
    except ValueError as error:
        raise gr.Error(str(error)) from error
    values = to_ui(config)
    # Dropdown choices must include imported names; generation resolves them
    # against Forge's registry and fails explicitly if the LoRA is unavailable.
    for i in range(MAX_CHARACTERS):
        index = 5 + i*10 + 7
        name = values[index]
        values[index] = gr.update(choices=lora_choices([name]), value=name)
    return [*values, preview(config, ident, width, height)]


def restore_value(index, params):
    try:
        config = Config.from_json(params[INFOTEXT_KEY])
        value = to_ui(config)[index]
        if 5 <= index < 105 and (index-5) % 10 == 7:
            return gr.update(choices=lora_choices([value]), value=value)
        return value
    except (ValueError, KeyError):
        return to_ui(defaults())[index]


def build(script, is_img2img):
    ident = "i2i" if is_img2img else "t2i"
    initial = defaults()
    controls, loras = [], []
    width = script.rs_dimensions['width']
    height = script.rs_dimensions['height']
    with gr.Accordion("RS MultiCharacter · Forge Neo · Anima", open=False,
                      elem_id=f"rs_mc_{ident}"):
        enabled = gr.Checkbox(label="멀티캐릭터 사용", value=False, elem_id=f"rs_mc_enabled_{ident}")
        gr.HTML('<p class="rs-mc-state" role="status">꺼짐 · 설정을 편집할 수 있지만 생성에는 적용되지 않습니다.</p>')
        gr.Markdown("**캐릭터 버튼이나 아래 영역을 눌러 프롬프트와 LoRA를 입력하세요.** "
                    "공통 장면은 기본 프롬프트에 입력합니다. 현재 Anima 전용입니다.")
        canvas = gr.HTML(preview(initial, ident, width.value, height.value))
        gr.HTML(launchers(initial, ident))
        reset = gr.Button("ComfyUI 기본 스케줄 적용", size="sm")
        # Keep the original argument order and actual Gradio controls. Floating
        # presentation does not create a second, disconnected copy of inputs.
        with gr.Accordion("고급 설정 / 분리 스케줄", open=False):
            gr.Markdown("유지 스텝 이후에는 매 스텝 감쇠량만큼 경계를 완화합니다. "
                        "기본값은 ComfyUI 원본과 같습니다. 비교할 때는 Euler a + SGM Uniform을 사용하세요. "
                        "이전 PNG·프리셋은 당시 값을 그대로 복원합니다. **ComfyUI 기본 스케줄 적용**은 스케줄만 초기화합니다.")
            with gr.Row():
                controls.append(gr.Slider(0, 1, value=initial.settings.common_prior, step=.01, label="Initial common prior"))
                controls.append(gr.Slider(1, 3, value=initial.settings.character_gain, step=.05, label="Early character V gain"))
            with gr.Row():
                controls.append(gr.Slider(0, .99, value=initial.settings.separation, step=.01, label="Initial spatial separation"))
                controls.append(gr.Slider(1, 150, value=initial.settings.hold_steps, step=1, label="Boundary hold steps"))
                controls.append(gr.Slider(.01, 1, value=initial.settings.decay, step=.01, label="Boundary decay per step"))
        reset.click(reset_schedule, inputs=[], outputs=controls[:5], show_progress="hidden")
        with gr.Group(elem_id=f"rs_mc_editor_{ident}", elem_classes=["rs-mc-character-editor"]):
            gr.HTML('<div class="rs-mc-character-heading"><div><span class="rs-mc-eyebrow">RS MultiCharacter</span>'
                    f'<h3 id="rs_mc_editor_title_{ident}">캐릭터 (프롬프트 입력)</h3></div>'
                    '<button type="button" class="rs-mc-character-close" aria-label="입력창 닫기">✕</button></div>')
            with gr.Tabs(elem_id=f"rs_mc_slots_{ident}"):
                for i, c in enumerate(initial.characters):
                    with gr.Tab(f"{i+1}"):
                        # Forge's UI defaults registry keys controls by label and
                        # ignores Tab/Row ancestry. Repeated labels make every slot
                        # inherit slot 1's defaults (including its X coordinate).
                        def slot_label(text):
                            return f"{text} · {i+1}"

                        on = gr.Checkbox(value=c.enabled, label=f"Character {i+1} / 캐릭터 {i+1}", elem_id=f"rs_mc_on_{ident}_{i}")
                        prompt = gr.Textbox(value=c.prompt, lines=3, label=slot_label("Character prompt / 캐릭터 프롬프트"), elem_id=f"rs_mc_prompt_{ident}_{i}")
                        with gr.Row():
                            x = gr.Slider(0, 1, value=c.x, step=.001, label=slot_label("X · left → right"))
                            y = gr.Slider(0, 1, value=c.y, step=.001, label=slot_label("Y · top → bottom"))
                        with gr.Row():
                            kind = gr.Radio([("위치로 나누기 (Point)", "Point"), ("사각형 지정 (Box)", "Box")],
                                            value="Point", label=slot_label("영역 지정"), elem_id=f"rs_mc_kind_{ident}_{i}")
                        with gr.Row(elem_id=f"rs_mc_box_{ident}_{i}", elem_classes=["rs-mc-box-size"]):
                            w = gr.Slider(.01, 1, value=.45, step=.01, label=slot_label("Box width"))
                            h = gr.Slider(.01, 1, value=.9, step=.01, label=slot_label("Box height"))
                        gr.Markdown("Box는 크기를 유지하며 화면 안에 맞춰 중심 좌표를 자동 보정합니다.")
                        with gr.Row():
                            lora = gr.Dropdown(choices=lora_choices(), value="None", label=slot_label("Character LoRA"), elem_id=f"rs_mc_lora_{ident}_{i}")
                            strength = gr.Slider(-3, 3, value=1, step=.05, label=slot_label("LoRA model strength"))
                            clip_strength = gr.Slider(-3, 3, value=1, step=.05, label=slot_label("LoRA text encoder strength"))
                        controls.extend([on, prompt, x, y, kind, w, h, lora, strength, clip_strength])
                        loras.append(lora)
            gr.HTML('<div class="rs-mc-character-footer"><span>입력값은 닫아도 유지됩니다.</span>'
                    '<button type="button" class="rs-mc-character-close">완료 / 닫기</button></div>')
        with gr.Accordion("3D Pose / 기존 3D 포즈 편집기", open=False):
            gr.HTML(f'<button type="button" class="rs-mc-pose-open" data-rs-target="{ident}">3D 편집기 열기 / Open 3D editor</button>')
            clear_scene = gr.Button("3D 영역 해제 · 위치/박스로 전환", size="sm")
            with gr.Accordion("고급 설정 / 3D 장면 JSON", open=False):
                scene = gr.Textbox(value="", lines=4, label="scene_json · 빈 값은 XY/박스 사용", elem_id=f"rs_mc_scene_{ident}")
            clear_scene.click(lambda: "", outputs=scene)
            controls.append(scene)
            gr.Markdown("기존 편집기의 관절·손가락·카메라·포즈 라이브러리를 사용합니다. Apply를 누르면 같은 번호의 캐릭터에 실루엣 영역을 적용합니다. 현재는 영역 마스크만 연결되어 있으며, 학습된 포즈 조건 적용과 이미지→3D 추정은 아직 연결 전입니다.")
        mode = gr.Radio(["normal", "precision"], value="precision", label="LoRA application mode / 적용 방식")
        gr.Markdown("**precision:** 캐릭터별로 계산해 분리 정확도를 우선합니다. 서로 다른 LoRA가 많으면 느려집니다. "
                    "**normal:** 한 번에 계산해 빠르지만 캐릭터 특징이 서로 섞일 수 있습니다.")
        controls.append(mode)
        refresh = gr.Button("Refresh LoRA list / LoRA 목록 새로고침", size="sm")
        refresh.click(refresh_loras, inputs=loras, outputs=loras)
        with gr.Accordion("Presets / JSON 프리셋", open=False):
            preset = gr.Textbox(lines=8, label="RS MultiCharacter JSON", value=initial.to_json(pretty=True))
            with gr.Row():
                save = gr.Button("Export settings / 설정 내보내기")
                load = gr.Button("Import settings / 설정 불러오기")
            save.click(export_preset, inputs=controls, outputs=preset)
            load.click(lambda text, w, h: import_preset(text, ident, w, h), inputs=[preset, width, height],
                       outputs=[*controls, canvas])
        gr.Markdown("Point는 가까운 좌표로 영역을 나누고, Box는 지정한 사각형을 사용합니다. "
                    "Box가 겹치면 두 캐릭터의 텍스트와 예측을 함께 반영합니다. "
                    "캐릭터 조립과 영역 계산은 기존 ComfyUI판과 같은 코드를 사용합니다.")

    def update_preview(*values):
        try:
            return preview(from_ui(values[:-2]), ident, *values[-2:])
        except ValueError as error:
            return f'<p role="alert">영역 설정을 확인해 주세요: {escape(str(error))}</p>'

    def update_geometry(slot):
        def update(*values):
            try:
                config = from_ui(values[:-2])
                c = config.characters[slot]
                offset = 5 + slot * 10
                return [preview(config, ident, *values[-2:]),
                        gr.update(value=c.x, step=.001) if c.x != values[offset+2] else gr.skip(),
                        gr.update(value=c.y, step=.001) if c.y != values[offset+3] else gr.skip()]
            except ValueError:
                return [update_preview(*values), gr.skip(), gr.skip()]
        return update

    preview_inputs = [*controls, width, height]
    for i in range(MAX_CHARACTERS):
        offset_base = 5+i*10
        for offset in (0, 2, 3, 4, 5, 6):
            controls[offset_base+offset].change(update_geometry(i), inputs=preview_inputs,
                                                outputs=[canvas, controls[offset_base+2], controls[offset_base+3]],
                                                show_progress="hidden")
    for component in (scene, width, height):
        component.change(update_preview, inputs=preview_inputs, outputs=canvas, show_progress="hidden")
    script.infotext_fields = [(enabled, lambda params: INFOTEXT_KEY in params)] + [
        (component, lambda params, index=index: restore_value(index, params))
        for index, component in enumerate(controls)]
    script.paste_field_names = [INFOTEXT_KEY]
    return [enabled, *controls]
