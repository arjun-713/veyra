# Benchmarks — Vinay. Compare Uniform5/40, DistanceLOD, UtilityLOD.
# Report analytical vs measured separately. See docs/datasets-benchmarks.md
# Results/dumps are git-ignored; only harnesses + summaries land here.

## Offline local run

Run this from the repository root after placing the original datasets under
the configured `data/raw/` paths:

```bash
benchmarks/run_local.sh --dataset semanticposs --sequence 00 --count 10 --warmup-frames 2 --repetitions 3
benchmarks/run_local.sh --dataset rellis3d --sequence 00000 --count 10 --warmup-frames 2 --repetitions 3
```

The wrapper builds the local `veyra_benchmark` target and then runs the same
selected frames through all four public policy adapters (`Uniform5`,
`Uniform40`, `DistanceLOD`, and stateful `UtilityLOD`). It uses identical V2
digest-protected inputs, map setup, warmup, and repetitions for every policy.
`UtilityLOD` loads the checked-in hysteresis/prediction configuration and
resource-governor configuration in the C++ runtime. It performs no network
access and writes schema-v2 JSON/CSV results to `benchmark-results/` by
default. JSON records runtime hardware/config provenance, scoped stage timing,
logical versus allocated-map memory availability, current/peak process RSS,
per-level cells, topology churn, and stream late/drop accounting.

## Real-data perception regression

CI uses one immutable Qualcomm AI Hub SalsaNext scan, downloaded at runtime
and checked against SHA-256 (1,994,688 bytes; never committed):

`https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/salsanext/v3/000000.bin`

The asset is raw float32 `XYZI`. Its source has no paired pose or timestamp,
so the harness preserves both as absent and does not claim temporal acceptance
or invent motion. The explicit `configs/perception-salsanext.yaml` pipeline
must provide the real SalsaNext model and Patchwork++ ground backend; missing
stages fail the run. The report stays before the mapper and records
input-to-ObservationFrame point correspondence, taxonomy/range validity,
per-stage timings, total latency, and process RSS. Accuracy is reported as
`null` because no paired upstream labels have been verified; no labels are
invented.

To run the bounded regression locally after building the benchmark and
placing the explicitly configured model in `data/cache/models/`:

```bash
python -m scripts.fetch_semantic_model
python -m benchmarks.regression --intensity-scale 1
```

The pull-request job uses one real scan as an affordable smoke test. The
scheduled/manual path is the place to add longer, data-backed perception
coverage. The Qualcomm scan has no paired pose or timestamp, so temporal
behavior cannot be validated with this sample.

## SemanticPOSS scheduled benchmark

The `semanticposs-benchmark` job uses the official SemanticPOSS archive from
the POSS website. The current archive is approximately 2.41 GB compressed and
extracts to approximately 4 GB. It is intentionally not part of ordinary PR
checks.

It runs on the weekly schedule or by manually dispatching the workflow with
`run_semanticposs=true`. Sequence `00` defaults to all 488 frames. The job
runs the same selected frames through `Uniform5`, `Uniform40`, `DistanceLOD`,
and `UtilityLOD` with one warmup and one measured repetition, then runs the
real SalsaNext + Patchwork++ + terrain perception validator over the same
sequence selection.

Artifacts include the downloaded archive SHA-256, four-policy JSON/CSV map
results, and the perception JSON report. The archive URL and expected byte
count are pinned in the workflow; the checksum is recorded at runtime because
the official page does not publish one. This job is deliberately a scheduled
or operator-triggered regression, not a fast PR gate.
