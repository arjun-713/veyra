# Architecture

Veyra converts dataset observations into a sparse, world-aligned semantic 2.5D
map. [README](../README.md) owns setup, [dataset adapters](../datasets/README.md)
own input conventions, and [product runtime](product-runtime.md) owns process,
telemetry and replay behavior.

```text
Dataset adapter + external pose
  → perception (semantics; optional ground, terrain and temporal stages)
  → aligned ObservationFrame → Python runtime → C++ policy + sparse map
  → bounded telemetry / visualization → desktop and benchmark consumers
```

## Map representation

The lattice stays fixed in `odom`; the active window follows the vehicle.
`resolution(level) = 0.05 * 2^level`, with levels 0–3 and deterministic
`(level, ix, iy)` identities. Four children cover one parent exactly. Motion or
rolling-window eviction never renames retained geometry. Distance bands and
optional utility promotions are defined once in [resolution policies](resolution-policies.md).

Storage uses sparse tile lookup, dense per-level cell arrays and a position
index, rather than a pointer-per-cell quadtree. Snapshots sort by cell ID.
Cells retain sufficient statistics: separate ground/obstacle/overhead height
layers, derived pooled elevation, count, semantics/confidence, supported ground
gradients, traversability, occupancy, motion, time and flags. They retain no
raw-point history. [Map correctness](map-correctness.md) specifies conservation,
exclusivity, visibility and merge rules and their tests.

## Observation protocol

`benchmarks/protocol.py` defines `PROTOCOL_VERSION = 4`. Batch streams announce
`VEYRA_STREAM 4`; persistent sessions announce `VEYRA_ENGINE 4`. Writers must
use the shared constant so the engine parses the layout they actually emit.
Both paths use `parse_observation_record` in `src/runtime/engine.cpp`.

Text records are `F` (frame), `P` (point) and `E` (end). Binary V4 rows carry
the same evidence in 79 bytes per point. V3 added height above ground; V4 added
ground-gradient X/Y. Older V2/V3 input remains readable with missing fields as
NaN. Missing height-above-ground support increments
`snapshot.layers.unmodelled_returns` rather than implying a ground surface.

| Field | Units / missing value | Map use |
| --- | --- | --- |
| Frame timestamp | `F` microseconds / `NA` | Ordering, lateness and point-time fallback. |
| Pose timestamp | `F` microseconds / `NA` | Reported; frame time determines ordering. |
| Pose matrix | `F` rigid 4×4 | Window centre and policy range; points are already transformed. |
| XYZ | metres | Leaf ownership and elevation statistics. |
| Intensity | dataset convention | Validation and frame summary only. |
| Mapped semantic ID | integer | Cell semantic evidence and policy importance. |
| Raw semantic ID | dataset integer | Validation, summary and legend; not retained in cells. |
| Semantic confidence | [0, 1] | Evidence weighting, uncertainty and quality gates. |
| Ground | boolean | Ground evidence and layer routing. |
| Drivable state | unknown=0, drivable=1, non-drivable=2 | Signed traversability evidence; unknown is not free. |
| Slope / roughness / step | radians / metres / metres; `NA` | Terrain classification in Python, C++ summary; not stored individually. |
| Height complexity | normalized local height spread / `NA` | Geometry policy signal and cell aggregate. |
| Terrain confidence | [0, 1] | Cell confidence and traversability-risk weighting. |
| Motion probability | [0, 1] | Cell motion aggregate and policy signal. |
| Motion state | static=0, possibly-moving=1, moving=2, unknown=3 | Validation/summary; probability is retained. |
| Velocity XY | m/s | Radial range rate for predictive refinement; not retained. |
| Observation quality | [0, 1] | Cell quality, uncertainty gate and governor utility. |
| Height above ground | metres / `NA` | Ground/obstacle/overhead routing; absent evidence routes fail-safe to obstacle. |
| Ground gradient X/Y | local plane gradient / `NA` | Confidence-weighted ground direction retained in cells. |

Parsed observations outside the active window increment `rejected_out_of_window`
without aborting the frame. Only accepted observations enter map state. Display
sampling and [visualization rows](product-runtime.md#visualization-contract)
are separate from this full-input protocol. `tests/test_layered_end_to_end.py`
guards version/layout agreement.

## Code ownership

| Location | Responsibility |
| --- | --- |
| `datasets/` | Adapters, taxonomy and common frame contract. |
| `perception/` | Semantic, ground, terrain and temporal processing. |
| `include/`, `src/` | C++ map, policy, governor and shared engine. |
| `runtime/` | Product service, protocol, supervision, replay and telemetry. |
| `apps/desktop/`, `src-tauri/` | Svelte/Three.js renderer and native Tauri shell. |
| `benchmarks/` | Reproducible policy/quality/resource evaluation. |
| `viewer/` | Standalone browser viewer. |

Pose is external input. ROS2 adapters, SLAM and vehicle planning are not
implemented as part of the mapper.
