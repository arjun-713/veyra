# Map-core stress proof — slice 1 survey (agent/map-hardening2)

Worktree: `worktrees/map-hardening2`, branch `agent/map-hardening2`, base `b3b2abf`.
Scope: `src/map/` production path (`Map`/`DistanceLodMap` public API only) vs
`docs/map-correctness.md` invariants. No map redesign; no interface changes.

## src/map layout (read 2026-09-17)

| File | Lines | Role |
| --- | --- | --- |
| `src/map/map.cpp` | 758 | Production `Map`/`DistanceLodMap`: update, split/merge, window, governor |
| `src/map/split_merge.cpp` | 136 | Split/merge statistics preservation |
| `src/map/tile_grid.cpp` | 116 | Tile storage |
| `src/map/fusion.cpp` | 113 | Observation fusion into `CellStats` |
| `src/map/resolution_pass.cpp` | 87 | Resolution policy pass |
| `src/map/snapshot.cpp` | 20 | Snapshot assembly |
| Headers `include/veyra/map/` | ~600 | `map.hpp` (Map/DistanceLodMap API), `snapshot.hpp`, `cell.hpp`, etc. |

## Invariants (docs/map-correctness.md, all covered by tests below)

1. Unique ownership (one obs → one active leaf). 2. Parent/child exclusivity.
3. Exact hierarchy (4 children = 1 parent). 4. Merge correctness
(count/min/max exact, mean rel 1e-9, variance rel 1e-5).
5. Safety floor (governor never coarsens near field). 6. Rolling-window
(eviction never renames in-window cells).

## Prior coverage (pre-existing)

`test_randomized_map_invariants.cpp`: 800-step Uniform40 churn, seed
`0x5EED2605`, checks one-owner + O(n²) disjointness + point conservation
per step. Short, single-policy, no long drive / boundary fuzz / repeated-churn proof.

## New in this slice

`tests/test_map_hardening_stress.cpp` (625 lines, deterministic mt19937 seeds,
public API only) + `tests/CMakeLists.txt` registration (`map_hardening_stress`,
TIMEOUT 600). Seven sections: (1) 6000-step DistanceLod mixed L0–L3 churn,
(2) boundary fuzz (L0 corners/edges ±eps + LOD band seams 10/30/60 m),
(3) 400 m rolling-window drive with survivor bit-identity + memory plateau,
(4) 200× split/merge cycles ×3 parents with exact stat round-trip,
(5) 120-trial merge-grouping numerical property (merge == sequential add),
(6) 30-round hostile near-field governor hold, (7) 8-rev synthetic LiDAR
replay (ground/curb/pole/pedestrian) spanning L0–L3.

No new focused test was added beyond this file: long stress coverage was
missing at slice start (only staged as uncommitted work) and this file fills
it; per mission no redesign was done.

## Results (Release, `-j2` build, ctest in worktree `build/`)

Mission regex `map|invariant|split|merge|rolling|snapshot|conservation|exclusivity`: **9/9 pass, 40.27 s total**.

| Test | Result | Duration |
| --- | --- | --- |
| map_engine | pass | 0.68 s |
| split_merge | pass | 0.02 s |
| point_conservation | pass | 0.02 s |
| rolling_window | pass | 0.06 s |
| parent_child_exclusivity | pass | 0.01 s |
| randomized_map_invariants | pass | 2.30 s |
| map_public_properties | pass | 0.02 s |
| snapshot | pass | 0.06 s |
| map_hardening_stress | pass | 37.07 s |

Remaining map-scope tests (outside mission regex, run for completeness): **5/5 pass, 0.47 s total**
(index_alignment, memory_accounting, boundary_neighbors,
near_field_protection, resolution_pass 0.44 s).

Full stress-trace: `stress-2026-09-17.txt` (this directory).
Key measured figures (x86_64, this worktree host — durations, not perf claims):
churn FINAL leaves=4086 tiles=458 points=3577 splits=1212 merges=887
(L0=2105 L1=558 L2=799 L3=624); drive plateau 986–988 leaves vs 2,010,619
all-L0 analytic ceiling; replay accepted=4096 L0=360 L1=832 L2=1256 L3=1648.

## Gaps / next slices

- Real-scan replay: `data/raw` empty in checkout, so §7 is a deterministic
  synthetic surrogate; replay against KITTI/Rellis bags when datasets land.
- Stress binary is single-threaded correctness proof; no RSS/p50/p95/p99
  benchmark claimed (see `docs/development.md` — analytical vs measured).
- Governor proof covers DistanceLodMap near-field L0 hold; UtilityLOD
  promotion gating is a separate slice.
