# Platform survey — cross-platform slice 1 (inventory + Linux smoke)

Worktree: `worktrees/platform`, branch `agent/platform`, base `demo-readiness @ 1ad1388`.
Scope: survey + smoke only. No packaging changes. No VM/installer builds.

## 1. CI runners inventory (`.github/workflows/`)

| Workflow | Runners | Notes |
|---|---|---|
| `ci.yml` | `ubuntu-24.04` only (C++, Python, fmt) | No OS matrix |
| `benchmark.yml`, `benchmark-report.yml` | `ubuntu-24.04` only | Dataset-bound, Linux-only by design |
| `desktop-tauri.yml` (build check) | `ubuntu-24.04`, `windows-2025`, `macos-15` | `tauri build --no-bundle`: compiles app on all 3 OSes, packages nothing |
| `release-tauri.yml` (Tauri release) | `ubuntu-24.04`, `windows-2025`, `macos-15` | Full bundle per matrix below |
| `release.yml` (Electron release) | `ubuntu-24.04`, `windows-2025`, `macos-15`, `macos-15-intel` | Electron path; extra macOS-x64 leg Tauri lacks |
| `product.yml` | `ubuntu-24.04` only | Linux Electron shell + `xvfb` e2e |

No Fedora/RHEL runner anywhere. No `macos-15-intel` leg in any Tauri workflow.

## 2. Backend staging (`scripts/package_backend.py` + `stage_tauri_backend.py`)

- `package_backend.py --platform {linux,darwin,win32} --arch {x64,arm64}` builds a
  relocatable `backend/` dir: `bin/veyra_runtime[.exe]` + vendored venv-python +
  allowlisted roots (`runtime viewer benchmarks perception datasets configs`) +
  `manifest.json`; `verify_backend()` asserts binary + interpreter presence and
  platform match. Dataset/model suffixes (`.bin .onnx .pt .bag …`) are rejected
  from the package.
- `stage_tauri_backend.py` is a thin wrapper staging the same layout into
  `src-tauri/resources/backend` (bundled via `tauri.conf.json` → `"resources"`).
- Per-OS artifacts: **identical layout** on all three platforms; only the mapper
  filename (`veyra_runtime` vs `veyra_runtime.exe`) and venv layout
  (`bin/python3` vs `python.exe`) differ. No OS-specific sidecars
  (`externalBin` unused); the Rust side resolves the mapper at runtime
  (`src-tauri/src/control/controller.rs:184`: `VEYRA_MAPPER` env override →
  staged `bin/…` → dev fallback `build/apps/runtime/…`), with unit tests for
  staged-vs-dev resolution.

## 3. Tauri bundler config (`src-tauri/tauri.conf.json`)

`"targets": ["deb", "rpm", "appimage", "nsis", "dmg"]` — all five declared in one
static list (Tauri picks the applicable ones per runner OS; nothing OS-conditional
in-repo). Release matrix maps them explicitly:

| Release leg | Runner | Bundles |
|---|---|---|
| Linux x64 | `ubuntu-24.04` | `deb,rpm,appimage` |
| Windows x64 | `windows-2025` | `nsis` |
| macOS ARM64 | `macos-15` | `dmg` |

Signing: optional Apple cert (`APPLE_CERTIFICATE_BASE64`,
`release.yml`-style import step mirrored in `release-tauri.yml` job env) and
Windows cert materialization; builds proceed unsigned when secrets are absent.
`src-tauri/resources/` currently holds only `backend/.gitkeep` — the backend is
staged by CI at release time, never committed.

## 4. Per-OS status table

| OS | CI build check | Package smoke in CI | Sidecar/backend staging | Installer target | Gaps |
|---|---|---|---|---|---|
| Ubuntu (x64) | ✅ `desktop-tauri.yml` + `ci.yml` + `product.yml` | ✅ release `status` smoke; ✅ `product.yml` xvfb e2e | ✅ `package_backend.py` linux/x64 | ✅ `deb,rpm,appimage` | — (reference platform) |
| Windows (x64) | ✅ `desktop-tauri.yml` (`windows-2025`) | ✅ release `status` smoke (win32 path) | ✅ win32/x64 layout, `.exe` handling tested in controller unit tests | ✅ `nsis` | No `.msi`/WiX target; signing secret-dependent (unsigned by default) |
| macOS ARM64 | ✅ `desktop-tauri.yml` (`macos-15`) | ✅ release `status` smoke | ✅ darwin/arm64 layout | ✅ `dmg` | Signing/notarization secret-dependent; no `macos-15-intel` Tauri leg (Electron has one) |
| macOS x64 (Intel) | ❌ no Tauri runner | ❌ | ✅ script supports darwin/x64 (unused) | ❌ no dmg built | Add `macos-15-intel` leg to `release-tauri.yml` if Intel support is required |
| Fedora/RHEL | ❌ no runner (Ubuntu-built `rpm` only) | ❌ install-test on dnf system | ✅ same linux/x64 backend | ⚠️ `rpm` built but never install-tested on Fedora | No Fedora CI leg; `rpm` is cross-distro untested (deps, WebKit runtime) |

Cross-cutting gaps: (a) only `desktop-tauri.yml --no-bundle` exercises non-release
paths on Win/macOS — installer artifacts are produced **only** on tag/release
runs; (b) no install-and-launch test of any produced installer (deb/rpm/appimage/
nsis/dmg) on any OS; (c) Fedora has neither runner nor smoke.

## 5. Linux smoke results (this host, worktree `worktrees/platform`)

- Rust/Tauri lib: `cargo check -j2 --manifest-path src-tauri/Cargo.toml --lib` —
  **PASS**, `Finished dev profile in 7m 12s`, zero warnings/errors (fresh worktree
  target dir; full Tauri dep-graph compile, within the 600 s budget).
- Python backend CLI smoke (mirrors `release.yml` "Smoke test staged runtime"):
  `status` request → `VYRA`-framed reply, 1702 bytes, exit 0. **PASS**.
- Python `configure` + `step` on 1 real frame: `ProductRuntime` configured with
  `dataset=rellis3d`, `dataset_root=<main-repo> data/raw/rellis3d/Rellis-3D`
  (worktree `data/` holds only `.gitkeep`; main-repo data used read-only),
  `sequence=00000`, mapper = main-repo `build/apps/runtime/veyra_runtime`
  copied to worktree `build/` (gitignored, not committed) to satisfy the
  in-repo-executable check; `configure → ready`, `step → index 0`. **PASS**.

## 6. Gaps / next slices (no changes made here)

1. `cargo check` on a fresh worktree target dir takes ~7 min at `-j2` (full Tauri
   dep-graph compile); recommend shared `CARGO_TARGET_DIR` or `sccache` to keep
   future slices comfortably inside budget.
2. Installer-level verification missing everywhere: add install+launch smoke
   per bundle type (at least `deb` + `nsis` + `dmg`).
3. Decide macOS-Intel support for Tauri (drop or add `macos-15-intel` leg).
4. Decide Fedora support: `rpm`-on-Fedora install test or document Ubuntu-only.
