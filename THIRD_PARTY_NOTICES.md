# Third-party source and assets

The extension is GPL-3.0-only; see [COPYING](COPYING). Original modules/editor sources and adapted algorithms come from [ComfyUI RS MultiCharacter Sampler](https://github.com/raspie10032/ComfyUI_RS_MultiCharacter_Sampler). Copied-file hashes are recorded in the [source manifest](rs_forge_mc/shared/source-manifest.json).

- **Three.js 0.170.0**, MIT. [License](rs_forge_mc/shared/web/pose3d/THREE-LICENSE.txt).
- **MHR / Momentum Human Rig**, Copyright Meta Platforms, Inc. and affiliates, Apache-2.0. Baked adult LOD1 preset from toyxyz/ComfyUI_toyxyz_test_nodes revision 8291d9b65d56d65be55ee0f31df073d42b7d0eb6. RS retains the native mesh, bind transforms, four skin weights and procedural rotations; facial-landmark and shape/inference metadata were removed. Neural pose correctives are not implemented. [Notice](rs_forge_mc/shared/web/pose3d/MHR-NOTICE.txt) · [License](rs_forge_mc/shared/web/pose3d/MHR-LICENSE.txt).

No SAM model or landmark mapping, Anima checkpoint, text encoder, VAE or LoRA weights are distributed. MHR's body asset is a baked mesh/rig, not an inference model.
