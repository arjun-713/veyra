# Production UtilityLOD: bounded signal diagnosis

Scope: #57 diagnostics and the approved quality-boundary integration. This does not close
#60 (task-relevant benefit) or #62 (final integrated-main benchmark).

## Selection and provenance

`semanticposs-00-frames-0-2.json` records sequence 00, frames 0:2, 132,070
observations processed by production `utility_lod`. The actual pipeline used
GroundTruth semantics, Patchwork++, terrain processing, and disabled temporal
processing. It is **not neural inference or real-motion validation**.

Run source: `7f54285144eade166c28f9bfde31fb5531acd16b` on
`feat/utility-signal-diagnostics`. The binary was freshly built from the mapper
changes in `6e61036`; the subsequent commit changed only Python diagnostic
output/tests. Input, binary and configuration SHA-256 values, timestamp,
hardware and stage status are in the artifact. The preserved unrelated
`:memory:.ses` file makes `working_tree_dirty` true; the run is not claimed as a
clean-main benchmark. No untracked source files were present at capture.

## Original capture: measured findings

- 89,110 / 132,070 observations failed the quality gate (67.5%). Density failed
  for none: every density value occupied the top histogram bin, consistent with
  the current adapter's constant `point_density = 1`.
- Person (class ID 6) had 706 / 729 gate failures; bicyclist (ID 7) had
  153 / 158; pole (ID 18) had 1,366 / 1,367. Car (ID 1) had
  19,092 / 23,472 failures. IDs follow `datasets/common/taxonomy.py`, not model
  raw-label IDs. Counts are per observation, not distinct tracked objects.
- Semantic importance was near one for 128,862 observations (97.6%). The
  potential weighted semantic sum was 38,658.6, while the effective sum after
  gating was 12,888.0. Known-class confidence is not selective importance.
- Motion was zero for every observation because temporal processing was
  disabled; this is not evidence that the motion implementation is defective.
- Recorded request reasons include 9 ordinary new promotions, 532 safety
  promotions, 888 retained promotions, 25,749 score rejections and 2,994 dwell
  rejections. They are requests, **not counts of successful topology splits**.
- Final governor state was `approaching_budget`, with optional splits disabled
  and 121 budget suppressions. This short diagnostic does not isolate timing
  overhead or establish a resource-budget or latency distribution claim.

Reason counts, class counts, signal histograms and support histograms each
reconcile to 132,070 decisions. Gate-pass plus gate-fail counts also reconcile.
Quality failures and the `quality_gate` reason differ because protected-baseline
requests are classified separately even when their input quality is low.

## Integration prerequisite and next gate

Arjun subsequently authorized the narrow `perception/pipeline.py` correction
after confirming it was absent from Samay's PRs. Its contract and regression
fixtures are in `docs/utility-signal-integration-contract.md`. Ground still uses
conservative terrain quality; valid non-ground semantic evidence is no longer
erased solely because ground-fit confidence is zero. Unknown terrain stays unknown.

Review this correction before the overlapping mapper-side class-importance/support
correction. Temporal PR #68 is independently held for parked-support loss; do not
merge that defect as an integration prerequisite. Keep DistanceLOD,
safety floor, production defaults and frozen challenge selection unchanged.
Only then test actual critical-region retention against DistanceLOD; report
NO-GO if the advantage is not demonstrated. Final benchmark evidence must be
generated separately from approved, integrated, clean main.

## Reproduce

```sh
cmake -S . -B build-utility-diagnostics -DCMAKE_BUILD_TYPE=Release
cmake --build build-utility-diagnostics --parallel 2
.venv/bin/python -m benchmarks.utility_diagnostics \
  --executable build-utility-diagnostics/apps/benchmark/veyra_benchmark \
  --dataset semanticposs --sequence 00 --start 0 --count 2
```

Pipeline logs are on stderr; stdout is JSON. The CLI permits 1–8 frames only.
This report contains aggregates, not scans, model weights or raw-point history.

## Original capture: local verification

Fresh Release build and final full CTest: 22/22 passed, including the full
Python unittest target (147.80 seconds). The three focused diagnostic tests
passed, including enabled/disabled snapshot equality and Python/native stdout
isolation. Changed Python files passed Ruff/check/format; `git diff --check`
passed. Optional dependency/data skips in the broader suite remain skips, not
real neural/temporal/cross-platform proof. This report does not claim green CI.

## Quality-boundary replay (2026-09-27)

`quality-boundary-after.json` preserves a fresh branch-local diagnostic on the
same SemanticPOSS sequence and frames (0:2), with 132,070 observations, GT
semantics, real Patchwork++ and terrain, and temporal disabled. Its exact SHA,
dirty-state indicator, source/binary/configuration digests and input digest are recorded;
this is **not clean-main benchmark evidence**.

| Gate failures, per observation | Original | Corrected quality boundary |
|---|---:|---:|
| All classes | 89,110 | 3,877 |
| Car (ID 1) | 19,092 / 23,472 | 51 / 23,472 |
| Person (ID 6) | 706 / 729 | 26 / 729 |
| Bicyclist (ID 7) | 153 / 158 | 3 / 158 |
| Pole (ID 18) | 1,366 / 1,367 | 8 / 1,367 |

This demonstrates that the boundary stopped erasing legitimate non-ground
confidence. It does **not** demonstrate useful refinement or quality superiority.
Semantic importance still saturates for known classes, density still equals one,
and semantics alone still cannot cross the fused-score threshold. Those #57
mapper-side corrections remain outstanding. Governor suppression counts are
load-dependent and must not be interpreted as a controlled latency comparison.

### Integration verification

Fresh Release rebuild and full CTest: **22/22 passed** (346.48 s). The Python
entry ran **422 tests: 412 passed, 10 optional skips**, terminating in 286.69 s.
The 41 focused diagnostic, quality/resource and product-benchmark tests passed.
Changed Python files passed Ruff, formatting and compilation; diff checks passed.
These are local software gates, not neural quality, live UI or cross-platform proof.

Tests must use explicit paths to the freshly built executables. At present the
top-level CMake configures tests before apps, so the conditional benchmark-target
environment override is missing from generated CTest entries. Do not let an old
`build/` executable masquerade as verification of this branch:

```sh
VEYRA_BENCHMARK_BINARY="$PWD/build-utility-diagnostics/apps/benchmark/veyra_benchmark" \
VEYRA_RUNTIME_BINARY="$PWD/build-utility-diagnostics/apps/runtime/veyra_runtime" \
VEYRA_MAPPER="$PWD/build-utility-diagnostics/apps/runtime/veyra_runtime" \
ctest --test-dir build-utility-diagnostics --output-on-failure

VEYRA_BENCHMARK_BINARY="$PWD/build-utility-diagnostics/apps/benchmark/veyra_benchmark" \
.venv/bin/python -m unittest benchmarks.test_utility_diagnostics \
  benchmarks.test_quality_resource benchmarks.test_product_benchmark -q
```
