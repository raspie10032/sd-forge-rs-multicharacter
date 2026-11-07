# Third-party source and assets

The extension is GPL-3.0-only; see [COPYING](COPYING). Original modules/editor sources and adapted algorithms come from [ComfyUI RS MultiCharacter Sampler](https://github.com/raspie10032/ComfyUI_RS_MultiCharacter_Sampler). Copied-file hashes are recorded in the [source manifest](rs_forge_mc/shared/source-manifest.json).

- **Three.js 0.170.0**, MIT. [License](rs_forge_mc/shared/web/pose3d/THREE-LICENSE.txt).
- **MHR / Momentum Human Rig**, Copyright Meta Platforms, Inc. and affiliates, Apache-2.0. Baked adult LOD1 preset from toyxyz/ComfyUI_toyxyz_test_nodes revision 8291d9b65d56d65be55ee0f31df073d42b7d0eb6. RS retains the native mesh, bind transforms, four skin weights and procedural rotations; facial-landmark and shape/inference metadata were removed. Neural pose correctives are not implemented. [Notice](rs_forge_mc/shared/web/pose3d/MHR-NOTICE.txt) · [License](rs_forge_mc/shared/web/pose3d/MHR-LICENSE.txt).

No SAM model or landmark mapping, Anima checkpoint, text encoder, VAE or LoRA weights are distributed. MHR's body asset is a baked mesh/rig, not an inference model.

Additional inference code is adapted from the installed [ComfyUI](https://github.com/comfyanonymous/ComfyUI) source under GPL-3.0: `comfy/ldm/sam3d_body/`, `comfy_extras/sam3d_body/utils.py`, `comfy/ldm/anima/lllite.py` and small SAM execution helpers. Forge imports/device handling replace Comfy host APIs. File hashes and adaptations are recorded in the source manifest. No SAM 3D Body weights are bundled. Downloaded detector/tagger/adapter weights retain their authors' separate licenses and are not part of this source release. Optional Ultralytics dependencies have their own licensing terms.

License texts for optional upstream components are included as [SAM 3D Body license](SAM-3D-BODY-LICENSE), [Anima Role K/V code license](ANIMA-ROLE-KV-CODE-LICENSE), and [Krea 2 pose-adapter license](KREA2-POSE-LICENSE). Model weights remain separately downloaded under their own licenses.
