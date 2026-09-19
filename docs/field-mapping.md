# Field mapping: ObservationFrame → protocol → map/policy/summary

Version: VEYRA_STREAM v3 (`benchmarks/protocol.py`, `PROTOCOL_VERSION = 3`).
Single mapping implementation: `parse_observation_record` in
`src/runtime/engine.cpp`, consumed identically by batch runs and the
persistent engine. No viewer-specific conversion exists.

V3 adds one trailing field, `height_above_ground`. V2 streams are still
accepted; their points arrive with that field as NaN and are counted in
`snapshot.layers.unmodelled_returns` rather than assumed to be at ground
level.

**Every writer must announce the version of the records it writes.** The
batch path reads the version from the `VEYRA_STREAM` header and the
persistent engine reads it from the `VEYRA_ENGINE` handshake; both must be
`PROTOCOL_VERSION`, never a literal. A V3 writer behind a V2 handshake is
parsed field-by-field against the wrong layout and surfaces as
`nonfinite required point value` — an error pointing several fields away
from the actual fault. `tests/test_layered_end_to_end.py` guards this.

## Per-field path

| Field | Python source | V3 record | C++ consumer |
|---|---|---|---|
| frame timestamp | `ObservationFrame.timestamp` | `F` µs / `NA` | frame ordering, late detection, per-point fallback |
| pose timestamp | `PoseSE3.timestamp` | `F` µs / `NA` | reported; ordering uses frame time |
| pose matrix | `PoseSE3.matrix` (validated rigid) | `F` 16 floats | window center, policy range; points arrive pre-transformed |
| x, y, z | `points[:, :3]` | `P` ×3 | cell ownership, Welford z stats |
| intensity | `points[:, 3]` | `P` | validated; per-frame summary only (sensor diagnostic) |
| semantic class | mapped taxonomy id | `P` int | cell class/evidence/confidence; policy importance |
| raw semantic class | dataset id, never remapped | `P` int | validated; summary + viewer legend only |
| semantic confidence | `[0, 1]` | `P` | evidence weights; uncertainty term; quality gate |
| ground | bool mask | `P` 0/1 | ground evidence aggregate |
| drivable | drivable/non_drivable/unknown | `P` 0/1/2 | signed traversability evidence; `unknown` stays 0, never free |
| slope | radians, NaN when uncomputed | `P` / `NA` | terrain classifier input in Python; summary only in C++ |
| roughness | metres RMS, NaN when uncomputed | `P` / `NA` | terrain classifier input in Python; summary only in C++ |
| height complexity | local σ(z), NaN when uncomputed | `P` / `NA` | `geometry_complexity`: policy geometry term + cell aggregate |
| step | metres, NaN when uncomputed | `P` / `NA` | terrain classifier input in Python; summary only in C++ |
| terrain confidence | `[0, 1]` | `P` | cell confidence; traversability risk weight |
| motion probability | `[0, 1]` | `P` | motion evidence aggregate; policy motion term |
| motion state | static/possibly_moving/moving/unknown | `P` 0–3 | validated; summary + viewer only (probability is the sufficient statistic) |
| velocity XY | m/s, zeros when untracked | `P` ×2 | radial range rate → predictive refinement; never retained |
| observation quality | `[0, 1]` | `P` | uncertainty gate, cell quality, governor utility |
| height above ground | `perception.ground.height_above_ground`, NaN when no ground model | `P` / `NA` | **layer routing**: ground / obstacle / overhead. NaN routes to obstacle (fail-safe) and increments `unmodelled_returns` |

## Retention rule

Cells keep sufficient statistics only (`CellStats`): count, Welford
mean/M2/min/max z, last-seen, semantic class/evidence/confidence,
drivable/ground evidence, terrain confidence, motion evidence,
observation quality, three `HeightLayer` accumulators (ground, obstacle,
overhead), clamped log-odds occupancy, and the unmodelled/outlier
counters. Velocity, raw ids, slope/roughness/step, intensity,
and motion-state labels are transient evidence: parsed, validated,
consumed or summarized, then dropped. No raw point arrays are retained.

## Documented point rejections

A point that parses but falls outside the active window is counted in
`rejected_out_of_window`, never thrown into a frame abort. Identical
input selections therefore stay comparable across policies; only the
accepted count enters map state.
