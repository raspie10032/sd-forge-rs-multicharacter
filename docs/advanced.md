# 추가 기능 / Advanced features

`0.2.0a1`의 선택 기능 안내입니다. 기본 멀티캐릭터 생성은 추가 패키지가 필요 없습니다. 아래 명령은 **Forge가 실제 사용하는 Python**으로 실행합니다. 개발 검사 전용 `requirements-dev.txt`를 Forge에 설치하지 마세요.

## 마스크·부위·글자

캐릭터 플로팅 창의 **마스크 · 글자 · 참조 이미지 · 신체 부위**를 엽니다.

- **마스크 그리기 / 가져오기**: 흰 영역이 해당 슬롯입니다. 브러시·지우개·이미지 가져오기 후 적용합니다. 여유 폭은 원본 마스크 픽셀, 이동은 캔버스 비율, 크기는 캔버스 중심 기준입니다. 범위 밖은 잘립니다.
- **부위 이름 강조**: OpenPose JSON/PNG를 공통 추가 기능에서 넣거나 3D 장면을 적용한 뒤 강도를 올립니다. 원본의 의미 부위 마스크를 사용합니다. 임의의 세부 부위 마스크는 JSON 프리셋으로도 넣을 수 있습니다.
- **글자 영역**: 슬롯 용도를 글자로 바꾸고 Box와 실제 문자를 지정합니다. 읽을 수 있는 문자를 그리는 능력은 모델에 달려 있습니다. Anima가 정확한 영문을 그린다는 보장은 없습니다.

## 상호작용·카메라·해상도

공통 **추가 기능** 패널에 있습니다.

- 상호작용 기본 / 3스텝 / 6스텝 / 사용자 경계 스케줄은 원본의 겹침 경계 제어입니다. 동작은 공통·캐릭터 프롬프트에 함께 씁니다.
- 카메라 조건은 수평·수직·거리·roll과 강도를 프롬프트에 반영하고, 선택에 따라 영역 좌표도 원본 방식으로 변환합니다. 3D 편집기의 화면 회전과 별도입니다.
- 점진 해상도는 시작 배율을 `0.5–1`로 지정합니다. `1`은 끄기입니다. 세 단계로 latent를 키우고 한 sigma 스케줄을 나눠 사용합니다. Forge Hires.fix와 동시에 켜지 않습니다. 마스크 인페인팅은 고정 해상도가 필요합니다. 솔버의 이력은 단계가 바뀔 때 다시 시작합니다.
- 레이아웃의 MOSS 기본 JSON 방식은 MOSS 전용이며 모든 슬롯에 Box/마스크가 필요합니다. 다른 모델에서 선택하면 설명과 함께 중단합니다.

## 이미지 참조·학습된 포즈

각 캐릭터에 **참조 이미지 넣기**로 업로드하고 강도·긴 변 해상도를 설정합니다. 공통 참조 패널에서 Anima 방식을 선택합니다. 모델별 원본 어댑터·인코더는 선택 기능을 실행할 때 검증/준비됩니다. PNG에는 이미지 원본 대신 로컬 자산 ID가 저장됩니다. 파일은 **`models/rs_mc/assets/`**에 보관됩니다.

```bash
python -m pip install -r extensions/sd-forge-rs-multicharacter/requirements-reference.txt
```

원본과 같은 제한이 있습니다. 참조와 학습된 자세는 함께 쓰지 않습니다. Role K/V는 baseline 상호작용·부위 강조 0을 사용하고 캐릭터 LoRA는 Normal이 필요합니다. Asymmetric v2는 Anima 2B 전용이며 캐릭터 LoRA 조합은 원본에서 검증되지 않아 차단합니다. Anima 2.9B에는 전용 frame 어댑터가 필요합니다. SD·FLUX·Krea·MOSS 참조 경로는 연결됐지만 이번 배포에서 해당 실제 체크포인트로 생성하지 않았습니다.

3D 편집기에서는 **이미지→3D**로 선명한 한 사람의 크롭을 넣을 수 있습니다. SAM 3D Body 모델은 약 2.83 GB이며 `models/detection/`에서 찾습니다. 추정 결과는 수정 가능한 MHR 관절과 입력 프레임을 포함합니다. 가려진 신체와 깊이를 정확히 복원한다는 뜻은 아닙니다. 학습된 자세 유도는 3D 장면을 적용하고 공통 패널에서 자세 적용을 자동으로 바꿉니다.

## 디테일러·태거·폴더 보정

```bash
python -m pip install -r extensions/sd-forge-rs-multicharacter/requirements-detailer.txt
```

**생성 후 디테일러 사용**을 켜고 SEGM 또는 BBOX 모델을 지정합니다. SEGM이 있으면 BBOX·SAM 경로는 건너뜁니다. BBOX 경로의 SAM은 선택 사항이며 로컬 파일이 있어야 합니다. 낮은 매칭 점수·차이는 보수적으로 건너뜁니다. 선택된 인물의 프롬프트·LoRA로 Forge 마스크 img2img를 수행하고 원본 마스크 안에 합성합니다.

태거 선택은 WD ViT v3 / WD EVA02 Large v3 / PixAI Tagger v1.0입니다. 캐릭터 창의 **참조 이미지 태그 분석**은 업로드한 참조를 분석합니다. 이식판 태거와 YOLO 검출은 CPU에서 실행하고, 확산 생성·이미지→3D는 Forge가 선택한 GPU를 사용합니다.

PixAI는 Transformers 5가 필요합니다. 기존 Forge의 Transformers 호환성을 확인한 별도 환경에서만 선택합니다.

```bash
python -m pip install -r extensions/sd-forge-rs-multicharacter/requirements-pixai-tagger.txt
```

폴더 보정은 공통 패널의 **로컬 폴더 일괄 보정**에서 입력·출력 경로를 지정합니다. 입력 폴더 바로 아래의 PNG/WebP/JPG/JPEG를 최대 512장 처리합니다. 입력과 출력은 달라야 하고 이미 있는 결과를 덮어쓰지 않습니다. 현재 캐릭터·디테일러와 공통 Positive/Negative를 사용합니다.

모델 위치는 Forge `models/` 아래 원본 폴더 구성을 사용합니다: `ultralytics/bbox/`, `ultralytics/segm/`, `sams/`, `rs_wd_tagger/`, `detection/` 및 각 참조 어댑터의 전용 폴더. **Settings → RS MultiCharacter → 추가 모델 루트**로 ComfyUI의 `models`를 재사용할 수 있습니다. 경로 구분자는 Linux `:`, Windows `;`입니다. 호환 파일은 복제하지 않고 참조합니다.

## 설정 교환과 남은 제한

공통 패널에서 ComfyUI RS / NAI PNG·JSON을 가져오고 NAI 호환 JSON을 내보냅니다. 마스크·부위·LoRA 강도·스케줄을 함께 보존합니다. 원본 ComfyUI 노드 그래프는 Forge에서 실행하지 않으며, NAI API 생성이나 결제도 수행하지 않습니다. 앱 모드·캐릭터별 네거티브는 포함하지 않았습니다.

전체 조합 검증이나 모든 장면의 품질 보장은 아닙니다. 다른 모델 계열·양자화·확장 조합의 범위는 [검증 기록](validation.md)과 [기능표](feature-parity.md)를 참고하세요.
