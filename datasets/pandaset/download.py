"""Fetch selected PandaSet sequences without downloading the whole archive.

The public Hugging Face mirror (``georghess/pandaset``, CC BY 4.0) is a single
~44.5 GB ZIP. This tool reads the archive's central directory with HTTP range
requests and extracts only the requested sequences and subdirectories, so a
labelled sequence costs ~330 MB instead of the full archive.

Stdlib only. Existing files with the expected size are skipped, so an
interrupted download can be resumed by re-running the same command.

    python -m datasets.pandaset.download --root data/raw/pandaset/raw \
        --sequences 001 027 --parts lidar annotations/semseg meta
    python -m datasets.pandaset.download --list-labelled
"""

from __future__ import annotations

import argparse
import http.client
import struct
import sys
import time
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ARCHIVE_URL = (
    "https://huggingface.co/datasets/georghess/pandaset/resolve/main/pandaset.zip"
)
DEFAULT_PARTS = ("lidar", "annotations/semseg", "meta")
_TIMEOUT_S = 120


@dataclass(frozen=True)
class Entry:
    name: str
    method: int
    compressed_size: int
    size: int
    header_offset: int


def _range(url: str, start: int, end: int, attempts: int = 6) -> bytes:
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                if response.status != 206:
                    raise RuntimeError(
                        f"server ignored range request (HTTP {response.status})"
                    )
                data = response.read()
            if len(data) != end - start + 1:
                raise http.client.IncompleteRead(data, end - start + 1 - len(data))
            return data
        except (OSError, http.client.HTTPException):
            # Mirror/CDN connections drop mid-transfer; back off and retry.
            if attempt == attempts - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _archive_size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        return int(response.headers["Content-Length"])


def read_central_directory(url: str = ARCHIVE_URL) -> list[Entry]:
    size = _archive_size(url)
    tail = _range(url, max(0, size - 65536), size - 1)
    zip64 = tail.rfind(b"PK\x06\x06")
    if zip64 >= 0:
        cd_size, cd_offset = struct.unpack("<QQ", tail[zip64 + 40 : zip64 + 56])
    else:
        eocd = tail.rfind(b"PK\x05\x06")
        if eocd < 0:
            raise RuntimeError("ZIP end-of-central-directory record not found")
        cd_size, cd_offset = struct.unpack("<II", tail[eocd + 12 : eocd + 20])
    data = _range(url, cd_offset, cd_offset + cd_size - 1)
    entries: list[Entry] = []
    pos = 0
    while pos < len(data) and data[pos : pos + 4] == b"PK\x01\x02":
        (method,) = struct.unpack("<H", data[pos + 10 : pos + 12])
        csize, usize = struct.unpack("<II", data[pos + 20 : pos + 28])
        name_len, extra_len, comment_len = struct.unpack(
            "<HHH", data[pos + 28 : pos + 34]
        )
        (offset,) = struct.unpack("<I", data[pos + 42 : pos + 46])
        name = data[pos + 46 : pos + 46 + name_len].decode("utf-8")
        extra = data[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        cursor = 0
        while cursor + 4 <= len(extra):
            header_id, length = struct.unpack("<HH", extra[cursor : cursor + 4])
            if header_id == 1:  # ZIP64 extended information, in fixed field order
                field = extra[cursor + 4 : cursor + 4 + length]
                read = 0
                if usize == 0xFFFFFFFF:
                    (usize,) = struct.unpack("<Q", field[read : read + 8])
                    read += 8
                if csize == 0xFFFFFFFF:
                    (csize,) = struct.unpack("<Q", field[read : read + 8])
                    read += 8
                if offset == 0xFFFFFFFF:
                    (offset,) = struct.unpack("<Q", field[read : read + 8])
            cursor += 4 + length
        entries.append(Entry(name, method, csize, usize, offset))
        pos += 46 + name_len + extra_len + comment_len
    return entries


def labelled_sequences(entries: list[Entry]) -> list[str]:
    return sorted(
        {
            e.name.split("/")[1]
            for e in entries
            if e.name.count("/") >= 4
            and e.name.split("/")[2:4] == ["annotations", "semseg"]
        }
    )


def _extract(url: str, entry: Entry, destination: Path) -> int:
    if destination.is_file() and destination.stat().st_size == entry.size:
        return 0
    header = _range(url, entry.header_offset, entry.header_offset + 29)
    if header[:4] != b"PK\x03\x04":
        raise RuntimeError(f"bad local header for {entry.name}")
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    start = entry.header_offset + 30 + name_len + extra_len
    raw = _range(url, start, start + entry.compressed_size - 1)
    if entry.method == 0:
        payload = raw
    elif entry.method == 8:
        payload = zlib.decompress(raw, -zlib.MAX_WBITS)
    else:
        raise RuntimeError(f"unsupported ZIP method {entry.method} for {entry.name}")
    if len(payload) != entry.size:
        raise RuntimeError(f"size mismatch for {entry.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.write_bytes(payload)
    partial.replace(destination)
    return len(payload)


def download(
    root: Path,
    sequences: list[str],
    parts: tuple[str, ...] = DEFAULT_PARTS,
    url: str = ARCHIVE_URL,
    workers: int = 8,
) -> None:
    entries = read_central_directory(url)
    available = set(e.name.split("/")[1] for e in entries if e.name.count("/") >= 2)
    missing = [s for s in sequences if s not in available]
    if missing:
        raise SystemExit(f"unknown PandaSet sequences: {', '.join(missing)}")
    wanted = [
        e
        for e in entries
        if not e.name.endswith("/")
        and e.name.count("/") >= 3
        and e.name.split("/")[1] in sequences
        and any(
            ("/".join(e.name.split("/")[2:]) + "/").startswith(p + "/") for p in parts
        )
    ]
    total = sum(e.size for e in wanted)
    print(f"{len(wanted)} files, {total / 1e6:.0f} MB -> {root}", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_extract, url, e, root / Path(*e.name.split("/")[1:]))
            for e in wanted
        ]
        for index, future in enumerate(futures, 1):
            done += future.result()
            if index % 50 == 0 or index == len(futures):
                print(
                    f"  {index}/{len(futures)} files, {done / 1e6:.0f} MB fetched",
                    flush=True,
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path("data/raw/pandaset/raw"))
    parser.add_argument("--sequences", nargs="*", default=[])
    parser.add_argument("--parts", nargs="*", default=list(DEFAULT_PARTS))
    parser.add_argument("--url", default=ARCHIVE_URL)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--list-labelled", action="store_true")
    args = parser.parse_args(argv)
    if args.list_labelled:
        print(" ".join(labelled_sequences(read_central_directory(args.url))))
        return 0
    if not args.sequences:
        parser.error("--sequences is required (see --list-labelled)")
    download(args.root, args.sequences, tuple(args.parts), args.url, args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
