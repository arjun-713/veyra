# Iteration 03 — Track 2: semantic root-cause + native model (2026-09-22, fixed-benchmarks)

## Root cause (confirmed, not re-litigated)
SalsaNext KITTI checkpoint on Pandora scans: mIoU 0.093 (FOV/geometry/taxonomy mismatch).
The pipeline gate refusing POSS frames for SalsaNext stays correct.

## Key find: native weights were in the tree all along, packed
`data/cache/models/cenet-poss/cenet-poss-291MB.bin` (sha d466d387…) is the upstream
Google-Drive bundle, NOT loadable weights. Extracted `res/SENet_valid_best` (54 MB,
sha 9c07cead… matches the config pin exactly) — no download needed, git-ignored.

## Measurement (canonical script, production code path, system torch 2.14 CPU)
`scripts/measure_cenet_poss.py`, POSS seq00, 8 frames, 532,806 pts, threads=4:
- Veyra mIoU 0.628, accuracy 0.891 (6.8× SalsaNext). Closure's 0.65/0.81 reproduced
  within frame-selection spread.
- Range bins: 0–10 m 0.355 (car 0.97), 10–30 m 0.686, 30–60 m 0.503, 60 m+ 0.225.
  Genuine distance degradation, documented per-class (road null — absent in POSS, not zero).
- Latency p50 5412 ms, p95 6320 ms; torch RSS ~1 GB.

## CPU optimization (exhausted, not cherry-picked)
Thread sweep on identical 4-frame selection: 2T 5867 ms / 4T 5412 ms / 8T 8115 ms,
quality identical (0.620–0.628). 4 threads optimal; oversubscription hurts on 4C.
ResNet34-40×1800 forward dominates — no thread setting reaches real-time.
Quantization considered and rejected: even 3× faster (~1.8 s) stays 18× over a
100 ms budget while risking the quality just proven. Recorded, not attempted.

## Decision (production runtime unchanged)
- Real-time neural semantic on this CPU: REFUTED as a bottleneck proof (5.4 s ≫ budget).
- Map benchmarks keep `ground_truth` semantic mode; CENet recorded as the quality path.
- No default switch: it would trade the map's honest GT-mode claims for slower,
  still-non-real-time neural runs. Semantic status: quality PROVEN, real-time NOT PROVEN.

## Gates
- No production code changed this iteration (weights extraction is data staging).
- Artifact: `reports/benchmark-loop/iteration-03/cenet_metrics.json`.
