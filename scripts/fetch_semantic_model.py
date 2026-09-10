"""Fetch the pinned, checksum-verified public SalsaNext asset into ignored data.

Run from repository root: python -m scripts.fetch_semantic_model
No archive code is executed and only manifest-listed files are extracted.
"""

import hashlib
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def fetch(destination: Path, manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text())
    destination.mkdir(parents=True, exist_ok=True)
    files = manifest["files"]
    if all(
        (destination / name).is_file()
        and hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
        for name, digest in files.items()
    ):
        return destination / manifest["model"]
    with tempfile.TemporaryDirectory(prefix="veyra-model-") as directory:
        archive = Path(directory) / "model.zip"
        with (
            urllib.request.urlopen(manifest["url"], timeout=60) as response,
            archive.open("wb") as output,
        ):
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > manifest["size_bytes"]:
                    raise ValueError("model exceeds declared download size")
                output.write(block)
        if (
            size != manifest["size_bytes"]
            or hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]
        ):
            raise ValueError("model archive checksum/size mismatch")
        with zipfile.ZipFile(archive) as source:
            verified = {}
            for name, digest in files.items():
                target = destination / name
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError("unsafe model member path")
                info = source.getinfo(name)
                if info.file_size > 64 * 1024 * 1024:
                    raise ValueError("model member exceeds size limit")
                content = source.read(name)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError(f"model member checksum mismatch: {name}")
                verified[target] = content
            for target, content in verified.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    return destination / manifest["model"]


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    print(fetch(repo / "data/cache/models", repo / "configs/salsanext-model.json"))
