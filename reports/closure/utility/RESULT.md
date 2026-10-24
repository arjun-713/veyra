# Historical UtilityLOD governor and ablation experiments

These four experiments describe September 2026 source revisions, not current-main
acceptance. On their selected SemanticPOSS stream, full UtilityLOD did not
improve task retention over DistanceLOD. Three budgeted matrices were confounded
by governor pressure; the fourth isolated the policy and reproduced an identical
full-utility/distance map. A semantics-only leg refined more, at substantial cost
and mixed quality. Later evidence is kept separately in
[utility diagnostics](../../utility-diagnostics/README.md) and the
[frozen challenge conclusion](../../utility-hardcore/CONCLUSION.md).

## Shared method

- SemanticPOSS seq00, frames 0–29; 3 repetitions, 2 warmup frames, 28 measured
  map updates/run (84 samples/policy).
- Identical staged stream SHA-256:
  `4cd60ac5a5746bbc142d56e36fdbc4a89b8707e6cb905c8dae4f9d4f9c8c43dc`.
- Nine policies: Uniform5, Uniform40, DistanceLOD, distance ablation,
  geometry/semantics/motion/traversability ablations, and full UtilityLOD.
- Ground-truth semantics; ground/terrain unavailable and temporal disabled.
  There were no non-drivable reference bins or measured motion, so hazard and
  motion benefits were untested. These are not neural-quality experiments.
- Host: Intel i5-8350U, 8 logical CPUs, 15.4 GB RAM, Fedora Linux
  7.2.5-200.fc44. Shared load limits absolute timing comparisons.
- Quality: final-run elevation RMSE/coverage against executed Uniform5, plus
  dominant-label 5 cm semantic/object retention bins. Cost: aggregate map
  p50/p95/p99, peak process RSS, leaves and topology churn. Logical bytes and
  RSS are separate. Each run checks conservation and active-leaf topology.

## Governor matrices

| Matrix / source | Config | Result |
| --- | --- | --- |
| Initial, `247f127493ebecdca14fbf4222909e1a84e997b1` | Default 250k cell / 100 ms operating point | Utility legs end overloaded; optional detail blocked, 1,792 coarsen actions/run. No useful per-signal attribution. |
| Rerun, `8cb0bbd66cc084782d749aedc9d8007f13e15a32` | `resource_governor-utility-rerun.yaml`: 750k cells / 500 ms | Cell pressure relieved, latency still binds; geometry/semantics snapshots vary between repetitions. |
| Run3 A, `31f91d41f86f6fe03e570f5bdbd60ea8e25cd2f5` | `resource_governor-utility-run3.yaml`: 750k cells / 1,200 ms / 128 MiB logical | Semantics is clamped in two of three repetitions; full utility remains identical to distance. |
| Run3 B, `ccb496e747d7bed5da497cc93d0551a7250d1d83` | `resource_governor-unclamped.yaml`: 100M cells / 1,000,000 ms / 100 GiB logical | Diagnostic effectively disables pressure. All utility runs end normal, splits allowed, zero interventions/actions. |

Run3 A uses pressure/recovery ratios 0.90/0.75, three overload frames and five
recovery frames; near-field protection and operation limits remain unchanged.
Its semantics frame-pipeline p95/p99/max are 1689.3/1985.7/1985.7 ms, exceeding
the 1,080 ms pressure boundary. One repetition escapes to 519,378 leaves;
the other two end at 313,420 and 319,395 with heavy merge churn. Aggregating
those outcomes cannot establish a pure signal effect.

The Rerun had only one deterministic map shape across its non-semantics legs;
Run3 A also had only one such shape. In Run3 B, the semantics-only leg becomes
a second deterministic shape, while geometry/motion/traversability/full
utility remain identical to distance. Its semantics snapshot prefix
`03a8943ad259932c` matches Run3 A's sole unclamped repetition. Distance/full
utility retain prefix `d50c441328f6f2c4`.

## Pure-policy result

Run3 B ran 2026-09-18 08:15–08:33 UTC; Run3 A ran 08:00–08:15 UTC.
The table uses `run3b_matrix.json`: final-run quality, aggregate cost.

