# Benchmark data contract

The benchmark workspace, CI summary, and exported files consume the same
schema-v2 artifact produced by `benchmarks/run_benchmark.py`. Consumers use
policy keys rather than table position because experiment runs may include
additional policies.

## Stable top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Currently `2`; strict consumers reject unknown major schemas. |
| `dataset`, `sequence`, `start`, `input_frames` | Selected source data. |
| `provenance` | Input/config digests, git and workflow identity, host facts, frame range, warmup, repetitions, execution order, and timing scopes. |
| `shared_stage_latency_ns` | Work shared before policy runs, currently perception. `null` means the stage was skipped. |
| `policies` | Requested benchmark names mapped to adapter metadata, raw repetitions, and aggregates. |
| `utility_vs_distance_detail` | Convenience comparison for the two public adaptive policies. |
| `utility_ablation` | Self-describing distance/signal/full UtilityLOD experiment. |

Every `policies.<name>` value contains `adapter`, `runs`, and `aggregate`.
`adapter.suite` distinguishes the four `public` policies from
`utility_ablation` variants. `adapter.signals` records enabled promotion
signals. A run includes the C++ schema-v2 response plus `quality` and
`detail_metric`. Aggregate latency percentiles use nanoseconds. Missing
measurements use JSON `null`; zero is a measured zero.
`aggregate.governor` totals per-frame interventions and applied merges across
repetitions and preserves the final governor status returned by the engine.

The stable public keys are `uniform5`, `uniform40`, `distance_lod`, and
`utility_lod`. The benchmark-only ablation matrix is:

1. `ablation_distance`: radial DistanceLOD control.
2. `ablation_geometry`: distance plus geometry complexity.
3. `ablation_semantics`: distance plus semantic importance and uncertainty.
4. `ablation_motion`: distance plus motion and prediction.
5. `utility_lod`: all configured utility signals, including traversability.

`utility_ablation.status` is `complete`, `partial`, or `not_run`, and
`missing_policies` makes partial execution explicit. Each member reports raw
measurements and `delta_vs_distance`. Negative RMSE is better, negative
weighted mean level means finer retained detail, and negative resource
fractions mean lower measured use. `full_vs_distance_assessment` describes
only the selected data and host. It is never a general quality claim.

The quality block evaluates point conservation, parent/descendant exclusivity,
split/merge sufficient-statistic conservation, and elevation reconstruction
against observed 5 cm bins. `coverage` states what fraction of reference bins
had a final active owner. Consumers show coverage beside RMSE and do not treat
finer detail alone as quality improvement.

## CSV and compatibility

CSV contains one row per requested policy with common latency, memory,
topology, and quality columns. JSON is authoritative for per-level cells,
individual repetitions, provenance, and ablations.

The report renderer accepts earlier schema-v2 four-policy artifacts that lack
`utility_ablation`; it displays the ablation as unavailable. Baseline
regression compares only policy keys present in both artifacts, so adding an
experiment does not create a false regression. Correctness failures remain a
hard gate. Hosted-runner latency and RSS changes remain warnings because those
runners are not controlled hardware.

## Commands

Run the four public policies:

```bash
benchmarks/run_local.sh --dataset semanticposs --sequence 00
```

Run the complete UtilityLOD ablation on a generic manifest dataset:

```bash
benchmarks/run_local.sh --dataset generic --dataset-root /path/to/dataset \
  --sequence drive-01 --policies \
  ablation_distance,ablation_geometry,ablation_semantics,ablation_motion,utility_lod
```

Scheduled CI includes the complete matrix. Pull requests retain the smaller
four-policy comparison, while product CI exercises the matrix against a tiny
generic-manifest fixture through the real C++ benchmark executable.
