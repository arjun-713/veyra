"""Frozen production UtilityLOD support-preservation comparison, not V2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from benchmarks.run_benchmark import (
    POLICY_ADAPTERS,
    _fine_reference_from_snapshot,
    _write_csv,
    run,
)
from benchmarks.utility_hardcore_run import (
    _args,
    _score_group,
    _verified_sources,
    load_manifest,
)


def frozen_semantic_window(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Selection is fixed before execution, not chosen from policy outcomes."""
    selected = [
        item
        for item in manifest["challenges"]
        if item["dataset"] == "semanticposs"
        and item["sequence"] == "00"
        and item["frame_start"] == 0
        and item["frame_end_exclusive"] == 10
        and item["challenge_type"] == "semantic_object"
    ]
    if len(selected) != 4:
        raise ValueError(
            "expected the four unchanged frozen SemanticPOSS 00 challenges"
        )
    return selected


def compact(value: Any) -> Any:
    """Retain metrics/provenance, not giant leaf dumps, after regional scoring."""
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if key != "leaves"}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def input_provenance(repo: Path, sequence_root: Path) -> list[dict[str, Any]]:
    files = []
    for frame in range(10):
        for subdir, extension in (("velodyne", "bin"), ("labels", "label")):
            files.append(sequence_root / subdir / f"{frame:06d}.{extension}")
    files.extend(sequence_root / name for name in ("poses.txt", "calib.txt"))
    return [
        {
            "path": str(path.relative_to(repo)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]


def acceptance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    useful = []
    for challenge in sorted({row["challenge_id"] for row in rows}):
        policies = {
            row["policy"]: row for row in rows if row["challenge_id"] == challenge
        }
        baseline, utility = policies["distance_lod"], policies["utility_lod"]
        required = (
            "critical_completion",
            "semantic_retention_critical",
            "critical_accuracy_10cm",
            "critical_chamfer_m",
        )
        if any(row.get(key) is None for row in (baseline, utility) for key in required):
            continue  # unavailable quality cannot establish an advantage
        retention = utility["semantic_retention_critical"]
        if (
            utility["promotion_recall"] > 0
            and utility["promotion_precision"] > 0
            and utility["critical_completion"] >= baseline["critical_completion"]
            and retention is not None
            and retention >= baseline["semantic_retention_critical"]
            and (
                utility["critical_accuracy_10cm"] > baseline["critical_accuracy_10cm"]
                or utility["critical_chamfer_m"] < baseline["critical_chamfer_m"]
            )
        ):
            useful.append(challenge)
    return {
        "useful_frozen_challenges": useful,
        "critical_benefit_gate": "PASS" if useful else "NO_GO",
        "scope": "GT-semantic production-policy potential, not neural or app acceptance",
        "current_main_acceptance": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--dataset-sha256", required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    manifest = load_manifest(repo / "benchmarks/utility_challenge_manifest.json")
    challenges = frozen_semantic_window(manifest)
    _verified_sources(repo, challenges)
    inputs = input_provenance(
        repo, (repo / challenges[0]["source_scan_path"]).parent.parent
    )
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    if digest != args.dataset_sha256:
        raise ValueError(
            "frozen input file digest does not match requested dataset provenance"
        )
    with tempfile.TemporaryDirectory(prefix="veyra-support-comparator-") as temporary:
        config = (repo / "configs/utility_lod.yaml").read_text()
        setting = "detail_sketch_max_regions: 128"
        if config.count(setting) != 1:
            raise ValueError("expected the documented production detail-sketch bound")
        disabled = Path(temporary) / "utility-no-sketch.yaml"
        disabled.write_text(config.replace(setting, "detail_sketch_max_regions: 0"))
        comparator = "utility_no_sketch"
        if comparator in POLICY_ADAPTERS:
            raise ValueError("support comparator already registered")
        POLICY_ADAPTERS[comparator] = replace(
            POLICY_ADAPTERS["utility_lod"],
            name=comparator,
            utility_config=str(disabled),
            suite="support_preservation_control",
            integration_note="same production policy with only detail preservation disabled",
        )
        try:
            options = _args(
                repo,
                args.binary.resolve(),
                challenges[0],
                ["uniform5", "uniform40", "distance_lod", "utility_lod", comparator],
                args.repetitions,
                0,
                repo / "configs/perception.yaml",
            )
            options.require_clean_source = True
            options.dataset_sha256 = args.dataset_sha256
            report = run(options)
            if (
                input_provenance(
                    repo, (repo / challenges[0]["source_scan_path"]).parent.parent
                )
                != inputs
            ):
                raise ValueError("dataset source files changed during measurement")
        finally:
            del POLICY_ADAPTERS[comparator]
    reference = _fine_reference_from_snapshot(
        report["policies"]["uniform5"]["runs"][-1]["snapshot"]
    )
    rows = _score_group(repo, challenges, report, report, reference)
    outcome = acceptance(rows)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "frozen_manifest_sha256": manifest["sha256"],
        "challenges": [item["id"] for item in challenges],
        "acceptance": outcome,
        "critical_rows": [
            {key: value for key, value in row.items() if key != "promotion_telemetry"}
            for row in rows
        ],
        "input_files": inputs,
        "benchmark": compact(report),
        "disabled_comparator_config": config.replace(
            setting, "detail_sketch_max_regions: 0"
        ),
    }
    (output / "acceptance.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    # Scalar CSV columns remain directly readable; structured telemetry is JSON.
    fields = [key for key in rows[0] if key != "promotion_telemetry"]
    with (output / "critical-regions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    _write_csv(output / "benchmark.csv", compact(report))
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
