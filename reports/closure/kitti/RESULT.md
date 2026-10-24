# Closure — kitti (SemanticKITTI real-data validation)

Status: **PARTIAL PASS** — official val-sequence labels + poses verified;
full scan replay remains login-gated. No fake timestamps. No invented numbers.

## What was done

- Downloaded the official public SemanticKITTI label archive
  (`https://www.semantic-kitti.org/assets/data_odometry_labels.zip`,
  179298418 bytes, sha256
  `408ec524…7e6dda`) and streamed-validated **sequence 08** (the published
  val split: `valid: [8]` in `semantic-kitti-api/config/semantic-kitti.yaml`).
- Verified 4071 label files vs 4071 `poses.txt` lines (exact 1:1 sequential
  alignment), label sizes consistent with ~92k–128k points/frame, all raw IDs
  inside the v1.1 `learning_map` (moving IDs 252–254/259 present), all 4071
  poses finite + rigid, frame-to-frame motion smooth
  (median 0.85 m, p99 1.26 m, max 1.35 m, zero >5 m jumps).
- Proved the adapter's KITTI pose path parses the official seq08 pose line
  into the canonical world frame (`coordinate_frame=world`,
  `pose_source=dataset`); absent timestamps stay `None`/`absent`.
- Ran the sequential replay mechanics on the legal equivalent sharing the
  same KITTI-contract base class: local SemanticPOSS sequence 00, 8 frames —
  numeric ordering, determinism, world-frame provenance, scan/label
  alignment; timestamps honestly absent, never generated.
- Added `--labels-only` mode to `datasets/download_semantickitti.sh` for the
  public labels+poses subset; full-scan mode unchanged.
- Added 3 adapter tests (absent-timestamp, world-requires-pose, v1.1 taxonomy).

## Root cause of the remaining gap

KITTI benchmark `download.php` for `data_odometry_velodyne.zip` (80 GB),
`data_odometry_calib.zip`, and therefore `times.txt` returns an email-gated
form without credentials — verified 2026-09-17. No anonymous fetch exists, so
official scans, `Tr` calibration, and dataset timestamps could not be obtained
by supported means in this session. Temporal `dt` on KITTI data stays blocked
until an operator supplies authenticated archive URLs via `--data-url`.

## Files changed (ownership-respecting)

- `datasets/semantickitti/*` (README status only; adapter untouched)
- `datasets/download_semantickitti.sh` (`--labels-only`, provenance notes)
- `tests/test_semantickitti_adapter.py` (+3 metadata/taxonomy tests)
- Historical dataset-status documentation; current contract:
  [dataset validation](../../../datasets/README.md#metadata-and-validation).
- `reports/closure/kitti/validation_seq08.json` (new evidence artifact)

Untouched: `perception/semantic/*`, `src/map/*`, `src-tauri/*`.

## Tests

`python3 -m pytest tests/test_semantickitti_adapter.py
tests/test_dataset_validation.py tests/test_taxonomy.py
tests/test_semanticposs_adapter.py` → **31 passed, 3 skipped**
(skips = real-data smoke tests; worktree holds no local data by policy).
KITTI adapter file alone: 7 passed, 1 skipped.

## Real data

Official SemanticKITTI v1.1 val sequence 08 labels + SuMa poses (CC BY-NC-SA;
cite Behley et al. ICCV19 + Geiger et al. CVPR12). Archive kept outside git
(`/tmp/opencode`, gitignored); only the JSON evidence is committed.

## Gaps / next steps for temporal unblock

1. Operator provides authenticated KITTI velodyne + calib URLs → install via
   `download_semantickitti.sh`, re-run smoke + `times.txt` check.
2. Then: scan/label byte-alignment on seq08, `Tr`-conjugated world frame with
   real calibration, timestamp monotonicity → temporal `dt` unblocked.

Raw artifact: `reports/closure/kitti/validation_seq08.json`.
