# Production UtilityLOD diagnostics and perception handoff

Scope: #57, on production `utility_lod`. This adds observability, the approved
narrow perception-quality correction and the subsequent measured-support/class
signal correction. It is not a V2 import, weight retune, new default, or claim
that UtilityLOD beats DistanceLOD. The new policy contract is documented in
`docs/utility-production-signal-correction.md`.

## What the mapper now reports

Enable the existing `--promotion-telemetry` switch on the benchmark executable.
The existing report remains intact; additive diagnostic version 1 supplies:

- Independent quality/density failure counts and 20-bin support histograms.
- Per-taxonomy-ID decision and failed-quality-gate counts (IDs 0–19; bucket 20
  means an unrecognized ID, not a new class).
- Effective weighted signal sums after the quality gate, alongside the existing
  potential weighted sums. A rejected observation contributes zero effective
  score. Safety/predictive overrides must be interpreted separately.
- One recorded reason per policy request: protected baseline, quality gate,
  density gate, state capacity, cooldown, score below split, insufficient dwell,
  level-change limit, new promotion, safety/predictive promotion, or retained
  promotion. Reason counts sum to decisions; quality/density failures can overlap.

These are **policy requests**, not proof that a map split succeeded. Existing
governor suppression, applied actions, topology statistics, and leaf footprints
must still be checked. Reasons are recorded at the decision site; they are not
reconstructed from a heatmap. Hysteresis aggregates the maximum evidence in a
frame; a later weak point can inherit an earlier strong region decision.

Instrumentation is opt-in, fixed-size, and stores no observation history.
`CellStats` and `Leaf` are unchanged. Enabled/disabled runs must have identical
snapshots and leaf statistics on deterministic inputs with non-binding resource
limits. Under deadline pressure, tracing overhead can affect the governor's
timing-based decisions. Do not compare traced latency to an untraced baseline,
or assume unchanged topology under every timing-dependent pressure condition.

For a bounded diagnostic replay using the configured real pipeline:

```sh
cmake -S . -B build-utility-diagnostics -DCMAKE_BUILD_TYPE=Release
cmake --build build-utility-diagnostics --parallel 2
.venv/bin/python -m benchmarks.utility_diagnostics \
  --executable build-utility-diagnostics/apps/benchmark/veyra_benchmark \
  --dataset semanticposs --sequence 00 --start 0 --count 2
```

The CLI is limited to 1–8 frames. It records input/config/binary digests,
commit/dirty-source provenance, hardware, actual pipeline stages, and diagnostics.
It does not call a missing model real inference, and it intentionally does not
publish latency/FPS/quality claims from this short run.
Native and Python pipeline logs go to stderr; stdout is a single JSON document.

The bounded measured diagnosis and full aggregate artifact are recorded in
`reports/utility-diagnostics/README.md`. This is branch-local GT-semantic
diagnostic evidence, not the final-main benchmark required by #62.

## Original defects (preserved diagnosis)

Before the signal correction, `MapPolicyAdapter::update` used confidence for
every known class, without class-specific importance, and supplied constant
`point_density = 1`.
Production config has semantic weight `0.30` and split threshold `0.55`; semantics
alone cannot pass this fused-score threshold. This is a reachability limitation,
not proof that changing one weight would establish useful refinement. The new
path has explicit class priorities, measured range-aware support and separately
quality-gated critical semantic admission; the weights/thresholds are unchanged.

The original `PerceptionPipeline._quality` took the minimum of semantic and
terrain confidence for all points. Terrain confidence may legitimately be zero
for a non-ground object; that must not automatically erase object confidence.
The approved integration correction now uses the aligned ground-stage mask:
ground remains `min(semantic_confidence, terrain_confidence)`, non-ground uses
semantic confidence, and terrain-unavailable behavior remains unchanged.
Terrain confidence, traversability, motion and semantic unknown are not modified.

## Approved quality-boundary integration

Originally reserved for **Samay**. After his PRs were reviewed and this fix was
confirmed absent, Arjun explicitly authorized the narrow change in our #57 PR.
This branch now edits `perception/pipeline.py` and its regression tests; preserve
Samay's fail-closed model/status work during integration. The contract is:

The smallest correction in `_quality` and its call in `process`:

1. Keep point ordering and all existing ObservationFrame fields/protocols.
2. Supply the actual aligned ground mask (from the ground stage when available,
   otherwise the canonical frame's mask) to the quality decision.
3. For a supported ground point, retain conservative terrain-dependent quality:
   `min(semantic_confidence, terrain_confidence)` when terrain evidence exists.
4. For a non-ground point, use valid semantic confidence as semantic observation
   quality; absent ground-fit/terrain confidence must not alone veto that object.
   Measured local support/density is the mapper's independent gate, not a value
   the provider should fabricate as 1.
5. With no terrain stage, preserve the existing semantic-confidence behavior.
6. Keep terrain confidence, ground mask, unknown traversability, semantic unknown,
   and unavailable motion honest. Increasing object quality must NOT turn unknown
   ground into drivable terrain or assign motion from a semantic class.
7. Reject malformed/misaligned/nonfinite evidence using existing validation.

Required regression fixtures:

- The existing composed pipeline fixture has ground `[true,true,false]`, semantic
  confidence `[0.9,0.8,0.8]`, and terrain confidence `[0.9,0.7,0]`. The corrected
  quality should be `[0.9,0.7,0.8]`, while the third traversability stays unknown.
- High-confidence non-ground person/pole/vehicle with terrain confidence zero
  remains eligible for the mapper's separate support gate.
- Low-confidence non-ground evidence stays low; unsupported ground stays low.
- Terrain unavailable, unknown semantics, absent motion, and malformed shapes
  retain truthful behavior, with no unconditional skips/fallback success.

Regression tests exercise the real pipeline composition, including high- and
low-confidence non-ground support, conservative unsupported ground, unknown
semantics, absent terrain, and unchanged unknown traversability/motion. The two
quality-boundary assertions failed against the old code before implementation.
No provider/default/temporal behavior was rewritten.

## Remaining merge gates

1. Merge/review diagnostics independently of signal corrections.
2. The approved quality boundary is included here. Temporal PR #68 remains on
   hold after real KITTI parked-support loss; do not merge it just to satisfy a
   dependency. Coordinate later `engine.cpp` edits for measured support/class
   importance with its separate persistent-session changes.
3. Correct only defects demonstrated by diagnostics; preserve DistanceLOD,
   safety detail, hysteresis, and frozen challenge selections.
4. Independently measure task benefit (#60). An equal-range resolution change is
   not automatically useful information retention; record NO-GO if it is weak.
5. Generate final benchmark evidence (#62) only on the approved integrated clean
   main SHA, after report/comparison consumer work. Branch-local GT smoke is not
   neural end-to-end validation or final current-main evidence.
