"""Produce bounded, local-only evidence for the dataset adapter contract.

The script exercises adapters through ``list_frames`` and ``load_frame``; it
does not inspect or rewrite dataset files, download assets, or turn missing
metadata into synthetic values.  JSON is written to stdout unless ``--output``
is supplied.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

# ``python scripts/validate_dataset_capabilities.py`` places ``scripts/`` on
# sys.path, not the repository root. Keep the documented direct invocation
# working without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datasets.rellis import Rellis3DDataset
from datasets.semantickitti import SemanticKITTIDataset
from datasets.semanticposs import SemanticPOSSDataset

ADAPTERS = {
    "rellis3d": Rellis3DDataset,
    "semanticposs": SemanticPOSSDataset,
    "semantickitti": SemanticKITTIDataset,
}
DEFAULT_ROOTS = {
    "rellis3d": Path("data/raw/rellis3d/Rellis-3D"),
    "semanticposs": Path("data/raw/semanticposs/dataset"),
    "semantickitti": Path("data/raw/semantickitti/dataset"),
}


def _sample_refs(refs: list[Any], limit: int) -> list[Any]:
    if not refs:
        return []
    indices = np.linspace(0, len(refs) - 1, num=min(limit, len(refs)), dtype=int)
    return [refs[int(index)] for index in dict.fromkeys(indices)]


def _metadata_status(values: list[str], available: str = "dataset") -> dict[str, Any]:
    observed = sorted(set(values))
    if not observed:
        return {"status": "unavailable", "observed_sources": []}
    if observed == [available]:
        status = "available"
    elif available in observed:
        status = "partially_available"
    else:
        status = "unavailable"
    return {"status": status, "observed_sources": observed}


def build_report(
    *, dataset_name: str, root: Path, sequences: list[str] | None, sample_limit: int
) -> dict[str, Any]:
    """Return JSON-compatible capability evidence for one configured adapter."""
    if dataset_name not in ADAPTERS:
        raise ValueError(f"unknown dataset adapter: {dataset_name}")
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive")

    report: dict[str, Any] = {
        "schema_version": 1,
        "dataset": dataset_name,
        "root": str(root),
        "status": "unvalidated_local",
        "checks": {
            "point_label_alignment": False,
            "finite_points_and_intensity": False,
            "deterministic_ordering": False,
            "deterministic_replay": False,
            "taxonomy_and_instance_mapping": False,
        },
        "metadata": {
            "pose": {"status": "unavailable", "observed_sources": []},
            "timestamp": {"status": "unavailable", "observed_sources": []},
            "calibration": {"status": "unavailable", "observed_sources": []},
            "labels": {"status": "unavailable", "observed_sources": []},
        },
        "total_frame_count": 0,
        "representative_frame_count": 0,
        "representative_frames": [],
    }
    if not root.is_dir():
        report["reason"] = "local_root_unavailable"
        return report

    adapter = ADAPTERS[dataset_name](root, sequences=sequences)
    selected_sequences = adapter.list_sequences()
    all_ids: dict[str, list[str]] = {}
    samples: list[tuple[str, Any]] = []
    for sequence in selected_sequences:
        try:
            refs = adapter.list_frames(sequence)
        except (OSError, ValueError, TypeError) as error:
            report["status"] = "invalid_local_data"
            report["reason"] = "frame_discovery_failed"
            report["diagnostic"] = f"{dataset_name}/{sequence}: {error}"
            return report
        report["total_frame_count"] += len(refs)
        all_ids[sequence] = [ref.frame_id for ref in refs]
        samples.extend((sequence, ref) for ref in _sample_refs(refs, sample_limit))

    report["checks"]["deterministic_ordering"] = all(
        ids
        == sorted(
            ids, key=lambda value: (0, int(value)) if value.isdigit() else (1, value)
        )
        for ids in all_ids.values()
    )
    pose_sources: list[str] = []
    timestamp_sources: list[str] = []
    calibration_sources: list[str] = []
    label_sources: list[str] = []
    intensity_min = float("inf")
    intensity_max = float("-inf")
    all_checks = {
        "point_label_alignment": True,
        "finite_points_and_intensity": True,
        "taxonomy_and_instance_mapping": True,
    }
    replay_pairs_equal = True
    for sequence, ref in samples:
        try:
            first = adapter.load_frame(sequence, ref.frame_id)
            second = adapter.load_frame(sequence, ref.frame_id)
        except (OSError, ValueError, TypeError) as error:
            report["status"] = "invalid_local_data"
            report["reason"] = "frame_validation_failed"
            report["diagnostic"] = (
                f"{dataset_name}/{sequence}/{ref.frame_id}: {error}"
            )
            return report
        replay_pairs_equal &= np.array_equal(first.points, second.points)
        replay_pairs_equal &= np.array_equal(
            first.semantic_class, second.semantic_class
        )
        replay_pairs_equal &= np.array_equal(first.instance_id, second.instance_id)
        all_checks["point_label_alignment"] &= len(first.points) == len(
            first.semantic_class
        )
        all_checks["finite_points_and_intensity"] &= bool(
            np.isfinite(first.points).all()
        )
        all_checks["taxonomy_and_instance_mapping"] &= len(
            first.raw_semantic_class
        ) == len(first.semantic_class) and len(first.instance_id) == len(
            first.semantic_class
        )
        if first.points.shape[0] == 0:
            report["status"] = "invalid_local_data"
            report["reason"] = "frame_validation_failed"
            report["diagnostic"] = (
                f"{dataset_name}/{sequence}/{ref.frame_id}: frame contains no points"
            )
            return report
        intensity_min = min(intensity_min, float(first.points[:, 3].min()))
        intensity_max = max(intensity_max, float(first.points[:, 3].max()))
        provenance = first.provenance
        pose_sources.append(provenance.pose_source)
        timestamp_sources.append(provenance.timestamp_source)
        calibration_sources.append(provenance.calibration_source)
        label_sources.append(provenance.label_source)
        report["representative_frames"].append(
            {
                "sequence": sequence,
                "frame_id": first.frame_id,
                "points": len(first.points),
                "labels": len(first.semantic_class),
                "raw_taxonomy_ids": int(np.unique(first.raw_semantic_class).size),
                "nonzero_instance_ids": int(np.count_nonzero(first.instance_id)),
                "intensity_min": float(first.points[:, 3].min()),
                "intensity_max": float(first.points[:, 3].max()),
                "provenance": {
                    "coordinate_frame": provenance.coordinate_frame,
                    "pose_source": provenance.pose_source,
                    "timestamp_source": provenance.timestamp_source,
                    "calibration_source": provenance.calibration_source,
                    "label_source": provenance.label_source,
                },
            }
        )

    report["representative_frame_count"] = len(report["representative_frames"])
    report["checks"].update(all_checks)
    report["checks"]["deterministic_replay"] = replay_pairs_equal
    report["checks"]["finite_points_and_intensity"] &= bool(
        intensity_min >= 0.0 and intensity_max <= 255.0
    )
    report["intensity"] = {
        "constraint": "finite byte-scale reflectance [0, 255]",
        "observed_min": None if not samples else intensity_min,
        "observed_max": None if not samples else intensity_max,
    }
    report["metadata"] = {
        "pose": _metadata_status(pose_sources),
        "timestamp": _metadata_status(timestamp_sources),
        "calibration": _metadata_status(calibration_sources),
        "labels": _metadata_status(label_sources),
    }
    if not samples:
        report["status"] = "invalid_local_data"
        report["reason"] = "no_frames_available"
        return report
    report["status"] = (
        "validated_local" if all(report["checks"].values()) else "invalid_local_data"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(ADAPTERS), required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--sequence", action="append", dest="sequences")
    parser.add_argument("--sample-limit", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(
        dataset_name=args.dataset,
        root=args.root or DEFAULT_ROOTS[args.dataset],
        sequences=args.sequences,
        sample_limit=args.sample_limit,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
