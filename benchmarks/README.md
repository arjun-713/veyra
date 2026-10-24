# Benchmarks

Compare Uniform5, Uniform40, DistanceLOD, and UtilityLOD. Report analytical
and measured values separately. See the [benchmark contract](../docs/benchmark-contract.md).
Results/dumps are git-ignored; keep harnesses and lightweight evidence in Git.

## Offline local run

Run this from the repository root after placing the original datasets under
the configured `data/raw/` paths:

```bash
benchmarks/run_local.sh --dataset semanticposs --sequence 00 --count 10 --warmup-frames 2 --repetitions 3
benchmarks/run_local.sh --dataset rellis3d --sequence 00000 --count 10 --warmup-frames 2 --repetitions 3
```

The wrapper builds the local `veyra_benchmark` target and then runs the same
selected frames through all four public policy adapters (`Uniform5`,
`Uniform40`, `DistanceLOD`, and stateful `UtilityLOD`). It uses identical V4
digest-protected inputs, map setup, warmup, and repetitions for every policy.
`UtilityLOD` loads the checked-in hysteresis/prediction configuration and
resource-governor configuration in the C++ runtime. It performs no network
access and writes schema-v2 JSON/CSV results to `benchmark-results/` by
default. JSON records runtime hardware/config provenance, scoped stage timing,
logical versus allocated-map memory availability, current/peak process RSS,
per-level cells, topology churn, and stream late/drop accounting.

Pass
`--policies ablation_distance,ablation_geometry,ablation_semantics,ablation_motion,ablation_traversability,utility_lod`
to run the complete UtilityLOD signal experiment. Its structured result,
delta directions, CSV behavior, and compatibility rules are defined in
[`docs/benchmark-contract.md`](../docs/benchmark-contract.md). Scheduled CI
runs are not configured for this workflow; start it manually when the selected
data and runtime permit.

## Legacy standalone scan harness

`benchmarks/regression.py` remains available for debugging a single raw scan,
but it is not part of the manual SemanticPOSS benchmark workflow. That workflow
uses the official archive and can run adapter, perception, map-policy, and
correctness/performance checks together. Older four-policy schema-v2
artifacts remain valid regression baselines; comparisons use policy keys
present in both artifacts.

## Map-quality and planner-evaluation artifacts

Run the bounded selected SemanticPOSS workload with the four public policies,
quality/resource artifacts, and evaluation-only planner ablations:

```bash
.venv/bin/python benchmarks/run_benchmark.py \
  --repo "$PWD" --binary "$PWD/build/apps/benchmark/veyra_benchmark" \
  --dataset semanticposs --sequence 00 --start 0 --count 10 \
  --warmup-frames 2 --repetitions 2 \
  --policies uniform5,uniform40,distance_lod,utility_lod --retain-frames \
  --planner-evaluation --quality-artifact-dir reports/external-review \
  --output /tmp/veyra-quality.json --csv-output /tmp/veyra-quality.csv
```

The artifact directory contains `quality_resource_table.json/.csv`,
`pareto_summary.json`, nine dependency-free SVGs (logical map memory, measured
process peak RSS, and map-update p50 or p95 versus height
accuracy/completion/Chamfer; p95 is used only when every policy has at least
20 map-update samples),
and `planner_ablation.json/.csv`. Uniform5 is a same-stream high-resolution
representation reference, not surveyed ground truth. Height accuracy is the
fraction of matched common 5 cm XY bins within 10 cm vertical error;
completion is matched/valid Uniform5 bins; Chamfer is the symmetric mean
unsquared 3D nearest-neighbour distance on matched support. Range-binned
Chamfer uses within-band point sets, so another range cannot mask the reported
band's error. Planner comparisons rasterize all policies onto the same
bounded, world-aligned 5 cm ROI selected from Uniform5 bounds; crops are
reported in the artifact provenance. The complete metric and planner definitions are in
[`docs/benchmark-contract.md`](../docs/benchmark-contract.md).

## Manual SemanticPOSS benchmark

The `SemanticPOSS benchmark` workflow is started with `workflow_dispatch`.
It uses the official SemanticPOSS archive from the POSS website. Archive size
and SHA-256 are pinned in the workflow and checked before use.

