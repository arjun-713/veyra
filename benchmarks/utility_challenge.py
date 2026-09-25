"""Freeze UtilityLOD challenge scenes from raw data, before policy evaluation.

Run ``python -m benchmarks.utility_challenge discover --output ...`` first.
The selection reads scan XYZ, dataset labels and trusted metadata only. The
resulting manifest is content-hashed and must be supplied unchanged to the
separate benchmark runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from benchmarks.utility_hardcore import (
    contiguous_window,
    manifest_digest,
    select_geometry_candidates,
    select_semantic_candidate,
)
from datasets.common.taxonomy import (
    DATASET_TAXONOMY_VERSIONS,
    RELLIS_LABELS,
    SEMANTICKITTI_LABELS,
    SEMANTIC_POSS_LABELS,
    map_dataset_labels,
)
from datasets.rellis import Rellis3DDataset
from datasets.semantickitti import SemanticKITTIDataset
from datasets.semanticposs import SemanticPOSSDataset

DATASETS = {
    "semanticposs": SemanticPOSSDataset,
    "rellis3d": Rellis3DDataset,
    "semantickitti": SemanticKITTIDataset,
}
LABEL_MAPS = {
    "semanticposs": SEMANTIC_POSS_LABELS,
    "rellis3d": RELLIS_LABELS,
    "semantickitti": SEMANTICKITTI_LABELS,
}
SEMANTIC_CLASSES = {"pedestrian": 6, "pole": 18, "vehicle": 1}
FAR_BANDS = ((30, 60), (60, 100))
MOVING_RAW_KITTI = {252, 253, 254, 255, 256, 257, 258, 259}


def _digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _sparse_far_patch(points: np.ndarray) -> dict[str, Any] | None:
    """Find a 5 m patch with >=20 returns and sparse 1 m subcell occupancy."""
    radial = np.hypot(points[:, 0], points[:, 1])
    far = points[(radial >= 60) & (radial < 100)]
    if len(far) < 20:
        return None
    patch = np.floor(far[:, :2] / 5).astype(np.int64)
    keys, inverse, counts = np.unique(
        patch, axis=0, return_inverse=True, return_counts=True
    )
    for index in np.lexsort((keys[:, 1], keys[:, 0])):
        if counts[index] < 20:
            continue
        subset = far[inverse == index]
        _, subcounts = np.unique(
            np.floor(subset[:, :2]).astype(np.int64), axis=0, return_counts=True
        )
        sparse_fraction = float(np.sum(subcounts[subcounts <= 3]) / len(subset))
        if sparse_fraction < 0.8:
            continue
        ix, iy = (int(value) for value in keys[index])
        return {
            "bbox_xy_m": [ix * 5, iy * 5, (ix + 1) * 5, (iy + 1) * 5],
            "points": int(counts[index]),
            "sparse_return_fraction": sparse_fraction,
            "range_band_m": [60, 100],
            "selection_patch_size_m": 5,
        }
    return None


def _motion_candidate(
    points: np.ndarray, raw_ids: np.ndarray, instances: np.ndarray
) -> dict[str, Any] | None:
    moving = np.isin(raw_ids, list(MOVING_RAW_KITTI)) & (instances > 0)
    pairs, counts = np.unique(
        np.stack((raw_ids[moving], instances[moving]), axis=1),
        axis=0,
        return_counts=True,
    )
    if not len(pairs):
        return None
    order = sorted(
        range(len(pairs)),
        key=lambda index: (
            -int(counts[index]),
            int(pairs[index, 0]),
            int(pairs[index, 1]),
        ),
    )
    raw_class, chosen = (int(value) for value in pairs[order[0]])
    subset = points[moving & (raw_ids == raw_class) & (instances == chosen)]
    if len(subset) < 20:
        return None
    return {
        "bbox_xy_m": [
            float(subset[:, 0].min() - 0.5),
            float(subset[:, 1].min() - 0.5),
            float(subset[:, 0].max() + 0.5),
            float(subset[:, 1].max() + 0.5),
        ],
        "points": len(subset),
        "instance_id": chosen,
        "raw_moving_ids": [raw_class],
        "range_band_m": [0, 100],
    }


def _world_bbox(
    adapter: Any,
    sequence: str,
    frame_id: str,
    raw_points: np.ndarray,
    bbox: list[float],
) -> tuple[list[float], dict[str, Any]]:
    frame = adapter.load_frame(sequence, frame_id, max_range_m=100.0)
    matrix = np.asarray(frame.pose.matrix, dtype=np.float64)
    x0, y0, x1, y1 = bbox
    chosen = (
        (raw_points[:, 0] >= x0)
        & (raw_points[:, 0] < x1)
        & (raw_points[:, 1] >= y0)
        & (raw_points[:, 1] < y1)
    )
    xyz = raw_points[chosen, :3].astype(np.float64)
    if not len(xyz):
        raise ValueError("challenge region contains no source points")
    world = xyz @ matrix[:3, :3].T + matrix[:3, 3]
    result = [
        float(world[:, 0].min()),
        float(world[:, 1].min()),
        float(world[:, 0].max()),
        float(world[:, 1].max()),
    ]
    # A thin pole may have zero XY width; include a 5 cm evaluation margin.
    result = [result[0] - 0.05, result[1] - 0.05, result[2] + 0.05, result[3] + 0.05]
    return result, {
        "pose_source": frame.provenance.pose_source,
        "timestamp_source": frame.provenance.timestamp_source,
        "calibration_source": frame.provenance.calibration_source,
        "coordinate_frame": frame.provenance.coordinate_frame,
        "timestamp": frame.timestamp,
    }


def discover(
    repo: Path,
    *,
    stride: int = 4,
    max_scanned_per_dataset: int = 1200,
    window_frames: int = 10,
) -> dict[str, Any]:
    if stride <= 0 or max_scanned_per_dataset <= 0 or window_frames < 2:
        raise ValueError("stride/max scanned must be positive and window at least two")
    config = yaml.safe_load((repo / "configs/datasets.yaml").read_text())
    challenges: list[dict[str, Any]] = []
    scanned: dict[str, int] = {}
    eligible_keys: set[tuple[str, str, tuple[int, int]]] = set()
    for dataset, adapter_type in DATASETS.items():
        entry = config[dataset]
        adapter = adapter_type(repo / entry["root"])
        scanned[dataset] = 0
        for sequence in adapter.list_sequences():
            refs = adapter.list_frames(sequence)
            numeric_ids = [int(ref.frame_id) for ref in refs]
            for position in range(0, len(refs), stride):
                if scanned[dataset] >= max_scanned_per_dataset:
                    break
                ref = refs[position]
                scanned[dataset] += 1
                window = contiguous_window(
                    numeric_ids, int(ref.frame_id), window_frames
                )
                if window is None or ref.label_path is None:
                    continue
                raw = np.fromfile(ref.scan_path, dtype=np.float32)
                labels = np.fromfile(ref.label_path, dtype=np.uint32)
                if raw.size % 4 or len(labels) != raw.size // 4:
                    raise ValueError(f"malformed paired scan/label: {ref.scan_path}")
                points = raw.reshape(-1, 4)
                semantic_raw = labels & 0xFFFF
                classes = map_dataset_labels(semantic_raw, LABEL_MAPS[dataset])
                instances = (labels >> 16).astype(np.int32)
                proposed: list[tuple[str, str | None, dict[str, Any]]] = []
                for class_name, class_id in SEMANTIC_CLASSES.items():
                    for band in FAR_BANDS:
                        key = (dataset, class_name, band)
                        if key in eligible_keys:
                            continue
                        item = select_semantic_candidate(
                            points,
                            classes,
                            instances,
                            class_id=class_id,
                            lower_m=band[0],
                            upper_m=band[1],
                            min_points=20,
                        )
                        if item:
                            proposed.append(("semantic_object", class_name, item))
                            eligible_keys.add(key)
                if dataset == "rellis3d" and not any(
                    item["challenge_type"] == "geometry_hazard" for item in challenges
                ):
                    pair = select_geometry_candidates(points)
                    if pair["geometry_hazard"] and pair["flat_control"]:
                        proposed.extend(
                            (name, None, pair[name])
                            for name in ("geometry_hazard", "flat_control")
                        )
                if dataset == "semantickitti" and not any(
                    item["challenge_type"] == "motion_candidate" for item in challenges
                ):
                    moving = _motion_candidate(points, semantic_raw, instances)
                    if moving:
                        proposed.append(("motion_candidate", None, moving))
                if dataset == "semanticposs" and not any(
                    item["challenge_type"] == "sparse_far_control"
                    for item in challenges
                ):
                    sparse = _sparse_far_patch(points)
                    if sparse:
                        proposed.append(("sparse_far_control", None, sparse))
                for challenge_type, relevant_class, item in proposed:
                    bbox, metadata = _world_bbox(
                        adapter, sequence, ref.frame_id, points, item["bbox_xy_m"]
                    )
                    if challenge_type == "motion_candidate" and (
                        metadata["pose_source"] != "dataset"
                        or metadata["timestamp_source"] != "dataset"
                    ):
                        continue
                    start, end = window
                    challenges.append(
                        {
                            "id": f"{dataset}-{sequence}-{ref.frame_id}-{challenge_type}"
                            + (
                                f"-{relevant_class}-{item['range_band_m'][0]}"
                                if relevant_class
                                else ""
                            ),
                            "dataset": dataset,
                            "sequence": sequence,
                            "frame_start": start,
                            "frame_end_exclusive": end,
                            "source_frame_id": ref.frame_id,
                            "challenge_type": challenge_type,
                            "relevant_class": relevant_class,
                            "selection_reason": {
                                "semantic_object": "first >=20-point GT class/instance in distance stratum",
                                "geometry_hazard": "first >=12-return 1m cell with height IQR >=0.25m and paired flat cell",
                                "flat_control": "same-frame nearby 1m cell with height IQR <=0.04m",
                                "motion_candidate": "first >=20-point SemanticKITTI moving raw label with trusted pose/time",
                                "sparse_far_control": "first 5m far patch >=20 returns with >=80% returns in <=3-point 1m cells",
                            }[challenge_type],
                            "sensor_region_bbox_xy_m": item["bbox_xy_m"],
                            "bbox_xy_m": bbox,
                            "support": {
                                key: value
                                for key, value in item.items()
                                if key != "bbox_xy_m"
                            },
                            "metadata": metadata,
                            "source_scan_sha256": _digest_file(ref.scan_path),
                            "source_label_sha256": _digest_file(ref.label_path),
                            "source_scan_path": str(ref.scan_path.relative_to(repo)),
                            "source_label_path": str(ref.label_path.relative_to(repo)),
                            "taxonomy_version": DATASET_TAXONOMY_VERSIONS[dataset],
                        }
                    )
            if scanned[dataset] >= max_scanned_per_dataset:
                break
    manifest = {
        "schema_version": 1,
        "selection_policy": "first qualifying original frame in numeric order, fixed stride; no map output inspected",
        "selection_parameters": {
            "stride": stride,
            "max_scanned_per_dataset": max_scanned_per_dataset,
            "window_frames": window_frames,
            "semantic_min_points": 20,
            "geometry_cell_m": 1.0,
            "geometry_min_points": 12,
            "geometry_hazard_iqr_m": 0.25,
            "flat_max_iqr_m": 0.04,
            "matched_flat_max_range_difference_m": 5.0,
        },
        "scanned_frames": scanned,
        "challenges": challenges,
        "unavailable": {
            "great_outdoors": "dataset absent locally",
            "motion_ground_truth": "moving raw labels identify candidates, not tracked-object ground truth",
        },
    }
    manifest["sha256"] = manifest_digest(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover",))
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/utility_challenge_manifest.json"),
    )
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--max-scanned-per-dataset", type=int, default=1200)
    parser.add_argument("--window-frames", type=int, default=10)
    args = parser.parse_args()
    repo = args.repo.resolve()
    result = discover(
        repo,
        stride=args.stride,
        max_scanned_per_dataset=args.max_scanned_per_dataset,
        window_frames=args.window_frames,
    )
    destination = args.output if args.output.is_absolute() else repo / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"froze {len(result['challenges'])} challenges at {destination} ({result['sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
