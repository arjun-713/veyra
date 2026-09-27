# Veyra desktop

Tauri 2 + Svelte 5 + TypeScript + Vite, with Three.js and uPlot. Mapping and
perception run in separate backend processes. The desktop consumes the product
runtime protocol in `../../runtime/` through Tauri commands and events
(`src-tauri/`).

## Run from source

Build `veyra_runtime` with the root CMake project and install the root Python
requirements into a virtual environment. Then:

```sh
cd apps/desktop
npm ci
VEYRA_PYTHON=/absolute/path/to/venv/bin/python npm run tauri:dev
```

On Windows, set `VEYRA_PYTHON` to the environment's `python.exe` (PowerShell:
`$env:VEYRA_PYTHON = 'C:\path\to\venv\Scripts\python.exe'`). Without an override,
the supervisor prefers bundled Python, then the repository virtual environment,
then the platform's Python executable on PATH.
The dataset root is chosen through the native directory picker. Imported
configuration cannot replace the trusted C++ executable. Generic datasets use
the existing manifest adapter; real external poses remain required by mapping.

## Session flow

1. Open **Session setup**, choose the dataset format, and select its directory.
   Files are read in place; selecting a folder does not yet process the map.
2. Review the discovered sequence, frames, labels, poses and timestamps.
   Missing timestamps mean temporal motion evidence is unavailable, not measured.
3. Keep **Low resource** for laptop replay (first 30 frames by default). Choose
   a resolution policy. **Replay the full sequence** is an explicit override.
4. Select **Open dataset & preview**. The backend validates configuration,
   starts the session and processes the first frame; Viewer opens automatically.
5. Play, pause, seek, change speed/layers/policy in **Viewer**. **Overview**
   shows the same real raw, semantic and adaptive-map frame.
6. Inspect measured stages/process memory in **Performance**. **Evaluation**
   runs session validation and four-policy benchmarks or opens saved reports.
7. Stop or restart the active session in **Session setup**. Advanced JSON,
   preset import/check/save stay collapsed until needed.

Viewer provides point/cell layers, camera presets, follow mode, cell inspection,
playback, seek and policy switching. Performance reports backend
measurements; desktop-shell process rows are unavailable in Tauri builds,
which emit no `desktop_telemetry`. Missing measurements remain unavailable.
Evaluation consumes existing schema-2 reports. Session setup imports, validates
and saves session JSON; all display budgets are bounded independently from map
input. The Utility heatmap displays the normalized score exported by the engine.

## Checks

```sh
npm test
npm run check
npm run build
```

`npm run build` compiles the renderer frontend consumed by the Tauri shell
(`npm run tauri:build:frontend` is the same build under its Tauri alias).
End-to-end desktop coverage is the Rust packaged suite in `src-tauri/`
(real-data flow on the staged bundle; see `reports/closure/tauri/RESULT.md`).
Data/engine acceptance remains in the root runtime test suite.

## Packaging

Tauri builds the Linux deb/rpm/AppImage, Windows NSIS, and macOS DMG bundles
(see `src-tauri/tauri.conf.json` and `.github/workflows/release-tauri.yml`).
Run `npm run tauri:build` on the target OS. A release package must stage a
backend directory with `scripts/stage_tauri_backend.py` (built on
`scripts/package_backend.py`).
The staging command copies only the allowlisted application packages, configs,
native mapper and supplied Python runtime. It rejects mapper paths outside the
checkout and writes a size/SHA-256 manifest. `verify_backend` validates that
manifest; the desktop's runtime discovery checks for its presence and runtime
entrypoint, not every file hash on each launch.

```text
backend/
  runtime/ viewer/ datasets/ perception/ benchmarks/ configs/
  bin/veyra_runtime[.exe]
  python/bin/python3          # Linux/macOS; relocatable distribution
  python/python.exe          # Windows
  manifest.json
```

The Python distribution must include its required dependencies, the native
backend must have its shared libraries, and paths must remain valid after
installation. Models/datasets remain explicit external assets. A missing staged
bundle cannot count as runnable. Process errors preserve bounded stderr context;
restart is explicit rather than an automatic three-attempt retry policy.
Normal shutdown asks the runtime to close its mapper and then closes stdin.
The supervisor escalates to killing/reaping the Python child after a bounded
wait. Forced whole-process-tree cleanup on every OS is not claimed verified.

`.github/workflows/release-tauri.yml` builds the Tauri bundles on their native
runners, stages the backend, runs product checks, emits `SHA256SUMS`, and
uploads the bundles as CI artifacts. GitHub Release publishing and bundle
signing remain future work there. Tags with a suffix and manual prerelease
runs require separate channel/publishing verification. Signing/notarization is
not proven by these build commands; Tauri bundles remain unsigned until the
release workflow implements and validates signing with real credentials.

### macOS specifics

- **Framework Python is made self-contained.** Python.org and Homebrew
  interpreters are framework builds. Staging finds their real prefix through
  the `executable` key in `pyvenv.cfg` and skips the base interpreter's
  site-packages. `relocate_darwin_python` then points the interpreter at the
  bundled `Python` dylib through `@loader_path`, copies every non-system dylib
  into `python/lib/vendored` (OpenSSL, xz, sqlite and mpdecimal from
  Homebrew), and ad-hoc re-signs each rewritten binary. Staging fails if any
  absolute non-system link remains. Without this step, a staged Homebrew
  interpreter still ran with `sys.prefix` pointing into `/opt/homebrew`.
- **The app bundle is ad-hoc signed and sealed**
  (`bundle.macOS.signingIdentity: "-"`), so `codesign --verify --deep --strict`
  passes. It is not notarized. A downloaded copy triggers Gatekeeper's
  unidentified-developer prompt: open it with Control-click → Open, or
  `xattr -dr com.apple.quarantine Veyra.app`. Set `APPLE_SIGNING_IDENTITY`
  and notarization credentials for real distribution.
- **The frontend build step has a pinned directory.** `beforeBuildCommand` and
  `beforeDevCommand` run in `apps/desktop` explicitly. Otherwise the Tauri CLI
  picks `landing-page/` as the frontend and the build fails.
- **DMG window styling needs Finder automation.** Tauri's DMG script styles the
  window through Finder AppleScript. In a session without that permission it
  fails after bundling `Veyra.app`. Building the DMG with
  `bundle/dmg/bundle_dmg.sh --skip-jenkins` produces an unstyled image.

The configured native runners do not prove latest macOS, Windows 11 or Ubuntu
install-and-launch compatibility. See `../../reports/desktop-ui-review/README.md`
for locally observed results and explicit cross-platform verification gaps.

## Boundaries

The Tauri frontend talks to named Rust commands only (`open_dataset`,
`command`, event subscription over `veyra://event`). Renderer requests carry
no shell or process APIs; the Svelte side cannot launch programs. The Rust
side owns native pickers, export paths and the trusted backend command.
Diagnostics preserve bounded recent process context; log rotation is not claimed.

Runtime stdout is decoded with version and length limits. Visualization has a
coalesced latest update in the native relay; slow UI may supersede visualization,
not mapper ingestion. Three.js reuses bounded point/instancing GPU buffers and
discloses rendering sampling. uPlot retains at most 300 samples.
