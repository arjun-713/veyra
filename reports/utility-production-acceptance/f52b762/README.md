# Committed-source production baseline (before bounded support preservation)

This is an unmerged candidate-source measurement, **not current-main acceptance**.
Source: `f52b762616f44aa0948df9899faec195c0123d40`; main base:
`c6e2c30f43f00a0f35c3b2e094d3850cf6d3da3c`.

SemanticPOSS sequence 00, frames 0:30, two repetitions, two warmup frames:
56 measured mapper updates per policy. All four policy input-stream hashes match.
Ground-truth semantics, Patchwork++ ground and terrain; temporal disabled.
This does not validate neural semantics or real motion. Any checkpoint digest
in the general provenance is an available-file fingerprint, not an executed model.
The source-clean gate and executable digest are recorded in `benchmark.json`.
An unrelated pre-existing `.ses` file makes whole-tree dirty status true;
execution source was clean and unchanged for the complete run.

The result does **not** establish a critical-region UtilityLOD advantage.
Frame-local planning prevents same-scan oscillation, but historical coarse
evidence still becomes a non-spatial prior on a split. Support preservation
and its resource cost require a separate reviewed change.

Reproduce from the recorded source after a Release build:

```sh
.venv/bin/python -m benchmarks.run_benchmark \
  --binary build/apps/benchmark/veyra_benchmark \
  --dataset semanticposs --sequence 00 --start 0 --count 30 \
  --warmup-frames 2 --repetitions 2 --retain-frames --require-clean-source \
  --dataset-sha256 0b28c64d8a7b19aa41aac8116ba27c6011f6abe3693026a1cdc4289dbee37944 \
  --output /tmp/veyra-production-baseline.json --csv-output /tmp/veyra-production-baseline.csv \
  --quality-artifact-dir /tmp/veyra-production-quality
```

This run meets the harness's minimum sample count for p95, not a reliable p99
tail study. Latencies exclude parsing, snapshots and serialization as documented
in the report. Logical payload and measured process RSS are separate quantities.
After integration, issue #62 still requires a new run on the approved main SHA.
