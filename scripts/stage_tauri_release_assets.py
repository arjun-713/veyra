"""Copy only final Tauri installers into a clean per-platform artifact directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

INSTALLER_SUFFIXES = {
    "deb": ".deb",
    "rpm": ".rpm",
    "appimage": ".appimage",
    "nsis": ".exe",
    "dmg": ".dmg",
}


def stage_installers(bundle_root: Path, output: Path, bundles: list[str]) -> list[Path]:
    bundle_root = bundle_root.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(f"release staging directory is not empty: {output}")
    staged: list[Path] = []

    for bundle in bundles:
        suffix = INSTALLER_SUFFIXES.get(bundle)
        if suffix is None:
            raise ValueError(f"unsupported Tauri bundle type: {bundle}")
        candidates = [
            path
            for path in bundle_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() == suffix
            and (bundle != "nsis" or path.name.lower().endswith("-setup.exe"))
        ]
        if not candidates:
            raise FileNotFoundError(f"no {bundle} installer found under {bundle_root}")
        for source in sorted(candidates):
            destination = output / source.name
            if destination.exists():
                raise ValueError(f"duplicate installer filename: {source.name}")
            shutil.copy2(source, destination)
            staged.append(destination)

    return staged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--bundles", required=True, help="Comma-separated Tauri bundle types"
    )
    args = parser.parse_args()
    staged = stage_installers(
        args.bundle_root,
        args.output,
        [item.strip().lower() for item in args.bundles.split(",") if item.strip()],
    )
    for path in staged:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
