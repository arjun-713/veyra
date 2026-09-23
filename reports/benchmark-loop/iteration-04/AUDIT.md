# Iteration 04 — Tracks 4/5/6: range quality + retention + UtilityLOD verdict (2026-09-22)

## Instrumentation (benchmark + snapshot surface; no runtime representation change)
1. `src/runtime/engine.cpp`: leaf-details JSON now emits `semantic_class` (stats winner)
   and `drivable_evidence` (float). Only with `--include-leaf-details`; production
   memory layout untouched (fields already lived in CellStats).
2. `benchmarks/run_benchmark.py`: `mapping_quality_report` gains `by_range` elevation
   bands (0–10/10–30/30–60/60–100 m, RMSE + coverage + mean owner level per band);
   `_fine_reference` carries per-bin mean range from retained-frame poses;
   `_finalize_policy_runs` prefers the point-built reference when frames retained.
3. `scripts/validate_sih.sh`: gate failure now prints an explicit REAL DATA:
   UNAVAILABLE verdict (fixes stale-expectation benchmark test; fail-closed kept).

## Measured (POSS 00 fr 0–9, identical digest, 2 reps; ablation status complete)

| Policy | Logical | RMSE | Bands RMSE | Mean lvl/band | Sem | Haz | Ped | Pole | Veh |
|---|---|---|---|---|---|---|---|---|---|
| Uniform5 | 53.2 M | 0.000 | 0/0/0/0 | 0/0/0/0 | .995 | .933 | .968 | .964 | .991 |
| Uniform40 | 4.5 M | 0.564 | .11/.42/.81/.72 | 3/3/3/3 | .945 | .844 | .748 | .938 | .977 |
| DistanceLOD | 25.8 M | 0.432 | .02/.24/.63/.72 | .03/1/2/3 | .972 | .890 | .860 | .955 | .971 |
| UtilityLOD | 27.5 M | 0.434 | .02/.24/.63/.73 | .03/.97/1.98/2.97 | .959 | .848 | .859 | .938 | .953 |

Ablation (each signal added to distance): geometry/semantics/motion/traversability/full
all land at 27.5 MB, RMSE 0.434–0.435, sem 0.957–0.959 — every signal costs +1.7 MB
and retains slightly LESS than pure distance (0.972).

## UtilityLOD verdict: DISTANCELOD BETTER (this selection, honestly scoped)
Utility loses on every retention metric, every band ties, memory +6.6%, and applies
1024 governor churn actions vs distance's 0. Mechanism: promotions churn topology
without landing on task classes in flat-campus scenes. Headline production policy:
DistanceLOD. UtilityLOD stays experimental, not default. Not overfit-claimed: one
10-frame selection; scenes with far-field small objects untested.

## Graceful degradation: PROVEN for the map
DistanceLOD band RMSE 0.02 → 0.24 → 0.63 → 0.72 tracks owner levels 0 → 1 → 2 → 3.
Error grows exactly where resolution coarsens, by design, with coverage ≥0.993.

## Gates
- New benchmark-harness test failure (stale SIH verdict expectation): fixed via script.
- benchmarks/ suite: 20 passed 1 skipped after fix (was 1 failed).
- Full gates + canonical rerun: iteration-05 (performance) then final.
