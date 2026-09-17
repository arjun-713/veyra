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
- **RELLIS-3D** — off-road terrain validation.
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
