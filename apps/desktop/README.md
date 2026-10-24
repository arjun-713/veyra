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
3. Review the resource profile, selected frame limit and full-sequence setting;
   choose a resolution policy before opening the session.
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

## Judge View and cell inspection

In Viewer, select **Map** or **Both**, then enable **Judge View** in the map
toolbar. It turns on semantic display and range rings without changing policy,
perception or telemetry. Camera/follow/visibility settings remain selected;
exiting restores the preceding display state. Live and Smooth Replay are
labelled separately; [runtime replay](../../docs/product-runtime.md#smooth-replay)
defines recorded metrics and presentation FPS.

Range bands and resolution explanations come from the engine's
`policy_descriptor` (level ladder, boundaries and protected/window radii).
Older caches without it show unavailable configuration. Click a rendered cell
to highlight its world-space footprint and open the inspector:

- **Resolution:** Uniform policies explain their fixed level; DistanceLOD
  compares configured range with stored level. UtilityLOD shows refinement
  direction and stored signals; absent decision attribution remains explicit.
- **2.5D anatomy:** separate ground, obstacle and overhead profiles show
  count/mean/min/max, with unavailable empty layers. Pooled elevation is a
  summary, not a physical surface. Ground absent beside obstacle support is
  unobserved; it is not proof of backend visibility or free space.
- **Perception/state:** taxonomy names, confidence, motion, traversability,
  observations and quality use measured fields. Unsupported surface/visibility
  evidence stays unavailable. Selection re-resolves by world key each frame
  and reports when that leaf is no longer active.

Layer transport is defined in the [visualization contract](../../docs/product-runtime.md#visualization-contract).
The coordinate bar discloses cell selection mode, displayed/total counts and
renderer clamps. Unknown is never presented as drivable. Same-frame policy
comparisons need benchmark artifacts, and ghost-cleanup demonstrations need
real timestamps and usable motion evidence.

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
For a standalone executable without installer bundles, run
`npm run tauri:build -- --no-bundle` from `apps/desktop`. Use the Tauri production
build, not plain `cargo build --release`: the production build enables Tauri's
custom protocol and embeds the frontend instead of loading the development URL
at `127.0.0.1:1420`. No Vite server is needed to launch the installed app.
On Linux, a per-user standalone installation can place `resources/backend/`
beside the executable; the app resolves that bundle when system resources are
not installed.

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
runners, stages the backend, runs product checks, creates an aggregate
`release-manifest.json` and `SHA256SUMS`, and publishes installers to a GitHub
Release. Signing/notarization is separate from a successful build or publish;
do not describe a bundle as signed unless release provenance verifies it.

### Automatic releases

Every push to `main` starts the native release workflow. Its run number provides
the automatic patch increment: with a checked-in version of `0.1.0`, workflow
run 12 builds `0.1.12` and publishes tag `v0.1.12`. Retries retain the same
version; skipped/failed runs can leave version gaps. Keep the checked-in version
as the release-series baseline, rather than stamping it back into Git after
each build. Explicit `v*` tags and manual versions remain supported; semantic
prerelease versions do not become the stable download.

The version is stamped before staging so the backend manifest and installer
agree. Each native job verifies a relocated bundled Python runtime, its
dependencies and mapper before the production Tauri build. Only after all four
platform jobs succeed are the Linux `.deb`/`.rpm`/`.AppImage`, Windows NSIS
installer and both macOS DMGs assembled with checksums. Uploads go into a draft
pinned to the built commit; publication exposes the complete release. Published
assets are not overwritten on retries. A failed build leaves the previous
stable release available.

Running releases are not cancelled by new pushes. GitHub concurrency retains
one pending run per ref, so rapid pushes can supersede a pending build; the
latest queued main state is built after the active run finishes. This does not
automatically update apps already installed on user machines.

No Python installation or development server is required by the packaged app.
Datasets/model weights remain user-provided; Intel macOS currently lacks the
Patchwork++ backend. Native install/launch testing and OS signing/notarization
are distinct from these packaging checks. Windows/macOS security warnings can
remain until signing credentials are configured.

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
install-and-launch compatibility. The [recorded Linux packaged-runtime checks](../../reports/closure/tauri/RESULT.md#phase-b-packaged-runtime)
describe their own build and verification scope; repeat installation and launch
checks for the release and platform being distributed.

## Runtime boundaries

Rust owns native pickers, export paths, process launch and named commands
(`open_dataset`, `command`, `veyra://event`). The renderer has no shell/process
API. Bounded diagnostics, telemetry windows, GPU/display budgets and coalescing
are documented in the [product runtime](../../docs/product-runtime.md).

## Visual conventions

The desktop uses a light shell and dark spatial viewports: precise alignment,
system typography, quiet separators and one primary action per task. Navigation
is Overview / Viewer / Session setup / Performance / Evaluation; source settings
belong to setup, playback to Viewer. Advanced settings are disclosed progressively.

- Font: `-apple-system, BlinkMacSystemFont, Inter, Segoe UI, sans-serif`;
  monospace for measurements/paths/config. Type: 9–11 px viewport labels,
  12–15 px controls, 17–21 px panels, 24 px pages, 32–40 px empty states.
- Palette: canvas `#f5f5f7`, surface `#ffffff`, sidebar `#ededf0`, ink `#1d1d1f`,
  secondary `#626269`, separator `#dedee3`, accent `#0069df`.
- Radius: controls 8 px, panels 14 px, toolbars 12 px. Spacing: 4/8/12/16/24/32/48 px.
- Icons: authored 24 px SVGs, rounded 1.7 px strokes. Motion: 140 ms feedback,
  200 ms ease-out entry; only busy indicators loop, respecting reduced motion/transparency.

Empty screens explain the next action; active Overview uses the three real
spatial previews. Ground truth stays labelled, missing values stay unavailable,
and resource savings do not imply map-quality superiority.
