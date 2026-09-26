# Desktop refinement: native verification and screenshots

This is a local review of `revamp-app-ui`, based on production-ready benchmark
work from `fixed-benchmarks-pr`. It is not a cross-platform certification.
The precise checkout, dirty state, timestamp and runtime samples are recorded in
[flow.json](flow.json); capture methods and visible states are in
[screenshots.json](screenshots.json).

## Verified locally

- Fedora 44 / WebKitGTK: release Tauri application with its bundled backend,
  served from `tauri://localhost`, with the frontend development server stopped.
- Real SemanticPOSS sequence 00, a bounded 30-frame session, eight received
  processing results in the control smoke. Dataset labels provide ground-truth
  semantics: this does **not** demonstrate neural inference quality.
- Real Python runtime, Patchwork++ ground/terrain, C++ mapper, visual frames and
  telemetry. Dataset discovery reports all six sequences / 2,988 source frames.
- Invalid configuration and missing dataset rejection; preview, play, pause,
  speed, seek, cameras, raw/map visibility, actual cell inspection, all seven
  map layers, Uniform40/DistanceLOD switching, governor selection, validation,
  benchmark invocation, restart, stop and stopped empty state.
- Actual WebGL context loss/restoration and subsequent rendering.
- The benchmark button exercises a one-frame/four-policy operation smoke, not
  a statistically meaningful benchmark. Quality plots load the existing measured
  `reports/external-review/benchmark_run.json`; these are not newly measured
  quality results. Surface and reconstruction metrics remain separately labeled.

The existing staged backend manifest (version 0.1.0, 5,640 files) was checked
against sizes and SHA-256 hashes. This review used a release executable with
Tauri resources, **not** a newly installed .deb/.rpm/NSIS/.dmg package.
Do not restage resources or rebuild while a bundled runtime is using them:
an exploratory overlapping build failed with `Text file busy` and a runtime
SIGSEGV. Subsequent isolated builds and native sessions passed; this does not
prove every possible crash cause is resolved.

## Gates

Fresh local gates passed: 86 frontend tests; 76 Rust library/CLI/control tests;
37 focused Python capture, backend-package and runtime tests; Svelte check;
Vite build; Rust fmt and Clippy with warnings denied; changed-file Ruff/format/
compilation; and `git diff --check`. These are scoped checks, not a claim that
whole-repository Ruff or every unrelated suite passed.

The desktop retains its light shell/dark viewports. Its scoped visual contract
is in [DESIGN.md](../../apps/desktop/DESIGN.md). Three local design-hook exceptions
apply only to the desktop stylesheet's intentional type, color and radius
tokens; other design checks remain enabled.

## Cross-platform limits

| Platform | Current evidence |
| --- | --- |
| Fedora 44 | Native bundled release session verified locally |
| Ubuntu/latest | Not executed locally; native installer/runtime verification pending |
| Windows 11 | Not executed; Windows CI runner is not installed Windows 11 proof |
| Latest macOS | Not executed; macOS 15 CI configuration is not latest-macOS runtime proof |

Read-only Actions inspection found desktop run `35590162103` had no executed
job steps: GitHub reported failed payments/spending-limit restrictions.
No release workflow runs were available. No jobs were dispatched or rerun.
Billing must be restored and native build/install/dataset/render/shutdown flows
run on target systems before claiming those platforms verified.

## Capture method and remaining Wayland requirement

These 54 checkpoint screenshots are **native WebKitWebDriver captures**.
They are not `wayland-screenshot` captures. No fake screenshots or rendered mock
states were substituted. The raw-canvas export is separate from screenshots.
The checkpoints cover all five pages and major states, not every possible
OS dialog or state combination.

The requested command was attempted:
`wayland-screenshot snap -o .../wayland-overview.png`.
It failed because no capture daemon was running. Starting window capture requires
a stored consent token; operator enrollment is pending. The user must run:

```bash
wayland-screenshot cast enroll --window
# Choose the Veyra window in the portal's consent dialog.
wayland-screenshot cast start -w --no-persist
wayland-screenshot snap -o reports/desktop-ui-review/wayland-overview.png
```

After consent, the smoke can capture every checkpoint with
`--wayland-screenshots` (prefer a separate output subdirectory to preserve these
review captures). The helper fails explicitly on capture errors; it never
silently relabels WebDriver images as Wayland images.

## Reproduce the native review

Build first, before starting any test application:

```bash
cd apps/desktop
npm test
npm run check
npm run build
npm run tauri:build -- --no-bundle
cd ../..
env -u VEYRA_PYTHON XDG_CONFIG_HOME=/tmp/veyra-ui-bundled-config \
  TAURI_WEBVIEW_AUTOMATION=true WEBKIT_DISABLE_COMPOSITING_MODE=1 \
  WebKitWebDriver --port=4446
```

