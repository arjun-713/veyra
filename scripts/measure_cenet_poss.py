"""CENet native Pandora checkpoint measurement on SemanticPOSS frames.

Run from the repository root::

    python3 scripts/measure_cenet_poss.py --sequence 00 --frames 16 \
        --checkpoint data/cache/models/cenet-poss/SENet_valid_best \
        --output reports/closure/semantic-finetune/cenet-poss-metrics.json

Requires torch (explicit, CPU) and the published CENet SemanticPOSS weights
at ``--checkpoint`` (never committed; provenance recorded in the artifact).
Reads raw sensor-frame ``.bin``/``.label`` pairs directly so the i-th point
aligns with the i-th label. Reports the Veyra projection (directly
comparable with the SalsaNext closure artifact), the native head view, and
the 8 coarse reporting groups, all overall and range-binned.
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
_FALLBACK_ROOT = Path("/home/arjun/Captain/SIH/Lidar")
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if _FALLBACK_ROOT != _REPO_ROOT and str(_FALLBACK_ROOT) not in sys.path:
    sys.path.append(str(_FALLBACK_ROOT))
_REPOS = [_REPO_ROOT, _FALLBACK_ROOT]

import numpy as np

from datasets.common.taxonomy import (
    SEMANTIC_POSS_LABELS,
    TAXONOMY_VERSION,
    map_dataset_labels,
)
from perception.semantic.cenet import CENetSemanticProvider, model_contract
from perception.semantic.pandora import (
    GROUP_INDEX,
    GROUP_NAMES,
    fold_to_native,
    native_to_group_ids,
    project_pandora_beams,
)

VEYRA_CLASSES = 20
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
            ["git", "-C", str(_REPOS[0]), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _resolve(path_arg: str, *, kind: str) -> Path:
    path = Path(path_arg)
    if path.is_absolute():
        return path
    for repo in _REPOS:
        candidate = repo / path
        if kind == "dir" and candidate.is_dir():
            return candidate
        if kind == "file" and candidate.is_file():
            return candidate
    return _REPOS[0] / path


def prf_per_label(pred, gt, labels):
    out = {}
    for cls in labels:
        tp = int(np.count_nonzero((pred == cls) & (gt == cls)))
        fp = int(np.count_nonzero((pred == cls) & (gt != cls)))
        fn = int(np.count_nonzero((pred != cls) & (gt == cls)))
        union = tp + fp + fn
        if union == 0:
            out[str(cls)] = {"iou": None, "precision": None, "recall": None,
                             "f1": None, "support": 0, "union": 0}
            continue
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        out[str(cls)] = {
            "iou": tp / union, "precision": precision, "recall": recall, "f1": f1,
            "support": int(np.count_nonzero(gt == cls)), "union": union,
        }
    return out


def _mean(values):
    scored = [v for v in values if v is not None]
    return float(np.mean(scored)) if scored else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/raw/semanticposs/dataset")
    parser.add_argument("--sequence", default="00")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument(
        "--checkpoint", default="data/cache/models/cenet-poss/SENet_valid_best"
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument(
        "--output",
        default="reports/closure/semantic-finetune/cenet-poss-metrics.json",
    )
    args = parser.parse_args()

    root = _resolve(args.root, kind="dir")
    checkpoint = _resolve(args.checkpoint, kind="file")
    scan_dir = root / "sequences" / args.sequence / "velodyne"
    label_dir = root / "sequences" / args.sequence / "labels"
    scans = sorted(scan_dir.glob("*.bin"))[: args.frames]
    if not scans:
        raise FileNotFoundError(f"no scans in {scan_dir}")

    provider = CENetSemanticProvider(checkpoint, threads=args.threads)
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    all_pred, all_gt, all_raw_pred, all_raw_gt = [], [], [], []
    all_group_pred, all_group_gt, all_range, all_conf = [], [], [], []
    lat_ms, per_frame = [], []
    warmup = np.fromfile(scans[0], dtype=np.float32).reshape(-1, 4)
    provider.infer(warmup)

    coverages = []
    for scan in scans:
        points = np.fromfile(scan, dtype=np.float32).reshape(-1, 4)
        raw = np.fromfile(label_dir / f"{scan.stem}.label", dtype=np.uint32)
        assert raw.shape[0] == points.shape[0]
        raw_ids = (raw & 0xFFFF).astype(np.int64)
        gt_veyra = map_dataset_labels(raw_ids, SEMANTIC_POSS_LABELS)
        gt_native = fold_to_native(raw_ids)
        depth = np.linalg.norm(points[:, :3], axis=1)
        started = time.perf_counter()
        result = provider.infer(points)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert result.semantic_class.shape == gt_veyra.shape
        raw_pred, _, _ = provider.infer_raw(points)
        group_pred = native_to_group_ids(fold_to_native(raw_pred))
        _, _, valid = project_pandora_beams(points)
        coverages.append(float(valid.mean()))
        lat_ms.append(elapsed_ms)
        all_pred.append(result.semantic_class)
        all_conf.append(result.semantic_confidence)
        all_gt.append(gt_veyra)
        all_raw_pred.append(raw_pred)
        all_raw_gt.append(raw_ids)
        all_group_pred.append(group_pred)
        all_group_gt.append(native_to_group_ids(gt_native))
        all_range.append(depth)
        per_frame.append(
            {
                "frame_id": scan.stem,
                "points": int(points.shape[0]),
                "beam_fov_fraction": float(valid.mean()),
                "latency_ms": round(elapsed_ms, 1),
                "pred_histogram_veyra": {
                    str(k): int(v)
                    for k, v in zip(*np.unique(result.semantic_class, return_counts=True))
                },
            }
        )

    pred = np.concatenate(all_pred)
    conf = np.concatenate(all_conf)
    gt = np.concatenate(all_gt)
    raw_pred = np.concatenate(all_raw_pred)
    raw_gt = np.concatenate(all_raw_gt)
    group_pred = np.concatenate(all_group_pred)
    group_gt = np.concatenate(all_group_gt)
    depth = np.concatenate(all_range)
    labelled = gt != 0

    veyra = prf_per_label(pred[labelled], gt[labelled], list(range(1, VEYRA_CLASSES)))
    native_ids = sorted(int(v) for v in np.unique(
        np.concatenate([fold_to_native(raw_pred), fold_to_native(raw_gt)])))
    native = prf_per_label(
        fold_to_native(raw_pred), fold_to_native(raw_gt), native_ids)
    groups = prf_per_label(group_pred, group_gt, list(range(len(GROUP_NAMES))))
    range_binned = {}
    for lo, hi in RANGE_BINS:
        key = f"{lo:g}-{hi:g}m" if np.isfinite(hi) else f"{lo:g}m+"
        mask = labelled & (depth >= lo) & (depth < hi)
        b = prf_per_label(pred[mask], gt[mask], list(range(1, VEYRA_CLASSES)))
        bg = prf_per_label(
            group_pred[mask], group_gt[mask], list(range(len(GROUP_NAMES))))
        range_binned[key] = {"points": int(mask.sum()),
                             "veyra_miou_1_19": _mean([v["iou"] for v in b.values()]),
                             "veyra_prf": b,
                             "group_miou": _mean([v["iou"] for v in bg.values()]),
                             "group_prf": bg}

    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    known = pred != 0
    correct = pred[labelled] == gt[labelled]
    artifact = {
        "method": "direct CENetSemanticProvider.infer on sensor-frame points "
        "(tag-free beam projection, per-point argmax, no KNN); provider dataset "
        "gate accepts semanticposs",
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
            "native_head": "14 CENet POSS learning IDs -> raw via learning_map_inv; "
            "raw 0 + unmapped fold to unknown",
            "groups": {name: GROUP_INDEX[name] for name in GROUP_NAMES},
            "unmapped_raw_become_unknown": True,
        },
        "checkpoint": {
            "path": str(checkpoint),
            "sha256": _sha256(checkpoint),
            "contract": model_contract(),
            "threads": args.threads,
        },
        "sensor_evidence": {
            "beam_fov_fraction": float(np.mean(coverages)),
        },
        "metrics": {
            "veyra_all_return_mean_iou_1_19": _mean([v["iou"] for v in veyra.values()]),
            "veyra_accuracy_labelled": float(np.mean(correct)),
            "veyra_accuracy_all": float(np.mean(pred == gt)),
            "veyra_per_class": veyra,
            "native_accuracy": float(
                np.mean(fold_to_native(raw_pred) == fold_to_native(raw_gt))),
            "native_mean_iou": _mean(
                [v["iou"] for k, v in native.items() if k != "0"]),
            "native_per_class": native,
            "group_accuracy": float(np.mean(group_pred == group_gt)),
            "group_mean_iou": _mean([v["iou"] for v in groups.values()]),
            "group_prf": groups,
            "range_binned": range_binned,
            "gt_histogram_veyra": {
                str(k): int(v) for k, v in zip(*np.unique(gt, return_counts=True))
            },
            "pred_histogram_veyra": {
                str(k): int(v) for k, v in zip(*np.unique(pred, return_counts=True))
            },
            "gt_histogram_native": {
                str(k): int(v)
                for k, v in zip(*np.unique(fold_to_native(raw_gt), return_counts=True))
            },
            "pred_histogram_native": {
                str(k): int(v)
                for k, v in zip(*np.unique(fold_to_native(raw_pred), return_counts=True))
            },
            "pred_confidence_mean_on_predicted_known": float(conf[known].mean())
            if np.any(known)
            else None,
            "pred_confidence_p50_on_predicted_known": float(np.median(conf[known]))
            if np.any(known)
            else None,
            "pred_confidence_mean_on_correct": float(conf[labelled][correct].mean())
            if np.any(correct)
            else None,
            "pred_confidence_mean_on_wrong": float(conf[labelled][~correct].mean())
            if np.any(~correct)
            else None,
        },
        "performance": {
            "latency_ms_p50": float(np.median(lat_ms)),
            "latency_ms_p95": float(np.percentile(lat_ms, 95)),
            "latency_ms_p99": float(np.percentile(lat_ms, 99)),
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
            "numpy": np.__version__,
            "torch": __import__("torch").__version__,
        },
    }
    out = Path(args.output)
    if not out.is_absolute():
        out = _REPOS[0] / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, default=str))
    m = artifact["metrics"]
    print(
        f"frames={len(scans)} points={pred.size} "
        f"veyra-mIoU={m['veyra_all_return_mean_iou_1_19']:.4f} "
        f"acc={m['veyra_accuracy_labelled']:.4f} "
        f"p50={artifact['performance']['latency_ms_p50']:.0f}ms "
        f"p95={artifact['performance']['latency_ms_p95']:.0f}ms"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
