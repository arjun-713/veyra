# Desktop flow and control ownership

This audit describes the production Svelte → Tauri command → Rust controller →
Python runtime → C++ mapper path. A source trace is not a claim that every OS
or installer was exercised. Native smoke evidence is generated separately by
`scripts/desktop_flow_smoke.py`.

## User flow

1. Open **Datasets**, select the adapter, and choose its existing directory.
   Files remain on disk; this operation does not upload or copy the dataset.
2. Inspect discovered sequences, frame/label counts, poses and timestamps.
3. Select a sequence and **Open dataset & preview**. This applies the visible
   settings, starts the backend, processes frame zero, and opens Live Mapping.
4. Wait for the preview. Configuration success alone does not mean render data
   arrived. Processing, waiting for visualization, and errors are distinct.
5. Play, pause, step or seek in **Live Mapping**; select layers and map policy
   there. Policy changes reset the map and generate a fresh preview.
6. Use **Dashboard** for an overview, **Performance** for measured stage/process
   data, and **Validation & benchmarks** for explicit validation and reports.
7. **Stop session** releases the runtime. **Restart** reapplies its configuration
   and requests a fresh preview. Advanced JSON settings are under a disclosure
   in Datasets rather than a duplicate Settings screen.

### Laptop defaults

New sessions use **Low resource**: first 30 frames, DistanceLOD, 15,000 displayed
points, 10,000 displayed cells, and 2 Hz automatic visualization. Opening a
preview stays paused. The backend enforces the frame window and allows only
one processing operation at a time. Explicit step/seek previews are delivered
even when the automatic visualization interval has not elapsed.

Use **Full sequence** only when needed. Save/import a configuration preset to
retain custom overrides; the default remains bounded on every fresh launch.
These display budgets never reduce the observations ingested by the mapper.

## Control map

| Surface / control | Handler → action | Result / restriction |
| --- | --- | --- |
| Navigation | `workspace` | View-only; does not start/stop processing |
| Dataset format | update draft config; clear old catalog | Prevents reusing another adapter's path |
| Choose directory | `chooseDataset` → `choose_dataset` → `datasets` | Real directory inspection; cancel is neutral |
| Sequence selection (Datasets) | update draft configuration | Applied by Open preview |
| Display profile / draft policy | `profileConfig` / config update | Explicitly applied when opening; not a live policy control |
| Open dataset & preview | `configure` → `runtime_configure` → `step` | Opens Map; waits for actual visualization event |
| Import / save configuration | native dialog + scoped filesystem | Cancel is not success; backend validates on apply |
| Validate configuration | `runtime_validate_config` | Configuration validation only, distinct from session validation |
| Apply advanced configuration | `configure` | Same setup path as Open preview; advanced alternative |
| Header session | read-only backend dataset/sequence/frame count | Dataset selection belongs to Datasets; no duplicate selector |
| Play / pause | `runtime_command(start/pause)` | Backend acknowledgement drives state |
| Step / seek | `runtime_command(step/seek)` | Real processing; bounded, disabled without a healthy session |
| Reset | `runtime_command(reset)` then `step` | Clears old view and map before preview |
| Speed | `runtime_command(speed)` | Changes backend playback scheduler |
| Live policy | `runtime_command(policy)` then `step` | Selects C++ policy via a new runtime session |
| Dashboard policy link | opens Live Mapping | Removes a duplicate live policy selector |
| Layer | `runtime_command(layer)` | Shared controller selection, then renderer coloring |
| Points / cells / boundaries | Three.js visibility/material | Intentionally display-only; does not alter fusion |
| Camera / follow | OrbitControls/camera | Intentionally display-only |
| Double-click cell | Three.js raycast | Inspects received cell buffer, not a synthetic record |
| Screenshot | native save + renderer canvas | Captures current rendered view |
| Governor override | `runtime_command(governor)` | Mapper control, restored selection on failure |
| Stop / restart | `runtime_stop` / `runtime_command(restart)` | Clears stale view, restart requests new preview |
| Session validation | `runtime_command(validation)` | Live dataset/perception/map smoke; not a full deployment certification |
| Benchmark frames / run | `runtime_command(benchmark)` | Async four-policy job; failure cannot remain a fake success |
| Open report / previous report | native JSON dialog | Explicit offline artifacts, independent of live metrics |
| Export report | scoped native save | Saves loaded/generated report only |
| Export diagnostics | `export_diagnostics` + native save | Bounded runtime diagnostic data |
| Error dismissal | clears UI alert | Does not claim runtime recovery |
| Event filter | filters bounded event history | Display-only |

