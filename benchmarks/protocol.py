"""Versioned, digest-protected protocol from Python observations to C++."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from datasets.common.observation import ObservationFrame

PROTOCOL_VERSION = 4
_DRIVABLE = {"unknown": 0, "drivable": 1, "non_drivable": 2}
_MOTION_STATE = {"static": 0, "possibly_moving": 1, "moving": 2, "unknown": 3}

# No alignment padding; C++ decodes little-endian scalars without pointer casts.
_BINARY_POINT = np.dtype(
    [
        ("xyzi", "<f4", (4,)),
        ("semantic", "<u4"),
        ("confidence", "<f4"),
        ("ground", "u1"),
        ("drivable", "u1"),
        ("slope", "<f4"),
        ("roughness", "<f4"),
        ("complexity", "<f4"),
        ("terrain", "<f4"),
        ("step", "<f4"),
        ("motion", "<f4"),
        ("state", "u1"),
        ("velocity", "<f4", (2,)),
        ("quality", "<f4"),
        ("raw", "<i4"),
        # V3. NaN means perception had no ground model for this return; the
        # map counts those rather than treating them as ground level.
        ("height_above_ground", "<f4"),
        # V4 carries the supported local ground-plane direction into the map.
        ("ground_gradient_x", "<f4"),
        ("ground_gradient_y", "<f4"),
    ]
)


def binary_frame_bytes(frame: ObservationFrame) -> bytes:
    """Encode full aligned evidence, 79 bytes/point; no point text conversion.

    Handshake is VEYRA_ENGINE 4. B count is followed by a 152-byte frame header
    and packed rows; the engine responds after consuming the complete frame.
    """
    return bytes(BinaryFrameEncoder().encode(frame))


class BinaryFrameEncoder:
    """Produce ``binary_frame_bytes`` records into one reused buffer.

    A live session sends one ~8 MB record per frame. Building it as a
    structured array, ``tobytes()`` and a prefix concatenation allocated three
    frame-sized blocks per frame, each a slightly different size as the point
    count varies, which the platform allocator keeps resident. The encoder
    writes rows in place into a buffer that grows geometrically and is then
    reused, so steady-state encoding allocates no frame-sized memory.

    The returned view aliases the buffer: it is valid until the next
    ``encode`` call and must be consumed (written or copied) before then.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        #: Points whose drivability is ``drivable`` or ``non_drivable`` in the
        #: last encoded frame (the ``np.isin`` count), taken from the codes.
        self.known_drivability_points = 0

    @property
    def capacity(self) -> int:
        return len(self._buffer)

    def encode(self, frame: ObservationFrame) -> memoryview:
        count = len(frame.points)
        if count > 2_000_000:
            raise ValueError("binary frame exceeds point limit")
        prefix = f"B {count}\n".encode("ascii")
        header = _binary_frame_header(frame)
        start = len(prefix) + len(header)
        size = start + count * _BINARY_POINT.itemsize
        if size > len(self._buffer):
            current = len(self._buffer)
            self._buffer = bytearray(max(size + size // 4, current + current // 2))
        view = memoryview(self._buffer)
        view[: len(prefix)] = prefix
        view[len(prefix) : start] = header
        points = np.frombuffer(
            self._buffer, dtype=_BINARY_POINT, count=count, offset=start
        )
        _fill_binary_points(points, frame)
        drivable = points["drivable"]
        self.known_drivability_points = int(
            np.count_nonzero(drivable == _DRIVABLE["drivable"])
            + np.count_nonzero(drivable == _DRIVABLE["non_drivable"])
        )
        return view[:size]


def _binary_frame_header(frame: ObservationFrame) -> bytes:
    missing = (1 << 64) - 1

    def stamp(value):
        result = missing if value is None else round(float(value) * 1_000_000)
        if result < 0 or result > missing:
            raise ValueError("timestamp outside binary range")
        return result

    source = int(frame.frame_id) if frame.frame_id.isdecimal() else missing
    if source >= missing and source != missing:
        raise ValueError("frame index outside binary range")
    return struct.pack(
        "<QQQ16d",
        stamp(frame.timestamp),
        stamp(frame.pose.timestamp),
        source,
        *frame.pose.matrix.reshape(-1),
    )


def _fill_binary_points(points: np.ndarray, frame: ObservationFrame) -> None:
    for destination, value in (
        ("xyzi", frame.points),
        ("semantic", frame.semantic_class),
        ("confidence", frame.semantic_confidence),
        ("ground", frame.ground),
        ("slope", frame.slope),
        ("roughness", frame.roughness),
        ("complexity", frame.height_complexity),
        ("terrain", frame.terrain_confidence),
        ("step", frame.step),
        ("motion", frame.motion_probability),
        ("velocity", frame.velocity_xy),
        ("quality", frame.observation_quality),
        ("raw", frame.raw_semantic_class),
        ("height_above_ground", frame.height_above_ground),
        ("ground_gradient_x", frame.ground_gradient_x),
        ("ground_gradient_y", frame.ground_gradient_y),
    ):
        points[destination] = value
    for field, values, mapping in (
        ("drivable", frame.drivable, _DRIVABLE),
        ("state", frame.motion_state, _MOTION_STATE),
    ):
        # Keys are distinct, so this equals np.select(..., default=255)
        # without its per-key int64 temporaries.
        codes = points[field]
        codes.fill(255)
        for key, code in mapping.items():
            codes[values == key] = code


def _number(value: float) -> str:
    """Encode a finite float for a float64 parser, otherwise explicit NA."""
    value = float(value)
    return format(value, ".17g") if math.isfinite(value) else "NA"


def _timestamp_us(value: float | None) -> str:
    return "NA" if value is None else str(round(float(value) * 1_000_000))


def _source_index(frame_id: str) -> str:
    return str(int(frame_id)) if frame_id.isdecimal() else "NA"


def frame_records(frame: ObservationFrame) -> list[str]:
    """Encode one observation frame as canonical V4 F/P/E records."""

    pose = " ".join(_number(value) for value in frame.pose.matrix.reshape(-1))
    records = [
        (
            f"F {_timestamp_us(frame.timestamp)} {_timestamp_us(frame.pose.timestamp)} "
            f"{_source_index(frame.frame_id)} {pose} {frame.points.shape[0]}\n"
        )
    ]
    for values in zip(
        frame.points,
        frame.semantic_class,
        frame.semantic_confidence,
        frame.ground,
        frame.drivable,
        frame.slope,
        frame.roughness,
        frame.height_complexity,
        frame.terrain_confidence,
        frame.step,
        frame.motion_probability,
        frame.motion_state,
        frame.velocity_xy,
        frame.observation_quality,
        frame.raw_semantic_class,
        frame.height_above_ground,
        frame.ground_gradient_x,
        frame.ground_gradient_y,
        strict=True,
    ):
        (
            point,
            semantic,
            confidence,
            ground,
            drivable,
            slope,
            roughness,
            height_complexity,
            terrain_confidence,
            step,
            motion_probability,
            motion_state,
            velocity_xy,
            observation_quality,
            raw_semantic_class,
            height_above_ground,
            ground_gradient_x,
            ground_gradient_y,
        ) = values
        records.append(
            " ".join(
                (
                    "P",
                    *(_number(value) for value in point),
                    str(int(semantic)),
                    _number(confidence),
                    "1" if bool(ground) else "0",
                    str(_DRIVABLE[str(drivable)]),
                    _number(slope),
                    _number(roughness),
                    _number(height_complexity),
                    _number(terrain_confidence),
                    _number(step),
                    _number(motion_probability),
                    str(_MOTION_STATE[str(motion_state)]),
                    _number(velocity_xy[0]),
                    _number(velocity_xy[1]),
                    _number(observation_quality),
                    str(int(raw_semantic_class)),
                    _number(height_above_ground),
                    _number(ground_gradient_x),
                    _number(ground_gradient_y),
                )
            )
            + "\n"
        )
    records.append("E\n")
    return records


def stream_bytes(frames: list[ObservationFrame]) -> tuple[bytes, str]:
    """Encode observations and digest every frame, point, and end record.

    V2 carries frame and pose timestamps in microseconds; ``NA`` is the sole
    missing-value sentinel. The digest protects pose and enriched fields, not
    merely the coordinates used by the current public map interface.
    """
    records: list[str] = []
    digest = hashlib.sha256()
    for frame in frames:
        for record in frame_records(frame):
            records.append(record)
            digest.update(record.encode("ascii"))
    checksum = digest.hexdigest()
    payload = f"VEYRA_STREAM {PROTOCOL_VERSION}\nH {checksum}\n" + "".join(records)
    return (f"{payload}D {checksum}\n".encode("ascii"), checksum)


def stream_file(frames: Iterable[ObservationFrame], path: str | Path) -> str:
    """Write the canonical stream incrementally and return its digest.

    Unlike :func:`stream_bytes`, this avoids retaining the serialized stream
    alongside source frames. ``frames`` may be a one-shot generator, allowing
    dataset and perception stages to stream without materialising a sequence.
    The fixed-width header digest is backfilled after records are written, then
    the trailer is appended. The resulting bytes are intentionally identical
    to ``stream_bytes(list(frames))[0]``.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"VEYRA_STREAM {PROTOCOL_VERSION}\nH ".encode("ascii")
    digest = hashlib.sha256()
    with output_path.open("wb+") as output:
        output.write(prefix + b"0" * 64 + b"\n")
        for frame in frames:
            for record in frame_records(frame):
                encoded = record.encode("ascii")
                output.write(encoded)
                digest.update(encoded)
        checksum = digest.hexdigest().encode("ascii")
        output.seek(len(prefix))
        output.write(checksum)
        output.seek(0, 2)
        output.write(b"D " + checksum + b"\n")
    return digest.hexdigest()


def binary_stream_file(frames: Iterable[ObservationFrame], path: str | Path) -> str:
    """Write a compact binary V2 stream without retaining the frame sequence.

    The digest covers the exact binary records written after the ``H`` line:
    each ``B <count>`` marker and its packed frame payload.  This is a distinct
    representation from the canonical text stream, so callers must pass the
    matching ``--binary-input`` mode to the native batch executable.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"VEYRA_STREAM {PROTOCOL_VERSION}\nH ".encode("ascii")
    digest = hashlib.sha256()
    encoder = BinaryFrameEncoder()
    with output_path.open("wb+") as output:
        output.write(prefix + b"0" * 64 + b"\n")
        for frame in frames:
            encoded = encoder.encode(frame)
            output.write(encoded)
            digest.update(encoded)
        checksum = digest.hexdigest().encode("ascii")
        output.seek(len(prefix))
        output.write(checksum)
        output.seek(0, 2)
        output.write(b"D " + checksum + b"\n")
    return digest.hexdigest()
