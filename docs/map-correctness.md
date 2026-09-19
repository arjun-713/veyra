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
8. **Pooled reconstruction** — Chan-merging the three layers reproduces
   the pooled accumulator. `count` exact; `mean_z` relative `1e-9`;
   variance relative `1e-5`; `min_z` / `max_z` to float precision
   (`1e-6`), because the layers store those two as `float` while the
   pooled fields are `double`.

   The pooled fields are unchanged by the layer work and remain the
   authoritative record that invariant 4's **exact** `min_z` / `max_z`
   rule is stated over. Reconstruction is a cross-check, not a
   replacement, so invariant 4 is not weakened.
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

Tests: `test_layered_terrain` (13 cases) and
`test_occupancy_uncertainty` (9 cases) cover all seven, plus the measured
per-cell memory cost so it cannot drift silently.
