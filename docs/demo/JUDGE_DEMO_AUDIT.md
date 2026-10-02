# Judge Demo Audit — Veyra Desktop App

Branch: `judge-demo-proof`. Date: 2026-09-22. App: `apps/desktop` (Electron+Svelte) + `runtime/service.py`.

Method: for each project claim — can a reviewer SEE it, VERIFY it, understand WHY it matters — without source code or terminal.

## Summary verdicts (pre-pass)

| # | Capability | Backend exists? | Currently visible? | Proof shown? | Judge clarity | Missing UI / evidence | Action |
|---|---|---|---|---|---|---|---|
| 1 | Raw LiDAR | Yes (`frame_payload`, decimated points) | Partial (Map viewport, no frame/point/range header) | Weak | Low — points vs cells confusable | Frame #, point count, range, dataset header; explicit Raw/Both/Map toggle | Phase 3–4 |
| 2 | Semantic segmentation | Yes (ground_truth default; ONNX/SalsaNext/CENet optional) | Partial (semantic colors, no legend, no class names) | Weak | Low | Legend w/ real taxonomy + per-class counts; provider badge (Ground Truth vs model) | Phase 5 |
| 3 | Ground / non-ground | Yes (Patchwork++ optional; status-gated) | Partial (Ground layer, neutral when unavailable) | OK when available | Medium | Explicit "unavailable: enable Patchwork++" note instead of silent neutral | Phase 5 |
| 4 | Drivable / non-drivable | Yes (TerrainAnalyzer; unknown≠free) | Partial (Traversability layer) | Weak | Low | Legend + counts; unknown≠free explainer | Phase 5 |
| 5 | Static objects | Yes (map persists static evidence) | No (no static-only view) | None | Low | Motion layer shows static implicitly; add STATIC count in motion legend | Phase 9 |
| 6 | Dynamic objects / motion | Yes (TemporalTracker; needs timestamps+world pose) | Partial (Motion layer) | Weak; often `unavailable` on SemanticPOSS (no timestamps) | Low | Honest "Motion evidence unavailable for this dataset" banner; track/velocity display where present | Phase 9 |
| 7 | 2.5D representation | Yes (`CellStats` XY + height/statistics) | No (cells look like 3D boxes) | None | Very low | Representation banner "Adaptive 2.5D Grid — Rendered in 3D, stored as XY cells + height/statistics" + explainer | Phase 6 |
| 8 | Cell inspector | Partial (dblclick, raw key/values, 9 fields) | Yes but weak | Weak | Low | Click-to-inspect labeled panel; all stored fields; Unavailable (never fabricated); XY/resolution/LOD/height stats/count/semantics/ground/trav/motion/utility | Phase 6 |
| 9 | Adaptive resolution | Yes (4-level dyadic map, split/merge) | Partial (LOD colors, legend, per-level counts) | Medium | Medium | Boundaries default-visible toggle; live splits/merges per sec in LOD panel; topology-change flash | Phase 7 |
| 10 | 5/10/20/40 hierarchy | Yes (`resolution(l)=0.05·2^l`) | Yes (legend + colors) | Medium | Medium | Range rings 10/30/60/100 m overlay; near→fine / far→coarse caption | Phase 7, 14 |
| 11 | DistanceLOD | Yes (shipping baseline) | Partial (policy dropdown) | Weak — dropdown state only | Low | Active-policy badge; topology + telemetry visibly change on switch | Phase 8 |
| 12 | UtilityLOD | Yes but **INCONCLUSIVE vs DistanceLOD** on tested selection (see `docs/resolution-policies.md:106`, `reports/closure/utility/RESULT.md`); ships OFF | Partial (dropdown) | None honest | Very low | Utility layer + per-cell utility in inspector; honest "no measured gain on this selection" note; must NOT claim a win | Phase 8 |
| 13 | Memory reduction | Yes (snapshot bytes, benchmark RSS) | Partial (dashboard comparison needs loaded report) | Weak | Low | Live: logical vs allocated vs mapper RSS vs total w/ domain labels; analytical-vs-measured separation | Phase 10–11 |
| 14 | FPS | Yes (telemetry fps) | Yes (cards + charts) | OK | Medium | Keep; add render-vs-processing distinction (already partially there) | Phase 10 |
| 15 | Latency (map p95 etc.) | Yes (per-stage ns) | Partial (frame p95; map p95 only in legacy viewer) | Weak | Low | Map p50/p95/p99 + E2E p95 in live evidence panel | Phase 10 |
| 16 | Active cells | Yes | Yes (cards + per-level counts) | OK | Medium | Keep; add splits/merges per sec next to counts | Phase 7, 10 |
| 17 | Map quality (RMSE/coverage/retention) | Yes (benchmark quality reports) | Partial (RMSE in comparison table only) | Weak | Low | Full comparison columns w/ MEASURED/ANALYTICAL/UNAVAILABLE chips; N/A not zero | Phase 13 |
| 18 | 3D comparison | Yes (analytical dense ref + measured sparse baseline) | Partial (rows appended, thin) | Weak | Low | Dedicated 2.5D-vs-3D panel; MEASURED vs ANALYTICAL labels; "never allocated" warning | Phase 12 |
| 19 | Validation | Yes (`validation` command, real validator) | Partial (PASS/FAIL + raw JSON) | Weak | Low | Details table: dataset/sequence/frames/commit/model/policy/hardware/result; never fabricate PASS | Phase 16 |
| 20 | Events/diagnostics | Partial (status/benchmark/validation/governor only) | Partial (dashboard log) | Weak | Low | Enriched messages (cells split/merged, policy activation, frame counts, warnings); also visible in Map workspace | Phase 15 |

## Backend fields dropped before the UI (found in audit)

C++ `render_cells` emits per cell: `l,ix,iy,z,c,semantic_confidence,ground_evidence,terrain_confidence,geometry_complexity,m,q,drivable_evidence,u`.
`runtime/visualization.py` packs only 9 floats `(x,y,z,size,c,m,q,d,u)` — **semantic_confidence, ground_evidence, terrain_confidence, geometry_complexity are discarded**, and per-cell **point count / height min-max / variance are never emitted** by C++.
Fix: additive `n,zmin,zmax,zvar` in `render_cells` + 17-float v3 cell rows with NaN fallback; accept v2 in frontend for backward compat.

## Judge questions the app cannot answer today

- "What makes this 2.5D and not 3D?" → no banner, no explainer, no inspector proof.
- "Why is this region 5 cm and that one 40 cm?" → no range rings, no per-cell reason (utility vs distance).
- "How much memory is saved — measured or estimated?" → domains mixed, no labels.
- "What did UtilityLOD improve?" → nothing honest; must show utility signal without claiming a win.
- "Are moving objects identified?" → silent neutral when dataset lacks timestamps.
- "Can I reproduce validation?" → raw JSON only.
