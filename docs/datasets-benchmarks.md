# Datasets & Benchmarks — Veyra

Source: `AGENTS.md` §§15–16 and `README.md` Datasets / Benchmark
Philosophy.

## Datasets (contents never committed)

- **SemanticKITTI** — primary dev + quantitative benchmark
  (sequential LiDAR, poses, semantic + moving/static labels,
  range-based eval).
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
