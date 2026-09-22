# Map Correctness — Veyra

Source: `AGENTS.md` §§6,17 and `README.md` Core Correctness Rules.
These invariants are non-negotiable. A perf optimization that breaks
one is not an optimization.

## Invariants

1. **Unique ownership** — every accepted XY observation belongs to
   exactly one active leaf. Never double-count across parent/child.
2. **Parent/child exclusivity** — a parent and any descendant must not
   simultaneously represent the same active area.
3. **Exact hierarchy** — four children exactly cover one parent.
4. **Merge correctness** — merging preserves point count, elevation
   mean, variance / second moment, min/max z, semantic evidence,
   timestamps / persistence within tolerance. "Within tolerance" means
   exactly this:

   | Quantity | Tolerance |
   | --- | --- |
   | `count` | exact equality |
   | `min_z`, `max_z` | exact equality |
   | `mean_z` | relative `1e-9` |
   | variance | relative `1e-5` |

   The mean is strict because it is stored as a `double`; the variance is
   looser because `m2` is stored as a `float`. These are four separate
   rules and must not be collapsed into one number.
5. **Safety floor** — the resource governor must never coarsen
   near-field safety-protected regions.
6. **Rolling-window correctness** — evicting distant tiles never
   changes identity of remaining in-window cells.

## Mandatory tests

```text
test_index_alignment, test_point_conservation, test_split_merge,
test_parent_child_exclusivity, test_boundary_neighbors,
test_rolling_window, test_memory_accounting, test_near_field_protection
```

## Layer invariants

`CellStats` carries three `HeightLayer` accumulators (ground, obstacle,
overhead) alongside the pooled accumulator. Design and rationale:
`docs/layered-map-design.md`.

7. **Layer exhaustiveness** — every accepted return enters exactly one
   layer, so `ground.count + obstacle.count + overhead.count == count`.
   Exact equality.
8. **Pooled statistics are derived, not stored** — `CellStats::mean_z()`,
   `m2_z()`, `min_z()` and `max_z()` Chan-merge the three layers on
   demand. There is one accumulator per surface and no duplicate that
   can drift.

   `count` and `last_seen` remain stored and exact, so invariant 4's
   `count` rule and point conservation are unchanged. The derived
   `mean_z` holds to relative `1e-9` and variance to `1e-5`, but
   `m2_z`, `min_z` and `max_z` now carry the layers' **float**
   precision rather than double. Invariant 4's exact-equality rule for
   `min_z` / `max_z` is therefore restated per layer, where each layer's
   merge is exact, rather than over a pooled value that no longer
   exists.
9. **Layer-wise merge** — `CellStats::merge` merges each layer
   separately. A pooled merge would fold the ground back into the
   overhead evidence and rebuild the defect the layers remove.
10. **Occlusion is not free space** — a cell with obstacle or overhead
    evidence but no ground evidence classifies as `GroundState::Occluded`
    and `Traversability::Unknown`. It must never report drivable.
11. **Staleness downgrades, never clears** — aged-out obstacle evidence
    yields `Unknown`, never `Drivable`. Only positive evidence of absence
    may free a cell.

12. **Only visibility frees a cell** — occupancy may reach
    `OccupancyState::Free` solely through `observe_free()`, which records
    a beam observed passing through the cell's claimed vertical extent.
    No timer, no ageing path, and no absence of evidence may produce
    `Free`.
13. **Bounded time to change state** — log-odds occupancy is clamped in
    both directions, so the observations needed to flip a saturated cell
    are bounded (currently 10) regardless of how long it was observed.
    A merge averages children's log-odds rather than summing, so
    coarsening buys no additional inertia.

15. **Evidence fields must remain able to change** — the count-weighted
    evidence averages are stored as `float`, not quantised. A running
    average whose per-update change falls below its storage quantum
    freezes silently. Guarded by
    `test_quantised_evidence_does_not_drift`.

14. **Only a beam through the claimed extent clears a cell** — visibility
    clearing compares a cell's obstacle extent against the scan at each
    beam's own elevation, using that beam's crossing range
    (`d / cos φ`), never a single range for the whole column. A beam
    that passes over or under the extent reports
    `ClearingOutcome::SparedByElevation` and changes nothing.

Tests: `test_layered_terrain` (14 cases), `test_occupancy_uncertainty`
(9 cases) and `test_depth_image_clearing` (8 cases) cover all nine, plus
the measured per-cell memory cost so it cannot drift silently.

## Storage invariants

16. **An active leaf owns no prior** — no retained non-spatial prior exists
    at an active leaf or at any of its descendants. Every path that creates
    a leaf first absorbs them (`coarsen_to`, `merge_children`, or a split of
    a parent that itself held none), and a prior is only created by
    splitting a leaf. With exclusivity (2) this makes the existing-leaf fast
    path in `Map::update_at_level` exact: `refine_ancestors` and
    `coarsen_to` would move nothing, so they are skipped.
17. **Storage order is not semantic** — each tile level keeps its cells in
    a dense array with an open-addressed position index (append on insert,
    swap-with-last on erase). The order is a deterministic function of the
    operation history; `Map::snapshot()` sorts explicitly and sets
    `leaves_ordered_by_id`, which `count_at_level` and
    `has_no_parent_descendant_overlap` use, while hand-built snapshots are
    scanned.

Tests: `test_map_public_properties` checks ordered queries against full
scans, catches injected overlaps and duplicates through both paths, and
asserts exact evidence conservation under split/merge churn. The storage
rewrite was also checked by a differential run against the previous
implementation (three policies, 26 checkpoints, every leaf id and
statistic hashed) and a byte-identical 40-frame PandaSet engine replay.
