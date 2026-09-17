#!/usr/bin/env python3
"""Write machine-readable release metadata for website download links."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_manifest(root: Path, output: Path, version: str, target: str) -> Path:
    root = root.resolve(strict=True)
    output = output.resolve()
    files = [
        path for path in sorted(root.rglob("*")) if path.is_file() and path != output
    ]
    manifest = {
        "schema_version": 1,
        "version": version,
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner": {"os": platform.platform(), "machine": platform.machine()},
        "artifacts": [
            {
                "platform": target.split("-")[0],
                "architecture": target.split("-")[-1],
                "filename": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": digest(path),
            }
            for path in files
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--version", default=os.environ.get("RELEASE_VERSION", "0.1.0"))
    parser.add_argument(
        "--target", default=f"{platform.system().lower()}-{platform.machine()}"
    )
    args = parser.parse_args()
    output = args.output or args.root / "release-manifest.json"
    print(write_manifest(args.root, output, args.version, args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
