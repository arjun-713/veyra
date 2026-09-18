# UtilityLOD Rerun — Governor-Recipe Matrix (UNCLAMPED attempt)

Status: FINAL (numbers) / STILL-CLAMPED — divergence gate FAILS. Do NOT read
a UtilityLOD-beats-DistanceLOD verdict from this matrix.

## Recipe

- Governor config `configs/resource_governor-utility-rerun.yaml` (SURVEY.md §5):
  `max_active_cells 750000`, `target_frame_time_ms 500.0`, rest default
  (near-field 10 m, hysteresis, op cap unchanged).
- Harness: `--governor-config` passthrough (`benchmarks/run_benchmark.py`);
  matrix args via `build_matrix.py <benchmark.json> <matrix.json>`.
- Stream: same staged SemanticPOSS seq00 frames 0–29, `--retain-frames`,
  3 reps, 2 warmup (28 measured frames/run, 84 map-update samples/policy).

## Digest check — PASS

- Expected stream prefix `4cd60ac5`; measured full digest
  `4cd60ac5a5746bbc142d56e36fdbc4a89b8707e6cb905c8dae4f9d4f9c8c43dc`.
- Identical in `provenance.selection_digest`, all 27 run `stream_digest`s,
  and the original closure matrix (`benchmark_semanticposs00.json`).
  1 distinct stream digest across all 9 policies. Provenance
  `config_sha256` carries `resource_governor-utility-rerun.yaml`
  (not the default). Hardware: i5-8350U, 8 logical CPUs, 15.4 GB RAM,
  Fedora Linux 7.2.5-200.fc44. Git `8cb0bbd` at run time.

## Divergence gate (SURVEY.md §5) — FAIL

Gate requires: (1) five utility-leg canonical snapshot SHAs NOT
byte-identical; (2) every utility leg ends `allow_optional_splits=true`,
state normal (approaching at most), `actions_applied ~= 0`.
`check_divergence.py` on `benchmark_rerun_semanticposs00.json`:

| leg | run SHAs (deterministic?) | splits | end states | actions/run | agg actions |
| --- | --- | --- | --- | --- | --- |
| ablation_geometry | 2 SHAs (`d50c44…`, `d970a4…`), NOT deterministic | {False, True} | recovering / normal / approaching | [64, 0, 0] | 64 |
| ablation_semantics | 3 SHAs (all distinct), NOT deterministic | {False} | approaching / recovering / overloaded | [0, 0, 64] | 64 |
| ablation_motion | 1 SHA (`d50c44…`), deterministic | {False} | approaching ×3 | [0, 0, 0] | 0 |
| ablation_traversability | 1 SHA (`d50c44…`), deterministic | {False, True} | normal / normal / recovering | [0, 0, 0] | 0 |
| utility_lod | 1 SHA (`d50c44…`), deterministic | {True} ×3 | normal ×3 | [0, 0, 0] | 0 |

- Distinct deterministic leg SHAs: 1 of 5 — the four non-semantics utility
  legs (plus both distance legs) are byte-identical to the distance
  baseline (`d50c441328f6f2c4`), final-run quality exactly equal.
- Only `utility_lod` passes part (2) cleanly (3/3 normal, 0 actions,
  0 interventions). Semantics run2 ends `overloaded`; geometry /
  motion / traversability end approaching/recovering with 1–4
  interventions. Splits were blocked at least intermittently on every
  leg except full utility.
- Worse: geometry and semantics legs are NON-deterministic across reps
  on the identical stream — timing-sensitive governor pressure, not pure
  policy signal.

Why still clamped: cell/logical ratios are fine (247–280k/750k = 0.33–0.37;
27–31 MB/128 MB = 0.20–0.23), but the LATENCY path still latches.
Governor `frame_time_ms` = parse + window-follow + update: semantics runs
show per-frame 285–903 ms, p50 394–471 ms, with 6–7 frames/run > 500 ms,
so pressure (≥0.90) and 3-consecutive-overload latches still fire on the
most expensive leg. 500 ms was sized from the OLD clamped p99 (392 ms);
unclamped semantics work is heavier (map-update p99 761 ms).

## Per-leg numbers (final run quality vs Uniform5 reference + aggregate cost)

