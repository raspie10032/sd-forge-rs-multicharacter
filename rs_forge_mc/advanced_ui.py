# SPDX-License-Identifier: GPL-3.0-only
"""Accessible controls backed by one versioned Gradio JSON input."""


def field(path, label, kind="number", value="", attrs=""):
    return f'<label>{label}<input data-rs-feature="{path}" type="{kind}" value="{value}" {attrs}></label>'


def select(path, label, options):
    return (
        f'<label>{label}<select data-rs-feature="{path}">'
        + "".join(f'<option value="{v}">{t}</option>' for v, t in options)
        + "</select></label>"
    )


def slot_html(ident, i):
    prefix = f"slots.{i + 1}"
    return (
        f'<details class="rs-mc-extra" data-rs-target="{ident}"><summary>마스크 · 글자 · 참조 이미지 · 신체 부위</summary><div class="rs-mc-feature-grid">'
        + select(prefix + ".kind", "슬롯 용도", [("character", "캐릭터"), ("text", "글자 영역 (Box 필요)")])
        + field(prefix + ".text", "그릴 글자", "text")
        + field(
            prefix + ".body_part_strength", "부위 이름 강조", value="0", attrs='min="0" max="0.8" step="0.05"'
        )
        + field(
            prefix + ".reference_strength", "이미지 참조 강도", value="1", attrs='min="0" max="2" step="0.05"'
        )
        + field(
            prefix + ".reference_resolution",
            "참조 이미지 긴 변",
            value="384",
            attrs='min="64" max="1024" step="64"',
        )
        + field(prefix + ".mask_margin", "마스크 여유 폭 (픽셀)", value="0", attrs='min="0" max="128"')
        + field(prefix + ".mask_offset_x", "마스크 가로 이동", value="0", attrs='min="-1" max="1" step=".01"')
        + field(prefix + ".mask_offset_y", "마스크 세로 이동", value="0", attrs='min="-1" max="1" step=".01"')
        + field(prefix + ".mask_scale", "마스크 크기", value="1", attrs='min=".05" max="4" step=".05"')
        + f'''</div><div class="rs-mc-feature-actions">
<button type="button" data-rs-mask="{i + 1}">마스크 그리기 / 가져오기</button>
<button type="button" data-rs-mask-clear="{i + 1}">마스크 해제</button>
<label class="rs-mc-upload">참조 이미지 넣기<input type="file" data-rs-reference="{i + 1}" accept="image/png,image/jpeg,image/webp"></label>
<button type="button" data-rs-reference-clear="{i + 1}">참조 해제</button>
<button type="button" data-rs-tag-reference="{i + 1}">참조 이미지 태그 분석</button>
</div><p data-rs-slot-status="{i + 1}" role="status"></p><p data-rs-tag-result role="status"></p><small>마스크는 직접 그린 영역을 사용합니다. 부위 강조는 3D 장면 또는 OpenPose가 필요합니다. 글자 영역은 LoRA를 사용하지 않습니다.</small></details>'''
    )


