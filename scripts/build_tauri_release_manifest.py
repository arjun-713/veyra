"""Create one release manifest for the curated cross-platform installer assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT_DIR = re.compile(r"^veyra-tauri-(linux|win32|darwin)-(x64|arm64)$")
PLATFORM_SUFFIXES = {
    "linux": (".deb", ".rpm", ".appimage"),
    "win32": ("-setup.exe",),
    "darwin": (".dmg",),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    root: Path, version: str, *, require_complete: bool = False
) -> dict[str, object]:
    root = root.resolve(strict=True)
    artifacts: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        match = ARTIFACT_DIR.fullmatch(directory.name)
        if not match:
            raise ValueError(f"unexpected artifact directory: {directory.name}")
        platform_name, architecture = match.groups()
        for path in sorted(item for item in directory.iterdir() if item.is_file()):
            filename_lower = path.name.lower()
            if not any(
                filename_lower.endswith(suffix)
                for suffix in PLATFORM_SUFFIXES[platform_name]
            ):
                raise ValueError(f"non-installer in release artifact: {path.name}")
            if path.name in seen_names:
                raise ValueError(f"duplicate release asset filename: {path.name}")
            seen_names.add(path.name)
            artifacts.append(
                {
                    "platform": platform_name,
                    "architecture": architecture,
                    "filename": path.name,
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    if not artifacts:
        raise ValueError("no Tauri installer assets were found")
    if require_complete:
        required = {
            ("linux", "x64", ".deb"),
            ("linux", "x64", ".rpm"),
            ("linux", "x64", ".appimage"),
            ("win32", "x64", ".exe"),
            ("darwin", "arm64", ".dmg"),
            ("darwin", "x64", ".dmg"),
        }
        found = {
            (
                item["platform"],
                item["architecture"],
                Path(item["filename"]).suffix.lower(),
            )
            for item in artifacts
        }
        if missing := required - found:
            raise ValueError(f"incomplete native release; missing: {sorted(missing)}")
    return {
        "schema_version": 1,
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }


def stage_release(
    root: Path, output: Path, version: str, *, require_complete: bool = False
) -> Path:
    root = root.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(f"release output directory is not empty: {output}")
    manifest = build_manifest(root, version, require_complete=require_complete)
    for artifact in manifest["artifacts"]:
        source = (
            root
            / f"veyra-tauri-{artifact['platform']}-{artifact['architecture']}"
            / str(artifact["filename"])
        )
        destination = output / str(artifact["filename"])
        if destination.exists():
            raise ValueError(f"duplicate release asset filename: {destination.name}")
        shutil.copy2(source, destination)
    path = output / "release-manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    print(
        stage_release(
            args.root, args.output, args.version, require_complete=args.require_complete
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
