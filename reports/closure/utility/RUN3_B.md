# UtilityLOD Run3 Matrix B — Disabled-override diagnostic (pure-policy deltas)

Status: FINAL (numbers) / DECISIVE — divergence gate PASSES with the
governor provably out of the loop, and full UtilityLOD is byte-identical
to DistanceLOD. Verdict: **REFUTED** (scoped below). This closes the
four-matrix arc (default-clamped → 750k/500 ms → 1200 ms/750k → disabled):
no further governor experiment can change a pure-policy Δ = 0.

## Recipe

- Governor config `configs/resource_governor-unclamped.yaml`:
  `max_active_cells 100000000`, `max_logical_bytes 107374182400`,
  `target_frame_time_ms 1000000.0` — effectively DISABLED (diagnostic
  only, never a deployment budget). Splits always allowed, ~0 actions.
- Harness: same `benchmarks/run_benchmark.py` invocation shape as Matrix A
  (one `--governor-config` per matrix, 9 policies, sequential in
  `reports/closure/utility/run3_launch.sh` — never parallelized).
- Stream: identical staged SemanticPOSS seq00 frames 0–29,
  `--retain-frames`, 3 reps, 2 warmup (28 measured frames/run,
  84 map-update samples/policy).
- Run window: 2026-09-18 08:15–08:33 UTC (`run3_launch.log`). Git
  `ccb496e` at run time. Hardware (provenance, runtime capture): i5-8350U,
  8 logical CPUs, 15.4 GB RAM, Fedora Linux 7.2.5-200.fc44.

## Digest check — PASS

- Expected stream prefix `4cd60ac5`; measured full digest
  `4cd60ac5a5746bbc142d56e36fdbc4a89b8707e6cb905c8dae4f9d4f9c8c43dc`.
- Identical in `provenance.selection_digest` and all 27 run
  `stream_digest`s (1 distinct digest across all 9 policies), matching all
  three prior matrices bit-for-bit.
- Provenance `config_sha256` carries `resource_governor-unclamped.yaml`
  (not default/rerun/run3). Provenance budget echoes
  100M cells / 1000000 ms on every utility-leg final status.

## Governor provenance — OUT OF THE LOOP (verified, not assumed)

Every utility leg on every rep ends `normal`, `allow_optional_splits=true`,
`actions_applied=0`, `interventions=0`, `overload_frames=0`. Aggregate
governor per leg: `0 interventions / 0 actions`. The latency path that
latched in all three prior matrices cannot fire at a 1000000 ms target;
the cell path cannot bind at 100M cells vs a 519k max working set.
Any remaining inter-leg difference is pure policy signal.

## Divergence gate — PASS (mechanically) / SUBSTANCE: 1 of 5 legs moves

`check_divergence.py` on `benchmark_run3_unclamped_semanticposs00.json`
(exit 0):

| leg | run SHAs (deterministic?) | splits | end states | actions/run | agg interv/actions |
| --- | --- | --- | --- | --- | --- |
| ablation_geometry | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0,0,0] | 0/0 |
| ablation_semantics | 1 SHA (`03a8943a…`), deterministic | {True} | normal ×3 | [0,0,0] | 0/0 |
| ablation_motion | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0,0,0] | 0/0 |
| ablation_traversability | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0,0,0] | 0/0 |
| utility_lod | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0,0,0] | 0/0 |

- Distinct deterministic leg SHAs: **2 of 5** — the gate's byte-identical
  check passes only via the semantics leg. Geometry/motion/
  traversability/full-utility are byte-identical to the distance baseline
  (`d50c441328f6f2c4`) on all 3 reps each.
- Determinism is now perfect (9/9 legs × 3/3 reps identical): removing the
  timing-driven governor removed the rep nondeterminism seen in all three
  prior matrices — confirming that nondeterminism was governor pressure,
  never policy signal.
- Cross-matrix reproduction: Matrix B semantics SHA `03a8943ad259932c` on
  all 3 reps **exactly equals Matrix A semantics run2**
  (`03a8943ad259932c`) — the lone unclamped rep of Matrix A is reproduced
  deterministically without a governor. A-run2 was the pure-policy shape;
  Matrix B proves it.

## Per-leg numbers (final run quality vs Uniform5 reference + aggregate cost)

Quality: elevation RMSE vs executed Uniform5, coverage, semantic/pole/
pedestrian/vehicle retention (dominant-label 5 cm bins). Hazard retention
is vacuous on this selection: 0 non-drivable reference bins on every leg.
Cost: aggregate over 3 reps; map-update p50/p95/p99 ms, peak RSS MB,
active leaves, churn p95, governor (interventions/actions). Frame-pipeline
p50/p95 appended (governor `frame_time_ms` = parse + window-follow +
update; unclamped here, reported for cost only).

