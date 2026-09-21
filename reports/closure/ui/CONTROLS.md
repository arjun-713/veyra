# Veyra UI / Telemetry / Renderer / Supervisor — Controls & Telemetry Inventory (slice 1)

- Scope: inventory only, no code changes. Read-only slice.
- Worktree: `worktrees/ui-telemetry`, branch `agent/ui-telemetry`, base `demo-readiness` @ `1ad1388`.
- Files read: `apps/desktop/src/renderer/App.svelte`, `Dashboard.svelte`, `MapCanvas.svelte`,
  `Chart.svelte`, `Icon.svelte`, `dashboard.ts`, `colors.ts`, `main.ts`, `main.ts` (Electron),
  `supervisor.ts` (Electron), `preload.ts`, `api.ts`, `core.ts`, `tauri-api.ts`,
  `src-tauri/src/telemetry.rs`, `supervisor.rs`, `commands.rs`, `lib.rs`,
  `desktop_control/mod.rs`, `control_host/mod.rs` (headers only),
  `runtime/service.py`, `runtime/telemetry.py`, `runtime/visualization.py` (pack path only).
- Convention below: **allowed-states** = when the control is enabled; **command** = wire call;
  **backend-result** = what the backend returns; **UI-response** = what the user sees.
  Unavailable numbers render `—` via `format`/`f`/`mb`/`memory` helpers (never fabricated).
- Control count: **~44 interactive controls + 4 non-interactive indicators** (C1–C48).
  Dead/dup/fake list: **2 dead, 4 dup, 5 fake-ish** (D-1…D-11).

---

## A. Visible controls inventory

### A1. Rail + header (always visible)

| ID | Control | Allowed states | Command | Backend result | UI response |
|----|---------|----------------|---------|----------------|-------------|
| C1–C5 | Rail nav: Dashboard / Live Mapping / Datasets / Benchmarks / Settings | always | none (local `workspace` state) | n/a | swaps main view; `active` class |
| C6 | Header Scenario select | enabled iff dataset catalog loaded (`catalog.sequences` non-empty) | `command('sequence',{sequence})` → Python `_execute('sequence')` → full `_configure` copy | `response.status` merged into `status` | status pill / playback limits update; failure → error alert |
| C7 | Export button | always | `diagnostics()` → save-file dialog with `{version,platform,arch,system,status,telemetry,ui_visualization_dropped,stderr}` | boolean (file written or not) | **no success feedback** (see D-6) |
| C8 | Theme sun indicator | n/a (span, no handler) | none | n/a | static icon (see D-1) |
| C9 | Error alert → Restart runtime (conditional) | visible iff `error` non-empty | Electron: `veyra:restart` (supervisor stop + relaunch + re-configure); Tauri: `runtime_command('restart')` → daemon controller restart | status object | `status` replaced, error cleared; failure re-arms alert + recovery |
| C10 | Error alert → Dismiss × (conditional) | visible iff `error` non-empty | none (local `error=''`) | n/a | alert hidden; backend state unchanged |

### A2. Dashboard workspace (`Dashboard.svelte`)

| ID | Control | Allowed states | Command | Backend result | UI response |
|----|---------|----------------|---------|----------------|-------------|
| C11a–f | 6 metric cards (FPS / latency / RAM / Active Cells / Mem-reduction / mIoU) | always (all six share one handler) | none — all call `openPerformance()` (local nav) | n/a | navigates to Performance workspace (see D-4) |
| C12–C14 | 3 panel camera selects (Raw / Semantic / Map) | always | none (local `rawView`/`semanticView`/`mapView`) | n/a | corresponding `MapCanvas` view changes |
| C15 | Empty-panel "Choose dataset" buttons (×2 shown when `!frame`) | visible iff no frame | none — `openDataset()` → `workspace='Datasets'` | n/a | shows config screen (§A5) |
| C16 | Dashboard policy select | disabled iff `!status.frames` | `runCommand('policy',{policy})` → `_configure` with new policy | `response.status` | caption policy label + map re-leaf; failure → error alert |
| C17 | Event-log filter select (All/Errors/Benchmarks) | always | none (local `eventFilter`) | n/a | filters last-30 list; store retains 200 |

