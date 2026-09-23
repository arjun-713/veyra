# Visual Proof Matrix — Veyra Judge Demo

Branch: `judge-demo-proof`. Rule: every claim has backend evidence, a UI representation, and a judge verification step. Missing data shows N/A / Unavailable — never zero, never fabricated.

| Claim | Backend evidence | UI representation | How judge verifies it | Status |
|---|---|---|---|---|
| Raw LiDAR input | `frame_payload` decimated points + metadata | Map viewport (Raw/Both/Map) + header: frame #, dataset/sequence, point count, range | Select dataset → first frame renders; toggle Both→Raw | PASS |
| Semantic interpretation | `pipeline_status.semantic` + taxonomy IDs; ground_truth default, model when configured | Semantic layer + 20-class legend + provider badge (dataset ground truth vs model) | Switch to Semantic; read legend; check provider in Performance | PASS |
| Ground vs non-ground | Patchwork++ binding or unavailable status | Ground layer; neutral + n/a badge when unavailable | Toggle Ground; unavailable shows n/a, never fake colors | PASS |
| Traversability | TerrainAnalyzer drivable/non/unknown; unknown≠free invariant | Traversability layer + legend (Unknown — never drivable) | Toggle Traversability; read counts in Performance | PASS |
| Motion where supported | TemporalTracker + timestamps + world pose; unavailable otherwise | Motion layer + STATIC/MOVING/UNKNOWN legend; honest unavailable banner | Toggle Motion; SemanticPOSS shows unavailable banner (no timestamps) | PASS (honest UNAVAILABLE) |
| Adaptive 2.5D storage | `CellStats` XY + height/statistics; `map_cells` leaves | Representation banner + 2.5D explainer + InstancedMesh cells | Read banner; expand "What is 2.5D?" | PASS |
| 2.5D cell contents | v3 17-float rows: xyz, size, class, motion, quality, drivable, utility, sem-conf, ground-ev, terrain-conf, geom-complex, count, zmin/zmax/zvar | Click cell → Cell Inspector, 15 labeled rows; Unavailable for absent fields | Click any cell; v2 backends show Unavailable for new fields | PASS |
| 5/10/20/40 hierarchy | `resolution(l)=0.05·2^l`; `cells_by_level` | LOD layer colors + legend + live per-level counts + splits/s + merges/s | Turn on LOD + boundaries; watch counts | PASS |
| Near→fine, far→coarse | DistanceLOD boundaries 10/30/60 m | Range-rings toggle (10/30/60/100 m, LOD colors) | Enable rings in top view | PASS |
| Policy switching | `policy` command → mapper → snapshot → telemetry | Policy select + policy badge + topology/memory/latency shift | Switch Uniform5→DistanceLOD; watch cells/memory change | PASS |
| UtilityLOD signal | Per-cell utility `u` in leaf dump; quality-gated promotion | Utility layer + per-cell utility in inspector | Toggle Utility; inspect high-utility cells. No win claimed: DistanceLOD remains baseline per `docs/resolution-policies.md` | PASS (signal visible, claim honest) |
| Measured memory | Snapshot logical/allocated bytes; OS RSS per process | Live evidence strip + Performance memory-domains card (logical / allocated / mapper / python / total backend) | Read Performance; domains labeled NOT COMPARABLE | PASS |
| Analytical vs measured | `reference_baselines` (analytical dense) vs executed policies | Comparison table MEASURED/ANALYTICAL/UNAVAILABLE chips; "never allocated" note | Open Compare; read chips | PASS |
| Latency / FPS | Per-stage ns; p50/p95/p99; processing + render FPS | Metric strip (E2E p95, MAP p95, FPS) + Performance charts + stage table | Watch strip while playing; open Performance | PASS |
| Map quality | RMSE vs Uniform5, coverage, semantic + task-class retention | Comparison columns: RMSE, coverage, semantic %, vehicle % (pole/ped in tooltip); N/A when absent | Open Compare after benchmark | PASS |
| 2.5D vs 3D | Adaptive 2.5D measured; sparse 3D measured; dense 3D analytical | Comparison 3D rows + strategy column | Read strategy + status chips | PASS |
| Benchmark method | Digest-pinned stream, repetitions, warmup, hardware profile | Benchmark controls + full-artifact details + previous-run compare | Run four-policy benchmark; open artifact JSON | PASS |
| Validation | Real `validation` command result | Benchmarks validation card: details table + PASS/PARTIAL/FAIL + raw JSON | Run session validation | PASS |
| Events | status/benchmark/validation/governor events | Dashboard log + Map events drawer, timestamps, error styling | Open drawer; trigger policy change | PASS |
| Dataset capability | Catalog sequences (frames/labels/poses/timestamps) | Datasets capability table + EMPTY→VALIDATING→LOADED→READY phase | Choose directory; read table before opening | PASS |
| Glossary | `GLOSSARY` in dashboard.ts | Tooltips (ⓘ) on LOD, RSS, p95, policy, memory | Hover ⓘ terms | PASS |

## Consumed by `fixed-benchmarks` later (display-ready, N/A today)

Semantic mIoU columns, per-range quality, critical-object retention beyond vehicle/pole/pedestrian, render-side track overlays — all render N/A when the report omits them.