def global_html(ident):
    html = f'<div class="rs-mc-advanced" data-rs-target="{ident}"><div class="rs-mc-feature-grid">'
    html += select(
        "interaction.preset",
        "상호작용 · 겹침 제어",
        [
            ("baseline", "기본 경계"),
            ("delay3", "개별 경계 3스텝 더 유지"),
            ("delay6", "개별 경계 6스텝 더 유지"),
            ("custom", "직접 설정"),
        ],
    )
    html += field(
        "interaction.delay_steps", "추가 유지 스텝", value="6", attrs='min="0" max="30" step="1"'
    ) + field("interaction.decrement", "감쇠량", value=".2", attrs='min=".01" max="1" step=".01"')
    html += select("syntax", "프롬프트 문법", [("ComfyUI", "기본 문법"), ("NovelAI", "NovelAI 가중치 문법")])
    html += field(
        "schedule.common_boost", "후반 공통 프롬프트 증가량", value=".1", attrs='min="0" max="1" step=".05"'
    )
    html += field(
        "schedule.region_feather", "영역 경계 완화", value=".04", attrs='min="0" max=".25" step=".01"'
    )
    html += select(
        "layout_method",
        "레이아웃 방식",
        [("regional", "영역별 계산"), ("moss_native", "MOSS 기본 레이아웃 JSON"), ("auto", "모델 자동 선택")],
    )
    html += field(
        "progressive.start_scale",
        "점진 해상도 · 시작 배율 (1 = 끄기)",
        value="1",
        attrs='min=".5" max="1" step=".01"',
    )
    html += '</div><details><summary>카메라 조건</summary><div class="rs-mc-feature-grid">'
    html += field("camera.enabled", "카메라 조건 사용", "checkbox")
    for k, label, value, attrs in [
        ("azimuth", "수평 각도", 0, 'min="-180" max="180"'),
        ("elevation", "수직 각도", 0, 'min="-90" max="90"'),
        ("distance", "거리", 0.5, 'min="0" max="1" step=".05"'),
        ("roll", "화면 기울기", 0, 'min="-45" max="45"'),
        ("strength", "조건 강도", 1, 'min="0" max="2" step=".05"'),
    ]:
        html += field("camera." + k, label, value=value, attrs=attrs)
    html += select(
        "camera.scope", "적용 대상", [("scene_and_characters", "공통 + 캐릭터"), ("scene_only", "공통")]
    ) + select(
        "camera.layout_sync",
        "영역 좌표 동기화",
        [("fixed", "끄기"), ("distance_and_roll", "거리·회전"), ("perspective", "원근 투영")],
    )
    html += '</div></details><details><summary>3D 학습된 자세 유도</summary><div class="rs-mc-feature-grid">'
    html += select(
        "pose.mode", "자세 적용", [("masks_only", "실루엣 영역만"), ("auto", "학습된 모델별 자세 어댑터")]
    )
    for k, label, value in [("strength", "강도", 1), ("start", "시작 비율", 0), ("end", "종료 비율", 1)]:
        html += field("pose." + k, label, value=value, attrs='min="0" max="1" step=".05"')
    html += '</div></details><details><summary>이미지 참조 방식</summary><div class="rs-mc-feature-grid">'
    html += select(
        "reference.method",
        "Anima 참조 방식",
        [
            ("reference_frame", "Reference frame"),
            ("asymmetric_v2", "Asymmetric v2 (실험적)"),
            ("role_kv", "Role K/V (2B BF16/FP32)"),
            ("legacy", "SigLIP IP-Adapter (이전 방식)"),
        ],
    )
    html += field(
        "reference.guidance", "참조 Guidance", value="4.5", attrs='min="0" max="20" step=".1"'
    ) + field("reference.reference_scale", "참조 배율", value="1", attrs='min=".25" max="1" step=".05"')
    html += field(
        "reference.adapter_strength", "참조 어댑터 강도", value="1", attrs='min="0" max="2" step=".05"'
    )
    html += select(
        "reference.correction",
        "Reference frame 보정",
        [("apg", "APG"), ("rescale", "Rescale"), ("none", "끄기")],
    )
    html += field("reference.cache", "참조 텍스트 K/V 캐시", "checkbox")
    html += "</div><small>선택한 기능을 실행할 때만 필요한 가중치를 준비합니다. 참조 원본은 로컬 모델 폴더에 보관하고 PNG에는 자산 ID를 기록합니다.</small></details>"
    html += '<details><summary>로컬 디테일러 · 태거</summary><div class="rs-mc-feature-grid">' + field(
        "detailer.enabled", "생성 후 디테일러 사용", "checkbox"
    )
    for key, label in [("segm", "SEGM 감지 모델"), ("bbox", "BBOX 감지 모델"), ("sam", "SAM 보정 모델")]:
        html += select("detailer." + key, label, [("OFF", "OFF")])
    html += select(
        "detailer.tagger",
        "캐릭터 매칭 태거",
        [(s, s) for s in ("WD ViT v3", "WD EVA02 Large v3", "PixAI Tagger v1.0")],
    )
    for k, label, v, attrs in [
        ("denoise", "보정 강도", 0.35, 'min="0" max="1" step=".01"'),
        ("size", "크롭 생성 크기", 768, 'min="64" max="2048" step="16"'),
        ("steps", "보정 스텝", 20, 'min="2" max="100"'),
        ("cfg", "보정 CFG", 4, 'min="0" max="30" step=".1"'),
        ("min_score", "매칭 최소 점수", 0.25, 'min="0" max="1" step=".01"'),
        ("min_margin", "매칭 최소 차이", 0.08, 'min="0" max="1" step=".01"'),
    ]:
        html += field("detailer." + k, label, value=v, attrs=attrs)
    html += "</div><small>SEGM이 있으면 BBOX·SAM을 건너뜁니다. 태거가 캐릭터를 확실히 구별하지 못한 영역은 보존합니다.</small>"
    html += '<details><summary>로컬 폴더 일괄 보정</summary><div class="rs-mc-feature-grid"><label>입력 폴더 경로<input type="text" data-rs-folder-source></label><label>결과 폴더 경로<input type="text" data-rs-folder-output></label></div><p>현재 캐릭터·디테일러 설정과 기본 프롬프트를 적용합니다. 원본을 보존하고 별도 PNG로 저장합니다.</p><button type="button" data-rs-folder-run>폴더 이미지 보정 시작</button></details></details>'
    html += '<details><summary>OpenPose / 원본 PNG·NAI 설정 가져오기</summary><div class="rs-mc-feature-actions"><label class="rs-mc-upload">OpenPose JSON / 뼈대 PNG<input type="file" data-rs-openpose accept=".json,image/png"></label><button type="button" data-rs-openpose-clear>OpenPose 해제</button><label class="rs-mc-upload">ComfyUI·NAI PNG / JSON 가져오기<input type="file" data-rs-metadata accept=".json,image/png,image/webp"></label><button type="button" data-rs-nai-export>NAI 호환 JSON 내보내기</button></div></details><p class="rs-mc-advanced-status" role="status"></p></div>'
    return html
