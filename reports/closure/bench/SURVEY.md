# Benchmark-credibility survey (slice 1: survey + protocol fix)

Worktree: `worktrees/benchmark2`, branch `agent/benchmark2` @ `b3b2abf`.
Scope: `benchmarks/protocol.py`, `benchmarks/run_benchmark.py`,
`docs/benchmark-contract.md`, latest `benchmark-results/` artifacts.
No dataset downloads; no full benchmark runs.

## Artifacts examined

- `benchmarks/run_benchmark.py` (schema v2 producer, `SCHEMA_VERSION = 2`).
- `benchmarks/protocol.py` (V2 binary/text stream, digest-protected; not a metrics artifact).
- `docs/benchmark-contract.md` (schema-v2 contract).
- `benchmark-results/semanticposs-00-0-1.json` — **schema v1**, 1 frame, 2 policies.
  Stale relative to the v2 contract; useful only as a cautionary example.
- `benchmark-results/poss-gt-30.json` — perception-stage artifact (30 frames),
  not a `run_benchmark.py` product. No map policies, no provenance block.
- No schema-v2 `run_benchmark.py` artifact exists yet in `benchmark-results/`
  (none in this worktree; main checkout holds only the two files above).

## (1) Provenance: RECORDED (current code) / ABSENT (legacy artifacts)

Current `run()` provenance (`run_benchmark.py:1554-1591`) records:
protocol version, stream `selection_digest`, per-file `config_sha256` +
aggregate `config_digest`, `dataset_sha256`, `model_checkpoint_sha256`,
`git_sha`, PR number, workflow run/event ids, UTC timestamp, frame range,
compiler string, build type, `perception_executed`, runtime-captured hardware
(`hardware_metadata`, capture=`runtime`), repetitions, warmup, per-repetition
execution order, map window radius, and per-stage measurement scope strings.

Gaps (all verified in code):
- `dataset_sha256` is a CLI passthrough (`args.dataset_sha256`, line 1559).
  `benchmarks/run_local.sh` leaves it empty unless `--dataset-sha256` is passed,
  so artifacts routinely record `null`. The stream `selection_digest` covers the
  transmitted bytes but is not a dataset-version identifier.
- `model_checkpoint_sha256` is `null` whenever the checkpoint file is absent
  (lines 1560-1562); the configured path
  (`data/cache/models/salsanext-onnx-float/salsanext.onnx`) is gitignored and
  normally missing in CI, so model provenance is usually `null` with no record
  of *which* checkpoint was expected.
- No benchmark-binary identity (digest, version, or build hash) is recorded;
  `--binary` is an opaque path.
- Legacy artifacts record none of this: `semanticposs-00-0-1.json` (schema v1)
  has only `selection_digest`; `poss-gt-30.json` has `input_sha256` + config +
  `platform/python` only (no commit, no config digests, no model sha).

## (2) Frame counts for p50/p95/p99: NO GUARD (fixed, see below)

- `nearest_rank_summary` (`run_benchmark.py:112-131`) computes p50/p95/p99 for
  any `n >= 1` with no minimum-sample signal. Nearest-rank p99 on `n` samples
  is `max` for all `n <= 100`.
- Demonstrated by the legacy artifact: `semanticposs-00-0-1.json` reports
  `perception_latency_ns` and `map_update_latency_ns` with `count: 1` and
  `p50 == p95 == p99 == max` — a single sample presented as a tail.
- Default run shape (`--count 10 --warmup-frames 2 --repetitions 3`) yields 24
  `map_update` samples per policy (p99 = max, p95 = 2nd max) and only
  **3 `fps` samples** per policy (`_aggregate_policy_runs` appends one fps per
  run, line 1244-1245), so published `fps.p99` is the max of 3.
- `poss-gt-30.json` (30 samples) is adequate for p50, marginal for p95, and
  still max-based for p99. Stable tails need roughly n>=20 (p95) / n>=100 (p99).
