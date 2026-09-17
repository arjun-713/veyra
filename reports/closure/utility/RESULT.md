# UtilityLOD Closure — Controlled Ablation vs DistanceLOD

Status: DRAFT (benchmark running) — UtilityLOD 70% → 100% requires the
numbers below, all measured on one identical real-data stream.

## Claim under test

UtilityLOD exists to spend fine resolution where losing information
matters (thin/small/hazardous evidence at range: poles, pedestrians,
vehicles, non-drivable terrain) while remaining cheaper than Uniform5.
DistanceLOD is the baseline it must beat; detail alone is not quality.

## Method (controlled)

- Same staged SemanticPOSS sequence-00 stream (frames 0–29) for every
  policy: one perception pass, one stream file, digest-pinned per run
  (`--retain-frames` so retention is measured, not unavailable).
- Legs: `ablation_distance` (control) vs `+geometry` vs
  `+semantics(+uncertainty)` vs `+motion` vs `+traversability` vs full
  `utility_lod`, plus `uniform5/uniform40/distance_lod` context.
- Invariants: every run checks point conservation, duplicate ownership,
  split/merge conservation, mixed-resolution topology.
- Motion caveat (data, not code): SemanticPOSS ships no timestamps, so
  the temporal stage is unavailable and motion evidence is uniformly
  zero; the motion leg is therefore a no-op control proving no spurious
  promotion/cost. Motion-path correctness is covered by unit tests.

## Results

(see `ablation_matrix.json`; analytical vs measured reported separately)

- Task quality: pole / pedestrian / vehicle / hazard retention, elevation
  RMSE vs Uniform5 fine reference.
- Cost: map-update p50/p95/p99, peak RSS, logical/allocated bytes,
  active leaves per level, topology churn, governor interventions.
- Only-promotes: property test over all signals × ranges × gate states
  × safety × hysteresis age (`tests/test_policy.cpp`).

## Verdict

TBD from `ablation_matrix.json`.
