# Judge Demo Flow — Veyra

Canonical path a judge walks without DevTools or terminal. Each step names the workspace and the visible proof.

```text
Launch → Datasets → Open Dataset → Map (Raw LiDAR) → Start Processing
→ Semantic → Traversability → Adaptive 2.5D Map → Resolution layer
→ Inspect cell → Motion (or honest unavailable) → Policy switch
(Uniform5 ↔ DistanceLOD) → Live evidence shift → Benchmarks (Compare)
→ 2.5D vs 3D → Validation (PASS/PARTIAL/FAIL)
```

## Step table

| # | Action | Where | Judge sees | Backend proof |
|---|---|---|---|---|
| 1 | Launch Veyra | Shell | Dashboard + "No dataset selected" | `info.status.state=unconfigured` |
| 2 | Datasets → Choose directory → sequence → Open dataset & preview | Datasets | EMPTY→VALIDATING→LOADED→READY; capability table (frames, labels, poses, timestamps, semantic/motion capability) | `chooseDataset` catalog; `configure` + first `step` |
| 3 | Raw LiDAR appears | Map (Raw) | First-frame point cloud + header: frame #, points, range, dataset | `frame_payload` decimated points; metadata |
| 4 | Start Processing (Play) | Map playback | Frames advance; telemetry ticks; events log | `start` + `telemetry` + `visualization` streams |
| 5 | Semantic view | Map layer=Semantic | Colored classes + legend + provider badge (Ground Truth / model) | `pipeline_status.semantic`, taxonomy IDs |
| 6 | Traversability view | Map layer=Traversability | Green/red/neutral + unknown≠free note | `drivable` evidence; terrain status |
| 7 | Adaptive map | Map (Both→Map) | Cells overlay points; representation banner "Adaptive 2.5D Grid" | `map_cells` leaves |
| 8 | Resolution layer | Map layer=LOD | 4 colors + boundaries + per-level live counts + splits/merges | `cells_by_level`, topology deltas |
| 9 | Inspect cell | Click cell | Inspector: XY, resolution, LOD, height mean/min/max/var, count, class+conf, ground, trav, motion, utility; Unavailable where absent | v3 cell rows (NaN-safe); v2 fallback |
| 10 | Explain 2.5D | Banner expander | "(X,Y) → elevation + statistics; not a dense XYZ volume" | `docs/layered-map-design.md` |
| 11 | Range rings | Toggle | 10/30/60/100 m rings; near→fine, far→coarse | DistanceLOD boundaries |
| 12 | Switch Uniform5 → DistanceLOD | Policy select | Topology + cells + memory + latency visibly change; active-policy badge | `policy` command → mapper → snapshot → telemetry |
| 13 | Live evidence | Metric strip + Performance | Policy, cells, logical/allocated/RSS, FPS, map p95, E2E p95, dropped | `telemetry` (all measured; N/A otherwise) |
| 14 | Motion | Map layer=Motion | STATIC/MOVING/UNKNOWN legend; tracks/velocity where present; else honest unavailable banner | Temporal status; motion evidence |
| 15 | Compare | Benchmarks | Uniform5/40, DistanceLOD, UtilityLOD, 3D rows; MEASURED/ANALYTICAL/UNAVAILABLE chips; N/A not zero | Benchmark report artifact |
| 16 | 2.5D vs 3D | Benchmarks panel | Adaptive 2.5D (measured) vs sparse 3D (measured) vs dense 3D (analytical, never allocated) | `reference_baselines` |
| 17 | Validation | Benchmarks → Run session validation | Details table + PASS/PARTIAL/FAIL from real validator | `validation` command result |

## Friction removed

- Dataset open jumps straight to Map with first frame; no empty viewer.
- Raw/Both/Map is one segmented control, not two checkboxes to puzzle over.
- Cell inspect is single-click with labeled fields (dblclick retained).
- Demo-critical proof (representation, policy, evidence) sits in Map; advanced JSON stays in collapsible details.
- Same production state/backend everywhere; no demo-only mock path.

## Walkthrough validation (2026-09-22, branch `judge-demo-proof`)

Headless worktree: no `data/` dataset, no display. Engine + packer + UI verified separately:

| # | Step | Result | Evidence |
|---|---|---|---|
| 1–2 | Launch, choose dataset | UI verified (build + `npm test` 57 pass); live dataset NOT RUN here | `npm run check/build` clean |
| 3–4 | Raw frame + play | Protocol verified: `VEYRA_ENGINE 2` → F/P/E → `available` | Engine smoke probe |
| 5–8 | Semantic/terrain/map/Resolution | Packer round-trip: M JSON → v3 17-float rows, XY/size/count exact | `PACK ROUND-TRIP OK` + unit tests |
| 9–11 | Inspect cell, 2.5D, rings | Inspector rows unit-tested (Unavailable-safe); rings render from pose | dashboard.test.ts |
| 12–13 | Policy switch, live evidence | `policy` command path unchanged; new strip fields from measured telemetry | telemetry mapping_p95 additive |
| 14 | Motion | Honest unavailable banner when temporal stage missing | `layerUnavailable` gate |
| 15–17 | Compare, 2.5D vs 3D, validation | Columns render N/A for absent fields; validator result passthrough | ComparisonEvidence + validation table |

Full 17-step live run with SemanticPOSS/RELLIS on a display machine remains for the demo rehearsal.
