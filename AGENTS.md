# Veyra — Agent Engineering Guide

Adaptive semantic 2.5D LiDAR mapping. Keep the map bounded and deterministic;
measure resource use and map quality rather than assuming a policy is better.

Full detail lives in `docs/` — this file is the always-loaded index.
Keep it under ~150 lines.

## Stack & commands

- Core: C++20, CMake. Runtime/perception: Python, ONNX Runtime,
  optional Patchwork++ bindings. ROS2 adapters are not implemented. CUDA/TensorRT optional;
  core mapper must run without CUDA.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
python -m venv .venv && source .venv/bin/activate
```

## Architecture

`Scan + pose → preprocess → ground/semantic → terrain + confidence →
temporal → importance → resolution controller → sparse world-aligned
2.5D map (5/10/20/40 cm) → traversability/viewer/metrics`.
Details: `docs/architecture.md`.

- Lattice fixed in `odom`; window follows vehicle, never recenter
  coordinates. `resolution(l) = 0.05 * 2^l`, id `(level,ix,iy)`.
- Cells hold sufficient statistics only (mean, variance, min/max z,
  count, class + confidence, traversability, motion, last-seen).
  No raw-point history. No pointer-heavy quadtree; no global rebalance.
- Each cell has pooled statistics and separate ground, obstacle, and
  overhead `HeightLayer` evidence. Missing ground is not treated as drivable.
  See `docs/map-correctness.md`.
- Occupancy is clamped log-odds (`unknown/free/occupied`); only an
  observed beam through a cell's claimed vertical extent may make it
  `free`, never a timeout. Visibility clearing uses a spherical depth image
  and beam elevation. See `docs/map-correctness.md`.

## Map invariants (non-negotiable)

One observation → one active leaf; parent/descendant exclusivity; four
children exactly cover parent; merge preserves statistics; governor
never coarsens safety-protected near-field; eviction never renames
in-window cells. Details + tests: `docs/map-correctness.md`.

## Resolution policies

`Uniform5 / Uniform40 / DistanceLOD / UtilityLOD`. Distance is the
baseline (`0–10 m→5 cm, 10–30→10, 30–60→20, 60–100→40`); utility only
promotes, gated by observation quality. Critical comparison:
DistanceLOD vs UtilityLOD. Details: `docs/resolution-policies.md`.

## Perception / terrain / temporal

Modular `SemanticProvider`: ground truth, CENet (PyTorch), SalsaNext
(ONNX), or an explicitly configured ONNX model. Patchwork++ for ground. `drivable /
non-drivable / unknown`; unknown ≠ free. `semantic_class` ≠
`motion_state` (`STATIC / POSSIBLY_MOVING / MOVING`); dynamics must not
contaminate terrain. Details: `docs/perception-terrain-temporal.md`.

## Workflow

Read `README.md` for setup, `docs/architecture.md` for system structure,
`docs/resolution-policies.md` for policy behavior, and
`docs/benchmark-contract.md` for evaluation definitions. Dataset guides live
under `datasets/`.

- Never invent perf numbers; report analytical vs measured (RSS, p50 /
  p95 / p99) separately on named hardware.

## Boundaries

- Always: run tests for map changes; preserve subsystem interfaces.
- Ask first: architecture changes, new dependencies, or changes to the
  safety-protected near-field floor.
- Never: commit datasets, weights, maps, dumps, engines, bags, secrets
  (see `.gitignore`); retain raw points in cells; train a custom LiDAR
  net as the main effort; add SLAM/planning/control/camera/LLM scope.
  Pose is external input.

## Docs index

[Architecture](docs/architecture.md), [map correctness](docs/map-correctness.md),
[resolution policies](docs/resolution-policies.md),
[perception/terrain/temporal](docs/perception-terrain-temporal.md),
[product runtime](docs/product-runtime.md), [benchmark contract](docs/benchmark-contract.md),
[smooth replay](docs/smooth-replay.md), and [Docker](docs/docker.md).