The operator selects sequence, frame count, perception mode, policies, and
repetitions at dispatch. Defaults select 488 frames of sequence `00` and the
four public policies. One configured perception output is sent through each
selected policy, preserving shared-input comparisons.

The archive URL, byte count, and trusted SHA-256 are pinned in the workflow;
any upstream archive mutation fails verification. Each JSON artifact records
the archive digest, git SHA, sequence/frame range, config digest, model digest
when applicable, runner CPU/RAM/OS, and compiler/build metadata. The workflow
uses an immutable archive cache keyed by its digest. A cache miss
downloads to a temporary path, verifies size and SHA-256, then saves only the
verified archive. The Actions summary contains the compact tables; JSON, CSV,
and provenance files remain available as artifacts. Hosted-runner performance
changes over 20% versus the latest successful `main` artifact are warnings;
correctness failures are hard failures.

## Frozen UtilityLOD challenges

This benchmark asks whether UtilityLOD preserves **task-relevant** evidence
better than DistanceLOD at a comparable cost. It does not retune either policy.

The committed `utility_challenge_manifest.json` was selected from raw XYZ,
dataset labels, range and available pose/time metadata before running any
policy. Its content SHA-256 is validated before each run. The fixed windows
contain ten consecutive original scan IDs; no window crosses a missing-ID gap.
Each selected scan and label file is also SHA-256 checked. The executed stream
digest covers every frame and must match across compared policies.

Run from the repository root after a Release build:

```bash
PYTHONPATH=. .venv/bin/python benchmarks/utility_hardcore_run.py \
  --repo . --repetitions 3 --matrix-repetitions 1 \
  --output-dir reports/utility-hardcore
```

The first four policies are Uniform5, Uniform40, DistanceLOD and production
UtilityLOD. A0 is DistanceLOD; A1–A4 retain the production weight magnitudes
for enabled signals but set other weights to zero; A5 is production UtilityLOD.
The safety override, quality gate, hysteresis and thresholds are **not**
changed. The +0/5/10/20/30% budget sweep copies the existing governor and
isolates its logical-byte budget by setting other limits high. It cannot
enforce an exact same-frame cap, so the report records whether each target was
actually met. Ablations and budget variants share one staged perception stream.

The challenge reference is the **observed Uniform5 map**, not surveyed ground
truth. Critical regions come from frozen GT semantic support or deterministic
height-IQR regions; labels select/evaluate scenes, while the full-policy run
explicitly uses the GroundTruth semantic provider. SemanticPOSS and RELLIS
object patches without instance IDs are not true tracked objects. RELLIS has
no trusted local pose/time metadata; multi-frame terrain quality there is an
exploratory sensor-frame result. SemanticKITTI moving raw labels select a
candidate but do not alone prove tracker motion or refinement following it.

Promotion precision here means the share of observed 5 cm bins finer in final
UtilityLOD than DistanceLOD that intersect the frozen critical region. Recall
uses critical observed bins whose DistanceLOD owner was coarser than L0.
`wasted_promotion_ratio` is the fraction of promoted observed bins **outside**
the critical region with no absolute elevation-error reduction against the
observed Uniform5 reference. These are benchmark definitions, not semantic
classifier precision/recall or proof that every outside-region promotion is
useless. Reason masks are from the triggering observation and are not exact
causal attribution across all observations in a state cell.

Map p95 with fewer than 20 measured frames is marked `tail_latency_credible:
false`. The opt-in diagnostic counters can add overhead to UtilityLOD. Repeat
the four-policy comparison without attribution to assess production timing:

```bash
PYTHONPATH=. .venv/bin/python benchmarks/utility_hardcore_run.py \
  --repo . --repetitions 3 --skip-ablations --skip-budgets \
  --disable-promotion-telemetry --output-dir reports/utility-hardcore-repeat
```

For a bounded GT-vs-real-CENet semantic-signal isolation experiment, use a
Python environment with PyTorch and run `utility_cenet_sensitivity.py` with
`--checkpoint`. Both arms intentionally disable ground, terrain and temporal;
the script rejects a silent model fallback. That result cannot stand in for
the complete GT+Patchwork++ production-path experiment.

All generated results contain run provenance, source/config digests, actual
policy settings, hardware, and sample counts. SVG plots label missing evidence
`UNAVAILABLE`; they never substitute zeros or theoretical values.
