# UtilityLOD Run3 Matrix A — 1200 ms / 750k-cell operating point

Status: FINAL (numbers) / STILL-CLAMPED — divergence gate FAILS (third
INCONCLUSIVE). Do NOT read a UtilityLOD-vs-DistanceLOD verdict from this
matrix. Pure-policy deltas await Matrix B (Disabled-override diagnostic,
still running at time of writing — see §Gaps).

## Recipe

- Governor config `configs/resource_governor-utility-run3.yaml`:
  `max_active_cells 750000`, `max_logical_bytes 134217728`,
  `target_frame_time_ms 1200.0`, `pressure_ratio 0.90`,
  `recovery_ratio 0.75`, `overload_consecutive_frames 3`,
  `recovery_consecutive_frames 5`, near-field 10 m / hysteresis / op cap
  unchanged from default. Sized from the rerun's ~900 ms frame spikes
  (RERUN.md gap 1: 500 ms recipe fixed the cell path but not the latency
  path on the semantics leg).
- Harness: `benchmarks/run_benchmark.py --governor-config` (one config per
  invocation); 9 policies
  (`uniform5,uniform40,distance_lod,ablation_distance,ablation_geometry,`
  `ablation_semantics,ablation_motion,ablation_traversability,utility_lod`).
- Stream: staged SemanticPOSS seq00 frames 0–29, `--retain-frames`, 3 reps,
  2 warmup (28 measured frames/run, 84 map-update samples/policy).
- Run window: 2026-09-18 08:00–08:15 UTC (`run3_launch.log`). Git
  `31f91d4` at run time. Hardware (provenance, runtime capture): i5-8350U,
  8 logical CPUs, 15.4 GB RAM, Fedora Linux 7.2.5-200.fc44.

## Digest check — PASS

- Expected stream prefix `4cd60ac5`; measured full digest
  `4cd60ac5a5746bbc142d56e36fdbc4a89b8707e6cb905c8dae4f9d4f9c8c43dc`.
- Identical in `provenance.selection_digest` and all 27 run
  `stream_digest`s (1 distinct digest across all 9 policies).
  Provenance `config_sha256` carries
  `resource_governor-utility-run3.yaml` (not the default or rerun config).

## Divergence gate (governor SURVEY.md §5) — FAIL

Gate requires: (1) five utility-leg canonical snapshot SHAs NOT
byte-identical; (2) every utility leg ends `allow_optional_splits=true`,
state normal (approaching at most), `actions_applied ~= 0`.
`check_divergence.py` on `benchmark_run3_semanticposs00.json`:

| leg | run SHAs (deterministic?) | splits | end states | actions/run | agg interv/actions |
| --- | --- | --- | --- | --- | --- |
| ablation_geometry | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0, 0, 0] | 0/0 |
| ablation_semantics | 3 SHAs (all distinct), NOT deterministic | {False, True} | recovering / recovering / normal | [0, 0, 0] | 5/0 |
| ablation_motion | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0, 0, 0] | 0/0 |
| ablation_traversability | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0, 0, 0] | 0/0 |
| utility_lod | 1 SHA (`d50c44…`), deterministic | {True} | normal ×3 | [0, 0, 0] | 0/0 |

- Distinct deterministic leg SHAs: 1 of 5 — geometry/motion/
  traversability/full-utility are byte-identical to the distance baseline
  (`d50c441328f6f2c4`), final-run quality exactly equal.
- Semantics is the only moving leg, and it fails part (2): runs 0–1 end
  `recovering` with `allow_optional_splits=false` (3 + 2 interventions);
  only run2 ends clean (`normal`, splits allowed, 0 interventions).
- Semantics is NON-deterministic across reps on the identical stream —
  timing-sensitive governor pressure, not pure policy signal (third
  consecutive matrix with rep nondeterminism on this leg).

## Per-leg numbers (final run quality vs Uniform5 reference + aggregate cost)

