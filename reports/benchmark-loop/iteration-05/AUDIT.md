# Iteration 05 — Tracks 7/8: profiled performance + memory (2026-09-22, fixed-benchmarks)

## Profiling (no blind optimizing)
- Python cProfile, 1 frame: terrain.analyze ~174 ms, height_above_ground ~71 ms,
  both already optimized in prior passes (lexsort medians, ndimage kernels, packed
  codes — comments document each). Remaining cost is numpy-intrinsic; float32
  conversion would risk quality for ~10 ms. Declined with reason.
- C++ binary ingest: per-point 2× Clock::now() kept (stage metrics depend on it).
- Found: begin_frame ran a FULL `snapshot()` (leaf collect + O(n log n) sort over
  ~150k leaves) per frame just for one conservation integer. map_window_follow
  p50 53 ms, mostly sort.

## Optimization: O(n) point_count() accessor (additive API, zero behavior change)
- `Map::point_count()` + 3 wrapper forwards + `MapPolicyAdapter::point_count()`;
  sums exactly the leaf+prior counts `snapshot()` sums (pinned by new
  `checkPointCountMatchesSnapshotTotal`, incl. post-eviction agreement).
- Both begin-frame uses switched; end-frame publishing snapshot untouched, so
  conservation semantics identical in all modes (eviction/clearing/governor).

## Measured (canonical 4-policy, 2 reps, identical digest)
- map_window_follow p50: 53 → 2–5 ms all policies (17×). E2E p95 improved
  (DistLOD 586 → 393 ms). FPS 2.38 → 2.97 (DistLOD).
- Regression check: logical bytes, RMSE, retention, conservation identical all policies.
- 10 Hz verdict unchanged: E2E ~340 ms vs 100 ms budget; neural alone 5.4 s.
  Bottleneck proven, best sustainable GT-mode rate ~3 FPS documented.

## Gates
- ctest 22/22. Full python+benchmarks: 427 passed, 20 skipped, 0 failed.
- Build warning-free; ruff/format/diff-check clean.
