# ComfyUI → Forge feature comparison

Audited 2026-11-07 against the installed original. Forge **0.2.0a1** ports the remaining feature modules, with **App Mode and per-character negative prompts deliberately omitted**. Host-specific graph connections are represented by forms or metadata interchange. An implemented path and an actual-checkpoint test are different claims.

| Original capability | Forge status | Scope and evidence |
| --- | --- | --- |
| Shared + numbered prompts, up to 10 slots | Included | Floating character forms; common Forge Negative |
| Per-character negatives | Omitted by request | Common negative remains |
| BuildPipe / Finalize / Point / Box | Reused | Original validation, priority and edge smoothing |
| Attention routing / separation / Normal / Precision | Included | Expanded Anima route: 36 exact small-model comparison cases |
| Character model / text-encoder LoRA strengths | Included | Native Forge loading and scoped deltas |
| LoCon / DoRA / LoHa / LoKr / GLoRA / OFT / IA³ / diff / set etc. | Included where loader/layer supports | Extended formats use Precision if shared Normal is unsuitable; full trained-adapter matrix unverified |
| Arbitrary painted / external masks | Included | Character form; expansion, offset and scale |
| Body-part masks and emphasis | Included | OpenPose / 3D semantic parts, actual Anima execution |
| 3D joints / fingers / mannequin / silhouettes | Included | Original editor and Forge adapter |
| Pose library / JSON / OpenPose / DWPose / Yu Zhu / BVH / ZIP | Included | Original library/import implementations |
| Interaction presets / custom separation schedule | Included | Original interaction.py; actual Anima execution |
| Dedicated camera conditions / coordinate synchronization | Included | Independent of editor orbit; original camera_control.py |
| Learned pose adapters | Included | Anima actual execution; native family paths retained where Forge has the architecture |
| Anima references: frame / asymmetric v2 / Role K/V / legacy | Included | All four executed with actual Anima weights; original mutual exclusions retained |
| SD IP-Adapter / native FLUX, Krea, MOSS references | Included | Native integrations; trained-checkpoint generation not validated here |
| Image → 3D | Included | SAM 3D Body; actual single-person inference and editor import |
| Detailer: SEGM / BBOX / SAM | Included | Forge masked img2img; actual YOLO + SAM execution |
| WD / PixAI taggers | Included | Actual local inference; optional dependencies |
| Local-folder detailer | Included | Explicit input/output paths; one small batch executed |
| Progressive resolution | Included | Native solver sigma slices / latent resizing; actual Anima execution |
| Literal text regions / layout selection | Included | Slot kind, MOSS native JSON selection and regional routes |
| NovelAI weighting syntax | Included | Original prompt syntax conversion |
| RS NAI / ComfyUI context interoperability | Metadata bridge | Original RS/NAI PNG/JSON import and NAI-compatible export; no graph executor in Forge |
| Native PNG / preset restoration | Included | Advanced state, masks, body parts, LoRAs, scene, seeds and schedule |
| App Mode / node graph | Omitted by request | Floating Forge forms |
| SD1.5 / SDXL / FLUX1 / FLUX2 / Krea 2 / MOSS | Native execution paths | Seven families including Anima passed small random-weight forward/cleanup checks |
| FLUX3 | Source route retained | Tested Forge revision has no native Flux3 implementation; unavailable there |
| Quantized/GGUF models | Conditional on host | Generic layer hooks retained; quantizer/device combinations unverified. Nunchaku rejected |
| txt2img / img2img / Hires.fix | Forge integration | a5 actual generation retained; progressive path is txt2img only |

Masks and pose controls guide generation; they do not guarantee exact people, text, anatomy, contact or identity. Every feature combination has not been tested. See [validation](validation.md) and [advanced setup](advanced.md).
