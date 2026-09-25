"""Bounded real CENet-vs-GT semantic-signal sensitivity experiment.

Ground, terrain, and temporal stages are disabled in BOTH arms to isolate the
semantic signal. This does not establish complete production-pipeline quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import yaml

from benchmarks.run_benchmark import _fine_reference_from_snapshot, run as benchmark_run
from benchmarks.utility_hardcore_run import (
    _args,
    _groups,
    _score_group,
    _verified_sources,
    load_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--frames",
        type=int,
        default=4,
        help="bounded prefix of the frozen ten-frame challenge window",
    )
    parser.add_argument(
        "--binary", type=Path, default=Path("build/apps/benchmark/veyra_benchmark")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/utility-hardcore/gt_vs_cenet.json")
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    checkpoint = args.checkpoint.resolve()
    binary = args.binary if args.binary.is_absolute() else repo / args.binary
    output = args.output if args.output.is_absolute() else repo / args.output
    if not checkpoint.is_file() or not binary.is_file():
        parser.error("checkpoint and benchmark binary must exist")
    environment_checkpoint = os.environ.get("VEYRA_CENET_CHECKPOINT", "").strip()
    if environment_checkpoint and Path(environment_checkpoint).resolve() != checkpoint:
        parser.error("VEYRA_CENET_CHECKPOINT would override the selected checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    manifest = load_manifest(repo / "benchmarks/utility_challenge_manifest.json")
    group = next(
        (
            items
            for items in _groups(manifest["challenges"])
            if items[0]["dataset"] == "semanticposs"
            and any(item["challenge_type"] == "semantic_object" for item in items)
        ),
        None,
    )
    if group is None:
        parser.error("frozen manifest has no SemanticPOSS object challenge")
    window_count = group[0]["frame_end_exclusive"] - group[0]["frame_start"]
    if not 2 <= args.frames <= window_count:
        parser.error(
            f"--frames must be between 2 and frozen window size {window_count}"
        )
    if (
        not group[0]["frame_start"]
        <= int(group[0]["source_frame_id"])
        < group[0]["frame_start"] + args.frames
    ):
        parser.error("selected frame would be outside the bounded prefix")
    _verified_sources(repo, group)
    original = yaml.safe_load((repo / "configs/perception.yaml").read_text())
    original["ground"]["enabled"] = False
    original["terrain"]["enabled"] = False
    original["temporal"]["enabled"] = False
    original["required_stages"] = ["semantic"]
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="veyra-cenet-sensitivity-") as temporary:
        for mode in ("ground_truth", "cenet"):
            print(
                f"semantic isolation {mode}: {args.frames} real SemanticPOSS frames",
                flush=True,
            )
            config = yaml.safe_load(yaml.safe_dump(original))
            config["semantic"] = {"mode": mode}
            if mode == "cenet":
                config["semantic"].update(
                    {
                        "checkpoint": str(checkpoint),
                        "checkpoint_sha256": digest,
                        "threads": 2,
                    }
                )
            path = Path(temporary) / f"{mode}.yaml"
            path.write_text(yaml.safe_dump(config, sort_keys=True))
            request = _args(
                repo,
                binary,
                group[0],
                ["uniform5", "distance_lod", "utility_lod"],
                1,
                1,
                path,
            )
            request.count = args.frames
            result = benchmark_run(request)
            actual = result["perception"]["status"]["semantic"]
            if mode == "cenet" and actual != "model":
                raise RuntimeError(f"CENet silently unavailable/fell back: {actual}")
            reference = _fine_reference_from_snapshot(
                result["policies"]["uniform5"]["runs"][-1]["snapshot"]
            )
            rows = _score_group(repo, group, result, result, reference)
            outcomes[mode] = {
                "actual_semantic_status": actual,
                "perception": result["perception"],
                "provenance": result["provenance"],
                "rows": [
                    row
                    for row in rows
                    if row["policy"] in {"distance_lod", "utility_lod"}
                ],
            }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment": "semantic-only isolation; no ground/terrain/temporal in either arm",
                "challenge_ids": [item["id"] for item in group],
                "evaluated_frame_range": [
                    group[0]["frame_start"],
                    group[0]["frame_start"] + args.frames,
                ],
                "checkpoint_sha256": digest,
                "results": outcomes,
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    print(f"GT and real CENet completed on {len(group)} frozen challenges: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
