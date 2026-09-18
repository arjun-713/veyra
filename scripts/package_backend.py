#!/usr/bin/env python3
"""Create and verify the allowlisted backend directory consumed by the desktop shell packagers (Tauri staging; formerly Electron Forge)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

PACKAGE_ROOTS = ("runtime", "viewer", "benchmarks", "perception", "datasets", "configs")
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
FORBIDDEN_ASSET_SUFFIXES = {
    ".bin",
    ".label",
    ".pcd",
    ".ply",
    ".las",
    ".laz",
    ".bag",
    ".db3",
    ".mcap",
    ".onnx",
    ".engine",
    ".pt",
    ".pth",
    ".ckpt",
}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except ValueError:
        return False


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    reject_assets: bool = False,
    materialize_internal_links: bool = False,
) -> None:
    if not source.is_dir():
        raise ValueError(f"required backend source is missing: {source}")
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if item.is_symlink():
            if not materialize_internal_links:
                raise ValueError(f"backend inputs may not contain symlinks: {item}")
            resolved = item.resolve(strict=True)
            if not _inside(resolved, source):
                raise ValueError(f"Python runtime symlink escapes its root: {item}")
            if resolved.is_dir():
                # Standard venvs use lib64 -> lib. The real lib directory is
                # copied independently, so duplicating it would only inflate
                # every package.
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, target)
            continue
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.suffix not in IGNORED_SUFFIXES:
            if reject_assets and item.suffix.lower() in FORBIDDEN_ASSET_SUFFIXES:
                raise ValueError(f"dataset/model asset is forbidden in package: {item}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_relative(platform: str) -> Path:
    return Path("python.exe") if platform == "win32" else Path("bin/python3")


def _source_python(root: Path, platform: str) -> Path:
    candidates = (
        (root / "python.exe", root / "Scripts" / "python.exe")
        if platform == "win32"
        else (root / "bin" / "python3",)
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _venv_base_root(runtime: Path, platform: str) -> Path | None:
    config = runtime / "pyvenv.cfg"
    if not config.is_file():
        return None
    values = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip().lower()] = value.strip()
    if not values.get("home"):
        raise ValueError("Python virtual environment does not declare its base home")
    home = Path(values["home"]).expanduser().resolve(strict=True)
    if platform != "win32" and home.name == "bin":
        home = home.parent
    if not _source_python(home, platform).is_file():
        raise ValueError(f"Python base runtime is missing an executable: {home}")
    return home


def _copy_python_runtime(runtime: Path, destination: Path, platform: str) -> None:
    base = _venv_base_root(runtime, platform)
    if base is None:
        _copy_tree(runtime, destination, materialize_internal_links=True)
        return

    # System-created virtual environments commonly point at /usr or
    # /usr/local. Copying that entire tree is both unsafe (it contains links
    # outside the runtime) and needlessly enormous. Copy only the interpreter
    # standard library plus the venv's installed site-packages; the native
    # interpreter dependencies remain ordinary OS package dependencies.
    if platform != "win32" and base in {Path("/usr"), Path("/usr/local")}:
        source_python = _source_python(runtime, platform).resolve(strict=True)
        paths = json.loads(
            subprocess.check_output(
                [
                    str(source_python),
                    "-c",
                    (
                        "import json,sysconfig; "
                        "print(json.dumps({'stdlib': sysconfig.get_path('stdlib'), "
                        "'version': f'{sysconfig.get_python_version()}', "
                        "'platlibdir': sysconfig.get_config_var('platlibdir') or 'lib'}))"
                    ),
                ],
                text=True,
            )
        )
        stdlib = Path(paths["stdlib"]).resolve(strict=True)
        python_lib = destination / paths["platlibdir"] / f"python{paths['version']}"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_python, destination / "bin" / "python3")
        _copy_tree(
            stdlib,
            python_lib,
            materialize_internal_links=True,
        )
        for packages in sorted(
            path for path in runtime.rglob("site-packages") if path.is_dir()
        ):
            _copy_tree(
                packages,
                python_lib / "site-packages",
                materialize_internal_links=True,
            )
        return

    # A venv is not relocatable: pyvenv.cfg points at the machine that created
    # it. Flatten the base interpreter into the package and overlay only the
    # installed site-packages so the result has no dependency on that path.
    _copy_tree(base, destination, materialize_internal_links=True)
    site_packages = sorted(
        path for path in runtime.rglob("site-packages") if path.is_dir()
    )
    if not site_packages:
        raise ValueError("Python virtual environment has no site-packages directory")
    for packages in site_packages:
        relative = packages.relative_to(runtime)
        _copy_tree(
            packages,
            destination / relative,
            materialize_internal_links=True,
        )


def stage_backend(
    repo: Path,
    output: Path,
    mapper: Path,
    python_runtime: Path,
    platform: str,
    arch: str,
) -> Path:
    repo, mapper, python_runtime, output = map(
        lambda value: Path(value).resolve(), (repo, mapper, python_runtime, output)
    )
    if platform not in {"linux", "darwin", "win32"}:
        raise ValueError("unsupported release platform")
    if arch not in {"x64", "arm64"}:
        raise ValueError("unsupported release architecture")
    if not mapper.is_file() or not _inside(mapper, repo):
        raise ValueError("mapper must be a built file inside the repository")
    python_executable = _source_python(python_runtime, platform)
    if not python_executable.is_file():
        raise ValueError(f"Python runtime is missing {python_executable}")
    if output == repo or repo in output.parents:
        raise ValueError("staging output must be outside the repository")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for name in PACKAGE_ROOTS:
        _copy_tree(repo / name, output / name, reject_assets=True)
    _copy_python_runtime(python_runtime, output / "python", platform)
    normalized_python = output / "python" / _python_relative(platform)
    if not normalized_python.exists():
        shutil.copy2(python_executable, normalized_python)
    binary_name = "veyra_runtime.exe" if platform == "win32" else "veyra_runtime"
    (output / "bin").mkdir()
    shutil.copy2(mapper, output / "bin" / binary_name)
    files = {
        path.relative_to(output).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": _digest(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "platform": platform,
        "arch": arch,
        "files": files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_backend(output, platform)
    return output


def verify_backend(root: Path, platform: str | None = None) -> dict:
    root = Path(root).resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("files"), dict
    ):
        raise ValueError("unsupported backend manifest")
    if platform is not None and manifest.get("platform") != platform:
        raise ValueError("backend platform does not match package platform")
    required = [
        Path("bin")
        / ("veyra_runtime.exe" if manifest["platform"] == "win32" else "veyra_runtime"),
        Path("python") / _python_relative(manifest["platform"]),
        Path("runtime/__main__.py"),
    ]
    for relative in required:
        if not (root / relative).is_file():
            raise ValueError(f"backend is missing {relative.as_posix()}")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("manifest contains an unsafe path")
        file = root / relative
        if not file.is_file() or file.stat().st_size != expected.get("bytes"):
            raise ValueError(f"backend file is missing or changed: {name}")
        if _digest(file) != expected.get("sha256"):
            raise ValueError(f"backend checksum failed: {name}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapper", type=Path, required=True)
    parser.add_argument("--python-runtime", type=Path, required=True)
    parser.add_argument(
        "--platform", choices=("linux", "darwin", "win32"), required=True
    )
    parser.add_argument("--arch", choices=("x64", "arm64"), required=True)
    args = parser.parse_args()
    stage_backend(
        args.repo,
        args.output,
        args.mapper,
        args.python_runtime,
        args.platform,
        args.arch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
