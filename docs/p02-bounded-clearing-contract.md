# P0.2 bounded evidence-clearing contract

Visibility clearing contradicts obstacle evidence with measured beams, never
with time. One contradictory frame applies **at most one `kMiss` (-405)**,
and only after arming. No timestamps, no ageing, no semantics consulted.

## Rules

1. **Per-frame delta cap.** Past arming, `Map::clear_free_space` applies
   exactly one clamped `observe_free()` (`kMiss`) per frame per cell
   (`src/map/map.cpp`, `ClearingStats::cleared` counts applied frames).
2. **Two-strike arm.** The first `logodds::kStrikesToDecrement` (= 2)
   contradictory frames per streak only increment
   `CellStats::consecutive_misses`; log-odds and `free_observations` are
   untouched. A single flicker frame (occlusion edge, one bad association)
   cannot demote an Occupied cell. Arming frames are observable as
   `ClearingStats::armed` (`include/veyra/map/depth_image.hpp`,
   rendered in `src/runtime/engine.cpp`).
3. **Clear vs reduce.** `Occupied → Unknown` is reduced confidence, **not**
   clearance: `src/map/terrain_query.cpp` clears an obstacle only when
   `occupancy == OccupancyState::Free` (`cleared_by_visibility`); anything
   above the Free threshold with a standing obstacle stays NonDrivable
   (over step limit) or Unknown — never Drivable.
4. **Reacquire.** Only accepted **obstacle-layer** evidence resets the
   streak (`Map::update_at_level`, `one.obstacle.count > 0` →
   `consecutive_misses = 0`). Ground-only returns neither reset the streak
   nor protect the cell — road seen through a departed ghost must not pin
   it (`tests/test_depth_image_clearing.cpp`,
   `test_current_ground_does_not_protect_a_departed_obstacle`).
5. **Raster geometry** (`src/map/depth_image.cpp`,
   `test_cell_against_scan`): measured (not raster-centre) angles test the
   cell's square footprint; the return must exceed the footprint **exit**
   range (not the centre) plus `clearing_margin_m` (**0.10 m**,
   `MapConfig::clearing_margin_m`); exit height is evaluated at the beam's
   own elevation (per-beam slant range, never one range per column);
   **blocked-wins**: any occluding return on the bearing forces `Occluded`
   even alongside a through-beam; beams passing over/under the claimed
   `[min_z, max_z]` extent count as `SparedByElevation`, never as clearing.
6. **Merge/split streak rules** (`src/map/map.cpp`): merged streaks take
   **max, never sum**; fresh split children start at **0** (refinement is
   not contradiction); a retained parent prior carries the parent streak
   back on merge (`CellStats::merge` copies it whole into an empty slot).
7. **New state bound.** `consecutive_misses` is one `uint8_t` per cell
   (saturating at 255, never wraps); merge takes max, so no accumulation
   across topology changes. No per-cell history, no timers.
8. **Mover clearing preserved.** The post-arming decrement rate is
   unchanged (one `kMiss`/frame), so genuine departures still clear in
   bounded time; arming shifts the schedule by exactly
   `+kStrikesToDecrement` frames versus the pre-strike path.

## Analytic frame counts (all asserted in `tests/test_ghost_retention.cpp`)

Engine-ingested cells pin at exactly `kHit` (847): count-weighted averaging
in `CellStats::merge` folds N identical hits to one hit. From 847:

- **Thin cell:** Unknown frame 3 (847−405 = 442), Free frame 6
  (arm + 4 applied, 847−4·405 = −773 ≤ −405).
- **Saturated cell** (3476, reachable only via direct `observe_occupied`):
  Unknown at applied miss 7, Free at applied miss 10
  (`misses_to_clear_from_saturated() == 10`,
  `frames_to_clear_from_saturated() == 12`, i.e. 2 arm + 10 applied —
  matched end-to-end by `tests/test_layered_end_to_end.py`, 12 frames).
- `hits_to_recover_from_misses(m)` states the exact re-hit arithmetic from
  any contradicted state (`include/veyra/map/occupancy.hpp`).

Scenario coverage: A sustained see-through (exact per-frame log-odds),
B parked untouched (retention 1.0), C occluded not falsely cleared,
D thin cell, E reacquire (streak reset, exact clamp arithmetic, one
follow-up contradiction re-arms without decrement), F ground through ghost,
G split/merge streak rules at `Map` level.

## Changed files

- `include/veyra/map/occupancy.hpp` — `kStrikesToDecrement`,
  `frames_to_clear_from_saturated()`, `hits_to_recover_from_misses()`
- `include/veyra/map/map.hpp` — `CellStats::consecutive_misses`
- `include/veyra/map/depth_image.hpp` — `ClearingStats::armed`
- `src/map/map.cpp` — arm-then-decrement in `clear_free_space`,
  obstacle-only streak reset in `update_at_level`, max-merge / zero-split
  streak rules
- `src/runtime/engine.cpp` — render `"armed"` in clearing JSON
- Tests: `test_ghost_retention.cpp` (scenarios A–G),
  `test_persistent_clearing.cpp`, `test_batch_clearing.cpp`,
  `test_depth_image_clearing.cpp`, `test_layered_end_to_end.py`

## Validation (dirty tree, uncommitted)

`test_persistent_clearing`, `test_ghost_retention`
(`thin_retention k=2 = 1.000 armed`, `thin_free_declaration k=6 = 1.000`),
`test_batch_clearing`, `test_depth_image_clearing`: all pass.
`test_layered_end_to_end.py -k "clearing or Clearing or departed"`:
3 passed. `test_track_identity.py`: 6 passed.
