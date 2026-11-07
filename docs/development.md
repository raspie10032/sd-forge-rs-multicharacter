# Development

The panel assembles the original BuildPipe / Finalize / CharacterPipe and installs an execution-local Forge UnetPatcher wrapper.

- shared/: original character/region/pose/reference/detailer/tagger modules, with documented host-import adaptations.
- routing.py: original attention/schedule code with Forge Krea latent-reference compatibility.
- geometry.py / shared_lora.py: original masks and Normal-mode algebra adapted to Forge.
- native_runtime.py / lora.py / adapter_delta.py / anima_math.py: native model calls, scoped hooks, native adapter deltas and compatible Anima math.
- ui.py / api.py / javascript/ / web/: Forge forms, previews, pose API and presentation adapter.

## Local checks

Use a separate development environment, not an existing Forge installation.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tools/verify_sources.py
.venv/bin/ruff check .
GRADIO_ANALYTICS_ENABLED=False .venv/bin/python -m pytest -q
node --check javascript/rs_multicharacter.js
node --check javascript/rs_features.js
node --check rs_forge_mc/web/pose-adapter.js
```

GitHub Actions runs these CPU checks. It does not download weights or run real-checkpoint WebUI experiments.

## Native backend and ComfyUI comparison

From an environment with the tested Forge dependencies:

```bash
python tools/validate_native.py /path/to/forge-neo --cpu --report native.json
```

This uses native model classes with random small weights and tests both modes, spatial changes and restoration. validate_webui.py runs actual generation through an already-running Forge API; inspect --help and supply two installed LoRA names. It does not start Forge or download weights. Browser UI/3D interactions require separate checks.

validate_comfy_parity.py compares original ComfyUI and Forge calculations; see --help for tiny and captured-real modes. capture_parity.py captures a model call for local replay. Captures contain learned weights and potentially private encoded prompts; do not include them in repository/release files.

## Rebuild the editor

The shipped bundle/rig works without Node or external CDNs. Included JS source can be rebuilt:

```bash
cd tools/pose3d
npm ci
npm run build
```

Three.js 0.170.0 / esbuild 0.25.12 are locked. Deliberate source changes require reviewing results and updating manifest hashes. Preserve notices.

## Source provenance

rs_forge_mc/shared/source-manifest.json records SHA-256 hashes of copied modules, editor assets and routing.py. The installed snapshot includes local pose-import/library work newer than inspected public source commit 721d57ab98e80dc6854d4f49758bc9c456bb925c; this is a reference commit, not an exact snapshot revision.

The previously recorded 5cc4b870094c89090db54bd8d12649dcaf89f2ba is the enclosing ComfyUI checkout's revision, not the extension's. It is retained only as comfy_revision. Per-file hashes identify copied content.


0.2 adds `features.py`, `advanced_ui.py`, `references.py`, `learned_pose.py`, `progressive.py`, `detail.py`, `folder_detail.py`, `assets.py`, and an adapted SAM 3D Body runtime. Optional weights/dependencies are loaded only on selected feature paths. `source-manifest.json` retains original hashes and separately records adapted hashes; it does not label modified modules as byte-identical upstream files.
