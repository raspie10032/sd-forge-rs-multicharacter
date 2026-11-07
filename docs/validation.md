# Validation for 0.1.0a5

Recorded 2026-11-07. These are compact summaries of local experiments. Checkpoint weights, raw model captures and machine-specific paths are excluded.

## Environment and repeatable checks

- Forge Neo neo-2.31, commit 4f4284b02a5c814b81c328c64ed7e99a139f21ef.
- Python 3.12, PyTorch 2.14.0+cu130, Gradio 4.40.0; Linux / NVIDIA RTX 4070 Ti SUPER for checkpoint generation.
- Anima 2B anima-base-v1.0; character tests used anima_RSC and anima_MyMyArtStyleLoRA. Weights not bundled.
- Publication recheck: **29 unit tests passed**, Ruff and bundled-source verification passed, native CPU smoke passed with exact restoration after completion and simulated failure.
- [Native backend report](validation/native-smoke.json): real Forge classes with small random weights, not trained-checkpoint generation.

## Original ComfyUI calculation comparison

Corrections: RoPE frequency precision, AdaLN operation ordering, Point smoothing 0.04, Box/Point overlap priority, BF16 Normal overlap averaging. Defaults restored to 0.05 / 1.7 / 0.9 / 3 / 0.2.

| Comparison | Result |
| --- | --- |
| Real small-model classes: 2 dtypes × 3 layouts × 2 modes × 3 stages | 36 cases, maximum absolute error 0 |
| Captured Anima 2B first step, 1728×1152, BF16, two LoRAs | Normal and Precision, maximum absolute error 0 |
| Actual captured Forge Precision prediction vs replay | Maximum absolute error 0 |

[Small-model report](validation/parity-tiny.json) · [Anima first-call report](validation/parity-real.json).

These compare **identical encoded text, latent, sigma and weights** through the model/region/LoRA path. Independent prompt parsing, encoding, RNG, complete sampling and VAE equality are not established. Actual-checkpoint comparison covers a captured first call, not all steps/configurations.

## Actual WebUI experiments

These were completed locally during development, with the relevant paths retained in a5:

- Normal/Precision generation with two different LoRAs; 1728×1152 generation; img2img and Hires.fix (768×512 → 960×640).
- Floating editor persistence, character add/disable, Escape, output-ratio preview and edge-clamped Boxes.
- Actual Chrome 3D rendering, applying silhouettes and generating; pose import/library APIs and original editor assets are bundled.
- PNG Info restoration to both tabs; exported RS JSON matched PNG JSON including strengths, regions and schedule.
- Prompt-drop handler tested using a PNG File in a browser DataTransfer, followed by Forge restore, in both tabs. **Physical file-manager mouse drag was not independently verified.** Dropping alone fills infotext; restore applies settings.
- Extension OFF generation after injected failure matched the pre-test OFF result pixel-for-pixel.

These are recorded experiments, not all CI browser tests. Other operating systems, browsers, extension combinations and model families are outside this validation.

## Two-, three- and four-person comparison

Left: Forge. Right: ComfyUI. Each scene generated once per app with the same requested model/LoRAs, prompts, coordinates, schedule and seed. Same seed numbers do not establish identical initial noise.

![Forge left, ComfyUI right: two, three and four people requested](images/forge-comfy-234-comparison.jpg)

All: 1728×1152, Euler ancestral / SGM uniform, 24 steps, CFG 4, Precision. Scene schedule: common 0.5, gain 1.0, separation 0.2.

| Request | Forge | ComfyUI |
| --- | --- | --- |
| 2, umbrella outside flower shop, seed 823401 | Two retained; bouquet holder also grabs umbrella | Two; similar action error |
| 3, strawberry cake, seed 823402 | Three; assigned baking roles largely absent | Two; male absent, roles also absent |
| 4, riverside picnic, seed 823403 | Four; identity/gender and interaction-pair errors | Three; missing person, merged silver hair/mint shirt |

One seed per scene cannot rank stability. Both apps lose identity, count or roles as complexity grows. Failures are retained intentionally. Hands, contact and shared objects remain limitations.
