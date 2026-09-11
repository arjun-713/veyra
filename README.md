# Veyra

### Adaptive Semantic 2.5D LiDAR Mapping for Dynamic Environments

Veyra compresses sequential 3D LiDAR into a semantic,
variable-resolution 2.5D elevation map — fine detail where it matters,
coarse elsewhere. Built for **SIH26053**.

> Preserve safety-relevant 3D info without paying uniform
> high-resolution costs across full LiDAR range.

## Why

Full-res 3D over 100 m is too heavy; 2D grids drop curbs, steps,
potholes, and obstacles. Veyra keeps elevation + semantics in 2.5D:

| Range | Cell |
| ----- | ---: |
| 0–10 m | 5 cm |
| 10–30 m | 10 cm |
| 30–60 m | 20 cm |
| 60–100 m | 40 cm |

Distance is the baseline; terrain, semantics, motion, and risk promote
important regions finer. Details: `docs/resolution-policies.md`.

## Quick start

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
python -m venv .venv && source .venv/bin/activate
```

Core needs only C++20/CMake; CUDA optional. The long-running runtime and
Electron application are documented in `docs/product-runtime.md`; engineering
rules remain in `docs/development.md`.
The shared benchmark artifact contract is documented in
`docs/benchmark-contract.md`.

## How it works

`Scan + pose → ground (Patchwork++) + semantics (pretrained provider)
→ terrain + confidence → temporal (STATIC / POSSIBLY_MOVING / MOVING)
→ importance → resolution controller → world-aligned adaptive map →
traversability / viewer / metrics`.

Map uses fixed `odom` lattice (`resolution(l) = 0.05 * 2^l`), implicit
`(level,ix,iy)` tiles, and per-cell sufficient statistics (mean,
variance, min/max z, count, class, traversability, motion). No raw
history. Details: `docs/architecture.md`,
`docs/perception-terrain-temporal.md`.

## Modes & guarantees

Modes: **Uniform5** (fine baseline), **Uniform40** (coarse reference),
**DistanceLOD** (range-only SIH baseline), **UtilityLOD** (intelligent
promotion). Always compare all four; key result is DistanceLOD vs
UtilityLOD.

Guarantees: one point → one leaf; no parent/child overlap; exact 4:1
merge-preserving hierarchy; stable rolling window; protected
near-field. Tests: `docs/map-correctness.md`.

## Data & evaluation

Primary: SemanticKITTI; plus RELLIS-3D (off-road) and Great Outdoors
(UGV). Data/weights/maps never committed. Metrics: memory/RSS, active
cells, p50/p95/p99 update latency, FPS, range-wise semantics,
traversability, elevation error, churn. Analytical vs measured numbers
reported separately. Details: `docs/datasets-benchmarks.md`.

## Status

The repository includes the four map policies, long-running replay runtime,
resource governor, measured telemetry, binary observation transport and an
Electron/Svelte operator application. No FPS/accuracy/RAM claim is published
until a reproducible benchmark on named hardware supports it. Scope excludes
SLAM, planning, control, camera fusion and LLMs. Pose is external.

See `AGENTS.md` for contributor constraints.