| leg | RMSE (m) | cover | sem ret | pole | ped | vehicle | mu p50 | mu p95 | mu p99 | fp p50/p95 | RSS | leaves | churn95 | gov |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ablation_distance | 0.46653 | 0.990 | 0.96170 (574569/597451) | 0.9231 (720/780) | 0.7096 (5015/7067) | 0.9510 (61334/64497) | 140.4 | 183.8 | 249.0 | 342.5/462.9 | 168.3 | 247845 | 786 | 0/0 |
| +geometry | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 165.2 | 231.4 | 289.7 | — | 172.9 | 247845 | 786 | 0/0 |
| +semantics | 0.36332 | 0.973 | 0.95740 (571997/597451) | 0.9474 (739/780) | 0.8752 (6185/7067) | 0.9619 (62040/64497) | 416.6 | 855.1 | 1442.2 | 932.2/1799.7 | 281.4 | 519378 | 2816 | 0/0 |
| +motion | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 161.0 | 227.9 | 463.7 | — | 172.8 | 247845 | 786 | 0/0 |
| +traversability | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 163.4 | 265.6 | 366.4 | — | 172.9 | 247845 | 786 | 0/0 |
| utility_lod (full) | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 161.2 | 335.4 | 378.6 | 388.8/760.8 | 172.8 | 247845 | 786 | 0/0 |
| distance_lod | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 142.5 | 252.7 | 346.9 | — | 168.4 | 247845 | 786 | 0/0 |
| uniform5 (ref) | 0.0 | 1.000 | 0.99164 (592458/597451) | 0.9551 (745/780) | 0.9182 (6489/7067) | 0.9814 (63298/64497) | 336.4 | 721.2 | 1109.4 | — | 307.9 | 630611 | 0 | 0/0 |
| uniform40 | 0.57569 | 1.000 | 0.94419 (564107/597451) | 0.9256 (722/780) | 0.5697 (4026/7067) | 0.9657 (62284/64497) | 233.5 | 394.8 | 636.3 | — | 35.6 | 35962 | 0 | 0/0 |

(all latencies ms; RSS MB; leaves = aggregate `final_leaves_per_level`
sum; semantics level split L0 381310 / L1 110225 / L2 22396 / L3 5447 vs
68k/130k/41k/8k on every other LOD leg; semantics wml 0.3888 vs 1.1623.)

Deltas vs distance control (`run3b_matrix.json`, via `build_matrix.py`):

| leg | dRMSE (m) | dSem | dPole | dPed | dVeh | dLeaves | dP95 (ms) | dRSS (MB) | dChurn95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +geometry | 0.00000 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | +47.6 | +4.6 | 0 |
| +semantics | −0.10322 | −0.00430 | +0.02436 | +0.16556 | +0.01095 | +271533 | +671.3 | +113.1 | +2030 |
| +motion | 0.00000 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | +44.1 | +4.5 | 0 |
| +traversability | 0.00000 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | +81.8 | +4.6 | 0 |
| utility_lod (full) | 0.00000 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | +151.6 | +4.5 | 0 |

Framework assessment stays `no_measured_quality_improvement`.
Latency caveat: the identical `distance_lod` policy measures p95 183.8 ms
as `ablation_distance` but 252.7 ms as `distance_lod` in this same matrix
(+37% run-to-run for byte-identical maps), so per-leg p95 spreads carry
wide noise bands on this i5 — the verdict rests on the deterministic
quality/retention/leaf deltas, not latency. Full utility's +151.6 ms p95
(+83%) for a byte-identical map exceeds the noise band and is pure signal-
evaluation overhead, but it is color, not the verdict.

## The semantics leg — a real signal that the composition discards

In isolation, with zero governor interference, the semantics (+uncertainty)
signal promotes deterministically and moves task quality both ways:

- Gains: RMSE −0.103 m vs distance (0.36332 vs 0.46653); pedestrian
  +0.1656 (+1170 bins, 6185 vs 5015); pole +0.0244 (+19 bins, 739 vs 720);
  vehicle +0.0109 (+706 bins, 62040 vs 61334); wml 0.3888 vs 1.1623
  (splits p95 2788 vs 526).
- Prices: overall semantic retention −0.0043 (−2572 bins, 571997 vs
  574569); coverage −0.017 (0.973 vs 0.990); leaves 2.10× (519378 vs
  247845); RSS +113.1 MB (281.4 vs 168.3); churn p95 3.6× (2816 vs 786);
  map-update p95 4.7× (855 vs 184 ms).
- The isolated cost approaches Uniform5 territory (519k vs 631k leaves;
  281 vs 308 MB RSS; p95 855 vs 721 ms) for a mixed tradeoff — better RMSE
  and thin-class retention, worse overall semantic retention and coverage.
  That is not "cheaper than Uniform5 at better quality"; it is
  near-Uniform5 cost for a quality tradeoff.