Quality: elevation RMSE vs executed Uniform5, coverage, semantic/pole/
pedestrian/vehicle retention (dominant-label 5 cm bins). Hazard retention
is vacuous on this selection: 0 non-drivable reference bins on every leg.
Cost: aggregate over 3 reps; map-update p50/p95/p99 ms, peak RSS MB,
active leaves, churn p95, governor (interventions/actions).

| leg | RMSE (m) | cover | sem ret | pole | ped | vehicle | p50 | p95 | p99 | RSS | leaves | churn95 | gov |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ablation_distance | 0.46653 | 0.990 | 0.96170 (574569/597451) | 0.9231 (720/780) | 0.7096 (5015/7067) | 0.9510 (61334/64497) | 128.8 | 158.4 | 371.0 | 168.5 | 247845 | 786 | 0/0 |
| +geometry | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 161.3 | 379.1 | 506.1 | 172.9 | 247845 | 786 | 2/64 |
| +semantics | 0.46645 | 0.989 | 0.96090 (574093/597451) | 0.9128 (712/780) | 0.7014 (4957/7067) | 0.9491 (61214/64497) | 277.1 | 570.8 | 761.1 | 230.9 | 251254 | 19008 | 5/64 |
| +motion | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 218.8 | 297.8 | 357.9 | 173.0 | 247845 | 786 | 3/0 |
| +traversability | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 170.8 | 277.7 | 330.0 | 172.9 | 247845 | 786 | 4/0 |
| utility_lod (full) | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 143.7 | 196.3 | 235.1 | 172.9 | 247845 | 786 | 0/0 |
| distance_lod | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 129.3 | 274.6 | 401.2 | 168.4 | 247845 | 786 | 0/0 |
| uniform5 (ref) | 0.0 | 1.000 | 0.99164 | 0.9551 | 0.9182 | 0.9814 | 333.9 | 534.1 | 673.4 | 307.9 | 630611 | 0 | 0/0 |
| uniform40 | 0.57569 | 1.000 | 0.94419 | 0.9256 | 0.5697 | 0.9657 | 236.7 | 315.3 | 348.5 | 35.5 | 35962 | 0 | 0/0 |

Full-utility vs distance deltas (final run): RMSE 0.00000 m, retention
±0 on every class, leaves ±0 — identical snapshots, not equivalence.
Framework assessment stays `no_measured_quality_improvement`.

Semantics-leg spread across reps (the only leg that moves — inconsistently):
run0 RMSE 0.46597 / sem 573875 / leaves 254304 / approaching;
run1 RMSE 0.46806 / sem 561803 (−12766 vs baseline) / leaves 280533 /
recovering; run2 RMSE 0.46645 / sem 574093 / leaves 251254 / overloaded.
Retention deltas are negative where they exist (−476 to −12766 bins),
churn explodes (p95 19008 vs 786), RSS +62 MB — governor churn, not a
policy win. Geometry run0 differs by −6 leaves / −4 vehicle bins only.

## Verdict — STILL CLAMPED / INCONCLUSIVE

UtilityLOD does NOT beat DistanceLOD on task quality here: full utility is
byte-identical to distance on quality and leaves, and the one diverging
leg (semantics) is worse-or-equal on retention at far higher cost, under
governor intervention, and irreproducible rep-to-rep. The 750k-cell / 500 ms
recipe fixed the cell path but not the latency path for the expensive leg
on this i5. No 70% → 100% claim; no per-signal attribution. Per SURVEY.md
§5: do not interpret deltas from a clamped run.

## Gaps / next steps

1. Latency governor still in the way: size the next operating point from
   the UNCLAMPED semantics working set (frame_time spikes to ~900 ms),
   or run the diagnostic Disabled-override leg for pure-policy deltas
   (recipe step 3, not yet run) before re-arming a deployment budget.
2. Rep nondeterminism under a timing-driven governor makes aggregates
   unreadable — gate on per-run SHAs and per-run governor traces, not
   final-run rows alone (`rerun_matrix.json` uses final runs by design).
3. Selection limits unchanged: 0 non-drivable bins (hazard vacuous),
   no timestamps (motion leg a no-op control). Traversability/motion legs
   need a selection with real terrain + time.
4. Artifacts: `benchmark_rerun_semanticposs00.{json,csv}`,
   `rerun_matrix.json` (via `build_matrix.py`), `check_divergence.py`,
   `configs/resource_governor-{utility-rerun,unclamped}.yaml`.
