# CI / Release Survey — slice 1 (read-only, no Electron removal)

- Scope: `.github/workflows/*` + release scripts. Survey only; Electron removal
  is gated on Tauri parity sign-off (docs/desktop-electron-audit.md Phase 20).
- HEAD: `demo-readiness` = `1ad1388` (verified via `git log` in worktree).
- Remote runs NOT fetched (sandboxed mission: report config, cannot confirm green).
- Validation: `python yaml.safe_load` OK on all 7 workflows
  (note: YAML 1.1 parses bare `on:` as boolean `True` — use `loader` quirk-aware
  parsing, not evidence of breakage). `shellcheck` not installed — skipped,
  stated honestly. `release_checksums.py --help` / `release_manifest.py --help`
  + functional smoke on fixture dir both pass (see §5).

## 1. Workflow table (7 files, 793 lines total)

| Workflow | Triggers | Runners | Jobs | What it validates | Artifacts |
|---|---|---|---|---|---|
| `ci.yml` (82L) | `push`, `pull_request` | `ubuntu-24.04` ×3 jobs | `cpp` (Debug+Release, `-Werror`, ctest excl. python/benchmark), `python` (ruff, format, `node --check app.js`, compileall, unittest `benchmarks`+`tests`), `formatting` (clang-format on `apps/benchmark/main.cpp` only) | Core C++/Python. No desktop at all. | None |
| `product.yml` (83L) | `push`, `pull_request` | `ubuntu-24.04`, timeout 30m | `desktop`: strict backend build, `test_engine_service`, `test_product_runtime`, `test_package_backend`, product benchmarks, `npm ci/test/check/build/package` in `apps/desktop`, `xvfb-run npm run test:e2e` | **Electron product only.** Runtime + Electron shell + E2E. | `veyra-linux-unpacked-<sha>` (7d, `apps/desktop/out/`); `veyra-product-failure` (test-results, playwright-report) on failure |
| `desktop-tauri.yml` (51L) | `push`, `pull_request` | matrix `ubuntu-24.04 / windows-2025 / macos-15` | `build`: WebView deps (Linux), `npm ci`, `npm run check/build`, `cargo fmt --check`, `cargo test`, `cargo clippy -D warnings` (manifest `src-tauri/Cargo.toml`), `tauri build --no-bundle` | **Tauri compile only.** No backend staging (`stage_tauri_backend.py` not invoked), no bundle, no smoke/E2E. | None |
| `release.yml` (159L) | tags `v*`, `workflow_dispatch(version, prerelease)` | matrix Linux x64 / Win x64 / macOS ARM64 **+ macOS x64 (intel)**; package timeout 60m; publish on `ubuntu-24.04` (`contents: write`) | `package`: native runtime build, venv + `package_backend.py`, runtime smoke (`VYRA` magic assert), conditional Apple/Windows signing, `npm version` stamp, `npm test/check`, `electron-forge make`, per-platform `SHA256SUMS` via `release_checksums.py`; `publish`: regen top-level `SHA256SUMS`, `gh release create/upload` stable/prerelease channel | **Electron release.** Full sign → make → checksum → publish loop. | `veyra-<platform>-<arch>` (`apps/desktop/out/make/`); GitHub release assets + `SHA256SUMS` |
| `release-tauri.yml` (80L) | tags `tauri-v*`, `workflow_dispatch(version)` | matrix Linux x64 / Win x64 / macOS ARM64 (**no macOS x64**) | `package` only: C++ mapper build, venv + `stage_tauri_backend.py`, `npm ci`, `tauri:build --bundles <deb,rpm,appimage / nsis / dmg>`, `release_manifest.py` + `release_checksums.py` on `src-tauri/target/release/bundle` | **Tauri release, unpackaged-to-GitHub.** Manifest + checksums written, but **no `publish` job** — artifacts die with the run. No signing. | `veyra-tauri-<platform>-<arch>` (`src-tauri/target/release/bundle/`, `if-no-files-found: error`); no retention-days set (default 90) |
| `benchmark.yml` (221L) | `pull_request`, schedule `17 2 * * *`, `workflow_dispatch` | `ubuntu-24.04`, timeout 360m | `benchmark`: pinned SemanticPOSS archive (size+SHA-256, cache), SalsaNext fetch, `veyra_benchmark` build, 4-policy run w/ retry on resource-kill, `render_report` + correctness gate, provenance env | Map/perception benchmark. Orthogonal to desktop. | `veyra-semanticposs-benchmark` (`artifacts/`) |
| `benchmark-report.yml` (117L) | `workflow_run[SemanticPOSS benchmark completed]` | `ubuntu-24.04` | `report`: download benchmark artifact, upsert PR comment (map/perception/quality/regression tables) | Reporting only. | Consumes `veyra-semanticposs-benchmark` |

