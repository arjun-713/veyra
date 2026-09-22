# Iteration 01 — Track 1: tests green + boundary semantics (2026-09-22, fixed-benchmarks)

## Changes
1. `tests/test_runtime_telemetry.py`: completed the `pipeline_status` input with a real
   ground backend (`pypatchworkpp.patchworkpp`). The implementation's fail-closed None
   on missing ground status is correct per the real PipelineStatus contract (always
   emits all four keys); the test input was incomplete. No production code touched.
2. `tests/test_map_public_properties.cpp`: new `checkWindowEdgePointYieldsExactlyOneLeaf`
   pinning the investigated 100 m boundary (accepted edge return owns exactly one leaf).
3. Audit correction (no code): the "100 m single point yields no leaf" finding from the
   prior audit was a probe-script artifact (missing `--include-leaf-details` flag read
   as empty). Re-measurement: 1 leaf, count 1, conservation holds. No tracker/map bug.

## Gates (main agent, idle machine)
- C++ Release: build ok; `map_public_properties` pass; full ctest pending final pass.
- Python: 327 passed / 11 skipped (all non-temporal files) + telemetry file 3/3.
- Temporal files: 51 passed, 1 skipped, 2 failed (see below — carried to Iteration 02).
- Ruff + `git diff --check`: clean.

## Baseline benchmark (this branch, before changes — logic-neutral test-only delta)
map_benchmark.json: U5 53.2 MB/RMSE 0.0, U40 4.5/0.5637, Dist 25.8/0.4320, Util 27.5/0.4342.
Identical logical/RMSE to main audit. Copied to `reports/benchmark-loop/baseline/`.

## Carried to Iteration 02 (Track 9: temporal)
Two KITTI-gated tests fail on first-ever local execution with real data:
- `test_moving_vehicle_tracked_with_consistent_velocity`: frame-44 non-unknown 1801 < 3000.
- `test_traffic_window_measures_the_pass_by_car`: velocity p95 3.61 > 2.0 (median ~0 ok,
  association_recall 1.0, frames 45–47 all asserts pass).
Root cause so far: thresholds encode the OLD greedy association's measurements; main runs
the deliberate Hungarian association fix (ghost-tested, all other KITTI tests green).
Frames 45–47 quantitative behavior is good (6.07/6.86/7.58 m/s, cosine >0.998).
Next: widen evaluator measurement beyond 5 frames before any tracker/threshold decision.
No thresholds changed in this iteration.
