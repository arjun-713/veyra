"""Cross-domain SalsaNext (SemanticKITTI) measurement on SemanticPOSS frames.

Run from repository root::

    python3 scripts/measure_salsanext_cross_domain.py --sequence 00 --frames 16 \
        --output reports/closure/semantic/salsanext-poss-metrics.json

Reads raw sensor-frame ``.bin``/``.label`` pairs directly so the i-th point
aligns with the i-th label (point order preserved by construction). Labels are
mapped with the same ``datasets.common.taxonomy`` function the adapter uses.
The pipeline-level dataset gate (``supported_datasets``) deliberately refuses
POSS frames; this script calls the provider directly for measurement only and
records that fact in the artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from datasets.common.taxonomy import (
    SEMANTIC_POSS_LABELS,
    TAXONOMY_VERSION,
    map_dataset_labels,
)
from perception.semantic.salsanext import (
    SalsaNextSemanticProvider,
    model_contract,
    project_scan,
)

N_CLASSES = 20
RANGE_BINS = ((0.0, 10.0), (10.0, 30.0), (30.0, 60.0), (60.0, float("inf")))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def per_class_iou(
    pred: np.ndarray, gt: np.ndarray
) -> tuple[dict[str, float | None], dict[str, int]]:
    ious: dict[str, float | None] = {}
    unions: dict[str, int] = {}
    for cls in range(1, N_CLASSES):
        tp = int(np.count_nonzero((pred == cls) & (gt == cls)))
        fp = int(np.count_nonzero((pred == cls) & (gt != cls)))
        fn = int(np.count_nonzero((pred != cls) & (gt == cls)))
        union = tp + fp + fn
        unions[str(cls)] = union
        ious[str(cls)] = tp / union if union else None
    return ious, unions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/raw/semanticposs/dataset")
    parser.add_argument("--sequence", default="00")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument(
        "--model", default="data/cache/models/salsanext-onnx-float/salsanext.onnx"
    )
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--intensity-scale", type=float, default=255.0)
    parser.add_argument(
        "--output",
        default="reports/closure/semantic/salsanext-poss-metrics.json",
    )
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_absolute():
        # Allow pointing at the shared checkout when a worktree has no local data.
        candidate = _REPO_ROOT / root
        root = (
            candidate
            if candidate.is_dir()
            else Path("/home/arjun/Captain/SIH/Lidar") / root
        )
    model_path = Path(args.model)
    if not model_path.is_absolute():
        candidate = _REPO_ROOT / model_path
        model_path = (
            candidate
            if candidate.is_file()
            else Path("/home/arjun/Captain/SIH/Lidar") / model_path
        )
    companion = model_path.parent / "salsanext.data"

    scan_dir = root / "sequences" / args.sequence / "velodyne"
    label_dir = root / "sequences" / args.sequence / "labels"
    scans = sorted(scan_dir.glob("*.bin"))[: args.frames]
    if not scans:
        raise FileNotFoundError(f"no scans in {scan_dir}")
    for scan in scans:
        if not (label_dir / f"{scan.stem}.label").is_file():
            raise FileNotFoundError(f"missing label for {scan.name}")

    provider = SalsaNextSemanticProvider(
        model_path, threads=args.threads, intensity_scale=args.intensity_scale
    )
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    all_pred: list[np.ndarray] = []
    all_gt: list[np.ndarray] = []
    all_valid: list[np.ndarray] = []
    all_range: list[np.ndarray] = []
    all_conf: list[np.ndarray] = []
    lat_ms: list[float] = []
    per_frame: list[dict[str, object]] = []
    # Warmup (untimed) so p50/p95 reflect steady-state CPU inference.
    warmup = np.fromfile(scans[0], dtype=np.float32).reshape(-1, 4)
    provider.infer(warmup)

    total_pitch_min, total_pitch_max = float("inf"), float("-inf")
    for scan in scans:
        points = np.fromfile(scan, dtype=np.float32).reshape(-1, 4)
        raw = np.fromfile(label_dir / f"{scan.stem}.label", dtype=np.uint32)
        assert raw.shape[0] == points.shape[0]
        gt = map_dataset_labels(raw & 0xFFFF, SEMANTIC_POSS_LABELS)
        depth = np.linalg.norm(points[:, :3], axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            pitch = np.degrees(
                np.arcsin(np.clip(points[:, 2] / np.maximum(depth, 1e-9), -1, 1))
            )
        finite = depth > 0
        total_pitch_min = min(total_pitch_min, float(pitch[finite].min()))
        total_pitch_max = max(total_pitch_max, float(pitch[finite].max()))
        started = time.perf_counter()
        result = provider.infer(points)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert result.semantic_class.shape == gt.shape
        _, _, _, valid = project_scan(points, intensity_scale=args.intensity_scale)
        lat_ms.append(elapsed_ms)
        all_pred.append(result.semantic_class)
        all_conf.append(result.semantic_confidence)
        all_gt.append(gt)
        all_valid.append(valid)
        all_range.append(depth)
        pred_hist = {
            str(k): int(v)
            for k, v in zip(*np.unique(result.semantic_class, return_counts=True))
        }
        per_frame.append(
            {
                "frame_id": scan.stem,
                "points": int(points.shape[0]),
                "in_fov_fraction": float(valid.mean()),
                "latency_ms": elapsed_ms,
                "pred_histogram": pred_hist,
            }
        )

    pred = np.concatenate(all_pred)
    conf = np.concatenate(all_conf)
    gt = np.concatenate(all_gt)
    valid = np.concatenate(all_valid)
    depth = np.concatenate(all_range)
    labelled = gt != 0

    ious, unions = per_class_iou(pred[labelled], gt[labelled])
    scored = [v for v in ious.values() if v is not None]
    ious_fov, _ = per_class_iou(pred[labelled & valid], gt[labelled & valid])
    scored_fov = [v for v in ious_fov.values() if v is not None]
    range_binned = {}
    for lo, hi in RANGE_BINS:
        mask = labelled & valid & (depth >= lo) & (depth < hi)
        b_ious, _ = per_class_iou(pred[mask], gt[mask])
        b_scored = [v for v in b_ious.values() if v is not None]
        range_binned[f"{lo:g}-{hi:g}m" if np.isfinite(hi) else f"{lo:g}m+"] = {
            "points": int(mask.sum()),
            "mean_iou": float(np.mean(b_scored)) if b_scored else None,
        }

    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    gt_hist = {str(k): int(v) for k, v in zip(*np.unique(gt, return_counts=True))}
    pred_hist_all = {
        str(k): int(v) for k, v in zip(*np.unique(pred, return_counts=True))
    }
    artifact = {
        "method": "direct SalsaNextSemanticProvider.infer on sensor-frame points; "
        "pipeline dataset gate bypassed for measurement only",
        "dataset": {
            "name": "semanticposs",
            "version": "SemanticPOSS-v1.0-LABEL_DICT",
            "root": str(root),
            "sequence": args.sequence,
            "frames": [s.stem for s in scans],
            "num_frames": len(scans),
            "total_points": int(pred.size),
        },
        "taxonomy": {
            "version": TAXONOMY_VERSION,
            "mapping": "SEMANTIC_POSS_LABELS raw->Veyra(SemanticKITTI-learning)",
            "unmapped_raw_become_unknown": True,
        },
        "checkpoint": {
            "model_sha256": _sha256(model_path),
            "companion_sha256": _sha256(companion) if companion.is_file() else None,
            "contract": model_contract(),
            "threads": args.threads,
            "intensity_scale": args.intensity_scale,
        },
        "sensor_evidence": {
            "pitch_deg_min": total_pitch_min,
            "pitch_deg_max": total_pitch_max,
            "in_model_fov_fraction": float(valid.mean()),
        },
        "metrics": {
            "all_return_mean_iou_1_19": float(np.mean(scored)) if scored else None,
            "all_return_accuracy_labelled": float(
                np.mean(pred[labelled] == gt[labelled])
            ),
            "all_return_accuracy_all": float(np.mean(pred == gt)),
            "model_fov_mean_iou_1_19": float(np.mean(scored_fov))
            if scored_fov
            else None,
            "model_fov_coverage_fraction": float(valid.mean()),
            "per_class_iou": ious,
            "per_class_union_points": unions,
            "model_fov_per_class_iou": ious_fov,
            "range_binned_model_fov_miou": range_binned,
            "gt_histogram": gt_hist,
            "pred_histogram": pred_hist_all,
            "pred_confidence_mean_on_predicted_known": float(conf[pred != 0].mean())
            if np.any(pred != 0)
            else None,
            "pred_confidence_p50_on_predicted_known": float(np.median(conf[pred != 0]))
            if np.any(pred != 0)
            else None,
        },
        "performance": {
            "latency_ms_p50": float(np.median(lat_ms)),
            "latency_ms_p95": float(np.percentile(lat_ms, 95)),
            "latency_ms_per_frame": [round(v, 1) for v in lat_ms],
            "peak_rss_mb": round(rss_after / 1024.0, 1),
            "rss_delta_mb": round((rss_after - rss_before) / 1024.0, 1),
        },
        "per_frame": per_frame,
        "hardware": {
            "cpu": _cpu_model(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "software": {
            "git_sha": _git_sha(),
            "onnxruntime": __import__("onnxruntime").__version__,
            "numpy": np.__version__,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, default=str))
    print(
        f"frames={len(scans)} points={pred.size} "
        f"all-mIoU={artifact['metrics']['all_return_mean_iou_1_19']:.4f} "
        f"fov-mIoU={artifact['metrics']['model_fov_mean_iou_1_19']:.4f} "
        f"acc={artifact['metrics']['all_return_accuracy_labelled']:.4f} "
        f"p50={artifact['performance']['latency_ms_p50']:.0f}ms "
        f"p95={artifact['performance']['latency_ms_p95']:.0f}ms "
        f"rss={artifact['performance']['peak_rss_mb']}MB"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