### A3. Map workspace (`App.svelte` §§Map + `MapCanvas.svelte`)

| ID | Control | Allowed states | Command | Backend result | UI response |
|----|---------|----------------|---------|----------------|-------------|
| C18 | Raw LiDAR toggle | always | none (local `showPoints`) | n/a | `points.visible` |
| C19 | Adaptive map toggle | always | none (local `showCells`) | n/a | `mesh.visible` |
| C20 | Cell boundaries toggle | always | none (local `boundaries`) | n/a | instanced-mesh wireframe |
| C21 | Follow robot toggle | always | none (local `follow`; needs `meta.pose` len 16) | n/a | camera target tracks pose; no-op if pose missing |
| C22–C28 | Layer buttons: Semantic / Elevation / Ground / Terrain / Motion / LOD / Utility | always; `n/a` badge via `layerUnavailable` for ground/terrain/motion/utility only | none (local `mode`; backend `layer` command exists but is **never sent**, see D-2) | n/a | recolors points+cells; `layer-warning` banner if unavailable |
| C29 | Cell inspector Close (conditional) | visible iff inspector open | none (local `inspector=null`) | n/a | panel collapses to hint |
| C30a–c | Camera segmented: orbit/top/driver | always | none (local `view`) | n/a | camera repositioned |
| C31 | Screenshot button | always | `screenshot()` → canvas `toDataURL` (Tauri) / `capturePage` (Electron) + save dialog | boolean | file written; failure → error alert |
| C32 | Empty-map CTA "Open dataset →" (conditional) | visible iff `!frame` | none — `workspace='Configuration'` | n/a | shows config screen (label mismatch, see D-8) |
| C33 | Reset ↺ | disabled iff `busy \|\| unconfigured` | `command('reset')` → `_configure(same config)` | status | map cleared, index reset |
| C34 | Play/Pause ▶/Ⅱ | disabled iff `busy \|\| unconfigured` | `command('start')` / `command('pause')` | status | `state` running↔paused; `start` at end re-configures |
| C35 | Step ▸\| | disabled iff `busy \|\| unconfigured` | `command('step')` → `_process(index+1, force_visual)` | status + telemetry + visualization | single frame advances even when paused |
| C36 | Seek slider | disabled iff `busy \|\| !status.frames` | `command('seek',{index})` (value latched on `oninput`, sent on `onchange`) | status + frame | jumps; backward seek bumps `generation` (stale frames rejected) |
| C37 | Playback speed select (0.25–8×) | always | `command('speed',{speed})` (validated 0.1–8) | status | `status.speed`; tick interval `1/(fps*speed)` |
| C38 | Mapping policy select (Map) | always | `command('policy',{policy})` (4 policies) | status | same as C16 (dup, see D-5) |

`MapCanvas` dbl-click pick (C48): local raycast → `onInspect` → inspector shows
`x,y,elevation,resolution,semantic_class,motion,quality,drivable_evidence,utility`
(cell row fields `r[0..8]`). No backend call.

### A4. Performance workspace (orphan — no rail entry, see D-3)

| ID | Control | Allowed states | Command | Backend result | UI response |
|----|---------|----------------|---------|----------------|-------------|
| C39 | Governor override select (Automatic / Disabled-debug / Conserve) | disabled iff `busy \|\| !status.frames` | `command('governor',{mode})` → `set_governor_override` | `{governor}` | budget/state rows update; select always re-displays Automatic (see D-7) |

Everything else here is display (see §B).

### A5. Benchmarks workspace