- **Fix implemented:** `provenance.sample_adequacy` block (constants
  `MIN_SAMPLES_FOR_P95 = 20`, `MIN_SAMPLES_FOR_P99 = 100`, helper
  `tail_reliability()` + `sample_adequacy_report()`). Advisory, not rejecting:
  a hard reject would break the legitimate 2-frame product-CI ablation smoke
  (`test_tiny_generic_dataset_executes_complete_ablation_matrix`, count=2).
  Short-run p99 values remain in the artifact but are now explicitly flagged
  unreliable. Renderers should surface the flag (follow-up F5).

## (3) 3D baseline labeling: CORRECT in current code

- `analytical_3d_reference*` (`run_benchmark.py:265-312`) returns
  `status: "analytical_only"`, `executed_through_map_engine: False`, plus an
  explicit `warning: "memory estimate only; no dense grid was allocated or timed"`.
- `render_report._reference_summary` prints "not executed through the map engine
  and not a measured RSS value"; CSV columns are prefixed `analytical_3d_*`.
- The executed fine control is separately labeled
  `status: "executed_as_fine_reference"` (`uniform_5cm_2d`). No path conflates
  analytical bytes with measured RSS. Covered by
  `test_analytical_3d_reference_is_explicitly_not_an_executed_policy`.
- Legacy artifacts predate the baseline entirely (no 3D reference present) —
  not mislabeled, just absent.

## (4) Raw frame-level measurements: PARTIAL

Persisted per run in `policies.<name>.runs[]`:
- `frame_metrics[]` with per-frame `stages_ns`, topology churn, splits/merges,
  governor counters — yes, retained (only leaf rows are dropped by
  `_compact_snapshot` after quality computation, by design; raw points are
  never retained, by architecture invariant).
- Aggregates additionally pool all repetitions, so per-repetition frame series
  are recoverable from `runs[]` but not from `aggregate` alone.

Not persisted:
- Perception per-frame records (`selection["perception_records"]`) are
  summarized by `summarize_perception` and then dropped; only stage aggregates
  + `samples` counts survive. Frame-level perception audit requires re-running.
- `bridge_samples_ns` are pooled into the perception summary only.

## Concrete fix list

- [x] F0 (this slice): advisory `provenance.sample_adequacy` with p95/p99
      reliability flags — implemented, tests green (see below).
- [ ] F1: make `dataset_sha256` real — compute a manifest/manifest-digest in
      `run_benchmark.py` or require `--dataset-sha256` in `run_local.sh`
      instead of silently recording `null`.
- [ ] F2: record benchmark-binary identity (sha256 + `--version` string) in
      provenance; same for the effective perception config.
- [ ] F3: record the *expected* model checkpoint path even when the file is
      absent, so `null` digests stay attributable.
- [ ] F4: optional `--perception-frames-output` to persist raw per-frame
      perception records for audit runs.
- [ ] F5: `render_report.py` — print sample counts beside p95/p99 and warn
      when `sample_adequacy` flags tails unreliable.
- [ ] F6: document `provenance.sample_adequacy` in `docs/benchmark-contract.md`.
- [ ] F7: stop publishing (or clearly quarantine) the stale schema-v1
      `semanticposs-00-0-1.json`; its 1-frame p99 is the exact anti-pattern.

## Fix implemented (F0)

`benchmarks/run_benchmark.py`:
- `MIN_SAMPLES_FOR_P95 = 20`, `MIN_SAMPLES_FOR_P99 = 100`.
- `tail_reliability(count)` → `{samples, p95_reliable, p99_reliable}`.
- `sample_adequacy_report(measured_frames_per_run, repetitions)` covering
  per-policy stage-latency samples (`measured_per_run * reps`) and fps samples
  (`reps`), with a note that short-run tails equal max and are descriptive only.
- Wired into `run()` provenance as `sample_adequacy`; `measured_frames_per_run`
  hoisted to a local reused by the top-level field.

## Tests run

- `python3 -m unittest benchmarks.test_runtime benchmarks.test_product_benchmark benchmarks.test_regression benchmarks.test_render_report`
  (binary-dependent cases skip without `VEYRA_BENCHMARK_BINARY`; dataset cases
  skip without local data — no downloads performed).