In another terminal, create a session (substitute your checkout's absolute path):

```bash
curl -sS -X POST http://127.0.0.1:4446/session \
  -H 'Content-Type: application/json' \
  -d '{"capabilities":{"alwaysMatch":{"webkitgtk:browserOptions":{"binary":"/home/arjun/Captain/SIH/Lidar/src-tauri/target/release/veyra"}}}}'
python3 scripts/desktop_flow_smoke.py \
  --driver http://127.0.0.1:4446 --session SESSION_ID \
  --dataset-root /path/to/semanticposs/dataset \
  --output reports/desktop-ui-review \
  --quality-report reports/external-review/benchmark_run.json --extended
curl -sS -X DELETE http://127.0.0.1:4446/session/SESSION_ID
```

Only native folder/report pickers are bypassed by automation. The runtime,
discovery, validation, commands, events, rendering and inspection are real.
Ground-truth mode and missing timestamps must not be mistaken for neural or
real temporal-motion validation.

## Screenshot index

| Capture | Page | Visible state |
| --- | --- | --- |
| [overview-empty.png](overview-empty.png) | Overview | No session |
| [evaluation-unavailable.png](evaluation-unavailable.png) | Evaluation | No session |
| [performance-waiting.png](performance-waiting.png) | Performance | No session |
| [viewer-empty.png](viewer-empty.png) | Viewer | No session |
| [setup-empty.png](setup-empty.png) | Session setup | No session |
| [setup-selected.png](setup-selected.png) | Session setup | No session |
| [setup-advanced.png](setup-advanced.png) | Session setup | No session |
| [configuration-error.png](configuration-error.png) | Session setup | No session |
| [dataset-error.png](dataset-error.png) | Session setup | No session |
| [preview-requested.png](preview-requested.png) | Session setup | No session |
| [viewer-preview.png](viewer-preview.png) | Viewer | Paused |
| [viewer-playing.png](viewer-playing.png) | Viewer | Playing |
| [viewer-paused.png](viewer-paused.png) | Viewer | Paused |
| [viewer-speed.png](viewer-speed.png) | Viewer | Paused |
| [viewer-elevation.png](viewer-elevation.png) | Viewer | Paused |
| [viewer-camera-top.png](viewer-camera-top.png) | Viewer | Paused |
| [viewer-camera-driver.png](viewer-camera-driver.png) | Viewer | Paused |
| [viewer-camera-orbit.png](viewer-camera-orbit.png) | Viewer | Paused |
| [viewer-inspection-map.png](viewer-inspection-map.png) | Viewer | Paused |
| [viewer-cell-inspector.png](viewer-cell-inspector.png) | Viewer | Paused |
| [viewer-visibility-raw.png](viewer-visibility-raw.png) | Viewer | Paused |
| [viewer-visibility-map.png](viewer-visibility-map.png) | Viewer | Paused |
| [viewer-visibility-both.png](viewer-visibility-both.png) | Viewer | Paused |
| [viewer-seek.png](viewer-seek.png) | Viewer | Paused |
| [viewer-ground.png](viewer-ground.png) | Viewer | Paused |
| [viewer-traversability.png](viewer-traversability.png) | Viewer | Paused |
| [viewer-motion.png](viewer-motion.png) | Viewer | Paused |
| [viewer-lod-resolution.png](viewer-lod-resolution.png) | Viewer | Paused |
| [viewer-utility.png](viewer-utility.png) | Viewer | Paused |
| [viewer-semantic.png](viewer-semantic.png) | Viewer | Paused |
| [viewer-uniform40.png](viewer-uniform40.png) | Viewer | Paused |
| [viewer-distance_lod.png](viewer-distance_lod.png) | Viewer | Paused |
| [viewer-webgl-context-lost.png](viewer-webgl-context-lost.png) | Viewer | Paused |
| [viewer-webgl-context-restored.png](viewer-webgl-context-restored.png) | Viewer | Paused |
| [performance-measured.png](performance-measured.png) | Performance | Paused |
| [performance-memory-detail.png](performance-memory-detail.png) | Performance | Paused |
| [performance-health-detail.png](performance-health-detail.png) | Performance | Paused |
| [performance-governor-detail.png](performance-governor-detail.png) | Performance | Paused |
| [performance-governor-conserve.png](performance-governor-conserve.png) | Performance | Paused |
| [performance-governor-automatic.png](performance-governor-automatic.png) | Performance | Paused |
| [validation-requested.png](validation-requested.png) | Evaluation | Paused |
| [validation-result.png](validation-result.png) | Evaluation | Paused |
| [benchmark-requested.png](benchmark-requested.png) | Evaluation | Paused |
| [benchmark-result.png](benchmark-result.png) | Evaluation | Paused |
| [evaluation-policy-comparison.png](evaluation-policy-comparison.png) | Evaluation | Paused |
| [evaluation-reconstruction-details.png](evaluation-reconstruction-details.png) | Evaluation | Paused |
| [evaluation-accuracy-tradeoff.png](evaluation-accuracy-tradeoff.png) | Evaluation | Paused |
| [evaluation-completion.png](evaluation-completion.png) | Evaluation | Paused |
| [evaluation-surfaceChamfer.png](evaluation-surfaceChamfer.png) | Evaluation | Paused |
| [dashboard.png](dashboard.png) | Overview | Paused |
| [setup-session-active.png](setup-session-active.png) | Session setup | Paused |
| [runtime-restarted.png](runtime-restarted.png) | Session setup | Paused |
| [runtime-stopped.png](runtime-stopped.png) | Session setup | Ready |
| [overview-stopped.png](overview-stopped.png) | Overview | Ready |