| ID | Control | Allowed states | Command | Backend result | UI response |
|----|---------|----------------|---------|----------------|-------------|
| C40 | Frames number input | always (1–100000) | none until Run (local `benchmarkCount`) | n/a | local value |
| C41 | Run four-policy benchmark | disabled iff `busy \|\| !status.dataset` | `command('benchmark',{dataset,sequence,count})` → subprocess `benchmarks.run_benchmark`; async `benchmark` events | `{state:'running'}` then `benchmark` complete/error event | `benchmarkState` chip; `report` table on completion; error → alert |
| C42 | Open report | always | `openReport()` file picker → JSON | JSON or null | `report` table renders |
| C43 | Export JSON | disabled iff `!report` | `exportReport(report)` save dialog | boolean | file written; no success feedback (same as D-6) |
| C44 | Compare previous run | always | `openReport()` (same picker as C42) | JSON or null | sets `previousReport` → comparison table (see D-5b) |

### A6. Datasets / Configuration (shared `{:else}` view — see D-3b)

| ID | Control | Allowed states | Command | Backend result | UI response |
|----|---------|----------------|---------|----------------|-------------|
| C45 | Import configuration | always | `openConfig()` picker → JSON (strips `map.executable`) | JSON or null | `configText` refreshed; notice to pick dataset dir |
| C46 | Dataset format select | always | none (local `dataset`) | n/a | arms C47 |
| C47 | Choose dataset directory… | disabled iff `busy` | `chooseDataset(dataset)` → dir picker + `datasets` inspect | `{root,status,sequences,diagnostics}` | catalog table; first non-empty sequence pre-selected |
| C48a | Sequence select | visible iff catalog | none (local `sequence` + `config.sequence`) | n/a | arms Configure |
| C49–C51 | Display profile presets (Performance/Balanced/Quality) | always | none — local `profileConfig` (point/cell budgets, update_hz, resource_profile; forces `governor_override:'automatic'`) | n/a | budget rows + JSON text update |
| C52 | Default map policy select | always | none (local `config.map.policy`; applied only on Configure) | n/a | JSON text update |
| C53 | Validate | disabled iff `busy` | `validateConfig(JSON.parse(configText))` → `config_validate` + `build_pipeline` | ok or error message | notice "Configuration is valid." or error alert |
| C54 | Save preset | disabled iff `busy` | `saveConfig(...)` (strips `map.executable`) | boolean | file written; no success feedback |
| C55 | Configure runtime | disabled iff `busy` | `configure(next)` → `configure` + auto `step` for first frame | status | `frame=null`, notices, first frame loaded; failure → alert |

Backend commands with **no UI sender** (reachable via API/tests only):
`status`, `shutdown`, `metrics`, `presets`, `diagnostics`(runtime-level),
`layer`, `sequence` (C6 does send `sequence`), `config_validate` (C53 sends it).
Notably `layer` (service.py `COMMANDS`) is accepted by Python but neither
Electron `validateCommand` nor any Svelte handler emits it — dead surface (D-2).

### Dead / duplicate / fake controls

- **D-1 (dead indicator):** header theme sun — decorative `<span>`, no handler.
- **D-2 (dead command):** backend `layer` command unreachable from UI; view layers are
  purely local recolorings of the already-packed frame (`mode` in `colors.ts`).
  Either wire C22–C28 to `layer` or remove the backend command. Owner: UI/telemetry.
- **D-3a (orphan):** Performance workspace has no rail button; reachable only via C11
  cards. Header title already handles `'Performance'`. Add rail entry or make cards
  deep-link with per-metric anchors.
- **D-3b (dup workspace):** rail Datasets and Settings(Configuration) render the
  identical `{:else}` config screen; only the `<h1>` differs. Split views or merge nav.
- **D-4 (dup action):** all six Dashboard metric cards navigate to Performance;
  no per-metric drilldown despite distinct labels.
- **D-5a (dup control):** C16 (Dashboard) and C38 (Map) are the same policy command
  in two places — acceptable but they can disagree mid-flight (each binds
  `status.policy`; last event wins — no conflict observed, just note).
- **D-5b (dup/confusing):** C42 vs C44 both open the same report picker; C44
  overwrites `previousReport` instead of `report`. Rename C44 "Load comparison
  baseline" or reuse C42 result.
