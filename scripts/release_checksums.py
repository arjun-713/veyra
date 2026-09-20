#!/usr/bin/env python3
"""Write deterministic SHA-256 sums for release files."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_checksums(root: Path, output_name: str = "SHA256SUMS") -> Path:
    root = Path(root).resolve(strict=True)
    output = root / output_name
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and path != output
    )
    output.write_text(
        "".join(
            f"{_digest(path)}  {path.relative_to(root).as_posix()}\n" for path in files
        ),
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(write_checksums(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
