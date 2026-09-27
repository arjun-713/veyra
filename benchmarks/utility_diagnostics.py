"""Bounded real-pipeline UtilityLOD diagnostics, not a quality/FPS benchmark."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.protocol import stream_bytes
from benchmarks.run_benchmark import (
    _git_source_state,
    hardware_metadata,
    load_selection,
)


def validate_selection(start, count):
    if start < 0 or not 1 <= count <= 8:
        raise ValueError("diagnostic selection requires start >= 0 and 1–8 frames")


@contextmanager
def pipeline_logs_to_stderr():
    """Keep native backend writes to descriptor 1 out of the JSON stream.

    Used only by this single-threaded diagnostic CLI, never the runtime server.
    Python redirect_stdout alone cannot capture Patchwork++'s native output.
    """
    sys.stdout.flush()
    saved_stdout = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved_stdout, 1)
        os.close(saved_stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument(
        "--dataset",
        choices=("semanticposs", "rellis3d", "semantickitti"),
        default="semanticposs",
    )
    parser.add_argument("--sequence", default="00")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=2)
    args = parser.parse_args()
    validate_selection(args.start, args.count)
    repo = Path(__file__).resolve().parents[1]
    executable = args.executable.resolve(strict=True)

    def git(*parts):
        return subprocess.check_output(
            ["git", "-C", str(repo), *parts], text=True
        ).strip()

    provenance = {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        **_git_source_state(repo),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware_metadata("utility-diagnostics"),
        "executable": str(executable),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "configs_sha256": {
            name: hashlib.sha256((repo / "configs" / name).read_bytes()).hexdigest()
            for name in (
                "datasets.yaml",
                "perception.yaml",
                "utility_lod.yaml",
                "resource_governor.yaml",
            )
        },
    }
    records = []
    with pipeline_logs_to_stderr():
        frames, _distance, _entry, _timings, radius = load_selection(
            repo,
            args.dataset,
            args.sequence,
            args.start,
            args.count,
            perception_records=records,
        )
    payload, digest = stream_bytes(frames)
    command = [
        str(executable),
        "--policy",
        "utility_lod",
        "--promotion-telemetry",
        "--window-radius",
        str(radius),
        "--warmup-frames",
        "0",
        "--utility-config",
        str(repo / "configs/utility_lod.yaml"),
        "--governor-config",
        str(repo / "configs/resource_governor.yaml"),
    ]
    result = subprocess.run(
        command, input=payload, capture_output=True, timeout=120, check=False, cwd=repo
    )
    if result.returncode:
        raise RuntimeError(
            f"mapper diagnostic failed: {result.stderr.decode(errors='replace')[-2048:]}"
        )
    report = json.loads(result.stdout)
    diagnostics = report.get("promotion_telemetry", {})
    if diagnostics.get("diagnostics_version") != 1:
        raise RuntimeError(
            "mapper lacks Utility diagnostics v1; build the current source first"
        )
    print(
        json.dumps(
            {
                "evidence_scope": "signal_diagnostics_not_quality_or_performance_evidence",
                "provenance": provenance,
                "command": command,
                "selection": {
                    "dataset": args.dataset,
                    "sequence": args.sequence,
                    "start": args.start,
                    "requested_count": args.count,
                    "frames": len(frames),
                    "points": sum(len(frame.points) for frame in frames),
                    "observation_digest": digest,
                },
                "pipeline": records,
                "diagnostics": diagnostics,
                "snapshot": report["snapshot"],
                "governor": report.get("governor"),
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