- **D-6 (fake feedback):** Export (C7), Export JSON (C43), Save preset (C54) discard
  the boolean result — user cannot tell success from cancel. Show a notice.
- **D-7 (fake state):** governor select (C39) is uncontrolled — always displays
  "Automatic" regardless of backend override; bind to `telemetry.governor` or
  `config.map.governor_override`.
- **D-8 (mislabel):** empty-map CTA "Open dataset →" navigates to Configuration,
  not Datasets. Point it at Datasets or relabel.
- **D-9 (heuristic health):** rail LiDAR/Localization/Mapping/Perception dots are
  local heuristics (`!!frame`, `pose_available`, `active_cells!=null`, semantic layer
  present) — not backend health probes. Mapping shows `—` until the first telemetry
  arrives even when configured. Label as signal presence or wire to `status.state`.
- **D-10 (asymmetric n/a):** `layerUnavailable` never flags `semantic`/`elevation`/`lod`
  (only ground/terrain/motion/utility), so a missing semantic layer shows no badge
  on C22 though D-9 checks it. Include `semantic` in the check.
- **D-11 (implicit mode):** Dashboard Raw panel uses `mode='raw'`, which has no branch
  in `colors.ts` (falls through to gray points / elevation cells). Works, but add an
  explicit `raw` branch so future modes fail loudly.

---

## B. Telemetry / displayed-number inventory

Notation: **source** = emitting code; **owner** = subsystem owning the measurement;
**freshness** = update cadence; **unavailable** = what the UI shows when missing.

### B1. Memory — four RAM domains + two map-byte counters (kept separate)

| # | Displayed number | Source | Unit | Freshness | Owner | Unavailable state |
|---|------------------|--------|------|-----------|-------|-------------------|
| M1 | Metric strip MAPPER RSS | `telemetry.processes[name==mapper].rss_bytes` ← `runtime/telemetry.py::rss_bytes(mapper pid)` via `/proc/<pid>/statm` | MB (`/1048576`) | per processed frame | Python reporter; measured C++ mapper proc | `—` (non-Linux → `None`; pid `None`) |
| M2 | Dashboard card RAM Usage | `sum(telemetry.processes[].rss_bytes)` — Python runtime + mapper only | MB | per processed frame | Python | `—`; label says "backend RSS" (excludes Electron — see G-1) |
| M3 | Processes table, Python rows (`runtime`, `mapper`: PID / CPU% / RSS) | same `processes[]`; CPU% = delta of `/proc` cpu ticks (`cpu_seconds`) or `process_time` for self; first sample always `None` | % / MB | per processed frame | Python | PID `—` if none; CPU `—` on first sample / missing `/proc` |
| M4 | Processes table, desktop rows (Browser/GPU/Renderer/…) | Electron `app.getAppMetrics()` → `desktop_telemetry` event, 1 s interval (`apps/desktop/src/main.ts:66`) | % / MB (`workingSetSize*1024`) | 1 Hz | Electron host (= system view of shell) | rows absent in Tauri builds (see G-2); CPU `—` if metric missing |
| M5 | Map allocation: Logical bytes | C++ `snapshot.logical_bytes` → `metrics.logical_map_bytes` → `telemetry.map.logical_bytes` | bytes → MB | per processed frame | Mapper (C++) | `—` |
| M6 | Map allocation: Allocated bytes | C++ `metrics.allocated_map_bytes` → `telemetry.map.allocated_bytes` | bytes → MB | per processed frame | Mapper (C++) | `—` |
| M7 | Benchmark tables: Peak RSS (per policy) | `benchmarks/run_benchmark.py` harness aggregate `peak_rss_bytes` | MB | on demand (benchmark run / opened file) | Benchmark harness | `—`; "No benchmark loaded" blank card |
| M8 | Dashboard card Memory Reduction % | derived `comparisonMetrics(report)`: `(1−adaptive/uniform)*100` from M7 | % | on report load | Renderer (local derivation) | `null` → `—` + "Load a policy benchmark" (never fabricated; `0` uniform guard) |

