# Clearing investigation: reproduced defects fixed; acceptance still partial

Historical intermediate result. The later two-strike experiment is recorded in
[the paired-replay report](RESULT.md); these findings are not current-main acceptance.

The original evidence is preserved in `paired-real-kitti08.json`. The new
`paired-real-kitti08-fixed.json` records the exact same KITTI 08 frames 43–54,
GT semantics (evaluation only), Patchwork++/terrain/temporal, real poses/times,
and paired identical observations. No manifests or input scans changed.

Three production regressions were reproduced before fixing them:

- A scan directly observed an obstacle, yet another beam reduced its occupancy
  in the same frame. Current-frame obstacle timestamps now protect those hits;
  ground-only observations cannot protect a departed obstacle.
- A raster row's centre elevation could intersect a column even though the
  measured beam passed over it. The nearest return now retains its real angles.
- A neighboring return in the same azimuth bin could clear a cell without
  crossing its XY footprint. The measured ray must intersect the square and
  reach beyond its exit. Occluding evidence wins over conflicting through-beams.

No point history was added to cells; Leaf/CellStats layouts are unchanged.
The fixed-size scan raster has two additional float arrays (measured angles).
Clearing remains opt-in and defaults are unchanged. Querying only the centre's
azimuth bin is conservative: missing intersecting rays may delay cleanup;
it must not manufacture evidence from unmeasured rays.

| Occupied seed bins | Original ON first/final | Fixed ON first/final | OFF final |
|---|---:|---:|---:|
| Moving car, raw252 instance4 | 1102 / 243 | 1200 / 25 | 1200 |
| Parked cars, raw10 | 641 / 368 | 664 / 584 | 664 |

All 1200 moving and 664 parked bins remain resident. At the end none of the
initial moving-car bins are currently observed; remaining ghost support is
2.08%, versus 20.25% before. Parked seed retention is 87.95%, versus 55.42%.
These are first-frame XY support bins, NOT object IoU or visibility ground truth.
The first-frame self-clearing failure is eliminated. Every frame passes point
conservation and parent/descendant ownership; both processes exit cleanly.

## Intermediate acceptance limitation

After earlier negative evidence, some reacquired obstacle cells remain below
the occupied log-odds threshold: 967/13151 current obstacle cells on frame54,
versus zero without clearing. Same-frame protection stops another miss; it does
not reset their Bayesian history. Resampling/aggregated extent contradiction
and recovery require further visibility-grounded validation. The 80 parked
seed-bin losses cannot all be labelled false clearing from this experiment.
Safe temporal-demo acceptance remained PARTIAL at this intermediate revision;
the experiment did not establish interactive temporal visualization acceptance.

The JSON includes actual SHA/dirty provenance and input digests. It is branch
evidence, not current-main proof. Twelve samples are descriptive, not p95/p99
tail validation. The original reproduction commands remain applicable.

## Local verification

Release build PASS; full CTest **24/24 PASS** (231.95s), explicitly pointing
all three executable environment overrides to the freshly built binaries.
Python discovery terminates: 427 tests, 417 passed and 10 optional skips.
The added ground-only recovery regression also passes after the full gate.
`git diff --check` passes. No frontend/Rust source changed in this follow-up.
