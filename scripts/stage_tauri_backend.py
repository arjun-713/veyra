#!/usr/bin/env python3
"""Stage the relocatable Python/C++ backend into Tauri resources."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

# Running this file directly is the documented CI/release invocation. Ensure
# the repository root, rather than only ``scripts/``, is importable so the
# shared backend packager is found in both invocation modes.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.package_backend import stage_backend


def stage(
    repo: Path,
    output: Path,
    mapper: Path,
    python_runtime: Path,
    platform: str,
    arch: str,
) -> Path:
    repo = repo.resolve(strict=True)
    output = output.resolve()
    if repo in output.parents:
        with tempfile.TemporaryDirectory(prefix="veyra-tauri-backend-") as temporary:
            staged = stage_backend(
                repo,
                Path(temporary) / "backend",
                mapper,
                python_runtime,
                platform,
                arch,
            )
            if output.exists():
                shutil.rmtree(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged, output)
    else:
        stage_backend(repo, output, mapper, python_runtime, platform, arch)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("src-tauri/resources/backend")
    )
    parser.add_argument("--mapper", type=Path, required=True)
    parser.add_argument("--python-runtime", type=Path, required=True)
    parser.add_argument(
        "--platform", choices=("linux", "darwin", "win32"), required=True
    )
    parser.add_argument("--arch", choices=("x64", "arm64"), required=True)
    args = parser.parse_args()
    print(
        stage(
            args.repo,
            args.output,
            args.mapper,
            args.python_runtime,
            args.platform,
            args.arch,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
