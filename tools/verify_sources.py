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
    count = 0
    for group in ("files", "web_assets", "extension_files"):
        parent = root if group == "extension_files" else directory
        for name, expected in manifest[group].items():
            path = parent / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                failures.append(name)
            count += 1
    if failures:
        raise SystemExit("Source verification failed: " + ", ".join(failures))
    print(f"Verified {count} original RS source files and editor assets.")


if __name__ == "__main__":
    main()
