"""Versioned, digest-protected protocol from Python observations to C++."""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path

import numpy as np

from datasets.common.observation import ObservationFrame

PROTOCOL_VERSION = 2
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
    ]
)


def binary_frame_bytes(frame: ObservationFrame) -> bytes:
    """Encode full aligned evidence, 67 bytes/point; no point text conversion.

    Handshake is VEYRA_ENGINE 2. B count is followed by a 152-byte frame header
    and packed rows; the engine responds after consuming the complete frame.
    """
    count = len(frame.points)
    if count > 2_000_000:
        raise ValueError("binary frame exceeds point limit")
    missing = (1 << 64) - 1

    def stamp(value):
        result = missing if value is None else round(float(value) * 1_000_000)
        if result < 0 or result > missing:
            raise ValueError("timestamp outside binary range")
        return result

    source = int(frame.frame_id) if frame.frame_id.isdecimal() else missing
    if source >= missing and source != missing:
        raise ValueError("frame index outside binary range")
    header = struct.pack(
        "<QQQ16d",
        stamp(frame.timestamp),
        stamp(frame.pose.timestamp),
        source,
        *frame.pose.matrix.reshape(-1),
    )
    points = np.empty(count, dtype=_BINARY_POINT)
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
    ):
        points[destination] = value
    for field, values, mapping in (
        ("drivable", frame.drivable, _DRIVABLE),
        ("state", frame.motion_state, _MOTION_STATE),
    ):
        points[field] = np.select(
            [values == key for key in mapping], list(mapping.values()), default=255
        )
    return f"B {count}\n".encode("ascii") + header + points.tobytes()


def _number(value: float) -> str:
    """Encode a finite float for a float64 parser, otherwise explicit NA."""
    value = float(value)
    return format(value, ".17g") if math.isfinite(value) else "NA"


def _timestamp_us(value: float | None) -> str:
    return "NA" if value is None else str(round(float(value) * 1_000_000))


def _source_index(frame_id: str) -> str:
    return str(int(frame_id)) if frame_id.isdecimal() else "NA"


def frame_records(frame: ObservationFrame) -> list[str]:
    """Encode one observation frame as canonical V2 F/P/E records."""

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


def stream_file(frames: list[ObservationFrame], path: str | Path) -> str:
    """Write the canonical stream incrementally and return its digest.

    Unlike :func:`stream_bytes`, this avoids retaining the serialized stream
    alongside all source frames. The fixed-width header digest is backfilled
    after records are written, then the trailer is appended. The resulting
    bytes are intentionally identical to ``stream_bytes(frames)[0]``.
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
