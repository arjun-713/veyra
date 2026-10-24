# Veyra

### Adaptive semantic 2.5D LiDAR mapping

Veyra turns sequential 3D LiDAR into a sparse, world-aligned 2.5D map.
Each map cell stores elevation and surface evidence; mapping policies choose
the spatial resolution used to represent observations.

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

DistanceLOD is the range-based baseline. UtilityLOD can request local
refinement using configured geometry, semantic, motion, traversability-risk,
and uncertainty evidence, subject to observation-quality gates. The policy
design does not itself establish a measured quality advantage. See
`docs/resolution-policies.md`.

## Quick start

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Core needs only C++20/CMake; CUDA is optional. Runtime details are in
`docs/product-runtime.md`, desktop operation in `apps/desktop/README.md`, and
the benchmark artifact contract in `docs/benchmark-contract.md`.

## Run with Docker

Tests, the headless runtime, the web viewer and PandaSet tooling run in
Docker. `data/` is bind-mounted, never baked in. The Tauri desktop stays
native.

```bash
docker compose build
docker compose run --rm test
docker compose up viewer        # http://localhost:8765
```

Services, data layout and caveats: `docs/docker.md`.

## How it works

`Dataset adapter → perception pipeline (semantic provider; optional ground,
terrain and temporal stages) → ObservationFrame → Python runtime → C++ map
engine and governor → telemetry / visualization → desktop or benchmark`.

Map uses fixed `odom` lattice (`resolution(l) = 0.05 * 2^l`), implicit
`(level,ix,iy)` tiles and per-cell sufficient statistics, including separate
ground, obstacle, and overhead height layers. Raw point history is not stored
in map cells. Details: `docs/architecture.md` and
`docs/perception-terrain-temporal.md`.

## Modes & guarantees

Modes: **Uniform5** (fine reference), **Uniform40** (coarse reference),
**DistanceLOD** (range-only baseline), and **UtilityLOD** (experimental
quality-gated local promotion). Policy comparisons should use the same input
stream; the key adaptive comparison is DistanceLOD vs UtilityLOD.

DistanceLOD is the proven result. UtilityLOD is not yet shown to beat it:
the frozen stress suite (`reports/utility-hardcore/CONCLUSION.md`)
found zero critical-region promotion recall. With a relaxed governor
budget it retains more pedestrian cells on SemanticPOSS seq 00, at extra
memory and latency and with lower vehicle and hazard retention, so treat
it as a trade-off mode until it wins at a matched memory and p95 budget.

Guarantees: one point → one leaf; no parent/child overlap; exact 4:1
merge-preserving hierarchy; stable rolling window; protected
near-field. Tests: `docs/map-correctness.md`.

## Data & evaluation

Adapters cover SemanticPOSS, RELLIS-3D, SemanticKITTI, and a generic manifest
format; PandaSet conversion targets the generic format. Local data availability
and metadata vary. Dataset files, weights, and maps are not committed. Metrics
and reference definitions are in the [benchmark contract](docs/benchmark-contract.md).
The [dataset guide](datasets/README.md) owns all supported layouts, metadata,
manifest conversion and validation commands.

Reports under `reports/` describe their recorded source, inputs and hardware.
They are historical evidence, not measurements of the latest source unless
their provenance matches it. Use the current [benchmark commands](benchmarks/README.md)
to produce a new comparison.

## Status

The repository includes four map policies, a replay runtime, an optional
resource governor, measured telemetry, binary observation transport, and a
Tauri/Svelte desktop application. Performance claims require a reproducible
benchmark with named hardware and provenance. Scope excludes
SLAM, planning, control, camera fusion and LLMs. Pose is external.

See `AGENTS.md` for repository guidance and `CONTRIBUTING.md` for contribution
workflow.