| Leg | RMSE m | Coverage | Semantic retention | Pole | Pedestrian | Vehicle | Leaves | Peak RSS MB | Map p50 / p95 / p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Distance ablation | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 247845 | 168.3 | 140.4 / 183.8 / 249.0 |
| Geometry | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 247845 | 172.9 | 165.2 / 231.4 / 289.7 |
| Semantics | 0.36332 | 0.973 | 0.95740 | 0.9474 | 0.8752 | 0.9619 | 519378 | 281.4 | 416.6 / 855.1 / 1442.2 |
| Motion | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 247845 | 172.8 | 161.0 / 227.9 / 463.7 |
| Traversability | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 247845 | 172.9 | 163.4 / 265.6 / 366.4 |
| Full UtilityLOD | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 247845 | 172.8 | 161.2 / 335.4 / 378.6 |
| DistanceLOD | 0.46653 | 0.990 | 0.96170 | 0.9231 | 0.7096 | 0.9510 | 247845 | 168.4 | 142.5 / 252.7 / 346.9 |
| Uniform5 | 0.00000 | 1.000 | 0.99164 | 0.9551 | 0.9182 | 0.9814 | 630611 | 307.9 | 336.4 / 721.2 / 1109.4 |
| Uniform40 | 0.57569 | 1.000 | 0.94419 | 0.9256 | 0.5697 | 0.9657 | 35962 | 35.6 | 233.5 / 394.8 / 636.3 |

Reference support is 597,451 semantic bins, 780 pole, 7,067 pedestrian and
64,497 vehicle bins. Semantics-only retains 571,997/739/6,185/62,040;
distance retains 574,569/720/5,015/61,334. The semantics leg gains 1,170
pedestrian, 19 pole and 706 vehicle bins, but loses 2,572 semantic bins overall.
Its 519,378 leaves comprise L0/L1/L2/L3 = 381,310/110,225/22,396/5,447;
weighted mean level falls from 1.1623 to 0.3888. Churn p95 rises from 786
to 2,816; RSS grows by 113.1 MB. It approaches Uniform5 resources with lower
coverage and a mixed retention trade-off.

All nine Run3 B legs are deterministic across three repetitions. Full utility
has zero quality/retention/leaf delta against distance even without governor
interference. This isolates a failure of the recorded combined policy to
realize the benefit visible in its semantics ablation. That revision used
weights 0.20/0.30/0.15/0.25/0.10, split threshold 0.55, quality/density gates
0.50 and two consecutive frames. These are historical settings, not a
prescription to tune current defaults.

Timing remains noisy: the same distance policy measures p95 183.8 ms under
its ablation name and 252.7 ms under its public name. The conclusion rests on
deterministic quality/topology, not small latency differences. Motion and
traversability remain untested here because their inputs were unavailable.

## Artifacts and reproduction

Full repetition rows, governor traces, metric tables and provenance are retained:

| Matrix | Benchmark JSON | Derived matrix |
| --- | --- | --- |
| Initial | [benchmark_semanticposs00.json](benchmark_semanticposs00.json) | [ablation_matrix.json](ablation_matrix.json) |
| Rerun | [benchmark_rerun_semanticposs00.json](benchmark_rerun_semanticposs00.json) | [rerun_matrix.json](rerun_matrix.json) |
| Run3 A | [benchmark_run3_semanticposs00.json](benchmark_run3_semanticposs00.json) | Per-run evidence in the benchmark JSON. |
| Run3 B | [benchmark_run3_unclamped_semanticposs00.json](benchmark_run3_unclamped_semanticposs00.json) | [run3b_matrix.json](run3b_matrix.json) |

CSV companions for Rerun and Run3 A/B remain beside the JSON. `build_matrix.py`
constructs the derived tables; `check_divergence.py` checks recorded canonical
snapshots and governor status. `run3_launch.sh` preserves the original Run3
invocation. Run these only against the recorded source/config/input when
reproducing a historical result; current harness instructions are in the
[benchmark guide](../../../benchmarks/README.md).

The scoped verdict is **no measured full-UtilityLOD advantage** on this input.
It does not establish performance on other datasets, live terrain/motion, a
matched-cost deployment budget or later policy revisions. Any new advantage
claim needs a new same-stream quality/resource comparison.