Quality: elevation RMSE vs executed Uniform5, coverage, semantic/pole/
pedestrian/vehicle retention (dominant-label 5 cm bins). Hazard retention
is vacuous on this selection: 0 non-drivable reference bins on every leg.
Cost: aggregate over 3 reps; map-update p50/p95/p99 ms, peak RSS MB,
active leaves, churn p95, governor (interventions/actions). Frame-pipeline
p50/p95/p99/max appended for the latency analysis (governor `frame_time_ms`
= parse + window-follow + update).

| leg | RMSE (m) | cover | sem ret | pole | ped | vehicle | mu p50 | mu p95 | mu p99 | fp p50/p95/p99/max | RSS | leaves | churn95 | gov |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ablation_distance | 0.46653 | 0.990 | 0.96170 (574569/597451) | 0.9231 (720/780) | 0.7096 (5015/7067) | 0.9510 (61334/64497) | 137.3 | 174.3 | 205.4 | 335.4/438.8/479.5/479.5 | 168.3 | 247845 | 786 | 0/0 |
| +geometry | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 161.8 | 233.1 | 317.3 | 395.0/612.7/684.9/684.9 | 172.8 | 247845 | 786 | 0/0 |
| +semantics | 0.36332 | 0.973 | 0.95740 (571997/597451) | 0.9474 (739/780) | 0.8752 (6185/7067) | 0.9619 (62040/64497) | 390.0 | 972.1 | 1268.9 | 834.9/1689.3/1985.7/1985.7 | 281.4 | 519378 | 20239 | 5/0 |
| +motion | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 157.4 | 227.3 | 401.1 | 386.4/573.0/829.8/829.8 | 172.8 | 247845 | 786 | 0/0 |
| +traversability | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 168.7 | 256.5 | 323.3 | 418.3/677.2/756.9/756.9 | 172.9 | 247845 | 786 | 0/0 |
| utility_lod (full) | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 168.3 | 224.9 | 268.0 | 397.3/570.4/625.8/625.8 | 172.8 | 247845 | 786 | 0/0 |
| distance_lod | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 139.8 | 173.8 | 255.9 | 350.4/415.8/539.8/539.8 | 168.3 | 247845 | 786 | 0/0 |
| uniform5 (ref) | 0.0 | 1.000 | 0.99164 (592458/597451) | 0.9551 (745/780) | 0.9182 (6489/7067) | 0.9814 (63298/64497) | 357.4 | 492.6 | 698.1 | 828.5/1168.3/1501.2/1501.2 | 308.0 | 630611 | 0 | 0/0 |
| uniform40 | 0.57569 | 1.000 | 0.94419 (564107/597451) | 0.9256 (722/780) | 0.5697 (4026/7067) | 0.9657 (62284/64497) | 235.0 | 305.7 | 419.0 | 333.0/435.2/609.1/609.1 | 35.5 | 35962 | 0 | 0/0 |

(all latencies ms; RSS MB; leaves = aggregate `final_leaves_per_level`
sum; level split for semantics final run: L0 381310 / L1 110225 /
L2 22396 / L3 5447, wml 0.3888 vs 1.1623 on every other LOD leg.)

Full-utility vs distance deltas (final run): RMSE 0.00000 m, retention
±0 on every class, leaves ±0 — identical snapshots, not equivalence.
Framework assessment stays `no_measured_quality_improvement`.

Semantics-leg spread across reps (the only leg that moves — inconsistently):

| rep | SHA | end state / splits | RMSE | cover | sem retained | pole / ped / veh | leaves | logical | splits/merges | wml |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run0 | `dfc73cbd…` | recovering / False (3 interv) | 0.46438 | 0.949 | 550086 (0.9207) | 0.9064 / 0.7026 / 0.9113 | 313420 | 33.3 MB | 81589 / 108507 | 1.0930 |
| run1 | `194c065c…` | recovering / False (2 interv) | 0.46204 | 0.962 | 558686 (0.9351) | 0.9000 / 0.7252 / 0.9282 | 319395 | 33.7 MB | 64684 / 93055 | 1.0755 |
| run2 | `03a8943a…` | normal / True (0 interv) | 0.36332 | 0.973 | 571997 (0.9574) | 0.9474 / 0.8752 / 0.9619 | 519378 | 56.3 MB | 50337 / 2323 | 0.3888 |

