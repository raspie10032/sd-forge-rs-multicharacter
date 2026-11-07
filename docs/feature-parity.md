# ComfyUI → Forge feature comparison / 기능 비교

Audited 2026-11-07 against the installed ComfyUI RS MultiCharacter Sampler source. Forge version: `0.1.0a5`. **App Mode is not the only omitted feature.**

| Original capability / 원본 기능 | Forge status / 상태 | Scope / 범위 |
| --- | --- | --- |
| Shared scene and numbered character prompts | Included | Up to 10 slots; actual count is model-dependent |
| Character-specific negative prompts | Not ported | Use the shared Forge Negative field |
| Character pipeline assembly and validation | Reused | Original BuildPipe / Finalize / CharacterPipe; Gradio presentation |
| Point / Box placement | Included | Original overlap priority and edge smoothing |
| Regional cross-attention / self-attention separation | Included | Original routing and schedule |
| Character model/text encoder LoRA strengths | Included | Floating-point plain linear LoRA factors only |
| Normal / Precision | Included | Original algebra; layer-layout fallback recorded |
| LoCon, DoRA, LoHa, LoKr, GLoRA, OFT, IA³, diff/set, etc. | Not ported | Original supports more adapter formats |
| GGUF / native quantization interoperability | Outside support scope | Original loader/adapter coverage is not claimed |
| 3D joint / finger / mannequin editing | Included | Original assets plus Forge presentation adapter |
| 3D camera, full/visible silhouette regions | Included | Mask projection; not camera conditioning |
| Body-part prompt masks / emphasis | Not ported | Current 3D path supplies whole-character silhouettes |
| Pose library save / random / JSON export | Included | Forge models/rs_pose3d/ |
| JSON / OpenPose / DWPose / Yu Zhu / named BVH / ZIP import | Included via 3D editor | 2D input cannot recover true depth |
| Arbitrary painted numbered masks / external masks | Not ported | Custom-mask UI currently uses 3D silhouettes |
| Dedicated interaction controls | Not ported | Actions can be written in prompt text |
| Dedicated camera conditioning | Not ported | Separate from orbit/FOV in 3D editor |
| Learned Anima pose adapter | Not ported | Silhouettes do not provide learned joint conditioning |
| Character image reference, including v2 | Not ported | Forge Anima reference rejected while enabled |
| Image → 3D body estimation | Not ported | Disabled; manual editing/import available |
| Detailer / segmentation / folder correction | Not ported | Original detector-based correction absent |
| Tagger and detection loaders | Not ported | No Forge adapters |
| Progressive-resolution sampler | Not ported | Forge Hires.fix is a separate tested feature |
| Text regions / layout tools | Not ported | Current slots are character prompts |
| RS NAI / context pipe interoperability | Not ported | Forge JSON does not replace node pipes |
| App Mode / graph UI | Not ported | Floating Forge character forms |
| Generation metadata and restoration | Forge equivalent | parameters + RS JSON; PNG Info / prompt-drop + restore / presets |
| ComfyUI workflow embedding/loading | Not included | No graph in Forge PNGs |
| SDXL/Illustrious, FLUX, Krea 2, MOSS, SD1.5 | Not ported | Current release targets Anima |
| txt2img / img2img / Hires.fix | Forge integration | Actual checkpoint generation tested |

“Included” identifies an implemented path, not every combination or guaranteed model output. See [validation](validation.md).