M5 vs M6 vs M7 are different concepts (live logical footprint vs allocator usage vs
harness peak) shown in different workspaces — do not compare across tables (G-3).

### B2. FPS — render vs processing vs input (kept separate)

| # | Displayed number | Source | Unit | Freshness | Owner | Unavailable state |
|---|------------------|--------|------|-----------|-------|-------------------|
| F1 | RUNTIME FPS (strip, Dashboard card, stat card, chart) | `telemetry.fps` = completed-frame rate over deque window (`runtime/telemetry.py:81`) | fps | per processed frame; rolling 300-sample chart | Python (processing throughput) | `0` before 2 frames; `—` pre-session |
| F2 | RENDER FPS (strip, Frame-stages "Renderer" latency) | `MapCanvas` rAF loop `onStats({fps, latency_ms, entities})` (~1 s window) | fps / ms | ~1 Hz while Map mounted | Renderer (Three.js) | `{}` initial → `—`; stale when Map unmounted (last value persists — G-4) |
| F3 | Input (playback) rate | **not displayed** — target = `config.playback.fps` (default 10) × `status.speed`; schedules `tick()` | — | — | Python (`service.tick`) | gap G-5 |
| F4 | Frame p50/p95/p99 (stat cards, charts) | `latency_ms.end_to_end` = `summary()` over Python `latencies` deque (cap 600) | ms | per processed frame | Python | `None` → `—` when empty |
| F5 | Frame stages: Perception / Bridge-IPC / C++ mapping / Viz-prep | `latency_ms.{perception=Σtimings, ipc=bridge, mapping=p50 ns→ms, visualization=visual_ms or None}` | ms | per frame; `visualization` None on throttled frames | Python + mapper timings | `—` when stage skipped/throttled |
| F6 | Perception stage rows (dynamic, `perception_stages_ms`) | passthrough `frame.perception_timings_ms{semantic,ground,…}` | ms | per frame | Pipeline stages | missing key → row absent; non-number → `—` |
| F7 | Benchmark: FPS p50 / Map p95 per policy | report `aggregate.fps.p50`, `stage_latency_ns.map_update.p95/1e6` | fps / ms | on demand | Benchmark harness | `—` |

### B3. Map / frame counters

