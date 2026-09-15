#!/usr/bin/env python3
"""Profile temporal clustering on original local dataset frames.

This script consumes the existing adapters and never creates timestamps or
poses. A frame with missing temporal metadata is measured in ``cluster-only``
mode; that is useful for sizing the spatial operation, but is not reported as
temporal validation. No dataset files are downloaded or written.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

# Direct ``python scripts/profile_temporal.py`` puts ``scripts/`` ahead of the
# repository root on sys.path; make the checked-out adapters importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datasets.rellis import Rellis3DDataset
from datasets.semanticposs import SemanticPOSSDataset
from perception.temporal.tracker import TemporalTracker


def _adapter(name: str, root: Path, sequence: str):
    if name == "semanticposs":
        return SemanticPOSSDataset(root), sequence
    if name == "rellis":
        return Rellis3DDataset(root), sequence
    raise ValueError(f"unsupported dataset: {name}")


def _profile_dataset(
    name: str,
    root: Path,
    sequence: str,
    frame_count: int,
    max_range_m: float | None,
) -> None:
    try:
        adapter, sequence = _adapter(name, root, sequence)
        frames = list(
            adapter.replay(sequence, end=frame_count, max_range_m=max_range_m)
        )
    except (FileNotFoundError, ValueError, NameError) as error:
        print(f"{name}: adapter error: {error}")
        return
    if not frames:
        print(f"{name}: no frames found")
        return

    tracker = TemporalTracker()
    timings_ms: list[float] = []
    modes: list[str] = []
    cluster_counts: list[int] = []
    point_counts: list[int] = []
    for frame in frames:
        point_counts.append(len(frame.points))
        has_timestamp = frame.timestamp is not None and np.isfinite(frame.timestamp)
        has_pose = frame.provenance.pose_source == "dataset"
        start = time.perf_counter()
        if has_timestamp and has_pose:
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
            cluster_counts.append(tracker.active_track_count)
            modes.append("temporal")
        else:
            world = frame.points[:, :3].astype(np.float64, copy=False)
            clusters = tracker._clusters(world, frame.semantic_class)
            cluster_counts.append(len(clusters))
            modes.append("cluster-only")
        timings_ms.append((time.perf_counter() - start) * 1000.0)

    values = np.asarray(timings_ms, dtype=np.float64)
    print(
        f"{name}: sequence={sequence} frames={len(frames)} "
        f"points={point_counts} clusters={cluster_counts} modes={modes} "
        f"p50_ms={np.percentile(values, 50):.3f} "
        f"p95_ms={np.percentile(values, 95):.3f} "
        f"p99_ms={np.percentile(values, 99):.3f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=("semanticposs", "rellis", "all"),
        default="all",
    )
    parser.add_argument(
        "--semanticposs-root", type=Path, default=Path("data/raw/semanticposs/dataset")
    )
    parser.add_argument(
        "--rellis-root", type=Path, default=Path("data/raw/rellis3d/Rellis-3D")
    )
    parser.add_argument("--semanticposs-sequence", default="00")
    parser.add_argument("--rellis-sequence", default="00000")
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--max-range-m", type=float, default=100.0)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")
    if args.max_range_m < 0 or not np.isfinite(args.max_range_m):
        parser.error("--max-range-m must be finite and non-negative")

    datasets = ("semanticposs", "rellis") if args.dataset == "all" else (args.dataset,)
    for name in datasets:
        _profile_dataset(
            name,
            args.semanticposs_root if name == "semanticposs" else args.rellis_root,
            args.semanticposs_sequence
            if name == "semanticposs"
            else args.rellis_sequence,
            args.frames,
            args.max_range_m,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
