# Architecture — Veyra

Source: condensed from `AGENTS.md` §§3–5,7,13 and `README.md` Architecture / Adaptive Map / Cell Information.

## Pipeline

```text
LiDAR Scan + Pose/odometry
  → Preprocessing / coordinate transform
    → Ground segmentation (Patchwork++) → Terrain geometry
    → Semantic segmentation (pretrained provider) → Semantic confidence
      → Temporal evidence (static / moving)
        → Importance Engine → Resolution Controller (distance + utility)
          → Sparse world-aligned 2.5D map (5 / 10 / 20 / 40 cm)
            → Traversability / Viewer / Metrics
```

Point-to-cell fusion consumes the same transformed points the
resolution controller configures. See `resolution-policies.md`.

## Dyadic hierarchy

| Level | Resolution | Typical range |
| ----- | ---------: | ------------- |
| L0    |       5 cm | 0–10 m        |
| L1    |      10 cm | 10–30 m       |
| L2    |      20 cm | 30–60 m       |
| L3    |      40 cm | 60–100 m      |

`resolution(l) = 0.05 * 2^l`. Four children exactly cover one parent —
no gaps, overlap, or fractional seams. L4 / 80 cm is reserved for
extreme resource-constrained operation, not the normal map.

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
elevation mean, variance / second moment, min/max z, point count,
semantic class + confidence, traversability, motion evidence,
last-seen time, flags
```

## Storage direction

Implicit hierarchy, `sparse tile hash → fixed-size tile → compact
cell arrays`. No millions of heap-allocated quadtree nodes. No
unrestricted global 2:1 rebalance cascade; mixed-resolution neighbors
must understand resolution. Any local balancing stays bounded with
proven latency.

## Repository layout (boundaries fixed, paths may evolve)

```text
veyra/ configs/ include/veyra/ src/ perception/{semantic,ground}
datasets/{common,semantickitti,rellis,great_outdoors}
apps/{player,benchmark,live} viewer/ ros2/ benchmarks/ tests/ scripts/
```

Subsystem boundaries (`perception → map → adaptive runtime`) must not
be broken by layout changes. See `development.md`.