## 2. Does CI validate the real Tauri product? — Partially (NO for packaged app)

- YES (compile): `desktop-tauri.yml` covers fmt + test + clippy + frontend
  `check/build` + `tauri build --no-bundle` on all 3 desktop OSes, every
  push/PR. `src-tauri/` layout verified present at repo root (`Cargo.toml`,
  `tauri.conf.json`, `capabilities/`, `icons/`); path usage verified
  consistent (cargo `--manifest-path src-tauri/…` + tauri `--config
  src-tauri/tauri.conf.json` run from repo root; `tools/tauri.mjs` pins
  `cwd=repository` root so `target/` lands at `src-tauri/target/`;
  `frontendDist: ../apps/desktop/dist` resolves root-relative correctly).
- NO (product): nothing in CI (a) stages the relocatable backend into the
  Tauri bundle, (b) smoke-tests a bundled Tauri artifact, or (c) runs any
  Tauri E2E. `desktop-tauri.yml` explicitly passes `--no-bundle`; backend
  staging exists only in `release-tauri.yml`. The only E2E in CI
  (`product.yml` Playwright/xvfb) drives the Electron shell.
- Release gap: `release-tauri.yml` builds real bundles (deb/rpm/appimage,
  nsis, dmg — closing the audit's Phase-12 gap list) but has no publish,
  no signing, no smoke test of the staged backend (contrast `release.yml`
  `VYRA`-magic runtime smoke).

## 3. Obsolete / duplicative analysis (Electron vs Tauri) — remove nothing yet

- `product.yml` (Electron) vs `desktop-tauri.yml` (Tauri): overlap in
  `npm ci` + `check` + `build` on the same `apps/desktop` frontend; diverge
  in shell (Forge package + Playwright E2E vs cargo checks + no-bundle
  build). Neither subsumes the other today.
- `release.yml` (Electron, `v*`, 4 targets incl. macOS x64) vs
  `release-tauri.yml` (`tauri-v*`, 3 targets, no macOS x64, no publish):
  duplicated C++ build + venv + backend-staging logic via two scripts
  (`package_backend.py` vs `stage_tauri_backend.py`); divergent signing,
  stamping, and publish paths. Tag namespaces are already collision-free.
- `ci.yml` is orthogonal (core); `benchmark*.yml` are orthogonal (eval).
- Verdict: **no workflow is obsolete today.** Electron tracks are the only
  paths with E2E + signed publish; Tauri tracks are the only paths with
  Rust gates + modern bundles. Dedup happens via the gated removal plan (§4).

## 4. Electron removal plan — GATED on Tauri parity sign-off (do not execute)

Preconditions (all must hold; owner: Tauri migration sign-off, Phase 20):

1. Tauri parity checklist from `docs/desktop-electron-audit.md` §2 (D1–D5,
   B1–B6, S1–S4, M1–M5, R1–R4) closed or explicitly waived with evidence.
2. Tauri CI covers what `product.yml` covers today: bundled-backend smoke
   + packaged-app launch check + E2E equivalent (Tauri driver/WebDriver or
   documented Playwright mapping) on Linux at minimum.
3. `release-tauri.yml` has publish + signing + version stamping (§5 items
   closed) and at least one `tauri-v*` release verified installable per OS.
4. Explicit sign-off recorded (migration issue / Phase-20 note); Electron
   stays the behavioral reference until then.

Removal steps (single separate commit, after sign-off):

1. Delete Electron-only CI: `product.yml` job body (or whole file if Tauri
   successor job exists), `release.yml` (after Tauri publish proven).
2. Strip Electron from `apps/desktop`: `forge.config.ts`, `vite.main/
   vite.preload.config.ts`, `main.ts`/`preload.ts`/Forge packaging sources +
   Electron Playwright spec, `electron` + `@electron-forge/*` devDeps.
3. Remove `electron`/`forge` references in docs (`desktop-electron-audit.md`
   marked historical) and `package.json` scripts (`start/package/make/
   test:e2e` replaced by `tauri:*` equivalents).
4. Keep `runtime/`, `viewer/`, C++ mapper, protocol untouched (shared).
5. Rollback: revert the single removal commit; `v*` Electron tags remain
   valid for prior releases.

## 5. Release hardening list (Tauri `release-tauri.yml` vs Electron baseline)

Scripts present and functional: `scripts/release_checksums.py` (deterministic
SHA-256, sorted, self-excluding) and `scripts/release_manifest.py`
(schema_version 1, version/target/timestamp/runner, per-file size+sha256) —
both `--help` clean and fixture-tested this survey. Gaps are in wiring:

1. **No `publish` job** — `release-tauri.yml` uploads workflow artifacts only;
   add a `publish` job mirroring `release.yml` (`download-artifact`, top-level
   `SHA256SUMS`, `gh release create/upload`, stable/prerelease channel) with
   `permissions: contents: write`. Decide tag policy (`tauri-v*` vs unified).
2. **No signing/notarization** — Electron has conditional Apple + Windows
   signing; Tauri has none. Add Tauri updater/signing keys or document
   unsigned status per bundle.
3. **No version stamping** — Electron runs `npm version`; nothing consumes
   `RELEASE_VERSION` into `src-tauri/Cargo.toml` / `tauri.conf.json`
   (grep-verified: env is passed but unread). Bundle ships `0.1.0` regardless
   of tag. Stamp versions before build.
4. **No staged-backend smoke test** — Electron asserts the `VYRA` magic frame;
   Tauri stages via `stage_tauri_backend.py` then builds without ever
   executing the backend. Add the same smoke between staging and bundling.
5. **Manifest/checksum ordering** — manifest is written before checksums, so
   `release-manifest.json` does not list `SHA256SUMS` (while `SHA256SUMS`
   covers the manifest). Pick and document the canonical order (recommend:
   manifest → checksums → top-level publish regen, as Electron does).
6. **Missing macOS x64 target** — Electron ships `macos-15-intel`; Tauri
   matrix drops it. Decide: add `x64 dmg` or record the deprecation.
7. **No timeouts/retention** — `release-tauri.yml` and `desktop-tauri.yml`
   set no `timeout-minutes`; Tauri artifact upload sets no `retention-days`.
   Pin both (suggest 60m release / 30m desktop, 7–30d retention).
8. **No Tauri E2E / bundle launch check** — `--no-bundle` CI plus untested
   bundles means a green run can still ship a broken app. Add at least a
   bundle-exists + backend-present assertion post-build (cheap) and a
   launch/smoke test (proper).
9. **Permissions minimal but publish-blocked** — `contents: read` is correct
   until publish is added; revisit when §5.1 lands.

## 6. Required checks — status unknown (no remote access)

- No `gh`/`git ls-remote` run fetch was attempted (mission bounds: local
  lint only, no pushes). Branch-protection / required-checks config cannot
  be confirmed from the checkout (only `dependabot.yml`, templates present
  locally). Last-known run state: **not verified — re-check in CI UI before
  any removal or release change.**

## 7. Validation log

```text
python yaml.safe_load: 7/7 OK (benchmark-report, benchmark, ci, desktop-tauri,
  product, release-tauri, release) — `on:` surfaces as True under YAML 1.1,
  expected quirk, triggers confirmed via raw grep.
release_checksums.py / release_manifest.py: --help OK; fixture dir produced
  valid SHA256SUMS + release-manifest.json (schema_version 1).
shellcheck: not installed in this environment — shell blocks in workflows and
  benchmark/run_local.sh NOT linted; rerun where shellcheck exists.
Local lint only: no builds, no tests, no network executed in this slice.
```
