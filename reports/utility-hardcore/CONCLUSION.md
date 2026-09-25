# UtilityLOD challenge benchmark conclusion

## Verdict: D. CURRENTLY NOT JUSTIFIED

The frozen suite is policy-blind and covers 14 challenges in six shared
10-frame streams: RELLIS-3D (geometry hazard, flat control, pedestrian),
SemanticKITTI seq08 (vehicle, pedestrian, pole, motion candidate), and
SemanticPOSS (pedestrian, pole, vehicle, sparse/far control). Ground-truth
labels are used as UtilityLOD inputs only in the policy-potential runs; these
are not neural-model quality results. The separate CENet sensitivity artifact
is a four-frame semantic-only experiment.

The complete policy-potential run has 182 policy-region rows, one measured
repetition, two warmup frames per stream, and 10 selected frames per stream.
This is sufficient to diagnose topology/quality allocation on the selected
scenes, but not to claim stable p95/p99: per-policy map samples are below 20.
The full run took about 106 minutes of summed benchmark wall time, excluding build and
analysis. `partial_results.json` is an older interrupted checkpoint; the
canonical completed result is `utility_full_results.json` (14/14 challenges,
6/6 streams).

## Main findings

- UtilityLOD did not refine any frozen critical region beyond DistanceLOD in
  these scenes: promotion recall and precision are 0 for all critical rows.
- It still created thousands of promoted bins. Wasted-promotion ratio was
  60.6–65.8% for the semantic/motion examples. The RELLIS geometry hazard had
  63.2% wasted promotions and unchanged critical accuracy (0.40), completion
  (1.0), and Chamfer (91.8 mm) versus DistanceLOD.
- Representative overheads were material: RELLIS geometry +1.16% logical
  bytes / +5.0% RSS; SemanticPOSS pedestrian +6.42% logical bytes / +16.7% RSS;
  SemanticKITTI motion +1.43% logical bytes / +10.4% RSS. Critical metrics
  were unchanged in those rows.
- SemanticPOSS seq01 pedestrian at 60 m had a mixed change: 10 cm height
  accuracy rose 2.25 percentage points and completion rose 9.52 points, but
  Chamfer worsened by 12.2 mm and measured promotion recall remained zero.
  This does not establish a UtilityLOD promotion benefit.
- The logical-memory governor did not match its requested budget within 2% at
  +0% or +5% in any of six unique streams; +10% met the tolerance in 5/6 and
  +20% in 6/6. A veto count is not proof the final target was respected.
- The SemanticKITTI temporal-enabled stream reported temporal `available`,
  but UtilityLOD motion-region recall remained zero. This candidate scene is
  not proof of correct moving-object tracking or ghost-free map behavior.

## Signal and ablation diagnosis

Across 3,963,465 instrumented decisions, semantic scores were near one for
91.97% of samples (quantile estimates use 20 histogram bins); geometry's p90
was 0.075 and exact zero occurred 58.3%; uncertainty was exactly zero for
92.0%; traversability risk was zero for 94.9%. The combined score was zero
for 59.9% and above the split threshold for only 4.47%. Signal histograms are
aggregated telemetry, not per-promotion causal attribution.

The geometry/semantics/motion ablations usually produced the same critical
topology and quality as full UtilityLOD. Motion altered the SemanticKITTI
runtime cost, not measured critical retention. The observed behavior is closer
to broad optional refinement outside the annotated critical masks than to
selective task-relevant allocation. No UtilityLOD weights, thresholds,
hysteresis, or governor behavior were tuned in this work.

## CENet sensitivity and repeatability

Corrected CENet sensitivity used SemanticPOSS seq00 frames 0–3 (264,075
points), CPU on an Intel i5-8350U. Semantic inference p50 was 8,439.8 ms/frame
(four samples); the checkpoint SHA-256 is in
`cenet_sensitivity_corrected.json`. This is a policy-sensitivity experiment,
not mIoU/precision/recall evaluation. Both the GT and CENet arms had zero
critical promotion recall on the five selected annotations.

A separate RELLIS geometry/flat-control repeat used two repetitions. Cell
counts, logical memory, and critical geometry values exactly matched the
canonical run; map-latency summaries shifted substantially (DistanceLOD p50
200.7→140.9 ms; UtilityLOD p50 268.8→162.8 ms). This confirms structural
determinism but exposes large timing variance. The repeat produced 16 map
samples, still short of the predeclared 20-sample tail threshold.

## Reproducibility and limitations

`utility_full_results.json`, `utility_full_results.csv`, per-challenge CSVs,
`budget_sweep.csv`, `ablation_results.csv`, `promotion_attribution.csv`,
`missed_promotions.csv`, `wasted_promotions.csv`,
`signal_distributions.json`, `reproducibility.json`, and 14 SVG plots are the
canonical artifacts. `challenge_manifest.json` is the frozen input manifest
under `benchmarks/`; the run records its digest, source frame provenance,
configuration digest, git SHA, build type, compiler, OS, CPU, and RAM.

The benchmark does not provide a matched-memory DistanceLOD comparator at
exactly equal allocated bytes; governor targets are post-frame constraints
with tolerance, not hard admission reservations. It also does not establish
per-object promotion causality/lifetime, controlled deadline-budget sweeps,
classifier mIoU, or motion ghosting. Those remain limitations, not inferred
passes. No 3D baseline is part of this UtilityLOD-only task.
