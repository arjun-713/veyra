#!/usr/bin/env python3
"""Validate Veyra's authoritative SIH submission closure scorecard."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_CAPABILITIES = {
    "Raw LiDAR ingestion",
    "Dataset-agnostic architecture",
    "Neural semantic segmentation",
    "Semantic quality",
    "Ground segmentation",
    "Drivable/non-drivable terrain",
    "Static obstacles",
    "Dynamic classes",
    "Real temporal motion",
    "Variable-resolution 2.5D map",
    "Mixed-resolution correctness",
    "Split/merge preservation",
    "Rolling 100 m map",
    "5/10/20/40 hierarchy",
    "DistanceLOD",
    "UtilityLOD",
    "Resource governor",
    "Reversible detail-preserving refinement",
    "Memory reduction proof",
    "Measured 3D baseline comparison",
    "Performance/FPS",
    "Range-binned evaluation",
    "Benchmark quality",
    "SemanticPOSS validation",
    "RELLIS validation",
    "SemanticKITTI validation",
    "Generic/custom dataset path",
    "Tauri desktop",
    "UI functionality",
    "Telemetry correctness",
    "Renderer stability",
    "Runtime supervision",
    "Electron removal",
    "Shared Control API",
    "CLI",
    "MCP",
    "Security",
    "Ubuntu/Debian",
    "Fedora/RPM",
    "Windows",
    "macOS",
    "Packaging",
    "Release readiness",
    "Test quality",
    "CI",
    "Documentation",
    "Reproducibility",
    "Demo readiness",
}

REQUIRED_ROW_KEYS = {
    "capability",
    "current_percent",
    "target_percent",
    "acceptance_criteria",
    "tests_required",
    "real_data_evidence_required",
    "benchmark_required",
    "platform_evidence_required",
    "status",
    "blocking_issue",
    "evidence_artifact",
    "closing_commit",
}

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")


def validate(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return [*errors, "rows must be a list"]

    capabilities: list[str] = []
    for index, row in enumerate(rows):
        prefix = f"rows[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = REQUIRED_ROW_KEYS.difference(row)
        if missing:
            errors.append(f"{prefix} is missing: {', '.join(sorted(missing))}")
            continue
        capability = row["capability"]
        if not isinstance(capability, str) or not capability:
            errors.append(f"{prefix}.capability must be a non-empty string")
            continue
        capabilities.append(capability)
        if row["target_percent"] != 100:
            errors.append(f"{capability}: target_percent must equal 100")
        current = row["current_percent"]
        if not isinstance(current, int) or not 0 <= current <= 100:
            errors.append(
                f"{capability}: current_percent must be an integer from 0 to 100"
            )
        for key in (
            "acceptance_criteria",
            "tests_required",
            "real_data_evidence_required",
            "benchmark_required",
            "platform_evidence_required",
        ):
            if not isinstance(row[key], str) or not row[key].strip():
                errors.append(f"{capability}: {key} must be a non-empty string")
        if current == 100:
            if row["status"] != "CLOSED":
                errors.append(f"{capability}: a 100% row must have status CLOSED")
            if row["blocking_issue"] not in (None, ""):
                errors.append(
                    f"{capability}: a 100% row cannot retain a blocking_issue"
                )
            evidence = row["evidence_artifact"]
            if not isinstance(evidence, str) or not evidence.strip():
                errors.append(f"{capability}: a 100% row requires evidence_artifact")
            commit = row["closing_commit"]
            if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
                errors.append(f"{capability}: a 100% row requires closing_commit SHA")
        elif row["status"] == "CLOSED":
            errors.append(f"{capability}: only a 100% row may have status CLOSED")
        elif (
            not isinstance(row["blocking_issue"], str)
            or not row["blocking_issue"].strip()
        ):
            errors.append(f"{capability}: an open row requires blocking_issue")

    duplicate_capabilities = {
        capability for capability in capabilities if capabilities.count(capability) > 1
    }
    if duplicate_capabilities:
        errors.append(
            "duplicate capability rows: " + ", ".join(sorted(duplicate_capabilities))
        )
    recorded = set(capabilities)
    missing_capabilities = EXPECTED_CAPABILITIES.difference(recorded)
    unexpected_capabilities = recorded.difference(EXPECTED_CAPABILITIES)
    if missing_capabilities:
        errors.append(
            "required capability rows missing: "
            + ", ".join(sorted(missing_capabilities))
        )
    if unexpected_capabilities:
        errors.append(
            "unexpected capability rows: " + ", ".join(sorted(unexpected_capabilities))
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report",
        nargs="?",
        type=Path,
        default=Path("reports/submission_closure.json"),
    )
    args = parser.parse_args()
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"submission closure report is unreadable: {error}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("submission closure report root must be an object", file=sys.stderr)
        return 2
    errors = validate(payload)
    if errors:
        print("submission closure report is invalid:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    rows = payload["rows"]
    closed = sum(row["current_percent"] == 100 for row in rows)
    print(f"submission closure scorecard: {closed}/{len(rows)} rows closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
