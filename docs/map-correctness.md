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
