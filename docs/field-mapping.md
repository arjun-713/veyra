# Field mapping: ObservationFrame → protocol → map/policy/summary

Version: VEYRA_STREAM v2 (`benchmarks/protocol.py`, `PROTOCOL_VERSION = 2`).
Single mapping implementation: `parse_observation_record` in
`apps/benchmark/main.cpp`, consumed identically by batch runs and the
persistent engine. No viewer-specific conversion exists.

## Per-field path

| Field | Python source | V2 record | C++ consumer |
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

## Retention rule

Cells keep sufficient statistics only (`CellStats`): count, Welford
mean/M2/min/max z, last-seen, semantic class/evidence/confidence,
drivable/ground evidence, terrain confidence, motion evidence,
observation quality. Velocity, raw ids, slope/roughness/step, intensity,
and motion-state labels are transient evidence: parsed, validated,
consumed or summarized, then dropped. No raw point arrays are retained.

## Documented point rejections

A point that parses but falls outside the active window is counted in
`rejected_out_of_window`, never thrown into a frame abort. Identical
input selections therefore stay comparable across policies; only the
accepted count enters map state.
