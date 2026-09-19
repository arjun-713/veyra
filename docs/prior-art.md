# Prior Art — what mature mapping systems do that Veyra did not

Survey of the open-source systems closest to Veyra's problem, what each
contributes, and which gaps have been closed. Written because "our
adaptive resolution is novel" is not a claim that survives contact with
this literature unless we know what the literature already does.

None of these systems is "better" than Veyra in a way a single number
captures — they solve overlapping but different problems, and several
target GPUs or full 3D. What they do have is a decade of hardening on
primitives Veyra was missing outright.

## The systems

| System | Group | What it contributes |
| --- | --- | --- |
| [OctoMap](https://octomap.github.io/) | Freiburg | Probabilistic occupancy octree, log-odds with **clamping** |
| [UFOMap](https://github.com/UnknownFreeOccupied/ufomap) | KTH | Explicit **unknown / free / occupied**, rather than unknown-by-absence |
| [elevation_mapping](https://github.com/ANYbotics/elevation_mapping) / [_cupy](https://github.com/leggedrobotics/elevation_mapping_cupy) | ETH Zürich / ANYbotics | Robot-centric 2.5D, **Kalman height fusion with a per-point sensor noise model**, Mahalanobis outlier rejection |
| [GridMap](https://github.com/ANYbotics/grid_map) | ETH Zürich | Multi-**layer** 2.5D grid as the standard representation |
| [wavemap](https://github.com/ethz-asl/wavemap) | ETH Zürich | Hierarchical multi-resolution via wavelet compression; coarse-to-fine integration |
| [D-Map](https://github.com/hku-mars/D-Map) | HKU MaRS (Fu Zhang) | Occupancy **without ray-casting** — depth-image rasterisation + 2D segment tree; decremental removal of known cells |
| [ROG-Map](https://github.com/hku-mars/ROG-Map) | HKU MaRS | Robocentric sliding-window occupancy grid for large-scene high-res LiDAR planning |

The HKU MaRS work (D-Map, ROG-Map, and the FAST-LIO line) is the closest
match to Veyra's constraints — high-resolution spinning LiDAR, real-time,
CPU, robocentric sliding window — and is the most useful comparison
target.

## Gaps found, and what was done

### 1. No probabilistic occupancy — **closed**

Veyra had float evidence fields updated by count-weighted averaging:
unbounded, not a probability, and with no principled way to express
"free".

Implemented log-odds occupancy in
[occupancy.hpp](../include/veyra/map/occupancy.hpp), OctoMap-style, as
fixed-point millilog-odds in an `int16`.

**Clamping is the part that matters**, and it is not an optimisation.
Without clamps, a wall observed 10,000 times needs on the order of 10,000
contradicting observations before it clears — a parked car that drives
away persists for minutes. Clamping bounds evidence in both directions,
so the observations needed to flip a cell are bounded regardless of how
long it was observed. Measured: **10 observations** from full saturation,
asserted in `test_clamping_bounds_time_to_change_mind`.

This also replaced the layered design's hand-tuned "K contradictions to
clear" constant. K now falls out of the clamp arithmetic.

### 2. No explicit free space — **closed**

`OccupancyState { Unknown, Free, Occupied }`, UFOMap's distinction. Veyra
previously conflated never-observed with observed-and-empty, because both
were "no cell". Only `observe_free()` — a beam through the volume — may
drive a cell to `Free`; ageing produces `Unknown`, never `Free`.

### 3. Every return weighted equally — **closed**

`elevation_mapping` carries a per-point variance from a sensor noise
model and rejects outliers on Mahalanobis distance. Veyra's Welford mean
treated a 3 m return and an 80 m return at grazing incidence as equally
trustworthy, and one spurious return permanently shifted a cell.

Implemented in [sensor_model.hpp](../include/veyra/map/sensor_model.hpp):
`sigma(r) = sigma_0 + k_linear*r + k_quadratic*r^2`, with a Mahalanobis
gate whose width is `layer variance + sensor variance at this range`.

One deviation from the reference implementations, deliberate: they use a
model quadratic in depth, taken from depth-camera literature. For a
spinning LiDAR, **beam divergence dominates at mid range and is linear**,
so a purely quadratic model understates error around 20–40 m. The linear
term is enabled by default and the quadratic is off until fitted.

Measured effect: 12 cm of disagreement is rejected at 5 m and accepted at
80 m, because at 80 m it is within what beam divergence explains
(`test_gate_widens_with_range`).

**Not** implemented: the Kalman *fusion* itself (variance-weighted height
update). That needs weighted Welford, which needs a sum-of-weights field
per layer — 8 more bytes per layer, 24 per cell, on a cell that has
already more than doubled. Rejection is the larger share of the benefit
for none of the memory. Fusion is a measured follow-up, not an oversight.

### 4. Ray-casting cost — **design superseded, not yet implemented**

[layered-map-design.md § 3.5](layered-map-design.md) flagged per-point ray
traversal as the largest latency risk in the dynamic-update plan
(~120 k points/frame, each walking several cells) and proposed decimation
and work caps to contain it.

**D-Map shows that is the wrong shape of solution.** Instead of tracing
rays, it rasterises the scan into a depth image at the sensor pose and
determines occupancy by projecting a cell into that image and comparing
depths, accelerated by a 2D segment tree. That is O(1) per cell rather
than O(cells along ray) per point, and it removes the decimation
trade-off entirely — no sampling, no work cap, no deferred backlog.

The occupancy primitives above are the half of this that is now in place:
`observe_free()` / `observe_occupied()` are exactly the interface a
depth-image pass would drive, and ingestion already drives
`observe_occupied()`. **The depth-image pass itself is not implemented**
and is the single highest-value remaining piece of work. § 3.2 of the
design doc should be rewritten around it before anyone builds the ray
traversal it currently specifies.

It needs sensor-frame geometry, which the protocol now has a precedent
for carrying after the V3 bump — the same mechanism, one more field or a
per-frame depth raster.

### 5. Coarse-to-fine integration — **open**

wavemap integrates observations coarse-to-fine over a hierarchy rather
than at the finest level then merging upward, which is where much of its
speed comes from. Veyra integrates at leaf level. Worth evaluating
against `UtilityLOD`, but it is an architecture change and belongs behind
the eight-question checklist.

### 6. Decremental map maintenance — **open**

D-Map removes *known* cells at each update, exploiting LiDAR's low false
alarm rate, so the structure holds mostly the uncertain frontier. Veyra
retains every observed cell until it leaves the window. Given the map has
more than doubled in per-cell size, this is the most promising memory
recovery available and should be evaluated before the resolution
controller is asked to pay that bill alone.

## What Veyra has that these do not

Stated for balance, and because the benchmark story depends on it.

- **Ground / obstacle / overhead separation with explicit occluded-ground
  reporting.** `elevation_mapping` estimates one height per cell;
  `GridMap` provides layers but no semantics for them. Reporting "the
  floor here was never observed" as distinct from a height estimate is
  not standard.
- **A utility-driven resolution controller** gated on observation
  quality. wavemap adapts resolution to *geometry*; adapting it to
  task-relevant hazard is a different and, as far as this survey found,
  less explored question.
- **A benchmark harness with pre-registered provenance** (schema-v2,
  input/config digests, execution order, warmup, repetitions). Most of
  these projects report numbers from papers; few ship the harness.

These are the three claims a comparison should be built on. "Adaptive
resolution" on its own is not one — wavemap has it.

## Honest position

Veyra is not ahead of these systems. It is a narrower system that, after
this work, has the standard primitives they have plus a terrain
representation they do not. The defensible claim is the layered
occluded-ground reporting and the hazard-driven controller — measured
against `distance_lod` and a properly built `timeout_clear`, per
[layered-map-design.md § 4](layered-map-design.md), and not against these
projects, which target different problems on different hardware.
