"""Serialize one adapter ObservationFrame and emit inspectable evidence.

This utility deliberately reports source provenance and serialization digest;
it does not synthesize pose, time, labels, quality, or model metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Direct invocation from the repository root's scripts/ directory does not
# otherwise place the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.protocol import stream_file
from datasets.semanticposs.adapter import SemanticPOSSDataset


PRIMARY_ROOT = Path("/home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset_root = args.dataset_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    adapter = SemanticPOSSDataset(dataset_root, sequences=[args.sequence])
    frame = adapter.load_frame(args.sequence, args.frame_id)
    digest = stream_file([frame], output)
    source_kind = (
        "real_semanticposs_fixture"
        if dataset_root == PRIMARY_ROOT.resolve()
        else "synthetic_fixture"
    )
    serialized_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    report = {
        "source_kind": source_kind,
        "dataset_root": str(dataset_root),
        "sequence": frame.sequence,
        "frame_id": frame.frame_id,
        "point_count": int(frame.points.shape[0]),
        "serialized_path": str(output),
        "serialized_sha256": serialized_sha256,
        "record_digest": digest,
        "provenance": {
            "coordinate_frame": frame.provenance.coordinate_frame,
            "timestamp_source": frame.provenance.timestamp_source,
            "pose_source": frame.provenance.pose_source,
            "calibration_source": frame.provenance.calibration_source,
            "label_source": frame.provenance.label_source,
        },
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
