"""Measure original dataset -> real perception -> ObservationFrame.

python -m scripts.validate_perception --dataset semanticposs --root
data/raw/semanticposs/dataset --sequence 00 --count 10 --config
configs/perception-salsanext.yaml --output benchmark-results/poss-perception.json
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
from time import perf_counter

import numpy as np
import yaml

from datasets.rellis import Rellis3DDataset
from datasets.generic import ManifestDataset
from datasets.semanticposs import SemanticPOSSDataset
from datasets.semantickitti import SemanticKITTIDataset
from benchmarks.protocol import frame_records
from perception.pipeline import PerceptionPipeline


def _sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _git_sha(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _physical_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def reproducibility_metadata(
    *,
    repo: Path,
    config_path: Path,
    config_data: dict,
    dataset_sha256: str | None,
    sequence: str,
    start: int,
    count: int,
) -> dict:
    """Record inputs needed to explain a future perception regression."""
    model_value = config_data.get("semantic", {}).get("model_path")
    model_path = repo / model_value if isinstance(model_value, str) else None
    return {
        "git_sha": _git_sha(repo),
        "dataset_sha256": dataset_sha256,
        "frame_range": {
            "sequence": sequence,
            "start": start,
            "end_exclusive": start + count,
            "count": count,
        },
        "config_sha256": _sha256_file(config_path.resolve()),
        "model_checkpoint_sha256": _sha256_file(model_path) if model_path else None,
        "runner": {
            "os": platform.platform(),
            "cpu": _cpu_model(),
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_bytes": _physical_memory_bytes(),
            "python": platform.python_version(),
        },
        "compiler": "not applicable (Python-only perception artifact)",
        "build_type": "not applicable",
    }


def latency_summary(values):
    values = np.asarray(values, np.float64)
    if not len(values) or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("latencies must be nonempty, finite, non-negative")
    return {
        **{f"p{p}_ms": float(np.percentile(values, p)) for p in (50, 95, 99)},
        "mean_ms": float(values.mean()),
        "max_ms": float(values.max()),
        "samples": len(values),
    }


def confusion_report(confusion):
    total = int(confusion.sum())
    intersection = np.diag(confusion)
    union = confusion.sum(0) + confusion.sum(1) - intersection
    valid = (union > 0) & (np.arange(20) != 0)
    return {
        "evaluated_points": total,
        "accuracy": float(intersection.sum() / total) if total else None,
        "mean_iou": float(np.mean(intersection[valid] / union[valid]))
        if valid.any()
        else None,
        "classes_in_iou": np.flatnonzero(valid).tolist(),
    }


def validate(args):
    adapters = {
        "generic": ManifestDataset,
        "semanticposs": SemanticPOSSDataset,
        "rellis3d": Rellis3DDataset,
        "semantickitti": SemanticKITTIDataset,
    }
    dataset = (
        adapters[args.dataset](args.root, args.manifest)
        if args.dataset == "generic"
        else adapters[args.dataset](args.root)
    )
    config_path = Path(args.config).resolve()
    config = yaml.safe_load(config_path.read_text())
    required = ["semantic", "ground", "terrain"]
    if args.require_temporal:
        config["temporal"] = {**config.get("temporal", {}), "enabled": True}
        required.append("temporal")
    config["required_stages"] = required
    pipeline = PerceptionPipeline.from_config(config)
    frames = dataset.replay(
        args.sequence, start=args.start, end=args.start + args.count, max_range_m=100
    )
    digest = hashlib.sha256()
    records = []
    boundaries = [(0, 10), (10, 30), (30, 60), (60, 100.0001)]
    confusion = [np.zeros((20, 20), np.int64) for _ in boundaries]
    while True:
        started = perf_counter()
        try:
            frame = next(frames)
        except StopIteration:
            break
        load_ms = (perf_counter() - started) * 1000
        digest.update(frame.points.tobytes())
        digest.update(frame.semantic_class.tobytes())
        output = pipeline.process(frame)
        if not np.array_equal(frame.points, output.frame.points):
            raise RuntimeError("perception changed point coordinates/order")
        if not np.any(output.frame.ground):
            raise RuntimeError(
                "representative ground validation found no ground returns"
            )
        sensor = frame.points[:, :3]
        if frame.provenance.coordinate_frame in {"world", "calibrated_lidar"}:
            sensor = (sensor - frame.pose.matrix[:3, 3]) @ frame.pose.matrix[:3, :3]
        distances = np.linalg.norm(sensor, axis=1)
        gt, pred = frame.semantic_class, output.frame.semantic_class
        for matrix, (lower, upper) in zip(confusion, boundaries):
            keep = (distances >= lower) & (distances < upper) & (gt > 0) & (gt < 20)
            if np.any((pred < 0) | (pred >= 20)):
                raise RuntimeError("output class outside canonical taxonomy")
            matrix += np.bincount(gt[keep] * 20 + pred[keep], minlength=400).reshape(
                20, 20
            )
        bridge_started = perf_counter()
        bridge_records = frame_records(output.frame)
        bridge_ms = (perf_counter() - bridge_started) * 1000
        records.append(
            {
                "frame_id": frame.frame_id,
                "points": len(frame.points),
                "provenance": asdict(frame.provenance),
                "status": asdict(output.status),
                "timings_ms": {
                    **output.timings_ms,
                    "load": load_ms,
                    "bridge": bridge_ms,
                    "end_to_end": load_ms + output.timings_ms["total"],
                },
                "bridge_bytes": sum(
                    len(record.encode("ascii")) for record in bridge_records
                ),
                "ground_fraction": float(output.frame.ground.mean()),
                "known_terrain_fraction": float(
                    (output.frame.drivable != "unknown").mean()
                ),
                "known_motion_fraction": float(
                    (output.frame.motion_state != "unknown").mean()
                ),
                "semantic_classes": np.unique(pred).tolist(),
            }
        )
    if len(records) != args.count:
        raise ValueError(
            f"requested {args.count} frames, dataset supplied {len(records)}"
        )
    timings = {
        name: latency_summary([row["timings_ms"][name] for row in records])
        for name in records[0]["timings_ms"]
    }
    model_mode = records[0]["status"]["semantic"] == "model"
    return {
        "dataset": args.dataset,
        "sequence": args.sequence,
        "frames": records,
        "input_sha256": digest.hexdigest(),
        "reproducibility": reproducibility_metadata(
            repo=config_path.parents[1]
            if config_path.parent.name == "configs"
            else Path.cwd().resolve(),
            config_path=config_path,
            config_data=config,
            dataset_sha256=args.dataset_sha256,
            sequence=args.sequence,
            start=args.start,
            count=args.count,
        ),
        "config": config,
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "timings": timings,
        "fps": 1000 / timings["end_to_end"]["mean_ms"],
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024),
        "semantic_evaluation": {
            "meaning": "model vs mapped ground truth; cross-dataset accuracy, not training-domain guarantee"
            if model_mode
            else "ground-truth passthrough alignment, not model accuracy",
            "by_range": [
                {"range_m": [a, min(b, 100)], **confusion_report(c)}
                for (a, b), c in zip(boundaries, confusion)
            ],
        },
        "temporal_proven": all(
            row["status"]["temporal"] == "available"
            and row["provenance"]["pose_source"] == "dataset"
            and row["provenance"]["timestamp_source"] == "dataset"
            for row in records
        ),
        "point_order_preserved": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=["generic", "semanticposs", "rellis3d", "semantickitti"],
        required=True,
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("manifest.json"))
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--config", default="configs/perception.yaml")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--require-temporal", action="store_true")
    parser.add_argument(
        "--dataset-sha256",
        help="SHA-256 of the source dataset archive, when the run used one",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1 or args.start < 0:
        parser.error("count must be positive; start non-negative")
    result = validate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "frames": len(result["frames"]),
                "timings": result["timings"],
                "temporal_proven": result["temporal_proven"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
