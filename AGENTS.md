# Veyra — Agent Engineering Guide

Adaptive semantic 2.5D LiDAR mapping for dynamic environments
(adaptive semantic 2.5D LiDAR mapping). Spend fine resolution where losing info matters; keep the
map bounded, deterministic, real-time capable.

Full detail lives in `docs/` — this file is the always-loaded index.
Keep it under ~150 lines.

## Stack & commands

- Core: C++20, CMake. Perception/research: Python, PyTorch,
  ONNX Runtime, Patchwork++, PCL/Open3D, ROS2. CUDA/TensorRT optional;
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
- Elevation is split into three `HeightLayer` accumulators per cell:
  ground / obstacle / overhead. Occluded ground is `unknown`, never
  drivable. Details: `docs/layered-map-design.md`.
- Occupancy is clamped log-odds (`unknown/free/occupied`); only an
  observed beam through a cell's claimed vertical extent may make it
  `free`, never a timeout. Clearing uses a spherical depth image, not
  ray casting, and compares each beam at its own elevation. Ingestion
  gates returns on a range-dependent noise model. Prior art and
  remaining gaps: `docs/prior-art.md`.

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

Modular `SemanticProvider`; pretrained first (SalsaNext, FRNet,
Cylinder3D, ONNX). Patchwork++ for ground. `drivable /
non-drivable / unknown`; unknown ≠ free. `semantic_class` ≠
`motion_state` (`STATIC / POSSIBLY_MOVING / MOVING`); dynamics must not
contaminate terrain. Details: `docs/perception-terrain-temporal.md`.

## Workflow

Order: loader → Uniform5 → height stats → DistanceLOD → split/merge
tests → semantic+terrain → temporal → UtilityLOD → optimize →
governor → advanced. Datasets/benchmarks: `docs/datasets-benchmarks.md`.
Standards, DoD, checklists: `docs/development.md`.

- Never invent perf numbers; report analytical vs measured (RSS, p50 /
  p95 / p99) separately on named hardware.

## Boundaries

- Always: run tests for map changes; preserve subsystem interfaces.
- Ask first: architecture changes (answer 8-question checklist in
  `docs/development.md`); new deps; touching safety floor.
- Never: commit datasets, weights, maps, dumps, engines, bags, secrets
  (see `.gitignore`); retain raw points in cells; train a custom LiDAR
  net as the main effort; add SLAM/planning/control/camera/LLM scope.
  Pose is external input.

## Docs index

`architecture.md`, `map-correctness.md`, `layered-map-design.md`,
`prior-art.md`,
`resolution-policies.md`,
`perception-terrain-temporal.md`, `datasets-benchmarks.md`,
`development.md`, `desktop-electron-audit.md` (Tauri migration reference),
`docker.md` (containerised tests, runtime, viewer).
