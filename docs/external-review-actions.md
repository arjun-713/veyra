# External Review Action #1: Quality/Resource Pareto Benchmark

Source: Jianhao Zheng's feedback supplied by the project owner. Evaluate the
trade-off between map quality and resource cost; memory/FPS alone is insufficient.

## Location of the implementation

Latest main includes the reconstruction comparison and trade-off plot from
PR #47 (`7fd2cae`, `2987333`). `fixed-benchmarks-pr` / PR #50 adds the
surface-support evaluation, directional ground evidence, robot-profile planner
evaluation and artifacts (`203b0ca`, `9f457a2`, `8c879b4`). `revamp-app-ui`
includes both through base `f3a1cb6`. UtilityLOD V2 is excluded.

## Quality/resource tasks

- [x] Compute accuracy, completion and symmetric Chamfer for the four public
  policies: Uniform5, Uniform40, DistanceLOD and production UtilityLOD.
- [x] Define the adaptive 2.5D comparison, shared frames/region/world frame and
  reference in [benchmark-contract.md](benchmark-contract.md).
- [x] Retain runtime/frame, map-update latency, logical/allocated bytes, RSS
  and active cells together with quality in CSV/JSON.
- [x] Generate quality vs latency, logical memory and peak-RSS plots and
  Pareto comparisons using `benchmarks/quality_resource.py`.
- [x] Preserve real-data evidence in `reports/external-review/` and protocol
  tests in `benchmarks/test_quality_resource.py` and `test_reconstruction.py`.
- [x] Surface measured quality/resource trade-offs in the desktop Evaluation
  screen; keep missing values and analytical baselines explicitly distinct.
- [ ] Add approved results to the final PPT under “Map Quality vs Resource Cost”.
  Presentation changes are outside this UI branch's scope.
- [ ] Obtain permission before publishing an acknowledgement or institutional
  attribution. No permission is recorded in the repository; do not imply endorsement.

Two definitions remain separate: observed Uniform5 support measures conditional
height accuracy and support completion; input reconstruction measures directed
nearest-neighbour distances and Chamfer. Neither is independent survey ground
truth. The supplied example numbers are illustrative and are not results.
Policy savings alone do not establish UtilityLOD superiority.

## Follow-up: per-device measured 3D baseline cache

This is an agreed design, not implemented by the desktop refinement PR.

- [ ] Run the measured 3D reference once for a device's first matching benchmark;
  compare against all four 2.5D policies with identical input and spatial bounds.
- [ ] Persist results and provenance locally. Reuse only when hardware/OS,
  dataset/input digest, sequence/frame range, reference resolution, build and
  relevant configuration match. Retain old records when the key changes.
- [ ] Label reused evidence “Measured on this device / Cached / recorded date”
  and expose an explicit recompute action.
- [ ] Use the bounded benchmark window on low-resource devices. If the reference
  fails or exceeds a resource limit, report unavailable rather than silently
  substituting an analytical estimate.

## Physical map versus robot traversal cost

- [x] Keep physical evidence separate from offline vehicle-profile costmaps.
- [x] Expose semantic class/confidence, elevation/layers, directional ground
  gradient/normal, slope, roughness and uncertainty in the map/query evidence.
- [x] Document the existing traversability label: perception evidence indicating
  drivable/non-drivable/unknown under configured terrain thresholds. It is not
  a universal vehicle safety truth; unknown remains blocked in planner evaluation.
- [x] Add bounded A* evaluation in `benchmarks/costmap_eval.py`.
- [x] Run semantics, slope, geometry, semantics+slope and full-map ablations;
  include occupancy as an additional control.
- [x] Store path length, hazard/unknown crossings, planning time and path-shape
  measurements in `reports/external-review/planner_ablation.json/.csv`.
- [x] Evaluate the same physical map with wheeled-UGV and quadruped profiles.
  These profiles are explicitly illustrative, not certified robot properties.
- [ ] Calibrate those profiles against actual robot specifications before
  making operational safety or universal traversability claims.
- [ ] Review whether a public-field rename is warranted; retain the current
  protocol field until a compatibility migration is approved.

Evidence may include partial/no-path outcomes. Check each artifact's status,
provenance and sample counts; an implemented evaluator is not proof that every
robot/profile/scene has a successful route.
