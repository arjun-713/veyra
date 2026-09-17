# Terrain closure — quality + latency (agent/terrain)

Status: **done**. Scope kept to owned files only:
`perception/terrain/features.py`, `tests/test_terrain_features.py`,
`docs/ground-terrain-evidence.md`, `reports/closure/terrain/*`.
Untouched as required: `perception/semantic/*`, `perception/temporal/*`,
`src/map/*`, `src-tauri/*`.

## Root causes found and fixed

1. **Height-spread measured elevation, not spread (quality bug).**
   `height_complexity` used `tanh(sqrt(mean(z^2)))` — the raw second moment,
   which grows with absolute elevation. A flat plane at z = 5 m scored
   `tanh(5) ≈ 1.0` (maximally complex) while the identical plane at z = 0
   scored 0. Fixed to `tanh(local height std)` from the centered variance
   (`czz`), which is elevation-invariant. Measured on SemanticPOSS reference
   ground (raw 22): complexity p50 **0.112 → 0.017**, p95 **0.26 → 0.09**.
2. **Phantom steps at the edge of ground support (quality bug).**
   The neighbor-step compared real cell heights against the zero fill of
   empty cells, fabricating metre-scale steps wherever ground support ended
   (curbs of the support mask, sparse far field). On RELLIS this vetoed
   nearly all off-road ground (step p50 on predicted ground was **0.93 m**).
   Only supported cells now participate; the in-cell range still catches
   isolated hazards. RELLIS step p50 on predicted ground is now **0.069 m**.
3. **Latency: 11 scipy `convolve` passes dominated the stage.**
   Replaced with one stacked integral-image box sum — O(K·H·W) instead of
   O(K·H·W·k²) — plus slice-based neighbor diffs (no `roll` temporaries),
   fused support-mask weighting, and no padded copy. Bitwise-identical step,
   slope/roughness within 1.2e-7, **100% drivable-label agreement** with the
   old numerics on real frames (verified before the intentional step fix).

## Quality evidence (10 real frames per dataset, production pipeline)

Ground binary metrics (documented reference: SemanticPOSS raw 22 = ground;
ground stage untouched, Patchwork++ `pypatchworkpp`):
SemanticPOSS 00 [0,10), 659,737 pts —
**precision 0.776, recall 0.950, F1 0.855, IoU 0.746**.
RELLIS ground P/R/F1/IoU remain **unavailable** (no documented
pointwise ground reference; dirt/mud not promoted to ground).

Terrain P/R/F1/IoU are **unavailable by construction** — neither dataset
documents drivable/non-drivable/unknown point labels. Proxies instead
(`reports/closure/terrain/terrain-quality.json`):

| proxy (SemanticPOSS 00, 10 frames) | value |
|---|---|
| P(drivable \| ref ground) | 0.911 (was 0.828 pre step-fix) |
| P(non-drivable \| ref ground) | 0.038 (was 0.121) |
| P(unknown \| ref ground) | 0.052 (unchanged) |
| P(drivable \| ref non-ground) — leakage | 0.036 |
| P(unknown \| ref non-ground) — unknown≠free | 0.901 |
| features on trusted ground (pred ∩ ref): slope p50/p95 | 0.014 / 0.097 rad |
| roughness p50/p95 | 0.008 / 0.060 m |
| step p50/p95 | 0.018 / 0.126 m |
| height-spread p50/p95 | 0.017 / 0.091 |

Semantic evidence (per raw-label state split): ref ground (22) is 91.1%
drivable while every other raw class is ≤12.8% drivable and ≥81% unknown —
the terrain boundary tracks semantics without any drivable labels.
Leakage (3.6%) is bounded by ground false positives (ground precision
0.776): a flat surface wrongly admitted as ground is geometrically
indistinguishable from ground. Unknown is never counted as drivable.

RELLIS-3D 00000 [0,10), 363,503 pts: 33.3% drivable / 10.3% non-drivable /
56.4% unknown (pre-fix: 9.8/33.7/56.4). Predicted-ground features:
slope p50 0.053/p95 0.359 rad, roughness p50 0.035/p95 0.202 m,
step p50 0.069/p95 0.401 m — off-road roughness vetoing as designed.

## Latency (named hardware — full breakdown in `terrain-latency.json`)

Intel i5-8350U, 8 threads, 15 GB RAM, Fedora Linux 7.2.5, Python 3.13.15.
Box was heavily contended (load avg 10–16), so absolute ms are
environment-bound; before/after deltas and the interleaved A/B matter:

| stage (10-frame runs) | baseline → after |
|---|---|
| RELLIS terrain p50 / p95 / mean | 130.8/177.8/129.1 → **77.7/94.3/77.3 ms** (−40/−47/−40%) |
| POSS terrain p95 / mean | 369.1/171.5 → **256.5/157.8 ms** (−31/−8%; outlier-driven, noisy box) |
| Interleaved A/B, same frame+mask, median | **1.35×** (POSS 66k pts), **1.31×** (RELLIS 36k pts) |
| Ground Patchwork++ p95 (untouched, measured) | POSS 74.5 ms, RELLIS 18.6 ms (run-to-run variance ±2× under load; no claim) |

## Tests

`tests/test_terrain_features.py` + `test_patchworkpp_ground.py` +
`test_perception_pipeline.py` + `test_perception_validation.py`:
**61 passed**. New quantified regressions: analytic-grade slope
(|median − atan(0.1)| < 0.005, all drivable), washboard roughness band +
100% veto, curb step magnitude in [0.29, 0.31] m, elevated-plane
complexity < 1e-6 (catches the elevation bug), empty-cell edge step = 0
(catches the phantom-step bug), sparse→unknown, non-ground slab never
drivable.

## Gaps / not claimed

- No terrain P/R/F1/IoU (no labels exist); proxies only.
- Far-field (>60 m) ground F1 stays weak (0.07 at 60–100 m) — ground-stage
  issue, out of scope.
- Absolute latency on idle hardware not measured; contention noted honestly.
- `unknown` on ref ground is 5.2% (thin support); map-level handling is
  out of scope (no `src/map` touch).
