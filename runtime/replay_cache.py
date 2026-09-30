"""Precomputed visualization replay cache (schema v1).

A ``*.veyra-replay`` file stores real ``pack_visualization`` outputs so demo
playback can present frames without rerunning perception or mapping:

    dataset frame -> perception -> mapper -> pack_visualization -> cache (once)
    cache -> decode -> GPU buffers -> display (every replay)

The per-frame payload layout is byte-identical to the live
``pack_visualization`` payload (17-float points, 17-float cells, optional
15-float physical layers), so the desktop viewer consumes cached frames
unchanged via the existing ``schema_version 2|3`` validation.

Single-file layout (all integers little-endian)::

    magic      8s  "VYRAREPL"
    schema     u32 (=1)
    head_len   u32
    header     head_len bytes of JSON (provenance, see PROVENANCE_KEYS)
    nframes    u32
    table      nframes * TABLE_ENTRY bytes
               each entry: frame_index u32, meta_len u32, payload_len u32,
                           meta_off u64, payload_off u64, sha256 32s
    blobs      per-frame metadata JSON bytes + payload bytes

The writer reserves the table up front (frame count is known when preparing
a sequence clip) and backfills it after streaming the blobs, so multi-GB
caches never sit fully in RAM.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import threading
import time
from pathlib import Path

MAGIC = b"VYRAREPL"
REPLAY_SCHEMA = 1
TABLE_ENTRY = struct.Struct("<IIIQQ32s")
TABLE_ENTRY_SIZE = TABLE_ENTRY.size
HEADER_STRUCT = struct.Struct("<8sII")
NFRAMES_STRUCT = struct.Struct("<I")

# Provenance keys a cache header must carry. A replay cache belongs to one
# exact policy/config; any mismatch invalidates it (fail-closed).
PROVENANCE_KEYS = (
    "replay_schema",
    "dataset",
    "sequence",
    "start",
    "count",
    "stride",
    "policy",
    "semantic_provider",
    "point_budget",
    "cell_budget",
    "perception_config_digest",
    "config_digest",
    "code_sha",
    "working_tree_dirty",
    "protocol_version",
    "viz_schema",
    "created_at",
)

MAX_META_BYTES = 1024 * 1024
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024


class ReplayError(ValueError):
    """Corrupt, truncated or incompatible replay cache."""


def code_sha(repo: Path | None = None) -> str:
    """Best-effort git SHA for provenance; ``"unknown"`` when unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo) if repo else None,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return "unknown"
    sha = (out.stdout or "").strip()
    if out.returncode == 0 and sha:
        return sha
    return "unknown"


