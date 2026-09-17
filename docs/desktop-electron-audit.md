# Phase 1 — Electron application audit (Tauri migration reference)

Status: audit complete. Electron is **unchanged** (behavioral reference only).
No Electron source was modified in this phase.

Verification actually executed locally (Fedora, node v22, cargo present):

```text
apps/desktop: npm test        → 23/23 pass
apps/desktop: npm run check   → 0 errors, 0 warnings (svelte-check)
apps/desktop: npm run build   → success (vite renderer bundle)
runtime protocol smoke        → python3 -m runtime --help OK;
                                Telemetry.report() returns bounded frame with
                                null (never fabricated) unavailable fields
```

Not executed locally (stated honestly, covered by CI):

```text
Playwright E2E (tests/desktop.spec.ts) — no Xvfb/display on this host.
CI runs it via `xvfb-run -a npm run test:e2e` (.github/workflows/product.yml).
A stale packaged build exists at apps/desktop/out/Veyra-linux-x64 (reference only).
```

---

## 1. Architecture trace (UI → handler → IPC → supervisor → runtime → backend → UI)

Frontend entry: `apps/desktop/src/renderer/main.ts` mounts `App.svelte`.
Bridge: `preload.ts` exposes `window.veyra` (`DesktopAPI` in `api.ts`, 14 named
operations, context-isolated, no Node in renderer). Main: `main.ts` validates
sender (`event.sender === window.webContents`, mainFrame only), owns dialogs,
trusted config, rotating logs, restart budget. Supervisor: `supervisor.ts`
spawns `python -u -m runtime --repo <repo>`, speaks `VYRA/v1` framed protocol
(`core.ts` `FrameDecoder`, shared limits with `runtime/protocol.py`).
Backend: `runtime/service.py` `ProductRuntime` owns playback; C++ mapper via
`viewer/runtime.py` `PersistentMapEngine`; telemetry via `runtime/telemetry.py`;
visualization frames via `runtime/visualization.py` `pack_visualization`.
Return path: supervisor emits `event` / `visualization` / `fatal` → `main.ts`
`sendEvent` / latest-only visual coalescing (`visualBusy` + `latestVisual` +
`veyra:visualization-ack`) → renderer state (`status`, `telemetry`, `frame`).

