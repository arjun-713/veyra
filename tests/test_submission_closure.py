from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


def row(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "capability": "Example capability",
        "current_percent": 0,
        "target_percent": 100,
        "acceptance_criteria": "An executable acceptance criterion.",
        "tests_required": "A focused regression test.",
        "real_data_evidence_required": "A real input artifact.",
        "benchmark_required": "A benchmark artifact.",
        "platform_evidence_required": "Linux",
        "status": "UNVERIFIED",
        "blocking_issue": "Evidence has not been collected.",
        "evidence_artifact": None,
        "closing_commit": None,
    }
    value.update(overrides)
    return value


class SubmissionClosureTests(unittest.TestCase):
    def run_validator(
        self, payload: dict[str, object]
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "closure.json"
            report.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, "scripts/validate_submission_closure.py", str(report)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_validator_accepts_an_open_well_formed_row(self):
        report = Path(__file__).resolve().parents[1] / "reports/submission_closure.json"
        result = subprocess.run(
            [sys.executable, "scripts/validate_submission_closure.py", str(report)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validator_rejects_missing_row_evidence_contract(self):
        incomplete = row()
        incomplete.pop("benchmark_required")
        result = self.run_validator({"schema_version": 1, "rows": [incomplete]})
        self.assertEqual(result.returncode, 2)
        self.assertIn("benchmark_required", result.stderr)

    def test_validator_rejects_unproven_claimed_completion(self):
        result = self.run_validator(
            {
                "schema_version": 1,
                "rows": [
                    row(current_percent=100, status="CLOSED", blocking_issue=None)
                ],
            }
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("evidence_artifact", result.stderr)


if __name__ == "__main__":
    unittest.main()
