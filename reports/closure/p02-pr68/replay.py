"""Bounded real KITTI paired clearing experiment, no modified scans or timestamps."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmarks.protocol import binary_frame_bytes
from datasets.semantickitti import SemanticKITTIDataset
from perception.pipeline import PerceptionPipeline

os.chdir(ROOT)
adapter = SemanticKITTIDataset(ROOT / "data/raw/semantickitti/dataset")
config = {
    "semantic": {"mode": "ground_truth"},
    "ground": {
        "enabled": True,
        "parameter_overrides": {"min_range": 0.0, "max_range": 100.0},
    },
    "terrain": {"enabled": True},
    "temporal": {"enabled": True, "exclude_classes": [9, 10, 11, 12, 17]},
    "required_stages": ["semantic", "ground", "terrain", "temporal"],
}
pipeline = PerceptionPipeline.from_config(config)
processes = []
records = []
digests = {}
seed = {}
try:
    for enabled in (False, True):
        cmd = [
            os.environ.get("VEYRA_GHOST_PROBE", "/tmp/veyra_persistent_probe"),
            "--policy",
            "distance_lod",
            "--sensor-height",
            "0",
        ]
        if enabled:
            cmd.append("--clear-free-space")
        processes.append(
            subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        )
    for number in range(43, 55):
        frame = adapter.load_frame("08", f"{number:06d}", max_range_m=100)
        assert (
            frame.provenance.timestamp_source == "dataset"
            and frame.provenance.pose_source == "dataset"
        )
        assert frame.provenance.coordinate_frame == "world"
        for path in (
            ROOT
            / "data/raw/semantickitti/dataset/sequences/08/velodyne"
            / f"{number:06d}.bin",
            ROOT
            / "data/raw/semantickitti/dataset/sequences/08/labels"
            / f"{number:06d}.label",
        ):
            digests[str(path.relative_to(ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        if not seed:
            masks = {
                "moving_car_4": (frame.raw_semantic_class == 252)
                & (frame.instance_id == 4),
                "parked_cars": frame.raw_semantic_class == 10,
            }
            for name, mask in masks.items():
                bins = np.unique(
                    np.floor(frame.points[mask, :2].astype(np.float64) / 0.05).astype(
                        np.int64
                    ),
                    axis=0,
                )
                seed[name] = (bins.astype(np.float64) + 0.5) * 0.05
                for process in processes:
                    for x, y in seed[name]:
                        process.stdin.write(f"ROI {name} {x:.17g} {y:.17g}\n".encode())
                    process.stdin.flush()
        output = pipeline.process(frame)
        packet = binary_frame_bytes(output.frame)
        pair = []
        for process in processes:
            process.stdin.write(packet)
            process.stdin.flush()
            report = json.loads(process.stdout.readline())
            assert report["snapshot"]["invariant_no_parent_descendant_overlap"]
            assert report["frame_metrics"][-1]["point_conservation"]["holds"]
            pair.append(report)
        assert pair[0]["snapshot"]["point_count"] == pair[1]["snapshot"]["point_count"]
        gt_bins = np.unique(
            np.floor(
                frame.points[
                    (frame.raw_semantic_class == 252) & (frame.instance_id == 4), :2
                ].astype(np.float64)
                / 0.05
            ).astype(np.int64),
            axis=0,
        )
        initial = set(
            map(tuple, np.floor(seed["moving_car_4"] / 0.05).astype(np.int64))
        )
        now = set(map(tuple, gt_bins))
        records.append(
            {
                "frame_id": frame.frame_id,
                "timestamp": frame.timestamp,
                "points": len(frame.points),
                "pipeline_status": asdict(output.status),
                "perception_timings_ms": output.timings_ms,
                "unique_track_ids": len(
                    np.unique(output.frame.track_id[output.frame.track_id >= 0])
                ),
                "moving_car_seed_bins_still_observed": len(initial & now),
                "disabled": pair[0],
                "enabled": pair[1],
            }
        )
        print(
            number,
            "clear",
            pair[1].get("snapshot", {}).get("clearing"),
            "seed",
            pair[1]["seed_support"],
            flush=True,
        )
finally:
    for process in processes:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

result = {
    "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "dirty": subprocess.check_output(
        ["git", "status", "--porcelain"], text=True
    ).strip(),
    "dataset": "semantickitti",
    "sequence": "08",
    "frame_ids": list(range(43, 55)),
    "semantic_mode": "ground_truth_evaluation_only",
    "pipeline_config": config,
    "sensor_origin": "adapter pose is LiDAR origin; sensor-height override 0, not a second 1.8m offset",
    "hardware": platform.uname()._asdict(),
    "python": sys.version,
    "input_sha256": digests,
    "seed_support_definition": "unique 5cm XY bins from first frame GT label; resident-leaf occupancy sampled at bin centers, not object IoU",
    "no_orphans": all(p.poll() is not None for p in processes),
    "records": records,
}
Path(
    os.environ.get("VEYRA_CLEARING_REPORT", "/tmp/veyra-p02-real-result.json")
).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