def working_tree_dirty(repo: Path | None = None) -> bool | None:
    """True/False when git can tell, else None (never raises)."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo) if repo else None,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return None
    if out.returncode == 0:
        return bool((out.stdout or "").strip())
    return None


def digest_mapping(mapping: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            mapping, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def frame_digest(meta_bytes: bytes, payload_bytes: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(meta_bytes)
    digest.update(payload_bytes)
    return digest.digest()


def build_header(
    *,
    dataset: str,
    sequence: str,
    start: int,
    count: int,
    stride: int = 1,
    policy: str,
    semantic_provider: dict,
    point_budget: int,
    cell_budget: int,
    perception_config_digest: str | None,
    config_digest: str | None,
    repo: Path | None = None,
    protocol_version: int = 4,
    viz_schema: int = 3,
    extra: dict | None = None,
) -> dict:
    header = {
        "replay_schema": REPLAY_SCHEMA,
        "dataset": dataset,
        "sequence": sequence,
        "start": int(start),
        "count": int(count),
        "stride": int(stride),
        "policy": policy,
        "semantic_provider": dict(semantic_provider),
        "point_budget": int(point_budget),
        "cell_budget": int(cell_budget),
        "perception_config_digest": perception_config_digest,
        "config_digest": config_digest,
        "code_sha": code_sha(repo),
        "working_tree_dirty": working_tree_dirty(repo),
        "protocol_version": int(protocol_version),
        "viz_schema": int(viz_schema),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        header.update(dict(extra))
    return header


def check_compatible(
    header: dict, *, policy: str | None = None, config_digest: str | None = None
) -> str | None:
    """Return a mismatch reason, or None when the cache may be used."""
    if header.get("replay_schema") != REPLAY_SCHEMA:
        return f"unsupported replay schema {header.get('replay_schema')!r}"
    missing = [key for key in PROVENANCE_KEYS if key not in header]
    if missing:
        return f"cache header is missing provenance: {', '.join(missing)}"
    if policy is not None and header.get("policy") != policy:
        return (
            f"cache policy is {header.get('policy')!r} "
            f"but {policy!r} was requested; prepare a separate cache per policy"
        )
    if (
        config_digest is not None
        and header.get("config_digest") is not None
        and header.get("config_digest") != config_digest
    ):
        return "configuration changed since the cache was built; rebuild the replay"
    return None


class ReplayWriter:
    """Stream frames into a ``*.veyra-replay`` file with a backfilled index."""

    def __init__(self, path: str | Path, header: dict, frame_count: int):
        if frame_count <= 0:
            raise ValueError("frame count must be positive")
        missing = [key for key in PROVENANCE_KEYS if key not in header]
        if missing:
            raise ValueError(f"header is missing provenance: {', '.join(missing)}")
        self.path = Path(path)
        self.header = dict(header)
        self.frame_count = int(frame_count)
        self._written = 0
        head_bytes = json.dumps(
            self.header, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(head_bytes) > MAX_META_BYTES:
            raise ValueError("replay header exceeds size limit")
        self._stream = self.path.open("wb")
        try:
            self._stream.write(
                HEADER_STRUCT.pack(MAGIC, REPLAY_SCHEMA, len(head_bytes))
            )
            self._stream.write(head_bytes)
            self._stream.write(NFRAMES_STRUCT.pack(self.frame_count))
            self._table_off = self._stream.tell()
            self._stream.write(b"\x00" * (TABLE_ENTRY_SIZE * self.frame_count))
            self._entries: list[tuple[int, int, int, int, int, bytes]] = []
        except Exception:
            self._stream.close()
            raise

    @property
    def written(self) -> int:
        return self._written

    def add_frame(
        self,
        frame_index: int,
        metadata: dict,
        payload: bytes,
        *,
        telemetry: dict | None = None,
    ) -> int:
        """Append one frame; returns the payload bytes written."""
        if self._written >= self.frame_count:
            raise ReplayError("replay cache already holds all declared frames")
        meta = dict(metadata)
        meta["replay_frame"] = self._written
        if telemetry is not None:
            # Historical processing telemetry travels with the frame so the
            # viewer can label it RECORDED — never as a live measurement.
            meta["recorded_telemetry"] = telemetry
        meta_bytes = json.dumps(meta, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
        payload_bytes = bytes(payload)
        if len(meta_bytes) > MAX_META_BYTES:
            raise ValueError("frame metadata exceeds size limit")
        if len(payload_bytes) > MAX_PAYLOAD_BYTES:
            raise ValueError("frame payload exceeds size limit")
        meta_off = self._stream.tell()
        self._stream.write(meta_bytes)
        payload_off = self._stream.tell()
        self._stream.write(payload_bytes)
        self._entries.append(
            (
                int(frame_index),
                len(meta_bytes),
                len(payload_bytes),
                meta_off,
                payload_off,
                frame_digest(meta_bytes, payload_bytes),
            )
        )
        self._written += 1
        return len(payload_bytes)

    def close(self) -> dict:
        """Backfill the index and return a build summary."""
        if self._written != self.frame_count:
            self._stream.close()
            raise ReplayError(
                f"incomplete replay: wrote {self._written}/{self.frame_count} frames"
            )
        ordered = sorted(range(len(self._entries)), key=lambda i: self._entries[i][0])
        indices = [self._entries[i][0] for i in ordered]
        if indices != sorted(indices) or len(set(indices)) != len(indices):
            self._stream.close()
            raise ReplayError("frame indices must be unique and ordered")
        self._stream.seek(self._table_off)
        for i in ordered:
            self._stream.write(TABLE_ENTRY.pack(*self._entries[i]))
        self._stream.flush()
        self._stream.close()
        size = self.path.stat().st_size
        payload_total = sum(entry[2] for entry in self._entries)
        return {
            "path": str(self.path),
            "frames": self.frame_count,
            "bytes": size,
            "payload_bytes": payload_total,
            "avg_frame_bytes": size // max(1, self.frame_count),
        }


class ReplayReader:
    """Random-access reader over a ``*.veyra-replay`` file."""

    def __init__(self, path: str | Path, *, verify: bool = False):
        self.path = Path(path)
        if not self.path.is_file():
            raise ReplayError(f"replay cache not found: {self.path}")
        self._stream = self.path.open("rb")
        try:
            head = self._stream.read(HEADER_STRUCT.size)
            if len(head) != HEADER_STRUCT.size:
                raise ReplayError("replay cache is truncated (header)")
            magic, schema, head_len = HEADER_STRUCT.unpack(head)
            if magic != MAGIC:
                raise ReplayError("not a Veyra replay file (bad magic)")
            if schema != REPLAY_SCHEMA:
                raise ReplayError(f"unsupported replay schema {schema}")
            if head_len > MAX_META_BYTES:
                raise ReplayError("replay header exceeds size limit")
            raw = self._stream.read(head_len)
            if len(raw) != head_len:
                raise ReplayError("replay cache is truncated (provenance)")
            header = json.loads(raw)
            if not isinstance(header, dict):
                raise ReplayError("replay header must be an object")
            missing = [key for key in PROVENANCE_KEYS if key not in header]
            if missing:
                raise ReplayError(
                    f"cache header is missing provenance: {', '.join(missing)}"
                )
            count_raw = self._stream.read(NFRAMES_STRUCT.size)
            if len(count_raw) != NFRAMES_STRUCT.size:
                raise ReplayError("replay cache is truncated (frame count)")
            (count,) = NFRAMES_STRUCT.unpack(count_raw)
            table_raw = self._stream.read(TABLE_ENTRY_SIZE * count)
            if len(table_raw) != TABLE_ENTRY_SIZE * count:
                raise ReplayError("replay cache is truncated (frame index)")
            entries = [
                TABLE_ENTRY.unpack_from(table_raw, offset)
                for offset in range(0, len(table_raw), TABLE_ENTRY_SIZE)
            ]
            indices = [entry[0] for entry in entries]
            if indices != sorted(indices) or len(set(indices)) != len(indices):
                raise ReplayError("replay frame index is not ordered/unique")
            file_size = self.path.stat().st_size
            for _, meta_len, payload_len, meta_off, payload_off, _ in entries:
                if (
                    meta_len > MAX_META_BYTES
                    or payload_len > MAX_PAYLOAD_BYTES
                    or meta_off + meta_len > file_size
                    or payload_off + payload_len > file_size
                    or payload_off < meta_off + meta_len
                ):
                    raise ReplayError("replay frame entry points outside the file")
            self.header = header
            self._entries = entries
        except Exception:
            self._stream.close()
            raise
        if verify:
            try:
                for position in range(len(self._entries)):
                    self.read_frame(position, verify=True)
            except Exception:
                self._stream.close()
                raise

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def frame_indices(self) -> list[int]:
        return [entry[0] for entry in self._entries]

    def disk_bytes(self) -> int:
        return self.path.stat().st_size

    def avg_frame_bytes(self) -> int:
        if not self._entries:
            return 0
        return self.disk_bytes() // len(self._entries)

    def frame_bytes(self, position: int) -> int:
        """Encoded metadata + payload bytes, known before reading a blob."""
        if not 0 <= position < len(self._entries):
            raise ReplayError(f"replay position {position} out of range")
        entry = self._entries[position]
        return entry[1] + entry[2]

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> ReplayReader:  # noqa: PYI034 - runtime class, not a stub.
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def read_frame(self, position: int, *, verify: bool = False) -> tuple[dict, bytes]:
        """Return ``(metadata, payload)`` for cache position ``position``."""
        if not 0 <= position < len(self._entries):
            raise ReplayError(f"replay position {position} out of range")
        frame_index, meta_len, payload_len, meta_off, payload_off, expected = (
            self._entries[position]
        )
        self._stream.seek(meta_off)
        meta_bytes = self._stream.read(meta_len)
        self._stream.seek(payload_off)
        payload_bytes = self._stream.read(payload_len)
        if len(meta_bytes) != meta_len or len(payload_bytes) != payload_len:
            raise ReplayError("replay cache is truncated (frame blob)")
        if verify and frame_digest(meta_bytes, payload_bytes) != expected:
            raise ReplayError(f"replay frame {frame_index} failed checksum")
        metadata = json.loads(meta_bytes)
        if not isinstance(metadata, dict):
            raise ReplayError("replay frame metadata must be an object")
        return metadata, payload_bytes


class ReplayPrefetch:
    """One reader-owning worker; control/tick never wait on speculative I/O.

    The worker has its own file handle so synchronous seek/step reads cannot
    race its seek/read cursor. Close cancels admission immediately; an ongoing
    OS read finishes before the worker closes its own reader. The byte cap
    includes encoded bytes being read, not Python object/allocator overhead.
    """

    def __init__(self, reader: ReplayReader, *, max_frames: int, max_bytes: int):
        self._reader = reader
        self._max_frames = max_frames
        self._max_bytes = max_bytes
        self._condition = threading.Condition()
        self._start: int | None = None
        self._closed = False
        self._frames: dict[int, tuple[dict, bytes]] = {}
        self._errors: dict[int, ReplayError] = {}
        self._bytes = 0
        self._in_flight_bytes = 0
        self._thread = threading.Thread(
            target=self._run, name="veyra-replay-prefetch", daemon=True
        )
        self._thread.start()

    def request(self, position: int) -> None:
        """Keep only the bounded window beginning at the next wanted frame."""
        with self._condition:
            self._start = position
            end = min(len(self._reader), position + self._max_frames)
            for key in list(self._frames):
                if not position <= key < end:
                    del self._frames[key]
                    self._bytes -= self._reader.frame_bytes(key)
            self._errors = {
                key: error
                for key, error in self._errors.items()
                if position <= key < end
            }
            self._condition.notify_all()

    def take(self, position: int) -> tuple[dict, bytes] | None:
        """Take a ready frame or return immediately; errors fail at consumption."""
        with self._condition:
            if position in self._errors:
                raise self._errors[position]
            frame = self._frames.pop(position, None)
            if frame is not None:
                self._bytes -= self._reader.frame_bytes(position)
                self._condition.notify_all()
            return frame

    def status(self) -> dict:
        with self._condition:
            return {
                "prefetch_frames": len(self._frames),
                "prefetch_bytes": self._bytes,
                "prefetch_in_flight_bytes": self._in_flight_bytes,
            }

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._frames.clear()
            self._errors.clear()
            self._bytes = 0
            self._condition.notify_all()

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    while True:
                        if self._closed:
                            return
                        position = None
                        if self._start is not None:
                            end = min(len(self._reader), self._start + self._max_frames)
                            position = next(
                                (
                                    key
                                    for key in range(self._start, end)
                                    if key not in self._frames
                                    and key not in self._errors
                                ),
                                None,
                            )
                        if position is not None:
                            size = self._reader.frame_bytes(position)
                            if size > self._max_bytes:
                                self._errors[position] = ReplayError(
                                    f"cached frame {position} exceeds prefetch byte budget"
                                )
                                continue
                            # A backward seek may retain far-ahead frames inside
                            # the wider frame-count window. Give the earliest
                            # missing frame priority when the byte cap is full.
                            for key in sorted(self._frames, reverse=True):
                                if (
                                    self._bytes + size <= self._max_bytes
                                    or key <= position
                                ):
                                    break
                                del self._frames[key]
                                self._bytes -= self._reader.frame_bytes(key)
                            if self._bytes + size <= self._max_bytes:
                                self._in_flight_bytes = size
                                break
                        self._condition.wait()
                frame = None
                error = None
                try:
                    frame = self._reader.read_frame(position)
                except Exception as cause:  # noqa: BLE001 - fail at the requested frame.
                    error = ReplayError(f"cached frame {position} unreadable: {cause}")
                with self._condition:
                    self._in_flight_bytes = 0
                    if self._closed:
                        return
                    if self._start <= position < self._start + self._max_frames:
                        if error is not None:
                            self._errors[position] = error
                        else:
                            self._frames[position] = frame
                            self._bytes += size
                    self._condition.notify_all()
        finally:
            self._reader.close()


def default_cache_path(
    *,
    dataset: str,
    sequence: str,
    start: int,
    count: int,
    policy: str,
    provider: str,
    point_budget: int,
    cell_budget: int,
    directory: str | Path = "data/cache/replays",
) -> Path:
    """Repository-consistent cache filename (git-ignored under data/cache)."""
    name = (
        f"{dataset}-{sequence}-{start}-{count}-{policy}-{provider}-"
        f"{point_budget}pt{cell_budget}cell.veyra-replay"
    )
    return Path(directory) / name