The single unclamped rep (run2) promotes aggressively: 2.1× the leaves of
distance, wml 0.39 vs 1.16, RMSE −0.103 m vs distance, ped +0.166 / veh
+0.011 / pole +0.024 retention — but overall semantic retention −0.004,
coverage −0.017, churn p95 20239 vs 786, RSS +113 MB vs distance. The two
clamped reps merge heavily (∼93–109k merges vs 2.3k) and land near
distance on RMSE with worse retention. The aggregate row above mixes
clamped + unclamped reps and is unreadable by design — gate on per-run
SHAs and per-run governor traces, not the aggregate.

## Binding constraint — LATENCY path on the semantics leg

- Cell path NOT binding: semantics runs hold 313–519k/750k cells
  (0.42–0.69) and 33–59 MB/128 MB logical (0.26–0.44). Utility/distance
  legs sit at 248k/750k (0.33) and 0.20 logical.
- Latency path IS binding: semantics aggregate frame-pipeline p95
  1689 ms / p99 1985 ms / max 1985 ms vs the 1200 ms target (pressure
  threshold 0.90 × 1200 = 1080 ms). Map-update alone hits p99 1268.9 ms.
  Runs 0–1 latched `recovering` with splits blocked; 5 aggregate
  interventions, 0 actions (interventions without coarsening actions —
  split-blocking + recovery cycling).
- Self-reinforcing loop: 1200 ms was sized from the rerun's ~900 ms
  spikes, but the unclamped semantics working set is heavier (run2: 519k
  leaves, 50k splits, frame tail to 1985 ms). Unclamped promotion → more
  leaves → heavier frames → latency trips on sibling reps. A static
  frame target cannot hold this leg open deterministically; rep
  nondeterminism persists across all three matrices.
- Full utility still shows zero promotion (byte-identical to distance):
  semantics-only promotion does not survive full-utility gating on this
  selection. Whether that is correct gating (combined quality gate
  rejecting semantics-only splits) or a second clamp interaction is
  undecidable from a clamped matrix — Matrix B's Disabled-override legs
  will show the pure-policy shape.

## Verdict — STILL CLAMPED / INCONCLUSIVE (3rd)

UtilityLOD does NOT beat DistanceLOD on task quality here: full utility is
byte-identical to distance on quality and leaves, and the one diverging
leg (semantics) is irreproducible rep-to-rep under governor intervention
(2/3 reps clamped, 1/3 unclamped with mixed quality deltas at 2.1× leaves
and 26× churn). Per SURVEY.md §5: do not interpret deltas from a clamped
run. No 70% → 100% claim; no per-signal attribution.

## Gaps / next steps

1. Matrix B (Disabled-override diagnostic,
   `configs/resource_governor-unclamped.yaml`: 100M cells / 1000000 ms —
   effectively disabled) was running at time of writing (started
   2026-09-18 08:15 UTC, early `distance_lod` leg). It gives pure-policy
   deltas for all 9 legs with no governor in the loop. Analyze
   `benchmark_run3_unclamped_semanticposs00.{json,csv}` separately when
   complete; do NOT mix A/B numbers.
2. The harness accepts ONE `--governor-config` per invocation, so latency
   budgets cannot be sized per-leg. If Matrix B shows the semantics
   working set needs it, options are a higher static target (≥2100 ms to
   clear the 1985 ms max, deployment-unrealistic on this i5) or per-leg
   governor overrides in the harness.
3. Rep nondeterminism under a timing-driven governor makes aggregates
   unreadable — all three matrices confirm this. Any future budgeted
   comparison must gate on per-run SHAs + per-run governor traces.
4. Selection limits unchanged: 0 non-drivable bins (hazard vacuous), no
   timestamps (motion leg a no-op control). Traversability/motion legs
   need a selection with real terrain + time.

Artifacts: `benchmark_run3_semanticposs00.{json,csv}` (Matrix A, this
report), `benchmark_run3_unclamped_semanticposs00.{json,csv}` (Matrix B,
pending), `configs/resource_governor-utility-run3.yaml`,
`reports/closure/utility/run3_launch.sh`, `run3_launch.log`.
