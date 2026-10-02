# Electron removal — agent/electron-rm

- Base: `demo-readiness` @ `a811e6f`; branch `agent/electron-rm`, worktree `worktrees/electron-rm`
- Gate: `reports/closure/electron/PARITY.md` — all five parity items PASS, so Phase 2 executed.
- Date (UTC): 2026-09-18
- Revert: `git revert <commit-SHA>` (single removal commit; PARITY.md was staged alongside — see commit stat).

## Deleted (production Electron)

| File | Reason |
|------|--------|
| `apps/desktop/forge.config.ts` | Electron Forge config (makers, VitePlugin entries) |
| `apps/desktop/src/main.ts` | Electron main entrypoint (`BrowserWindow`, `ipcMain`) |
| `apps/desktop/src/preload.ts` | Electron preload (`contextBridge`/`ipcRenderer`) |
| `apps/desktop/src/supervisor.ts` | Node `RuntimeSupervisor`; sole consumer was `main.ts`; superseded by `src-tauri/src/supervisor.rs` |
| `apps/desktop/vite.main.config.ts` | Forge main build config |
| `apps/desktop/vite.preload.config.ts` | Forge preload build config |
| `apps/desktop/tests/desktop.spec.ts` | Playwright `_electron` launch spec (Electron-only smoke) |
| `apps/desktop/tests/supervisor.test.ts` | Tested deleted node supervisor |
| `apps/desktop/playwright.config.ts` | Served only `*.spec.ts`; no specs remain |
| `.github/workflows/product.yml` | Electron CI. Coverage mapping: Python/C++ legs → `ci.yml` (discovers the same suites incl. `test_engine_service`, `test_product_runtime`, `test_package_backend`, benchmarks); `npm test`/`check`/`build` → `desktop-tauri.yml` frontend checks; `npm run package` → `tauri build --no-bundle` compile gate (+ full bundles in `release-tauri.yml`); xvfb Electron smoke → Rust real-data packaged E2E in the same Tauri workflow (strictly stronger) |
| `package.json`: `main`, `start`/`package`/`make`/`test:e2e` scripts, `electron` + `@electron-forge/*` + `@playwright/test` devDeps | Electron packaging scripts/deps; lockfile regenerated (`package-lock.json`, zero `electron` entries) |

## Retained (deliberate — NOT deleted)

- `.github/workflows/release.yml` — **kept per gate rule.** Tauri equivalent `release-tauri.yml` mirrors the 4-platform packaging matrix, backend staging, version stamping, manifest + checksums, and artifact upload, but explicitly defers the GitHub-Release **publish** job (comment: "await the future publish job") and does **no bundle signing** ("bundles ship unsigned until then"), while `release.yml` has both. Signing + publish are therefore uncovered → reported, not deleted. Note: its `make`-based package job is stale without Forge config; it triggers only on `v*` tags / manual dispatch, so normal CI is unaffected. Recommended follow-up: orchestrator approves deletion once Tauri publish + signing land.
- `docs/desktop-electron-audit.md` — intentional archival (Tauri migration reference per `AGENTS.md`).
- `docs/superpowers/plans/*` — dated historical plans, archival by nature.
- `apps/desktop/src/packaging.ts` + `tests/packaging.test.ts` — shared backend-layout resolution contract referenced by the Tauri closure; not Electron-only.
- `apps/desktop/tests/core.test.ts` ("does not direct Tauri users to Electron") — intentional no-leakage guard; still passes.
- `scripts/package_backend.py` — shared: imported by `scripts/stage_tauri_backend.py` (Tauri staging) and covered by `tests/test_package_backend.py`. One-line docstring updated (Forge → Tauri staging).
- `App.svelte:80` hint text noting `desktop_telemetry` is absent in Tauri builds — accurate, kept.

## Accuracy edits (live docs referencing removed entry points)

- `apps/desktop/README.md`: Electron → Tauri (intro, `tauri:dev`, checks, packaging, boundaries sections).
- `docs/tauri.md`: migration-in-progress note → removal recorded with PARITY.md pointer.
- `docs/product-runtime.md`: data-path diagram, `npm start`, main-process trust note, Forge packaging note → Tauri.

## Test results (this worktree, after removal)

| Suite | Result |
|-------|--------|
| `npm test` in `apps/desktop` | **29/29 pass** |
| `ctest --test-dir build` (fresh configure `-DBUILD_TESTING=ON -DVEYRA_BUILD_APPS=ON`, build `-j2`) | **19/19 pass** (103 s) |
| `python3 -m pytest -q` (full) | 348 passed, 38 skipped, **2 failed — both proven NOT caused by this change** (see below) |
| `cargo test --lib` in `src-tauri` | **52 passed, 0 failed** |
| `npm run check` (svelte-check, informational) | 1 error in `App.svelte:80` — byte-identical error on pristine `a811e6f` base → pre-existing |

Pre-existing/environmental failures (evidence, not assumptions):
1. `benchmarks/test_product_benchmark.py::...test_ablation_report...` — fails identically on pristine base (needs `VEYRA_BENCHMARK_BINARY` C++ ablation smoke).
2. The full validation entry-point test resolves project modules outside the checkout — passes on base, fails here only with `Python interpreter is unavailable: .../worktrees/electron-rm/.venv/bin/python`; the main checkout has `.venv`, fresh worktrees do not (untracked dir). Environmental; no Python logic was touched (only a docstring).

## Gaps / follow-ups for orchestrator

1. `release.yml` retained stale (see above) — needs Tauri publish + signing, then a deletion approval.
2. No `.venv` in fresh worktrees breaks one validator test — consider documenting worktree setup (symlink or create `.venv`) for future agents.
3. Pre-existing `svelte-check` error (`workspace!=='Map'` comparison, `App.svelte:80`) predates this removal; routed to UI owner.
