#!/usr/bin/env python3
"""Validate temporal tracking on a real, dataset-backed sequence.

This command is intentionally strict.  It requires every selected frame to
carry a dataset timestamp, a dataset pose, and world-frame coordinates.  It
never derives time from frame IDs, filesystem metadata, or an assumed sensor
rate.  Use ``profile_temporal.py`` when only spatial clustering timing is
wanted for a dataset without temporal metadata.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Support direct execution from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datasets.rellis import Rellis3DDataset
from datasets.semantickitti import SemanticKITTIDataset
from datasets.semanticposs import SemanticPOSSDataset
from perception.temporal import TemporalTracker


class TemporalValidationError(RuntimeError):
    """The selected sequence cannot provide trustworthy temporal evidence."""


def _adapter(dataset: str, root: Path):
    adapters = {
        "semanticposs": SemanticPOSSDataset,
        "rellis3d": Rellis3DDataset,
        "semantickitti": SemanticKITTIDataset,
    }
    try:
        return adapters[dataset](root)
    except KeyError as error:
        raise TemporalValidationError(
            f"unsupported temporal dataset: {dataset}"
        ) from error


def _latency_summary(values_ms: list[float]) -> dict[str, float | int]:
    values = np.asarray(values_ms, dtype=np.float64)
    if values.size == 0 or not np.all(np.isfinite(values)) or np.any(values < 0):
        raise TemporalValidationError("temporal timings are empty or invalid")
    return {
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
        "p99_ms": float(np.percentile(values, 99)),
        "mean_ms": float(values.mean()),
        "max_ms": float(values.max()),
        "samples": int(values.size),
    }


def validate_frames(
    root: Path,
    sequence: str,
    *,
    dataset: str = "semantickitti",
    start: int = 0,
    count: int = 100,
    stride: int = 1,
    max_range_m: float | None = 100.0,
    exclude_classes: tuple[int, ...] = (),
) -> dict:
    """Run the tracker over a strictly metadata-backed real replay.

    The returned report distinguishes tracker execution from motion quality:
    the tracker has no object-level ground-truth evaluator, so this function
    reports observed states and velocities without calling them ground truth.
    ``exclude_classes`` is forwarded to the tracker (ground-surface classes
    already consumed by the terrain branch) and recorded in the report.
    """
    if start < 0 or count < 1 or stride < 1:
        raise ValueError(
            "start must be non-negative; count and stride must be positive"
        )
    if max_range_m is not None and (not np.isfinite(max_range_m) or max_range_m < 0):
        raise ValueError("max_range_m must be finite and non-negative")

    adapter = _adapter(dataset, root)
    replay = adapter.replay(
        sequence,
        start=start,
        end=start + count * stride,
        stride=stride,
        max_range_m=max_range_m,
    )
    tracker = TemporalTracker(exclude_classes=tuple(exclude_classes))
    records: list[dict] = []
    timings_ms: list[float] = []
    previous_timestamp: float | None = None

    for index in range(count):
        try:
            frame = next(replay)
        except StopIteration as error:
            raise TemporalValidationError(
                f"sequence {dataset}/{sequence} supplied {index} frames; "
                f"{count} required"
            ) from error

        provenance = frame.provenance
        if frame.timestamp is None or not np.isfinite(frame.timestamp):
            raise TemporalValidationError(
                f"{dataset}/{sequence}/{frame.frame_id} lacks a finite dataset timestamp"
            )
        if provenance.timestamp_source != "dataset":
            raise TemporalValidationError(
                f"{dataset}/{sequence}/{frame.frame_id} timestamp provenance is "
                f"{provenance.timestamp_source!r}, not 'dataset'"
            )
        if provenance.pose_source != "dataset":
            raise TemporalValidationError(
                f"{dataset}/{sequence}/{frame.frame_id} lacks a dataset pose "
                f"(source={provenance.pose_source!r})"
            )
        if provenance.coordinate_frame != "world":
            raise TemporalValidationError(
                f"{dataset}/{sequence}/{frame.frame_id} is not in world coordinates "
                f"(frame={provenance.coordinate_frame!r})"
            )
        timestamp = float(frame.timestamp)
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise TemporalValidationError(
                f"dataset timestamps must be strictly increasing: "
                f"{previous_timestamp} then {timestamp} at {frame.frame_id}"
            )
        if frame.pose.timestamp is not None and not np.isclose(
            frame.pose.timestamp, timestamp
        ):
            raise TemporalValidationError(
                f"pose/frame timestamp mismatch at {frame.frame_id}"
            )

        started = time.perf_counter()
        evidence = tracker.update(
            frame.points,
            frame.semantic_class,
            frame.pose.matrix,
            timestamp=timestamp,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        timings_ms.append(elapsed_ms)
        speed = np.linalg.norm(evidence.velocity_xy, axis=1)
        state_counts = {
            state: int(np.count_nonzero(evidence.state == state))
            for state in ("static", "possibly_moving", "moving", "unknown")
        }
        records.append(
            {
                "frame_id": frame.frame_id,
                "timestamp_s": timestamp,
                "points": len(frame.points),
                "active_tracks": tracker.active_track_count,
                "motion_samples": int(np.count_nonzero(evidence.state != "unknown")),
                "state_counts": state_counts,
                "max_speed_mps": float(speed.max()) if speed.size else 0.0,
                "temporal_latency_ms": elapsed_ms,
                "pose_source": provenance.pose_source,
                "timestamp_source": provenance.timestamp_source,
            }
        )
        previous_timestamp = timestamp

    return {
        "dataset": dataset,
        "sequence": str(sequence),
        "frame_range": {
            "start": start,
            "count": count,
            "stride": stride,
            "max_range_m": max_range_m,
        },
        "tracker": {
            "exclude_classes": sorted(set(exclude_classes)),
        },
        "temporal_proven": True,
        "provenance": {
            "pose_sources": sorted({row["pose_source"] for row in records}),
            "timestamp_sources": sorted({row["timestamp_source"] for row in records}),
            "coordinate_frame": "world",
        },
        "frames": records,
        "timings": _latency_summary(timings_ms),
        "motion_quality": {
            "meaning": "observed tracker evidence; no object-level ground truth was supplied",
            "frames_with_motion_evidence": int(
                sum(row["motion_samples"] > 0 for row in records)
            ),
            "frames_with_moving_state": int(
                sum(row["state_counts"]["moving"] > 0 for row in records)
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=("semanticposs", "rellis3d", "semantickitti"),
        required=True,
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--max-range-m", type=float, default=100.0)
    parser.add_argument(
        "--exclude-classes",
        type=str,
        default="",
        help="comma-separated semantic class IDs excluded from tracking",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        exclude = tuple(
            int(value) for value in args.exclude_classes.split(",") if value.strip()
        )
    except ValueError as error:
        print(f"temporal validation failed closed: {error}", file=sys.stderr)
        return 2
    try:
        result = validate_frames(
            args.root,
            args.sequence,
            dataset=args.dataset,
            start=args.start,
            count=args.count,
            stride=args.stride,
            max_range_m=args.max_range_m,
            exclude_classes=exclude,
        )
    except (FileNotFoundError, ValueError, TemporalValidationError) as error:
        print(f"temporal validation failed closed: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps({"output": str(args.output), "timings": result["timings"]}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
