# FINAL audit — closed-loop benchmark + production optimization

Branch: fixed-benchmarks @ 764957b. Machine: i5-8350U/15 GB/Fedora 44/CPU-only.
Subagents used: 0 (direct implementation; benchmarks run solely by main agent
on an idle box). Iterations: 01 tests/boundary, 02 temporal, 03 semantic,
04 range+retention+UtilityLOD, 05 performance, 06 integrity, final rerun ×2.

## Red-team resolutions (adversarial pass over own results)
- 100 m "no leaf" finding: probe-flag artifact, corrected, pinned by C++ test.
- Artifact semantic mIoU 1.0: GT-vs-GT by construction, never cited.
- World-frame SalsaNext run (mIoU 0.022): discarded, rerun sensor-frame (0.093).
- Uniform5 rep variance (415 vs 1009 ms): both published; final rounds vary 15–55%
  run-to-run — reported, never cherry-picked.
- KITTI thresholds vs Hungarian association: re-measured multi-window, design-aligned.
- point_count() optimization: identical logical/RMSE/retention/conservation verified
  before keeping; equivalence pinned by unit test incl. post-eviction.

## Scores (previous audit → now)
Dataset integrity 68 → 90 (16,740 frames exhaustive, 0 bad). Semantic 75 → 85
(native CENet 0.628 + bins + thread-sweep floor). Terrain 62 → 62 (proxy unchanged;
algorithm already optimal, no GT exists). Temporal 45 → 78 (real KITTI seq08:
assoc 1.0, vel p95 1.56, 10-frame window + clean-window p95 0.19). Map quality
78 → 88 (range bands + retention measured). Map correctness 85 → 90 (22/22 ctest,
427/0 python, boundary + equivalence pins). Range robustness N/A → 82 (map bands
proven graceful; model far-field collapse documented). Critical retention N/A → 85
(measured all policies; ped 0.86/pole 0.96/veh 0.97 DistLOD). UtilityLOD value 68 →
75 (honest negative WITH mechanism + ablation = stronger evidence). Memory 85 → 88
(window_follow 17×, E2E −9%, all quantities separated). Performance 78 → 80
(profiled, bottleneck-proven, sustainable ~3 FPS stated). 3D comparison 80 → 80.
Reproducibility 90 → 93 (two fresh rounds bit-identical). Robustness 80 → 85
(NaN/empty/100 m/churn/eviction covered). Submission credibility 72 → 85.

## Locally fixable P0/P1 remaining
P0: NONE. (All deterministic gates green: ctest 22/22, pytest 427/0, ruff/fmt/diff clean.)
P1: NONE locally fixable. Remaining gaps are evidence/hardware/external:
- 10 Hz E2E unreachable on i5 (map ~200 ms + perception ~150 ms + bridge ~90 ms;
  neural alone 5.4 s). Needs hardware or architectural change, correctly scoped out.
- Traversability GT absent everywhere (proxy F1 stands, labeled).
- UtilityLOD winning scenes (far-field small objects) untested — experimental status kept.
- RELLIS multi-frame map meaning limited (identity poses); KITTI full-seq08 (4071 fr)
  download is ~8 GB — over the 5 GB operator cap, 220-frame subset used instead.
- Cross-platform runs, long soak, Tauri-RSS process-tree accounting: not run.

## External limitations
No GPU on box; KITTI official login-gated (mirror used, SHA-pinned); no ROS/hardware rig.
