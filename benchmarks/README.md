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

Pass
`--policies ablation_distance,ablation_geometry,ablation_semantics,ablation_motion,ablation_traversability,utility_lod`
to run the complete UtilityLOD signal experiment. Its structured result,
delta directions, CSV behavior, and compatibility rules are defined in
[`docs/benchmark-contract.md`](../docs/benchmark-contract.md). Scheduled CI
runs this full matrix; pull requests retain the four-policy comparison.

## Legacy standalone scan harness

`benchmarks/regression.py` remains available for debugging a single raw scan,
but it is not part of CI's primary validation path. CI uses the official
SemanticPOSS archive and runs the adapter, real perception stages, map policies,
and correctness/performance reporting together. Older four-policy schema-v2
artifacts remain valid regression baselines; comparisons use policy keys
present in both artifacts.

## SemanticPOSS CI benchmark

The `semanticposs-benchmark` job uses the official SemanticPOSS archive from
the POSS website. The current archive is approximately 2.41 GB compressed and
extracts to approximately 4 GB. It is part of ordinary PR checks through a
digest-keyed cache, with a smaller deterministic frame selection on PRs.

The workflow runs on every pull request, daily at 02:17 UTC, or by manual
dispatch. Pull requests use a deterministic 64-frame SemanticPOSS selection;
daily/manual runs default to all 488 frames of sequence `00`. The same job
validates the real perception pipeline and sends its configured perception
output through `Uniform5`, `Uniform40`, `DistanceLOD`, and `UtilityLOD`,
preserving fair shared-input comparisons.

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
