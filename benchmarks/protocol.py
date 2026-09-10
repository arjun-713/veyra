"""Versioned, digest-protected protocol from Python observations to C++."""

from __future__ import annotations

import hashlib
import math

from datasets.common.observation import ObservationFrame

PROTOCOL_VERSION = 2
_DRIVABLE = {"unknown": 0, "drivable": 1, "non_drivable": 2}
_MOTION_STATE = {"static": 0, "possibly_moving": 1, "moving": 2, "unknown": 3}


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
