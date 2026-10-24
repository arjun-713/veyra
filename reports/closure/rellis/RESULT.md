# RELLIS closure — RESULT

Status: CLOSED (real local data validated; malformed-path diagnostics proven).

## Root cause of prior "0 supported frames"

The scorecard blocker ("current path invalid/unsupported") is stale against the
current checkout. The canonical root `data/raw/rellis3d/Rellis-3D` (see
`configs/datasets.yaml`) exists on this host with 5 complete sequences. No
adapter change was needed for the happy path; this closure adds explicit
malformed-path tests and records measured evidence.

## Real-data proof (measured, host `mallik-fedora`, x86_64, Python 3.14.7)

Inspected actual layout under `<repo-root>/data/raw/rellis3d/`
(do not guess — done via `ls`/`find`/byte-level reads):

- Root: `data/raw/rellis3d/Rellis-3D/{00000,00001,00002,00003,00004}/`
  - `vel_cloud_node_kitti_bin/*.bin` (float32 XYZI) + `vel_cloud_node_semantickitti_label_id/*.label` (uint32)
  - Frame counts: 00000=2842, 00001=2315, 00002=4139, 00003=2180, 00004=2056; total **13532**, all bin/label stems paired (0 unpaired).
  - Sampled frames: 00000/000000 = 36383 pts, finite, intensity [0, 235]; per-sequence sizes ~35–42k pts/frame.
  - No other files under the root (`find` returns only `.bin`/`.label`): **no poses, timestamps, or calibration shipped in this local mirror.**

End-to-end (adapter → canonical `ObservationFrame`), sequence 00000 frame 000000:

- points `(36383, 4)`, finite, intensity byte-scale [0, 235]
- raw low-16 IDs `[0, 3, 4, 17, 18, 19, 23, 31, 33]` → mapped `[0, 6, 14, 15, 17]`, 13808 nonzero; instance high-16 all 0 (RELLIS ships no instances; honestly reported, contract holds)
- provenance `coordinate_frame=lidar, timestamp_source=absent, pose_source=identity_absent, calibration_source=identity_absent, label_source=dataset` — no world pose claimed, no values inferred
- reload is bit-identical (deterministic replay); `max_range_m=100.0` filter path keeps 36279/36383 pts
- taxonomy: versioned `RELLIS-3D-v1.1-learning_map` (`datasets/common/taxonomy.py:RELLIS_LABELS`, 20 entries); all 14 observed raw IDs map; unknown → 0 with 0.0 confidence

Validator: `scripts/validate_dataset_capabilities.py --dataset rellis3d --root <real-root> --sample-limit 2` →
`status=validated_local`, `total_frame_count=13532`, `representative_frame_count=10`, all 5 checks true, labels `available`, pose/timestamp/calibration honestly `unavailable`/`absent`. Artifact: `reports/closure/rellis/replay.json`.

## Calibration / poses / timestamps — where available

None available locally (proven by `find`, validator metadata, and provenance).
The adapter supports them when present (`poses/{seq}.txt` or per-sequence
`poses.txt`, `timestamps/…`, `calib/…` with `Tr:`/`Tr_velo_to_cam:`, validated
as rigid SE(3) and recorded — never composed into the world pose), covered by
unit tests with synthetic metadata. To obtain real RELLIS poses/odometry, use
the official RELLIS-3D release (Texas A&M, UGV rosbags) — not vendored here;
`data/` stays git-ignored and uncommitted.

## Malformed-path diagnostics (useful reason, tested)

- nonexistent root → `FileNotFoundError: RELLIS-3D root does not exist: <path>`
- missing scan dir → `FileNotFoundError: scan directory does not exist: <path>`
- unknown frame → `FileNotFoundError: frame <seq>/<id> does not exist`
- missing label (require_labels) → `FileNotFoundError: label file is missing for <seq>/<id> in <label_dir>`
- truncated scan / non-finite XYZI / scan-label length mismatch / bad timestamp / non-12-value pose / unalignable metadata row counts → `ValueError` naming file + line/row.
- New test: `test_malformed_paths_report_useful_reason` (root/scan-dir/frame/label).

## Files changed (ownership-respecting)

- `tests/test_rellis_adapter.py` — added malformed-path test only
- Historical dataset-status documentation — current [dataset-validation contract](../../../docs/dataset-validation.md) covers layout and absent metadata.
- `reports/closure/rellis/replay.json` + this `RESULT.md` — new evidence
- Untouched: `perception/semantic/*`, `src/map/*`, `src-tauri/*`, `mcp/*`; no data committed

## Tests

- `python3 -m pytest tests/test_rellis_adapter.py -v` → 14 passed, 3 skipped (skips are the relative-path real-data tests; worktree `data/` holds only `.gitkeep` since `data/` is git-ignored — real-data proof above uses the absolute host root)
- Validator (above) → `validated_local`, 13532 frames

## Gaps / follow-ups

- No local poses/timestamps/calibration → map/temporal consumers must treat RELLIS frames as `lidar`-frame unless external odometry is supplied. No action in this closure (inventing poses would violate the evidence rule).
