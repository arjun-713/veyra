# Veyra desktop bundle — rebuild mission evidence (stale-backend fix)

HEAD: `7d3b116` (`demo-readiness`, confirmed `git rev-parse HEAD` ==
`git rev-parse demo-readiness` before branching).
Branch: `agent/bundle-rebuild`, worktree `worktrees/bundle-rebuild`.
Date: 2026-09-18 ~14:41–14:55 IST. Host: Fedora, uid=1000 (not root).
Prior evidence: `/tmp/opencode/desktop-launch/REPORT.md` (stale-local-bundle
diagnosis: bundles built 13:09 Sep 17, backend staged 14:40 Sep 17).

## 0. Build location note

All staging/build work ran in the main checkout (same commit `7d3b116`,
warm `build/` + `src-tauri/target/` caches); the worktree holds only this
report for the `agent/bundle-rebuild` commit. Source inputs are identical
in both places, so artifacts are representative of this commit.

## 1. Step status

| Step | Result |
|---|---|
| (1a) Mapper build (`cmake --build build --config Release -j4`) | OK, no-op — all targets up to date, incl. `veyra_runtime` (config `Release`, `VEYRA_BUILD_APPS=ON`, same as CI). Binary `build/apps/runtime/veyra_runtime`, 313472 B, mtime Sep 17 17:04 |
| (1b) Stage backend (`scripts/stage_tauri_backend.py`) | OK (see deviation D1). Fresh `src-tauri/resources/backend/`, manifest mtime Sep 18 14:41, `schema_version=1`, `platform=linux`, `arch=x64`, 5638 files, `runtime/__main__.py` present |
| (2) Staged-content + `git status` check | OK — `manifest.json` + `runtime/__main__.py` present; both gitignored (`.gitignore:102`). Only pre-existing `?? worktrees/` in status (see deviation D2 for transient `.gitkeep`) |
| (3) Bundle rebuild (`npm run tauri:build -- --bundles "deb,rpm"` from `apps/desktop`) | OK — frontend 5.98 s, rust release 2 m 51 s, both bundles emitted, exit 0 (see deviation D3 for appimage scope) |
| (4) deb+rpm re-inspection | PASS — see §2 |
| (5) Display-isolated launch probe + orphan check | Same gtk-absent exit as prior probe, orphans CLEAN — see §3 |

## 2. Bundle contents verdict — FIXED (backend fully staged)

Rebuilt AFTER staging (deb 14:45, rpm 14:48 Sep 18 > staging 14:41).
Inspected without installing: deb via `ar x` + `tar tzf data.tar.gz`,
rpm via `rpm -qlp` (no dpkg on Fedora, uid 1000).

| Payload | deb | rpm |
|---|---|---|
| `usr/bin/veyra`, `veyra-cli`, `veyra-control` | YES | YES |
| `usr/lib/Veyra/resources/backend/manifest.json` | YES | YES |
| `usr/lib/Veyra/resources/backend/runtime/__main__.py` | YES | YES |
| `backend/bin/veyra_runtime` (sha256 == built mapper `1bf465d1…`) | YES | (payload shared; verified via deb) |
| backend entry count | 6179 (incl. dir entries) | 5639 (= 5638 manifest files + dir) |
| bare `.gitkeep` backend | NO (absent entirely) | NO |

Content proof: sha256 of staged `manifest.json` == sha256 of
deb-embedded `usr/lib/Veyra/resources/backend/manifest.json` ==
`0c6377ba1d6894d4c3127e1b79706d96f833aeeac72ff3376c0c9a6cf4e63b8d`
(pre-stage manifest was `40d49543…`, so the bundle provably embeds the
fresh staging, not the old one). `runtime_root()` (`src-tauri/src/lib.rs:155`)
now resolves the staged backend instead of falling back.

## 3. Launch observations (packaged layout, extracted deb root)

- `ldd usr/bin/veyra` → zero missing libs (unchanged).
- Sidecars run headless and print usage (`veyra-cli` structured
  `CLI_ERROR` usage JSON; `veyra-control` usage line).
- GUI binary, display-isolated (`env -u DISPLAY -u WAYLAND_DISPLAY
  -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR=<empty> GDK_BACKEND=x11`,
  `timeout -s KILL 15`): exit **101**, stderr = same
  `Failed to initialize gtk backend!` panic at `tao-0.35.3/.../event_loop.rs:217`.
  Identical to prior probe: binary loads, reaches window creation, fails
  ONLY on absent display. Expected headless behavior, no regression.
- Non-isolated live-display probe NOT repeated (prior mission §2 already
  covers it; left for a controlled demo session).
- Orphan check: `pgrep -x veyra` before NONE, after CLEAN. No `pkill`
  used (avoids the prior mission's self-match pitfall).

## 4. Tests run

- `cargo test --release` in `src-tauri` (warm cache): **63 passed,
  0 failed** — lib 52 (incl. `packaged_resource_directory_resolves_the_staged_backend_root`,
  `unstaged_backend_placeholder_never_masquerades_as_a_runnable_backend`,
  packaged-session e2e self-skips without dataset), cli 9, control 2.
- No C++ tests re-run (mapper build was a no-op; no source changed).
- No repo source files changed by this mission → no script/config fixes
  to commit (deviations below are behavioral notes, not code changes).

## Deviations / observations (no repo changes made)

- D1: the mission's staging command omits `--python-runtime`, which the
  script requires (`--help`: `--mapper` + `--python-runtime` + `--platform`
  + `--arch` all required). Ran with `--python-runtime .venv` (repo venv,
  Python 3.13.15, project deps installed, base `/usr/bin` — same shape CI
  builds with `python -m venv` + `requirements.txt`; no new installs).
  Consider updating the runbook copy of this command, not the script.
- D2: staging wipes the tracked `src-tauri/resources/backend/.gitkeep`
  (`shutil.rmtree(output)` in `stage()`). Same happens on CI (ephemeral
  checkout, harmless there). Locally restored afterwards with surgical
  `git checkout -- <file>` (no reset/clean); final `git status` shows only
  pre-existing `?? worktrees/`. Deliberately NOT "fixed" in script: preserving
  `.gitkeep` would change CI bundle payloads for zero functional gain.
- D3: built `--bundles "deb,rpm"` only; CI linux matrix adds `appimage`.
  Prior local bundles were deb+rpm-only, and the mission scope is deb+rpm.
  AppImage parity remains a CI-side property, untested locally.

## Gaps / next steps

1. Live windowed proof still open (nested compositor / VM + screenshot).
2. `demo_rehearsal.sh` step 4 still needs a headless pass/fail probe —
   the isolated GTK-init exit-101 check here remains the candidate assertion.
3. Local AppImage build not attempted (see D3).

Commit: `agent/bundle-rebuild` (this file only; no artifacts committed —
staged backend, `build/`, `src-tauri/target/` all gitignored).