| # | Number | Source | Unit | Freshness | Owner | Unavailable |
|---|--------|--------|------|-----------|-------|-------------|
| C-01 | ACTIVE CELLS (strip, Dashboard card, Map allocation) | `telemetry.map.active_cells` ← `snapshot.active_leaf_count` | cells | per frame | Mapper C++ | `—` |
| C-02 | L0–L3 legend counts | `telemetry.map.cells_by_level[i]`, `levels[str(i)]` | cells | per frame | Mapper C++ | `—` (missing level → 0) |
| C-03 | Points / cells displayed (map coordinate + panel captions) | `frame.metadata.points.count` / `.cells.count` (packed viz, bounded by budgets) | counts | per visualization frame (≤ `update_hz`) | Python pack (`pack_visualization`) | `—` when `!frame` |
| C-04 | FRAME index / N frames (playback, status pill) | `status.index` / `status.frames` (Python `_publish_status`; telemetry merges index/frames/state) | frames | per command + per frame | Python session | `0` initial |
| C-05 | Topology changes, Splits/s, Merges/s | `snapshot.topology_change_count`, `topology.per_frame.{splits,merges}.mean × fps` | counts / s | per frame | Mapper + Python derivation | `—` when metrics absent |
| C-06 | Queue depth | `commands.qsize()` (status) | cmds | per status/telemetry | Python | `0` idle |
| C-07 | Dropped frames | engine stream `dropped_frames` (source-frame gaps) via `service.dropped_frames` | frames | per frame | Mapper engine → Python | `0` |
| C-08 | Visualization superseded | `outbox.visualization_dropped` (coalesced Python viz queue) | frames | per status/telemetry | Python protocol | `0` |
| C-09 | Desktop updates superseded | `uiDropped` (Electron coalesced viz while renderer busy) + ack round-trip | frames | 1 Hz (`desktop_telemetry`) | Electron host | `—` in Tauri (G-2) |
| C-10 | Policy comparison: Active leaves, Elevation RMSE | report `final_leaves_per_level` sum; `aggregate.quality[-1].elevation_vs_fine_reference.rmse_m` | leaves / m | on demand | Benchmark harness | `—` |
| C-11 | Semantic mIoU card | `report.perception.semantic.miou` | % | on demand | Benchmark/eval | `—` + "Requires semantic evaluation" |
| C-12 | Object & Terrain summary table | locally counted from packed point buffer (`summarizeVisual`, semantic col) top-6 + % | points / % | per frame | Renderer derivation | placeholder rows + "Semantic observations unavailable." when layer unavailable |
| C-13 | Event log | `recordEvent`: only `status`/`benchmark`/`governor` (+errors); telemetry ignored; cap 200, shows 30 | — | on event | Renderer store | "No runtime events yet." |
| C-14 | Governor state + budget JSON | `frame.map.governor` or `{state:'unavailable',budget:None}` | — | per frame | Mapper governor | `unavailable` + `{budget:'unavailable'}` |
| C-15 | Perception evidence grid (4 stages × status+latency) | `frame.metadata.pipeline_status` + `perception_timings_ms` | status str / ms | per frame | Pipeline | `unavailable` / `—`; never rendered as data when unavailable |
| C-16 | Rail version/platform | `info()` → app version + `navigator.platform` (Tauri) / `process.platform` (Electron) | str | once on mount | Shell | `0.1.0` / `desktop` fallback |
| C-17 | Config digest chip | `config_digest(config)` (Python) via status | 12-char hex | per configure | Python | `NO SESSION` |
| C-18 | Cell inspector fields | viz cell row `r[0..8]` (x,y,elev,res,class,motion,quality,drivable,utility) | mixed | on dbl-click pick | Mapper cell schema | panel hidden until pick |

### Supervisor / event-pipe notes (for slice 2)

- Electron path: `supervisor.ts` (Node) spawns `python -u -m runtime`; `FrameDecoder`
  enforces `VYRA/1`, 1 MiB metadata / 32 MiB payload caps; viz validated by
  `validateVisualization` (68/36 strides, ≤100k rows); viz coalescing (`latestVisual`
  + `uiDropped`) + ack round-trip; auto-recovery via `RestartBudget`; renderer-gone
  does not stop mapping.
- Tauri path: `control_host` (loopback daemon + token) → `control` controller/daemon →
  Python; `supervisor.rs` owns the `VYRA` binary reader (16 B header, `MAX_PENDING=8`,
  `MAX_EVENTS=128`, stderr ring 64 KiB); `telemetry.rs` gates channels
  (`veyra://event` vs `veyra://visualization`), enforces `schema_version==1` for
  telemetry, flags `stale` (>30 s), 1 MiB event cap. Rust `supervisor.rs` unit tests
  hit the real Python `status` path.
- Viz metadata uses `schema_version: 2` (visualization.py) — accepted: the v1 gate
  applies to `type==telemetry` only. Not a bug, but pin the exemption in a comment.

---

## C. Telemetry gaps (must-fix before demo claims)

- **G-1 (RAM label):** Dashboard "RAM Usage — Measured backend RSS" sums only Python
  `runtime+mapper`; Electron shell/GPU/renderer RAM is excluded (but shown separately
  in Performance). Rename to "Python backend RSS" or sum `desktop.processes` too.
- **G-2 (Tauri gap):** no `desktop_telemetry` in the Tauri shell — processes table
  loses shell rows and "Desktop updates superseded" is permanently `—`. Emit an
  equivalent (even if `{}` + documented) or hide the row under Tauri.
