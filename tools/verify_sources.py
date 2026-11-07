#!/usr/bin/env python3
"""Verify the bundled original RS modules and editor assets, without Forge."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "rs_forge_mc" / "shared"
    manifest = json.loads((directory / "source-manifest.json").read_text(encoding="utf-8"))
    failures = []
    count = adapted = 0
    overrides = manifest.get("forge_adaptations", {})
    for group in ("files", "web_assets", "extension_files"):
        parent = root if group == "extension_files" else directory
        for name, expected in manifest[group].items():
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if relative in overrides:
                expected = overrides[relative]["sha256"]
                adapted += 1
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                failures.append(name)
            count += 1
    if failures:
        raise SystemExit("Source verification failed: " + ", ".join(failures))
    for name, expected in manifest.get("additional_sources", {}).items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name)
        count += 1
    if failures:
        raise SystemExit("Source verification failed: " + ", ".join(failures))
    print(f"Verified {count} bundled source/assets ({adapted} documented Forge adaptations).")


if __name__ == "__main__":
    main()
