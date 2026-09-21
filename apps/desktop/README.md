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

On Windows, set `VEYRA_PYTHON` to the environment's `python.exe`. Without this
variable, source runs use `python3` on Linux/macOS and `python` on Windows.
The dataset root is chosen through the native directory picker. Imported
configuration cannot replace the trusted C++ executable. Generic datasets use
the existing manifest adapter; real external poses remain required by mapping.

Map provides point/cell layers, camera presets, follow mode, cell inspection,
presets, follow mode, cell inspection,
playback, seek and policy switching. Performance reports backend
measurements; desktop-shell process rows are unavailable in Tauri builds,
which emit no `desktop_telemetry`. Missing measurements remain unavailable.
Benchmarks consumes existing schema-2 reports. Configuration imports, validates
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
checkout and writes a size/SHA-256 manifest that packaged startup validates.

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
installation. Models/datasets remain explicit external assets. Packaged startup
refuses a missing or platform-mismatched bundle. Runtime exits are restarted at
most three times with exponential delay; a stable 30-second session resets that
budget. Forced shutdown terminates the runtime process group so mapper children
do not survive the app.

`.github/workflows/release-tauri.yml` builds the Tauri bundles on their native
runners, stages the backend, runs product checks, emits `SHA256SUMS`, and
uploads the bundles as CI artifacts. GitHub Release publishing and bundle
signing remain future work there. Tags with a suffix and manual prerelease
runs use the prerelease channel. Windows signing
is enabled only when the `WINDOWS_CERTIFICATE_BASE64` and
`WINDOWS_CERTIFICATE_PASSWORD` secrets exist. macOS signing/notarization is
enabled only when the Apple certificate, identity, account password and team
secrets exist; Tauri bundles ship unsigned until signing lands there.

## Boundaries

The Tauri frontend talks to named Rust commands only (`open_dataset`,
`command`, event subscription over `veyra://event`). Renderer requests carry
no shell or process APIs; the Svelte side cannot launch programs. The Rust
side owns native pickers, export paths, the trusted backend command and
rotating diagnostic logs.

Runtime stdout is decoded with version and length limits. Visualization has a
single latest pending update plus one in flight, acknowledged after delivery;
slow UI drops only visual updates. Three.js reuses point and instancing GPU
buffers (maximum 100,000 entities each). uPlot retains at most 300 samples.
