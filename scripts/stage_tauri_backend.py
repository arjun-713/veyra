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


def _default_benchmark(repo: Path, platform: str) -> Path | None:
    """Locate a dev-built benchmark binary so restages never silently drop it.

    Forgetting ``--benchmark`` previously produced packages whose Benchmarks
    screen failed with ``Errno 2``. Auto-discovery keeps the flag as an
    explicit override while making the common layout work by default.
    """
    suffix = ".exe" if platform == "win32" else ""
    candidates = (
        repo / "build" / "apps" / "benchmark" / f"veyra_benchmark{suffix}",
        repo / "build" / "apps" / "benchmark" / "Release" / f"veyra_benchmark{suffix}",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def stage(
    repo: Path,
    output: Path,
    mapper: Path,
    python_runtime: Path,
    platform: str,
    arch: str,
    benchmark: Path | None = None,
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
                benchmark,
            )
            if output.exists():
                shutil.rmtree(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged, output)
    else:
        stage_backend(repo, output, mapper, python_runtime, platform, arch, benchmark)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("src-tauri/resources/backend")
    )
    parser.add_argument("--mapper", type=Path, required=True)
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=None,
        help=(
            "Optional veyra_benchmark executable staged to bin/ for packaged "
            "benchmarks. When omitted, the repo dev build output is used when "
            "present."
        ),
    )
    parser.add_argument("--python-runtime", type=Path, required=True)
    parser.add_argument(
        "--platform", choices=("linux", "darwin", "win32"), required=True
    )
    parser.add_argument("--arch", choices=("x64", "arm64"), required=True)
    args = parser.parse_args()
    benchmark = args.benchmark
    if benchmark is None:
        benchmark = _default_benchmark(args.repo, args.platform)
        if benchmark is not None:
            print(f"using dev-built benchmark binary: {benchmark}")
    print(
        stage(
            args.repo,
            args.output,
            args.mapper,
            args.python_runtime,
            args.platform,
            args.arch,
            benchmark,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