## Verified bugs addressed in this working tree

- Python emits visualization schema 2; Rust incorrectly required telemetry
  schema 1 for these frames. Telemetry passed while visualization was rejected.
- Desktop accepted CLI endpoint environment overrides with no event relay,
  including stale endpoints. Desktop now owns an event-capable host; CLI/MCP
  may attach using its generated discovery record.
- Blocking native commands ran on the UI thread. They now run on the blocking
  worker pool and return errors through the command response.
- Controller-only layer acknowledgements replaced complete session status,
  discarding frame/dataset metadata. Partial updates now merge.
- Missing/old telemetry and missing renderer health could look healthy.
- Sampled ground/unknown ratios used the full scan denominator. Ratios now
  use the matching evidence array; unavailable ground has no measured ratio.
- Partial RSS sums and Python-plus-mapper totals were labelled misleadingly.
- Session reset/restart could retain prior renderer ordering and stale data.
- Native directory cancellation appeared as a runtime error. Async event
  listener disposal could leak a subscription.

## Metric sources

| Value | Source / domain | Missing or stale behavior |
| --- | --- | --- |
| Processing FPS | Python completion timestamps, bounded history | — until at least two completions; includes replay pacing |
| Input target | configured playback FPS × speed | Target, never measured throughput |
| Render FPS | Three.js draw loop | Renderer-only; age shown off Map |
| Frame latency | Python processing timer | Does not include asynchronous desktop rendering |
| Mapping latency | C++ latency histogram | Explicit map stage, not whole application |
| Perception stages | pipeline timers | — for absent stages |
| Runtime / mapper RSS | OS process counters | Linux `/proc`; unavailable on unsupported hosts, never zero |
| Backend RSS | complete runtime + mapper RSS sum | — if any process reading is missing; excludes desktop |
| Map bytes / cells / levels | C++ metrics and snapshot | Separate from RSS |
| Perception ratios / counts | sampled per-point evidence | Sample size and full point count are distinct |
| Comparison | loaded benchmark artifact | Separate from live session; no invented baseline |
| Freshness | received timestamp compared to current clock | Waiting without timestamp; stale after 30 s |
| Renderer health | actual WebGL creation/context events | Unavailable before evidence; context loss is visible |

## Verification and platform boundaries

- `npm test`, `npm run check`, `npm run build` in `apps/desktop`.
- `cargo test --manifest-path src-tauri/Cargo.toml --lib` and strict Clippy.
- `.venv/bin/python -m unittest tests.test_product_runtime tests.test_runtime_player`.
- Native smoke: run `WebKitWebDriver --port=4445` with
  `TAURI_WEBVIEW_AUTOMATION=true`, create a WebDriver session whose
  `webkitgtk:browserOptions.binary` is the built Veyra executable, then run
  `scripts/desktop_flow_smoke.py --session ID --dataset-root PATH --output PATH`.
  The script bypasses only the OS directory chooser; discovery and all runtime
  work are real. It writes a dashboard screenshot and frame/telemetry evidence.
- Linux WebKit testing cannot certify Windows WebView2 or macOS WKWebView.
  Native dialogs, resource paths and process APIs remain platform-neutral.
  Windows/macOS installer, process cleanup and graphics acceptance still require
  their native runners. Unsupported process counters are explicitly unavailable.
- No new dependency or automatic expensive CI run is introduced by this work.

## Local regression evidence

