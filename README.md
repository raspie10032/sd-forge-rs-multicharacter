# RS MultiCharacter for Forge Neo

[한국어](README.ko.md) · **English** · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

**[User guide: installation, a two-character walkthrough and all feature controls](docs/user-guide.md)** · [Feature matrix](docs/feature-parity.md) · [Validation](docs/validation.md)

Regional character prompts, masks, LoRAs, references and pose controls for Forge Neo, based on [ComfyUI RS MultiCharacter Sampler](https://github.com/raspie10032/ComfyUI_RS_MultiCharacter_Sampler).

**Version `0.2.0a1`, alpha.** The original feature modules are now connected to Forge, except App Mode and per-character negatives. Actual-checkpoint validation is primarily **Anima 2B**. SD1.5, SDXL/Illustrious, FLUX, Krea 2 and MOSS have native runtime paths; small random-weight execution checks do not establish trained-checkpoint quality or all combinations.

![Actual Forge generation](docs/images/two-character-example.png)

## Install

In **Extensions → Install from URL**, use:

```text
https://github.com/raspie10032/sd-forge-rs-multicharacter
```

Restart Forge, or clone into `extensions/sd-forge-rs-multicharacter`. ZIP releases must retain `scripts/` directly inside that directory. No additional package is needed for basic sampling. Optional dependencies and model locations are listed in [Advanced features](docs/advanced.md). Weights are prepared when a selected feature runs, not on startup; no model weights are bundled.

Tested host: Forge Neo neo-2.31, `4f4284b02a5c814b81c328c64ed7e99a139f21ef`, Python 3.12 / Linux. Other host revisions are unverified.

## Use

1. Select a compatible checkpoint, encoder and VAE.
2. Enable **RS MultiCharacter · Forge Neo** in txt2img or img2img.
3. Put the shared scene/background in Forge Positive and the common negative in Negative.
4. Open **캐릭터 1 (프롬프트 입력)** for a floating character form. Set prompt, Point/Box and registered LoRA. Add up to ten slots.
5. For Anima, start with Precision / Euler a / SGM Uniform. Open **추가 기능** for the remaining controls.

![Floating input form](docs/images/floating-editor.png)

Character forms now include painted/imported masks, mask expansion/position/scale, reference images, body-part emphasis and literal text regions. The advanced panel adds interaction schedules, camera conditions, NovelAI weighting syntax, progressive resolution, learned pose, references, detector-based detailers, taggers, folder processing and metadata exchange. The 3D editor includes image-to-3D estimation alongside joints/fingers, silhouettes, library and JSON/BVH/ZIP imports.

Native adapter loading plus the original additional formats support extended LoRA/DoRA/LoHa/LoKr/GLoRA/OFT/IA³/diff/set deltas where Forge and the target layer support them. Normal falls back to Precision for unsupported shared execution; unmatched tensors fail explicitly.

See the [feature matrix](docs/feature-parity.md) and [feature guide](docs/advanced.md) for model-specific restrictions. NAI interoperability exchanges settings, not ComfyUI node-graph execution.

## Restore settings

Use **PNG Info → Send to txt2img/img2img**, or drop a PNG on Positive then press Forge's restore button. JSON presets also work. Advanced state is included in the `RS MultiCharacter` JSON inside native Forge `parameters`.

Reference assets stay in `models/rs_mc/assets/`; their original pixels are not embedded in generated PNGs. Re-upload on another installation. Model/LoRA files must also exist there. Metadata-stripped images and screenshots cannot restore settings.

Defaults remain the original `0.05 / 1.7 / 0.9 / 3 / 0.2` schedule. Saved values take priority. Normal shares supported layer calculations; Precision combines independent LoRA predictions regionally.

## Evidence and limits

[Validation](docs/validation.md) distinguishes actual-checkpoint generation, small native models and ComfyUI prediction comparisons. The expanded Anima route matches the original exactly in 36 small-model cases with identical encoded inputs. This does not prove independent end-to-end PNG identity, reference quality, every model family or arbitrary feature combinations.

Both apps can lose character count, identities and assigned actions as complexity increases. Ten input slots do not guarantee ten people. Other attention-replacement extensions, ControlNet combinations, quantized/GGUF configurations and other operating systems remain unverified. Nunchaku is rejected because it uses a different execution system.

[Development](docs/development.md) · [GPL-3.0-only](COPYING) · [Third-party notices](THIRD_PARTY_NOTICES.md)
