# RS MultiCharacter for Forge Neo

**한국어** · [English](README.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

**[사용자 가이드: 설치부터 2인 예제·전체 기능 조작까지](docs/user-guide.ko.md)** · [기능 비교](docs/feature-parity.md) · [검증 기록](docs/validation.md)

**Forge Neo에서 캐릭터별 프롬프트·영역·LoRA·이미지 참조를 조합하는 확장**입니다. [ComfyUI 원본](https://github.com/raspie10032/ComfyUI_RS_MultiCharacter_Sampler)의 영역 attention과 기능 모듈을 Forge 실행부에 연결했습니다.

**현재 `0.2.0a1` 알파입니다.** 앱 모드와 캐릭터별 네거티브는 제외했습니다. Anima 외에 SD1.5·SDXL/Illustrious·FLUX·Krea 2·MOSS 실행 경로도 추가했지만, 실제 체크포인트 생성 검증은 Anima 2B 중심입니다. 다른 모델의 작은 네이티브 모델 검사는 실제 체크포인트 품질 검증을 뜻하지 않습니다.

![실제 Forge에서 생성한 우산 공유 장면](docs/images/two-character-example.png)

예제: 1728×1152, Euler a / SGM Uniform, 24스텝, CFG 4, Precision, 서로 다른 스타일 LoRA 두 개. 장면용 스케줄은 `0.5 / 1.0 / 0.2`이고 기본값은 원본 스케줄입니다. 모델 가중치는 배포하지 않습니다.

## 설치와 기본 사용

Forge Neo **Extensions → Install from URL**에서 다음 저장소를 설치하고 WebUI를 재시작합니다.

```text
https://github.com/raspie10032/sd-forge-rs-multicharacter
```

또는 Forge Neo 폴더에서:

```bash
git clone https://github.com/raspie10032/sd-forge-rs-multicharacter.git extensions/sd-forge-rs-multicharacter
```

[릴리스 ZIP](https://github.com/raspie10032/sd-forge-rs-multicharacter/releases)은 `extensions/sd-forge-rs-multicharacter/scripts/` 구조로 풉니다. **기본 생성에는 별도 패키지 설치가 필요 없습니다.** 디테일러·태거·참조·이미지→3D의 선택 의존성은 [추가 기능 안내](docs/advanced.md)를 참고하세요. 선택한 기능을 실행할 때 모델을 준비하며, 기동만으로 가중치를 내려받지 않습니다.

1. 체크포인트와 맞는 인코더·VAE를 선택합니다.
2. txt2img / img2img의 **RS MultiCharacter · Forge Neo**를 열고 **멀티캐릭터 사용**을 켭니다.
3. Forge Positive에 공통 장면·배경, Negative에 공통 네거티브를 씁니다.
4. **캐릭터 1 (프롬프트 입력)** 버튼을 누르면 플로팅 창이 열립니다. 프롬프트·Point/Box·LoRA·강도를 지정합니다. **+ 캐릭터 추가**로 최대 10슬롯을 입력합니다.
5. Anima는 우선 **Precision / Euler a / SGM Uniform**으로 시작합니다. 추가 옵션은 **추가 기능 / 마스크·카메라·참조·디테일러**를 엽니다.

LoRA는 드롭다운으로 선택합니다. 캐릭터 문장 안의 `<lora:...>` 대신 모델·텍스트 인코더 강도를 나눠 설정합니다. Point는 중심 위치에 따라 화면을 나누고 Box는 사각형을 지정합니다.

![캐릭터 플로팅 입력창](docs/images/floating-editor.png)

## 추가된 기능

- 캐릭터 창: **직접 그리는 마스크 / 외부 마스크**, 여유 폭·이동·확대, **이미지 참조 업로드**, 신체 부위 강조, **글자 영역**.
- 공통 추가 기능: **상호작용 경계 스케줄**, 카메라 조건과 좌표 동기화, NovelAI 가중치 문법, **점진 해상도 샘플러**.
- 3D: 관절·손가락·실루엣·라이브러리·JSON/BVH/ZIP 가져오기, **학습된 자세 어댑터**, **이미지→3D** 추정.
- 참조: Anima reference frame / asymmetric v2 / Role K/V / legacy, SD 계열 IP-Adapter, FLUX·Krea·MOSS의 원본 참조 경로.
- 보정: **SEGM / BBOX / SAM 디테일러**, WD/PixAI 태거, 생성 후 보정, **로컬 폴더 일괄 보정**.
- 어댑터: Forge 네이티브 형식과 원본의 추가 LoHa·LoKr·DoRA·GLoRA·OFT·IA³·diff/set 등의 delta 연결. 레이어/형식이 맞지 않으면 오류로 알립니다. Normal 미지원 형식은 Precision으로 전환합니다.
- 설정: Forge PNG 복원·JSON 프리셋, **ComfyUI RS / NAI PNG·JSON 가져오기와 NAI 호환 JSON 내보내기**.

각 기능의 위치·모델 폴더·제한은 [추가 기능 안내](docs/advanced.md), 구현 여부는 [상세 기능표](docs/feature-parity.md)를 확인하세요. NAI 호환은 설정 교환이며 ComfyUI의 노드 그래프를 Forge에서 실행하는 기능은 아닙니다.

## 모드와 설정 복원

**Normal**은 가능한 레이어에서 계산을 공유하고, **Precision**은 LoRA 설정별 예측을 계산해 영역별로 합칩니다. 기본 스케줄은 공통 `0.05`, 강조 `1.7`, 초기 분리 `0.9`, 유지 `3`, 감쇠 `0.2`입니다. 불러온 설정이 우선이고 **ComfyUI 기본 스케줄 적용**은 다섯 값만 되돌립니다.

- PNG Info에 원본 PNG를 넣고 **Send to txt2img / img2img**를 누릅니다.
- Positive에 PNG를 드래그한 뒤 Forge **생성 설정 복원 버튼**을 누릅니다.
- JSON 프리셋도 사용할 수 있습니다. 추가 기능 상태는 PNG의 `RS MultiCharacter` JSON 안에 저장됩니다.

참조 이미지 원본은 PNG에 넣지 않습니다. 같은 설치의 `models/rs_mc/assets/`에 저장되므로 다른 PC로 옮길 때는 다시 업로드해야 합니다. LoRA·선택 모델 역시 대상 설치에 필요합니다. 메타데이터가 지워진 이미지나 스크린샷은 설정을 복원할 수 없습니다.

## 검증 범위

Anima 실제 생성으로 마스크·부위 강조·상호작용·카메라·글자 영역·점진 해상도·학습된 자세·참조 4종·디테일러를 확인했습니다. 3D 추정과 WD/PixAI 태거도 실제 가중치로 실행했습니다. 작은 실제 모델 36조건의 ComfyUI 계산 대조는 최대 오차 0이며, **모든 추가 기능과 모델 조합의 최종 PNG가 동일하다는 뜻은 아닙니다.** [검증 기록](docs/validation.md).

10슬롯은 정확한 인원수 보장이 아닙니다. 2/3/4인 비교에서 양쪽 모두 인원이 늘면 외형·역할 혼합과 누락이 생겼습니다. 다른 attention 교체 확장, ControlNet 조합, 양자화/GGUF 모델 조합과 다른 OS는 검증 범위 밖입니다. Nunchaku는 별도 실행 체계여서 차단합니다.

[개발 안내](docs/development.md) · [GPL-3.0-only](COPYING) · [외부 자산 라이선스](THIRD_PARTY_NOTICES.md)
