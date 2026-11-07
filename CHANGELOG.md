# Changelog

## 0.2.0a2 — 2026-11-07

- Add a standalone Windows BAT installer: choose the Forge Neo directory; Git is not required. Fetch the latest published release, including prereleases, and verify SHA-256 before replacing files.
- Refuse a running WebUI, back up the complete old extension outside `extensions/`, and roll back a failed replacement. Preserve host settings/models, GPU selection and launch options.
- Document BAT installation, updates and rollback in Korean, English, Japanese and Simplified Chinese. Optional packages/weights and Forge Neo itself remain separate.
- Add Windows PowerShell 5.1 CI for actual BAT execution, online release installation and running-process refusal, plus isolated backup/rollback/path/checksum/archive checks. Windows generation is outside this installer test.

## 0.2.0a1 — 2026-11-07

- Port the remaining original feature modules except App Mode and per-character negatives.
- Add mask painting/import/transforms, body parts, interaction/camera conditions, text/layout tools and progressive sampling.
- Add four Anima reference backends, native-family reference paths, learned pose, SAM 3D Body image estimation, detector/SAM detailers, WD/PixAI taggers and folder correction.
- Add native-family runtime dispatch and extended native/additional adapter deltas, with explicit Precision fallback.
- Preserve advanced state through presets/PNG and original RS/NAI metadata exchange.
- Correct Forge VAE latent-format conversion for references and learned pose; retain Comfy Anima arithmetic parity.
- Fix preview division by zero while dimensions are retyped.
- Separate implementation coverage from actual-checkpoint and small-model validation.

## 0.1.0a5 — 2026-11-07

First public Forge Neo alpha targeting Anima 2B.

- Regional character prompts, Point/Box placement, per-character plain linear LoRA and Normal/Precision modes.
- Floating forms, aspect-correct preview, clamped Boxes and txt2img/img2img settings.
- Original 3D editor, silhouette regions, pose library and JSON/BVH/ZIP import.
- JSON presets and Forge PNG restoration, including prompt-drop followed by restore.
- ComfyUI-compatible RoPE precision, AdaLN ordering, masks and BF16 Normal averaging.
- Original schedule defaults; explicit saved values remain authoritative.
- 29 unit tests, native smoke, scoped parity records and paired 2/3/4-person examples.
- Installation instructions, explicit feature gaps and source/license provenance.

Not full feature parity with the original. See [feature comparison](docs/feature-parity.md) and [validation limits](docs/validation.md).