The native WebKit smoke exercised real SemanticPOSS discovery, first-frame
processing, play/pause, speed, layer selection, three dashboard renderers and
stop. Capture: `/tmp/veyra-desktop-buffered-final/dashboard.png`; machine-readable
events: `/tmp/veyra-desktop-buffered-final/flow.json` (local, not committed).
These are ground-truth semantics, not a neural-inference quality evaluation.

An unbuffered mapper stdout `readline()` issued one read per byte. A deterministic
200 KB regression test demonstrated 200,051 reads before buffering; the fixed
reader requires fewer than 20 while preserving successive JSON records and the
32 MiB response bound. Local snapshot preparation fell from roughly 17–20 s to
0.36–0.51 s on the sampled frames; this is a diagnostic comparison, not a full
sequence performance benchmark. Command stdin remains unbuffered.

Late visualization events are ignored after stop so they cannot repopulate an
empty session. No claim is made that all native controls, packaged installers,
or all supported operating systems were exercised by this bounded smoke.

Bridge rejections (`diagnostics` events such as RUNTIME_EVENT_REJECTED) were
silently dropped by the event log. `recordEvent` now surfaces them as visible
error entries (tested).

A plain `cargo build` embeds no frontend: Tauri v2 only embeds `frontendDist`
when compiled through the Tauri CLI build. Packaging must go through
`npm run tauri:build` (or `tauri.mjs bundle` after such a build); a
`cargo build` + `bundle` shortcut ships a UI-less binary. Verified: release
binary embeds current `App-OyokbQQs.js`; RPM backend manifest and service
match staged source by hash.

## Measured visualization transport (2026-09-21, SemanticPOSS 00/000000)

Real v2 event: 33,329 points (stride 68), 18,625 cells (stride 36),
2,936,872-byte payload with exact section-length match,
`pose_available: true`, `layers.semantic: "ground_truth"`.

The same 2.9 MB payload serialized as a Tauri JSON number array measures
~11.7 MB and ~1.1 s (serde, release-mode equivalent path). This is recorded
as a limitation, not a redesign trigger: current frame rates do not saturate
on it, and the semantics must not change for transport reasons.

## Extended native acceptance (2026-09-21, release binary + WebKit WebDriver)

Expanded `scripts/desktop_flow_smoke.py --extended --soak-frames 10` passed
against the release build on SemanticPOSS 00 (30-frame LowResource session):
16 controls exercised (discovery, configure, preview, play, pause, speed,
layer, dashboard render, stop, seek, policy, governor, validation,
benchmark, bounded replay, restart), 15 telemetry samples, queue depth 0–1,
zero dropped frames. Evidence: `/tmp/veyra-desktop-acceptance3/`
(`dashboard.png`, `raw-canvas.png`, `flow.json`) — local, not committed.
Screenshots visually inspected: raw cloud, semantic coloring (road, vehicle,
person, terrain), adaptive map with L0–L3 legend, 153,257 active cells,
semantic class table, live event log.

Bounded 10-frame replay RSS (not a soak claim): runtime 138 → 157 → 155 MB,
mapper 24 → 140 → 78 MB (start → peak → end). No growth trend asserted.

Packaged benchmarks require the benchmark executable in the staged backend:
`runtime/service.py` previously hardcoded the dev-tree
`build/apps/benchmark` path, which does not exist inside a package, so every
packaged benchmark failed with `Errno 2`. Fixed by staging
`bin/veyra_benchmark` via `package_backend.py` (`--benchmark` plumbed through
`stage_tauri_backend.py`) and resolving staged-first with an explicit error
when absent. Follow-up: any restage without the flag silently dropped the
binary again, and CI never passed the flag, so intermittent `Errno 2`
persisted. Closed by auto-discovering the repo dev build when the flag is
absent plus passing `--benchmark` explicitly in `release-tauri.yml`.
The release RPM was rebuilt after restaging and verified:
current frontend embedded (`App-OyokbQQs.js`), backend manifest and service
hashes match staged source, packaged binary reaches window creation
headless with no orphans.
