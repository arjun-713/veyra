"""Verify a relocated release backend, without importing from the source tree."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.protocol import read_message
from scripts.package_backend import verify_backend


def validate_runtime_output(data: bytes) -> dict:
    stream = io.BytesIO(data)
    result = None
    while stream.tell() < len(data):
        metadata, _ = read_message(stream)
        if metadata.get("type") == "response" and metadata.get("id") == "release-smoke":
            if metadata.get("ok") is not True:
                raise ValueError(
                    f"packaged runtime rejected status: {metadata.get('error')}"
                )
            result = metadata.get("result")
            if (
                not isinstance(result, dict)
                or result.get("error")
                or result.get("state") != "unconfigured"
            ):
                raise ValueError(f"packaged runtime is not healthy: {result}")
    if result is None:
        raise ValueError("packaged runtime did not answer the status request")
    return result


def smoke_backend(root: Path) -> None:
    manifest = verify_backend(root)
    platform = manifest["platform"]
    with tempfile.TemporaryDirectory(prefix="veyra relocated backend ") as temporary:
        backend = Path(temporary) / "backend"
        shutil.copytree(root, backend)
        python = (
            backend
            / "python"
            / ("python.exe" if platform == "win32" else "bin/python3")
        )
        env = dict(os.environ)
        env.update(
            PYTHONHOME=str(backend / "python"),
            PYTHONPATH=str(backend),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONNOUSERSITE="1",
        )
        # Import the shipped dependencies and actually start the native mapper.
        # Intel macOS currently has no supported Patchwork++ wheel.
        imports = "import numpy, scipy, yaml, onnxruntime; "
        if not (platform == "darwin" and manifest["arch"] == "x64"):
            imports += "import pypatchworkpp; "
        probe = (
            imports
            + """
import sys
from pathlib import Path
from viewer.runtime import PersistentMapEngine
root = Path.cwd()
mapper = root / 'bin' / ('veyra_runtime.exe' if sys.platform == 'win32' else 'veyra_runtime')
engine = PersistentMapEngine(mapper, transport='binary')
try:
    status = engine.status()
    if status.get('status') != 'available':
        raise RuntimeError(f'packaged mapper unavailable: {status}')
finally:
    engine.close()
"""
        )
        subprocess.run(
            [str(python), "-B", "-s", "-c", probe],
            cwd=backend,
            env=env,
            check=True,
            timeout=60,
        )
        response = subprocess.run(
            [str(python), "-B", "-s", "-u", "-m", "runtime", "--repo", str(backend)],
            input=b'{"id":"release-smoke","command":"status","args":{}}\n',
            cwd=backend,
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        validate_runtime_output(response.stdout)
    print(
        json.dumps(
            {
                "status": "pass",
                "platform": platform,
                "arch": manifest["arch"],
                "version": manifest["version"],
                "source": manifest.get("source"),
            }
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    args = parser.parse_args()
    smoke_backend(args.backend.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
