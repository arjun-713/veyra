# Datasets & Benchmarks — Veyra

Source: `AGENTS.md` §§15–16 and `README.md` Datasets / Benchmark
Philosophy.

## Datasets (contents never committed)

- **SemanticKITTI** — primary dev + quantitative benchmark
  (sequential LiDAR, poses, semantic + moving/static labels,
  range-based eval). Validation status 2026-09-17
  (`reports/closure/kitti/RESULT.md`): official val sequence 08 labels +
  poses verified (4071/4071, taxonomy + sequential motion); Velodyne scans,
  `calib.txt`, and `times.txt` gated on KITTI login, so dataset timestamps
  stay absent and full scan replay is proven via the same-contract local
  SemanticPOSS sequence 00 instead.
- **RELLIS-3D** — off-road terrain validation. Local layout
  `data/raw/rellis3d/Rellis-3D/{00000..00004}/` with
  `vel_cloud_node_kitti_bin/*.bin` + `vel_cloud_node_semantickitti_label_id/*.label`
  (13532 paired frames: 2842/2315/4139/2180/2056; ~35–42k pts/frame).
  `scripts/validate_dataset_capabilities.py --dataset rellis3d` reports
  `validated_local` (alignment, finite byte-scale intensity, deterministic
  order/replay, taxonomy mapping all true). Poses, timestamps, and calibration
  are absent from this local mirror, so frames stay in the `lidar` frame with
  `identity_absent`/`absent` provenance; no pose is inferred. Raw low-16 IDs
  map through the versioned `RELLIS-3D-v1.1-learning_map` table
  (`datasets/common/taxonomy.py:RELLIS_LABELS`); instance high-16 bits are 0
  in sampled frames. Evidence: `reports/closure/rellis/RESULT.md` +
  `replay.json`.
- **Great Outdoors** — longer-term unstructured / UGV validation.

Keep download/setup scripts + metadata in Git; data, weights, maps,
dumps, engines, bags stay out. See `.gitignore`.

## Metrics

`logical map memory, process RSS, active cells, map-update
p50/p95/p99, end-to-end FPS, semantic accuracy by range, drivable
quality, elevation error, small-object retention, split/merge churn,
boundary correctness`. Measure perception / map-update /
visualization / end-to-end separately; prefer p50/p95/p99 over means.

Never invent numbers (`90% RAM`, `30 FPS`, `real-time guaranteed`).
Analytical estimates (e.g. `94.3% theoretical core-cell reduction`)
and measured RSS on named hardware must always be reported separately.

## Benchmark evidence contract

The benchmark executes perception once per selected frame before the policy
loop. Its JSON artifact reports per-frame dataset-load, semantic, ground,
terrain, temporal, total-perception, and C++ protocol-bridge p50/p95/p99
timings. When adapter labels are available, `semantic_quality` reports
overall and 0–10, 10–30, 30–60, and 60–100 m accuracy/mIoU; missing labels are
reported as unavailable. `reference_baselines.uniform_5cm_3d` is an explicit
analytical dense-voxel estimate only: it is never allocated, timed, or
presented as measured RSS.

The SemanticPOSS Actions workflow downloads the pinned official archive only
after an exact byte-count and SHA-256 check. It downloads to a temporary path
and atomically renames only after transfer completion, with an immutable cache
keyed by the digest. Pull requests use a deterministic 64-frame selection;
the daily schedule and manual dispatch default to sequence `00` with 488
frames. A failed checksum, benchmark, missing evidence artifact, or
correctness gate fails the benchmark job. An unavailable `main` baseline is
the only explicitly reported comparison warning. The Actions summary and
upserted PR comment show map/perception tables, range quality, provenance, and
artifact links.

## Wave-2 integration notes

- Metadata layout rule: per-present files (`len(lines) == len(refs)`) index by refs position, while absolute files (`len(lines) > len(refs)`, e.g. official full-length KITTI `poses.txt`/`times.txt` over a subset checkout) index by numeric frame id — see `datasets/semanticposs/adapter.py:_frame_index`.
- `provenance.sample_adequacy` is advisory, not rejecting (p95 needs n >= 20, p99 needs n >= 100; short-run tails equal max and are descriptive only) — see `reports/closure/bench/SURVEY.md`.
- UtilityLOD-vs-DistanceLOD claim is inconclusive-under-clamp (all utility legs byte-identical under the default governor operating point); the governor rerun with the fixed operating point is pending — see `reports/closure/utility/RESULT.md` and `reports/closure/governor/SURVEY.md`.