- None of it survives the shipped composition: full `utility_lod`
  (weights 0.20/0.30/0.15/0.25/0.10, split threshold 0.55, min observation
  quality/density 0.50, 2 consecutive frames — `configs/utility_lod.yaml`)
  is byte-identical to distance on all 3 reps. The combined gate rejects
  100% of the semantics-only promotion on this selection.

## The other three legs — exact nulls, two explainable, one live

- Motion / traversability: byte-identical with zero promotions — expected
  and unsurprising. SemanticPOSS ships no timestamps (temporal `disabled`,
  known-motion fraction 0.0) and ground/terrain are `unavailable` (known
  fractions 0.0), so both signals are structurally zero on this selection.
  These legs remain untested, not disproven.
- Geometry: byte-identical with zero promotions — a genuine pure-policy
  null. The geometry signal (adapter height-complexity) is live, splits are
  allowed, the governor is absent, and the leg still never promotes beyond
  distance on 30 real frames × 3 reps.

## Verdict — REFUTED (on the tested claim; Matrix B is decisive)

The claim under test (RESULT.md): UtilityLOD exists to spend fine
resolution where losing information matters — thin/small/hazardous evidence
at range (poles, pedestrians, vehicles, non-drivable terrain) — while
remaining cheaper than Uniform5; DistanceLOD is the baseline it must beat.

1. Full UtilityLOD does not beat DistanceLOD — it IS DistanceLOD.
   Pure-policy deltas with the governor provably absent: RMSE 0.00000 m,
   semantic/pole/pedestrian/vehicle retention ±0 bins, leaves ±0,
   wml ±0 — byte-identical canonical snapshots (`d50c44…`) on all 3 reps.
   No clamp, no nondeterminism, no reading ambiguity. The 70% → 100%
   claim is not demonstrated; the framework assessment
   (`no_measured_quality_improvement`) stands uncontradicted.
2. This selection contains exactly what the policy exists to serve —
   780 pole, 7067 pedestrian, 64497 vehicle reference bins, much of it at
   range — and the composed policy spends nothing extra on any of it.
   The semantics signal proves promotion *can* move those classes
   deterministically (ped +1170 bins, RMSE −0.103 m), so the null is in the
   composition's combined gate, not in the absence of promotable evidence.
3. The isolated signal's price refutes the cost half too: 2.10× leaves,
   +113 MB RSS, p95 4.7× — near-Uniform5 resources for mixed quality
   (overall semantic retention and coverage both fall). There is no
   operating point on this data where UtilityLOD is both cheaper than
   Uniform5 and better than DistanceLOD, because the only realized point
   beyond distance costs ~Uniform5.
4. Geometry had its clean shot (live signal, no governor) and promoted
   nothing. Motion/traversability/hazard could not be tested here
   (0 non-drivable bins, no timestamps, terrain unavailable) — that bounds
   the verdict's scope; it does not blunt it, since the refutation rests on
   classes that ARE present.

Scope, stated once: REFUTED for UtilityLOD-vs-DistanceLOD task quality on
real SemanticPOSS seq00 frames 0–29 with pure signal isolated. Not a claim
about other datasets, live terrain/motion evidence, or a re-gated future
policy — reviving UtilityLOD would require a new composition (threshold /
quality-gate redesign) and/or a selection with real hazard + motion, i.e. a
new claim, not a fifth governor experiment. The governor arc is closed:
default-clamped → 750k/500 ms (latency path binds) → 1200 ms/750k (1/3
reps escape) → disabled (deterministic pure policy, full ≡ distance).

## Gaps / follow-ups (none block this verdict)

1. If UtilityLOD is ever re-gated, the test is fixed: rerun THIS Matrix B
   recipe (unclamped config + `check_divergence.py` gate) and require full
   utility to diverge from distance with net-positive retention at
   sub-Uniform5 cost. The recipe, gate, and matrix builder
   (`run3b_matrix.json`) are committed and reusable.
2. Motion/traversability/hazard legs need a selection with timestamps,
   real terrain, and non-drivable bins — a dataset gap, unchanged across
   all four matrices.
3. `tests/test_policy.cpp` (`utility_only_promotes_relative_to_the_
   distance_baseline`) remains green and consistent: the property holds —
   utility only promotes — it is just vacuous for the full composition on
   this selection (zero promotions fired).

Artifacts: `benchmark_run3_unclamped_semanticposs00.{json,csv}` (Matrix B),
`run3b_matrix.json` (via `build_matrix.py`; `rerun_matrix.json` left
untouched as the rerun's record), `benchmark_run3_semanticposs00.{json,csv}`
(Matrix A), `configs/resource_governor-unclamped.yaml`,
`reports/closure/utility/run3_launch.sh`, `run3_launch.log`.
