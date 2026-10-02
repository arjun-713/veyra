# Architecture — Veyra

This page describes the checked-in mapping/runtime structure. Setup is in
`README.md`; desktop operation is in `apps/desktop/README.md`.

## Pipeline

```text
Dataset adapter + optional pose
  → perception pipeline (semantic provider; optional ground, terrain, temporal)
    → aligned ObservationFrame
      → Python runtime → C++ resolution policy and sparse map engine
        → bounded telemetry and visualization → desktop / benchmark consumers
```

The runtime sends observations to the C++ engine through the binary
ObservationFrame protocol. Desktop and batch benchmark mapping use the same
engine. See `product-runtime.md` and `resolution-policies.md`.

## Dyadic hierarchy

| Level | Resolution | Typical range |
| ----- | ---------: | ------------- |
| L0    |       5 cm | 0–10 m        |
| L1    |      10 cm | 10–30 m       |
| L2    |      20 cm | 30–60 m       |
| L3    |      40 cm | 60–100 m      |

`resolution(l) = 0.05 * 2^l`. The configured map levels are L0–L3. Four
children exactly cover one parent — no gaps, overlap, or fractional seams.

Distance sets the baseline; utility may only promote to finer cells.
See `resolution-policies.md`.

## World-aligned lattice

- Stable world/local frame (`odom`). Never recenter cell coordinates
  around `(0,0)` per frame.
- Active window follows the vehicle; lattice stays fixed.
- `(level, ix, iy)` derived deterministically from world coordinates,
  so motion never changes identity of in-window cells.

## Cell content

Compact sufficient statistics only — never raw-point history:

```text
pooled elevation statistics; ground, obstacle, and overhead height-layer
statistics; point count; semantic class and confidence; traversability and
occupancy evidence; motion evidence; timestamps and flags
```

Cells hold sufficient statistics, not retained raw point histories. See
`map-correctness.md` for layer and occupancy invariants.

## Storage

The map uses sparse tile lookup and dense per-level cell storage with an
index for locating entries. Snapshots are emitted in deterministic cell-ID
order. This is a sparse hierarchical grid, not a pointer-per-cell quadtree.

## Runtime components

```text
datasets/       format adapters and common ObservationFrame
perception/     semantic, ground, terrain, and temporal stages
include/ src/   C++ map, policy, and runtime engine
runtime/        replay, process, protocol, and product services
apps/desktop/   Tauri + Svelte desktop application
benchmarks/     reproducible policy and quality evaluation
viewer/         standalone local browser viewer
```

ROS2 adapters are separate from the mapper. Pose is an external input; the
repository does not implement SLAM or vehicle planning.
