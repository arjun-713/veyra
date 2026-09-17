# UtilityLOD Closure — Controlled Ablation vs DistanceLOD

Status: FINAL (numbers) / INCONCLUSIVE (claim) — full 9-leg matrix
measured on one identical real-data stream; UtilityLOD shows no measured
quality gain over DistanceLOD on this selection, and a governor clamp
confounds the per-signal ablation. 70% → 100% is NOT demonstrated.

## Claim under test

UtilityLOD exists to spend fine resolution where losing information
matters (thin/small/hazardous evidence at range: poles, pedestrians,
vehicles, non-drivable terrain) while remaining cheaper than Uniform5.
DistanceLOD is the baseline it must beat; detail alone is not quality.

## Method (controlled)

- Same staged SemanticPOSS sequence-00 stream (frames 0–29) for every
  policy: one perception pass, one stream file, digest-pinned per run
  (`--retain-frames` so retention is measured, not unavailable).
  Selection digest `4cd60ac5a5746bbc`, shared by all 9 policies (verified:
  1 distinct stream digest); 3 repetitions, 2 warmup frames
  (28 measured frames/run, 84 map-update samples/policy).
- Legs: `ablation_distance` (control) vs `+geometry` vs
  `+semantics(+uncertainty)` vs `+motion` vs `+traversability` vs full
  `utility_lod`, plus `uniform5/uniform40/distance_lod` context.
  Artifacts: `benchmark_semanticposs00.json` (3.8 MB),
  `ablation_matrix.json` (via `build_matrix.py`), this file.
- Invariants: every run checks point conservation, duplicate ownership,
  split/merge conservation, mixed-resolution topology.
- Motion caveat (data, not code): SemanticPOSS ships no timestamps, so
  the temporal stage is unavailable and motion evidence is uniformly
  zero; the motion leg is therefore a no-op control proving no spurious
  promotion/cost. Motion-path correctness is covered by unit tests.
- Perception reality on this selection: semantic `ground_truth`,
  ground/terrain `unavailable` (known fractions 0.0), temporal
  `disabled`. So traversability risk is uniformly 0 and hazard
  retention is vacuous (0 non-drivable reference bins) — reported, not
  hidden. Geometry signal is adapter height-complexity only.
- Hardware (measured, not invented): Intel i5-8350U, 8 logical CPUs,
  15.4 GB RAM, Fedora Linux 7.2.5-200.fc44. Analytical vs measured
  reported separately; no cross-hardware claim.

## Results (`ablation_matrix.json`; measured map-update ms, peak RSS)

Task quality (final run; elevation RMSE vs executed Uniform5 reference,
retention = dominant-label 5 cm bins kept):

| leg | RMSE (m) | cover | wml | sem ret | pole | ped | vehicle |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ablation_distance (control) | 0.46653 | 0.990 | 1.1623 | 0.96170 (574569/597451) | 0.9231 (720/780) | 0.7096 (5015/7067) | 0.9510 (61334/64497) |
| +geometry | 0.46829 | 0.990 | 1.1644 | 0.96166 | 0.9231 | 0.7096 | 0.9509 |
| +semantics | 0.46829 | 0.990 | 1.1644 | 0.96166 | 0.9231 | 0.7096 | 0.9509 |
| +motion | 0.46829 | 0.990 | 1.1644 | 0.96166 | 0.9231 | 0.7096 | 0.9509 |
| +traversability | 0.46829 | 0.990 | 1.1644 | 0.96166 | 0.9231 | 0.7096 | 0.9509 |
| utility_lod (full) | 0.46829 | 0.990 | 1.1644 | 0.96166 | 0.9231 | 0.7096 | 0.9509 (61329/64497) |
| uniform40 (context) | 0.57569 | — | 3.0 | — | — | — | — |
| uniform5 (context) | 0.0 (is the reference) | — | 0.0 | — | — | — | — |

Cost (aggregate over 3 reps; map-update p50/p95/p99 ms, peak RSS MB,
active leaves L0/L1/L2/L3, governor):

| leg | p50 | p95 | p99 | RSS | leaves | governor |
| --- | --- | --- | --- | --- | --- | --- |
| ablation_distance | 155.9 | 207.0 | 238.7 | 168.4 | 247845 (68k/130k/41k/8k) | 0 actions |
| +geometry | 179.5 | 298.7 | 392.2 | 175.6 | 247383 | 5376 applied |
| +semantics | 168.5 | 275.4 | 321.5 | 175.4 | 247383 | 5376 applied |
| +motion | 150.4 | 180.8 | 193.7 | 175.4 | 247383 | 5376 applied |
| +traversability | 155.0 | 251.7 | 284.2 | 175.4 | 247383 | 5376 applied |
| utility_lod (full) | 144.4 | 179.5 | 237.6 | 175.4 | 247383 | 5376 applied |
| uniform40 | — | 273.2 | — | 35.5 | 35962 | 0 |
| uniform5 | — | 543.6 | — | 307.9 | 630611 | 0 |

Deltas, full utility vs distance control: RMSE +0.00176 m (worse),
semantic retention −4.4e-05, vehicle retention −1 bin (61329 vs 61334),
pole/pedestrian identical, leaves −462, RSS +7.1 MB. Latency deltas are
noise-dominated on this box: the same `distance_lod` cpp policy measures
p95 207.0 ms as `ablation_distance` but 249.5 ms as `distance_lod`
(±20% run-to-run), so per-leg p95 spreads (179–299 ms) carry no policy
signal. Framework assessment: `no_measured_quality_improvement`.
- Only-promotes: property test over all signals × ranges × gate states
  × safety × hysteresis age (`tests/test_policy.cpp`,
  `utility_only_promotes_relative_to_the_distance_baseline`): PASS
  (`ctest -R policy`, 2/2 green).

## Verdict

INCONCLUSIVE for the claim, for two evidence-backed reasons:

1. Governor clamp confounds the ablation. All five utility legs are
   byte-identical snapshots (sha `08145ff8`, all reps), so per-signal
   deltas are exactly 0.00 by clamp, not by signal equivalence. Every
   utility run ended governor `overloaded` (3 overload frames,
   `allow_optional_splits=false`, 1792 coarsen actions/run) against the
   default budget (250k active-cell cap vs ~247k leaves; 100 ms frame
   target vs 144–179 ms p50 on this i5). Promotions were blocked before
   signal differences could materialize. Determinism across reps is
   perfect (identical sha), so the machinery is sound — the operating
   point is not.
2. No measured quality gain where it counts. Full utility is 1.8 mm
   worse on RMSE with identical pole/pedestrian retention and −1
   vehicle bin vs the distance control; hazard retention could not be
   tested (0 non-drivable bins in seq00 frames 0–29).

What UtilityLOD does show here: far cheaper than Uniform5
(RSS 175 vs 308 MB, p95 180 vs 544 ms, 247k vs 631k leaves) at better
RMSE than Uniform40 (0.468 vs 0.576 m) — i.e. it behaves as a
governor-limited near-distance map, not as demonstrated
spend-finer-where-it-matters.

To close (est. ~15 min each, do NOT combine with this selection):
(a) rerun the matrix with the governor operating point fixed
(e.g. raise `max_active_cells` / relax frame target) so optional
splits survive and legs can diverge — confirm legs differ before
reading deltas; (b) add a selection with real non-drivable terrain
and motion evidence so the traversability/motion legs are live.
Keep `tests/test_policy.cpp` green; do not touch the benchmark
statistics framework (benchmark agent owns `sample_adequacy`).