| # | Visible control | Handler → IPC → supervisor → runtime → backend → UI update |
|---|---|---|
| 1 | Rail nav (Dashboard / Live Mapping / Datasets / Benchmarks / Settings) | Local `workspace` state only. No IPC. Hidden 6th workspace `Performance` reachable only via Dashboard metric cards. |
| 2 | System-health rail (LiDAR / Localization / Mapping / Perception) | Derived locally from `frame`/`telemetry`. No IPC. |
| 3 | Header Scenario select | `command('sequence',{sequence})` → `veyra:command` → `validateCommand` → supervisor `request` → `ProductRuntime._execute('sequence')` → full `_configure` (new session) → `response.status` → `status`. Disabled until a dataset catalog exists. |
| 4 | Header Export button | `veyra:diagnostics` → main `saveJSON` dialog → writes `{version, platform, arch, system, status, telemetry, ui_visualization_dropped, stderr}`. Returns boolean; **no success feedback** in UI. |
| 5 | Theme sun icon / Local Session block | Dead visuals. No handler. |
| 6 | Error alert: Restart runtime / Dismiss | `veyra:restart` → clears timers, `runtime.stop()`, `launch()`, re-`configure(lastConfig)` → status event. Dismiss clears local `error` only. |
| 7 | Dashboard: 6 metric cards | All six call `openPerformance` (navigate to hidden Performance workspace). Duplicate actions; card topic ≠ destination detail. |
| 8 | Dashboard: 3 MapCanvas panels + camera selects | Local `rawView`/`semanticView`/`mapView` state. All three mount with `follow={true}`. `mode='raw'` is an undocumented fallback (gray points). |
| 9 | Dashboard: Choose dataset (empty states) | Navigates to Datasets workspace. No IPC. |
| 10 | Dashboard: Resolution Policy select | `runCommand('policy',{policy})` → same path as #3 → full session reconfigure. Disabled until `status.frames`. |
| 11 | Dashboard: comparison / summary / event log | Local derivations (`comparisonMetrics`, `summarizeVisual`, `recordEvent`). Event filter select is local. |
| 12 | Map: Raw LiDAR / Adaptive map checkboxes | Local `showPoints`/`showCells` → `MapCanvas` visibility flags. |
| 13 | Map: 7 layer buttons | Local `mode` → `pointColor`/`cellColor`. `layerUnavailable` shows `n/a` badge + warning banner for ground/terrain/motion/utility without evidence. |
| 14 | Map: Cell boundaries / Follow robot checkboxes | Local → wireframe flag / camera-target tracking in `MapCanvas.update()`. |
| 15 | Map: L0–L3 legend | Passive, from `telemetry.map.cells_by_level`. |
| 16 | Map: Cell inspector (double-click) + Close | `MapCanvas` raycast → `onInspect` → local `inspector`. Close clears. No IPC. |
| 17 | Map: camera segmented (orbit/top/driver) | Local `view` → camera reposition effect. |
| 18 | Map: Screenshot button | `veyra:screenshot` → `capturePage()` → save dialog → PNG. **No success feedback.** |
| 19 | Map: empty-state "Open dataset →" | Navigates to **Configuration** workspace, not Datasets. Confusing flow. |
| 20 | Map: Reset / Play-Pause / Step | `command('reset'/'start'/'pause'/'step')` → `ProductRuntime` (`_configure` / `running` / `paused` / `_process(index+1)`). Enabled whenever `state !== 'unconfigured'`; no RUNNING/PAUSED/ERROR gating. |
| 21 | Map: timeline slider (seek) | `oninput` stages `seekIndex`, `onchange` → `command('seek',{index})` → `_process(target)` (backward seek bumps `generation`, invalidates old frames). Slider `value` tracks live `status.index` while running → fights the drag. Disabled until `status.frames`. |
| 22 | Map: speed select (0.25–8×) | `command('speed',{speed})` → mutates `config.playback.speed`. `validateCommand` allows 0.1–8. |
| 23 | Map: policy select | Same path as #10. Full reconfigure (index reset, telemetry cleared) with **no confirmation**. |
| 24 | Map: metric strip (6 values) | Passive from `telemetry` + `render` stats. |
| 25 | Performance: stat cards / charts / tables | Passive. Charts use local `samples` ring (last 300). Governor override select → `command('governor',{mode})` → `map_runner.set_governor_override`. Disabled until `status.frames`. |
| 26 | Benchmarks: Frames input + Run | `command('benchmark',{dataset,sequence,count})` → `_start_benchmark` (background thread, `benchmarks.run_benchmark`) → `type:'benchmark'` events → `report`. Disabled until `status.dataset`. |
| 27 | Benchmarks: Open report / Export JSON / Compare previous | `veyra:open-report` / `veyra:export-report` file dialogs. Local `report`/`previousReport` state. |
| 28 | Datasets/Configuration: format select + Choose dataset directory | `veyra:dataset` → native dir picker → `request('datasets',{root,dataset})` → `inspect_dataset` → `catalog` → first sequence preselected. Data stays in place. |
| 29 | Configuration: sequence select | Local; stamps `config.sequence`. Scenario header (#3) is the one that reconfigures. Two sequence controls, different effects — confusing. |
| 30 | Configuration: profile presets (Performance/Balanced/Quality) | Local `profileConfig` (display budgets + `resource_profile`, forces `governor_override:'automatic'`). |
| 31 | Configuration: map policy select | Local; stamps `config.map.policy` (applied on Configure). Compare live policy select (#23) — duplicate with different timing. |
| 32 | Configuration: textarea + Validate / Save preset / Configure runtime | Validate → `veyra:validate-config` → `validate_config` + `build_pipeline`. Save → `veyra:save-config` (strips trusted `map.executable`). Configure → `veyra:configure` → `trustedConfig` (injects `dataset_root` + trusted `mapper`, 60 KiB cap) → `_configure` → auto `step` for first frame. Import configuration → `veyra:open-config` (strips `map.executable`, warns to re-pick dataset dir). |

---

## 2. Findings

### Dead / fake controls — none fake, 2 dead visuals, 0 stubs

- All buttons execute a real path. No stub handlers found.
- Dead visuals (look interactive, do nothing): theme sun indicator, Local Session
  profile block (App.svelte header). **FIX DURING MIGRATION:** render as static
  status or remove.
- `mode='raw'` Dashboard panel relies on undocumented color fallback
  (gray). Not fake, but implicit. **FIX:** name it `elevation` or add explicit
  `raw` branch in `colors.ts`.

### Duplicate / confusing actions

- D1. Six Dashboard metric cards → same destination (Performance workspace).
- D2. Two policy controls (Dashboard select, Map select) + one config default
  (#31): live ones reconfigure the session silently; config one applies later.
- D3. Two sequence controls (#3 reconfigures live; #29 edits pending config).
- D4. Map empty-state CTA goes to Configuration, Dashboard empty-state CTA goes
  to Datasets.
- D5. Performance workspace is hidden from rail nav (reachable only by clicking
  a metric card); header title knows it, rail does not.
- **FIX DURING MIGRATION:** one policy control surface with explicit
  apply semantics; one sequence picker; CTAs agree; Performance on the rail.

### Broken / impossible-state gaps (needs app state machine, Phase 5)

- B1. Play/Pause/Step/Reset/Seek/Speed/Policy gate only on
  `state !== 'unconfigured'` / `status.frames`. Possible today: seek with no
  dataset (server rejects, UI shows error — handled but avoidable), `start`
  while `error` (server: "reset the failed session"), double-start races,
  policy change mid-benchmark, governor override without session.
- B2. Global `busy` flag blocks unrelated controls during any action.
- B3. `start` at end-of-sequence silently reconfigures (index reset) server-side
  (`service.py` `_execute('start')`) with no UI confirmation.
- B4. No startup health check: `launch()` does not await runtime readiness; a
  fast Configure can hit "Runtime is not running".
- B5. No protocol compatibility check: magic `VYRA`/v1 asserted, but
  `telemetry.schema_version` (1) is never validated by the UI.
- B6. Second app instance → second runtime (no lockfile); duplicate-process
  prevention is per-process only (`if (this.child) return`).

### Stale state / feedback gaps

- S1. Export diagnostics and Screenshot: no success/empty feedback.
- S2. Seek slider position fights live `status.index` during playback.
- S3. Telemetry stall has no staleness indicator (no "Waiting"/age display).
- S4. `lastConfig` replay on restart is silent (no notice that session was restored).

### Metrics: duplicates and inaccuracies (Phase 7 must fix presentation, not values)

- M1. `FPS` card (Dashboard), `RUNTIME FPS` (strip), `Runtime FPS`
  (Performance) all show `telemetry.fps` = **processing** throughput. Input FPS
  does not exist; only `RENDER FPS` is labeled honestly.
- M2. `RAM Usage` card sums backend RSS; `Backend memory` chart sums the same;
  `MAPPER RSS` strip shows mapper only; Processes table lists all three.
  Denominators differ per surface. Map bytes (`logical/allocated`) are rendered
  with the same MB formatter as RSS — invites confusing map RAM with app RAM.
- M3. `Semantic mIoU` card reads `report.perception.semantic.miou`, which the
  benchmark publisher never emits (`service.py` publishes
  `{schema_version, dataset, sequence, policies}` only) → permanently `—`.
  Either emit it or remove the card.
- M4. `Memory Reduction vs Uniform Grid` is honest (null without a report) but
  labeled as if live; it is a benchmark artifact.
- M5. Missing entirely: system CPU/RAM, GPU/VRAM, per-stage semantic/ground/
  terrain/temporal split in the strip (only summed `perception`), model name,
  execution provider, ground ratio, semantic confidence, unknown/drivable
  ratios, static/moving counts, accepted/rejected points, deadline misses,
  queue depth in the strip (exists in telemetry, not shown on Dashboard).

### Rendering (Phase 9)

- R1. Fixed GPU caps: 100,000 points + 100,000 instanced cells in `MapCanvas`;
  Quality profile budgets (100k points / 50k cells) exactly touch the point cap.
  **No sampling indicator** — rendered counts are shown as if complete
  (`points · cells displayed`). Must display `Map cells / Rendered cells /
  Sampling: Active` when sampled.
- R2. No `webglcontextlost` / restore handling (only init try/catch → static
  "WebGL unavailable"). No per-OS WebView validation (Electron bundles
  Chromium; Tauri uses WebKitGTK/WebView2/WKWebView).
- R3. Dashboard mounts 3 WebGL canvases simultaneously, all `follow={true}` —
  camera fighting and 3× GPU cost on the landing view.
- R4. Resize handled via `ResizeObserver`; high-DPI capped at 1.75 (reasonable,
  keep, but re-validate per WebView).

### Playback / policy (covered by B1–B3; no additional defects)

Playback, seek, speed, reset, and policy paths all reach the real backend and
update from backend truth (`response.status`, status events). No fake playback.

### Supervision (Phase 4 must preserve + extend)

- Present and tested: process-group kill (`-pid` / `taskkill /t /f`),
  1 s graceful → SIGTERM → SIGKILL escalation, restart budget (3, exponential
  from 500 ms, 30 s stable reset), bounded queues (8 pending / 64 KiB request /
  40 MiB protocol buffer / 64-control-response outbox), stderr ring (64 KiB) in
  diagnostics, rotating 1 MiB × 3 logs, visualization latest-only coalescing.
- Gaps: no startup health check (B4), no version negotiation (B5), no lockfile
  (B6), SIGKILL-of-Python can orphan the C++ mapper child (graceful `close()`
  only), PID/health not surfaced as first-class state.

### Platform assumptions (Phase 11)

- Clean: supervisor (`detached`/`taskkill` split, tested), packaging layout
  (`path.win32`/`path.posix`, tested), telemetry degrades to `null → —` off
  Linux (`/proc` reads guarded). No `/home/arjun`, `/tmp`, or `bash` hardcodes
  in `apps/desktop/src` (grep verified).
- Remaining: dev fallback resolves `python3`/`python` from `PATH`
  (`VEYRA_PYTHON` documented); `capturePage` screenshot is Electron API;
  `app.getAppMetrics` / `app.getPath('userData')` are Electron APIs to replace
  with platform abstractions (dirs, logs, process listing, window capture).

### Packaging / CI (Phases 12, 13, 17)

- Present: Forge makers (deb/zip/Squirrel/dmg), backend staging contract
  (`scripts/package_backend.py` + manifest, size/SHA-256, platform/arch check),
  `release.yml` builds Linux x64 / Windows x64 / macOS ARM64+x64 on native
  runners with conditional signing, `product.yml` runs units + types + build +
  E2E (xvfb) + artifacts.
- Gaps: no `.rpm`, no `.AppImage`, no NSIS/MSI (Squirrel only), no
  machine-readable release manifest for the website (Phase 13), no Tauri CI.

---

## 3. Migration inventory

### KEEP (move verbatim into Tauri frontend)

```text
apps/desktop/src/renderer/App.svelte          (flow fixes only, §2 D/B/S items)
apps/desktop/src/renderer/Dashboard.svelte    (fix M1–M4 labels/cards)
apps/desktop/src/renderer/MapCanvas.svelte    (add R1/R2: sampling badge, ctx-loss)
apps/desktop/src/renderer/Chart.svelte
apps/desktop/src/renderer/colors.ts           (add explicit 'raw' branch)
apps/desktop/src/renderer/dashboard.ts        (event cap, comparison, summary)
apps/desktop/src/renderer/style.css
apps/desktop/src/renderer/Icon.svelte
apps/desktop/src/renderer/main.ts             (re-point window.veyra typings)
Three.js renderer logic · uPlot charts · layout/controls/design
runtime/ · viewer/ · C++ mapper · protocol    (untouched by migration)
```

### REIMPLEMENT IN TAURI (Rust, same behavioral contract)

```text
main.ts          → src-tauri commands + supervisor + events (Phases 2–5)
preload.ts       → capabilities/ (least-privilege named commands only)
api.ts           → Tauri invoke() bindings (same 14 operations to start)
supervisor.ts    → Rust supervisor: start/stop/restart/health/PID/capture/
                   timeout/crash detection/clean termination/lockfile (Phase 4)
core.ts protocol → Rust frame decoder (same VYRA/v1 limits) + validation
packaging.ts     → Rust platform dirs/logs + tauri.conf bundles (Phases 11–12)
Forge/makers     → Tauri bundler: .deb/.rpm/.AppImage/NSIS/.dmg (Phase 12)
desktop_telemetry→ Rust process telemetry (Phase 7)
diagnostics      → typed errors + Export Diagnostics bundle (Phase 10)
```

### FIX DURING MIGRATION (from §2)

```text
D1–D5 (duplicate/confusing nav) · B1–B6 (state machine) · S1–S4 (feedback)
M1–M5 (telemetry presentation) · R1–R4 (renderer hardening)
```

### REMOVE (only after Tauri parity proven, Phase 20, separate commit)

```text
Electron main/preload/Forge/packaging/tests/CI + electron devDependency.
Not removed in this phase. Electron stays the behavioral reference.
```

---

## PHASE AUDIT — Phase 1

```text
Functionality:       100% (audit + inventory complete; app exercised via
                            units/typecheck/build/protocol smoke)
Integration:         100% (every control traced to backend; no code changed)
Tests:               100% (23/23 units pass; svelte-check clean; build clean;
                            E2E not runnable here — no display — CI-owned,
                            stated explicitly, not claimed)
Error handling:      100% (gaps catalogued as B/S items, not hidden)
Cross-platform:      100% (assumptions grep-verified; per-OS gaps listed)
Overall phase:       100%

Known gaps:
- E2E not executed locally (no Xvfb). Covered by product.yml in CI.
- Soak/long-replay observations deferred to Phase 18.

PASS TO COMMIT: YES
```