- **G-3 ( incomparable memory):** live mapper RSS (M1) vs logical/allocated bytes
  (M5/M6) vs benchmark peak RSS (M7) invite invalid comparison. Add captions stating
  measurement domain per table.
- **G-4 (stale render stats):** `render` persists after leaving Map/Dashboard; strip
  and Frame-stages "Renderer" then show a stale value. Reset `render={}` on workspace
  switch or timestamp it.
- **G-5 (missing input FPS):** target input rate (`playback.fps × speed`) is nowhere
  displayed; RUNTIME FPS alone cannot show backpressure. Add "Input target" next to
  RUNTIME FPS, or show `tick` debt.
- **G-6 (stale flag ignored):** `telemetry.rs` sets `stale:true` for >30 s-old events;
  no Svelte component reads `stale`. Surface a "STALE" badge on the status pill.
- **G-7 (first-sample CPU):** Python CPU% is `None` on the first telemetry after
  (re)start by construction — table shows `—` once; acceptable but document so it is
  not filed as a bug.
- **G-8 (benchmark vs live):** Dashboard footnote already states benchmark ≠ live
  session — keep; extend the same disclaimer to the mIoU and memory-reduction cards.

## D. Tests run

- `npm test` in `apps/desktop` (node `--test tests/*.test.ts`):
  **26/26 pass** (`core`, `dashboard`, `supervisor`, `packaging`, `visual` suites).
- Playwright `desktop.spec.ts` / `visual.test.ts` e2e **not run** (needs Electron +
  backend; out of slice scope).
- Rust `supervisor.rs` / `telemetry.rs` unit tests **not run** (no Rust-toolchain
  change in this slice; slices owning control-api will run them).
- Manual verification: `format`/`f`/`mb`/`memory`/`width` helpers return `—`/0-width
  for `null`/`NaN`/missing — no fabrication path found in renderer derivations;
  `comparisonMetrics` guards divide-by-zero; `recordEvent` drops telemetry spam.

---

## Slice 2 amendments — `closure/opencode-tauri` (2026-09-20, headless)

No control wiring changed (no C-row behavior deltas); amendments only.

- **Tests (§D superseded):** `npm test` now **30/30 pass** (was 26; +clamp test +
  prior-slice additions); Rust `supervisor.rs` unit tests **now run: 11/11 pass**
  (`cargo test -j2 --lib supervisor::`; full lib 59/59, `veyra-cli` bin 9/9).
  `npm run check` 0 errors, `npm run build` green.
- **R2 (new, no C-row):** Tauri CSP tightened to the shipped meta policy
  (`script-src` drops `'unsafe-inline'`; `connect-src` dev entry reconciled;
  `img-src` drops dead `blob:`; adds `object-src`/`base-uri`/`frame-src`).
  No control affected — see `reports/closure/security/R1R2.md` for per-directive
  proof.
- **R1 (new, no C-row):** fs capability grant unchanged by verdict — all three
  fs-plugin call sites (C43/C54 export/save, C31 screenshot, C42/C44/C45 open)
  take paths exclusively from dialog results. See R1R2.md.
- **MapCanvas internals (no C-row change):** packed counts now clamped to the
  100 000 GPU-buffer capacity (`clampRenderCounts`; C-03 caption values
  unchanged in all reachable configs); `webglcontextlost` now surfaces a
  message instead of freezing silently (C18–C21 toggles themselves untouched).
- **Observed already-fixed in code (not by this slice, for the record):**
  D-6 (C7/C43/C54 now `confirmSaved` success/cancel notices), D-7 (C39 bound to
  `governorOverride` with revert-on-failure), G-5 (INPUT TARGET next to RUNTIME
  FPS), G-6 (`STALE` badge on status pill), G-3/G-8 (`MEMORY_DOMAIN_NOTE` +
  benchmark-domain captions), D-8 (empty-map CTA now labeled "Open
  configuration →", matching its destination). D-2 (`layer` command still
  UI-unreachable),
  D-3a/D-3b, D-4, D-5b, D-9, D-10, D-11 remain as inventoried.
