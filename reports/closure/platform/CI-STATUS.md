# Tauri CI status — per-OS checklist × job coverage × gaps (closure packaging lane)

Branch: `closure/opencode-packaging`. Workflows owned: `.github/workflows/desktop-tauri.yml`
(unchanged this lane), `.github/workflows/release-tauri.yml` (**hardened this lane**).
Electron files: none remain in these workflows; no other workflow touched.

## 1. Workflow validation log (this lane)

- `python3 yaml.safe_load`: `desktop-tauri.yml` + `release-tauri.yml` parse OK.
- `release-tauri.yml` step order eyeballed (14 steps): checkout → node →
  python → rust → linux-deps → **mapper build → stage backend → ★smoke-test
  staged backend (NEW)** → npm ci → stamp version → tauri build →
  **★assert bundle artifacts present (NEW)** → manifest → checksums → upload.
  Staging-before-bundle order holds; provenance order (manifest → checksums,
  SHA256SUMS covers manifest) holds per the in-file canonical-order comment.
- Matrix legs (unchanged): Linux x64 (`ubuntu-24.04`, `deb,rpm,appimage`),
  Windows x64 (`windows-2025`, `nsis`), macOS ARM64 (`macos-15`, `dmg`),
  macOS x64 (`macos-15-intel`, `dmg`). Timeouts 60m, artifact `retention-days: 30`,
  `if-no-files-found: error` — all present.
- `python3 -m py_compile`: `release_manifest.py`, `release_checksums.py`,
  `stage_tauri_backend.py`, `package_backend.py` all OK (no script changes this lane).
- `shellcheck`: **absent** on this host (`which shellcheck` → not found); new
  `run:` blocks are POSIX-`bash` mirroring `release.yml`'s proven smoke block
  (same `$RUNNER_TEMP`, same `VYRA`-magic python assert). Rerun shellcheck
  where installed before merge.
- Functional simulation (no CI run from this lane): the exact smoke command
  shape was executed against the main checkout's staged backend
  (`src-tauri/resources/backend`, read-only): `status` → 1701 bytes,
  `VYRA` magic, assert PASS. The assert-step python was run against a synthetic
  bundle tree: positive case (`deb,rpm,appimage` all present → PASS) and
  negative case (missing `nsis` → correctly fails the leg).

## 2. Workflow diffs this lane (`release-tauri.yml` only)

1. **`Smoke-test staged backend`** (after staging, before `npm ci`): runs on
   all four matrix legs, no secrets. Uses the staged flattened interpreter
   (`backend/python/bin/python3`, or `backend/python/python.exe` on win32),
   pipes a `status` request into `python -m runtime --repo
   src-tauri/resources/backend`, asserts `len>16` and `VYRA` magic — verbatim
   mirror of `release.yml`'s Electron smoke. Closes CI survey §5.4.
   Root cause it fixes: a green release could previously ship a dead backend
   (staging succeeded structurally via `verify_backend`, but nothing ever
   *executed* it before bundling).
2. **`Assert bundle artifacts present`** (after build, before manifest):
   maps each requested target in `${{ matrix.bundles }}` to its suffix
   (`.deb/.rpm/.AppImage/.exe/.dmg`) and fails the leg on any missing one.
   Closes CI survey §5.8-cheap-half. Root cause it fixes: the bundler could
   silently emit a subset (e.g. AppImage tooling failure) and the run would
   still publish manifest+checksums for whatever happened to exist.
3. `desktop-tauri.yml`: **no change.** It is documented compile-only
   (`--no-bundle`, no artifacts by design). Adding bundle builds there would
   triple per-PR cost and contradict the in-file comment; the release legs now
   carry the smoke+assert gates instead (§4, decision D1).

## 3. Per-OS checklist × job coverage

Legend: ✅ covered in CI config (not yet observed green from this lane — no
remote run fetch) · ⚠️ partial · ❌ open gap.

| Check | Ubuntu x64 | Windows x64 | macOS ARM64 | macOS x64 (Intel) | Fedora/RHEL |
|---|---|---|---|---|---|
| Compile (`desktop-tauri.yml`) | ✅ `ubuntu-24.04` | ✅ `windows-2025` | ✅ `macos-15` | ❌ no leg (compile-only; Intel covered only at release) | ❌ no runner |
| Mapper build (release) | ✅ | ✅ | ✅ | ✅ (`macos-15-intel` leg) | ❌ |
| Backend staging | ✅ | ✅ | ✅ | ✅ | n/a (same linux/x64 payload) |
| ★ Staged-backend smoke (NEW) | ✅ | ✅ | ✅ | ✅ | ❌ |
| Bundle produced | ✅ deb/rpm/appimage | ✅ nsis | ✅ dmg | ✅ dmg | ❌ (Ubuntu-built rpm only) |
| ★ Bundle-exists assert (NEW) | ✅ | ✅ | ✅ | ✅ | ❌ |
| Version stamping | ✅ (tag → `tauri.conf.json` + `Cargo.toml`) | ✅ | ✅ | ✅ | — |
| Manifest + checksums | ✅ | ✅ | ✅ | ✅ | — |
| Installer install-and-launch | ❌ (archive-inspected only, MANIFEST.md) | ❌ needs native runner | ❌ needs native runner | ❌ needs native runner | ❌ |
| Signed / notarized installer | n/a (unsigned .deb/.rpm norm) | ❌ secret-gated | ❌ secret-gated | ❌ secret-gated | — |
| Publish to GitHub release | ❌ no `publish` job (all OSes) | ❌ | ❌ | ❌ | — |
| E2E / packaged launch check | ❌ (`product.yml` xvfb E2E is Electron-only) | ❌ | ❌ | ❌ | — |

## 4. What only a native runner can prove (do NOT fake locally)

No emulation, container, or cross-OS inspection substitutes for these. Each
row names the workflow job that must grow it when the lane is scheduled:

| # | Native-only proof | OS / runner | Covers which gap | Future job |
|---|---|---|---|---|
| N1 | `nsis` installer installs + app launches, sidecar `veyra_runtime.exe` discovered via staged `bin/` (not dev fallback) | `windows-2025` | installer, sidecar naming (`.exe`), discovery, supervision | `release-tauri.yml`: post-bundle `nsis` install + launch smoke |
| N2 | `dmg` mounts, app launches, `darwin/{arm64,x64}` backend resolves, no Gatekeeper block on unsigned build documented | `macos-15` + `macos-15-intel` | installer, arch-specific sidecar, supervision | `release-tauri.yml`: post-bundle `dmg` mount + launch smoke (both arch legs) |
| N3 | `deb` installs (`apt`/`dpkg -i`) + launches on Ubuntu; AppImage mounts + launches (needs FUSE) | `ubuntu-24.04` | installer, AppImage wrapper (MANIFEST.md §5) | `release-tauri.yml`: `deb` install + AppImage mount smoke |
| N4 | Ubuntu-built `rpm` installs (`dnf`) + launches on Fedora/RHEL (WebKitGTK runtime deps!) | Fedora runner (does not exist) | cross-distro rpm validity | new runner or documented Ubuntu-only support |
| N5 | Signed + notarized installers (Apple cert, Windows cert) | native runners + secrets | signing/notarization | `release-tauri.yml` signing steps (secret-gated, cf. `release.yml`) |
| N6 | Packaged-app E2E (Tauri driver/WebDriver or Playwright mapping) | `ubuntu-24.04` minimum | release confidence parity with Electron `product.yml` | new E2E job or `desktop-tauri.yml` successor |

Decisions recorded this lane:
- **D1:** No bundle-build legs added to `desktop-tauri.yml` — does not fit its
  compile-only structure; release legs now carry smoke+assert. A Windows-CI
  smoke leg and macOS-dmg smoke leg *as release steps* were added instead
  (matrix-scoped, secret-free); as *separate PR-check jobs* they are deferred
  to N1/N2 (need installer execution, impossible in `--no-bundle` mode).
- **D2:** No `publish` job, no signing, no version-bump beyond existing stamp —
  all need secrets / release-policy decisions owned by the orchestrator.
- **D3:** No Fedora runner, no local AppImage build (root/FUSE + still
  un-install-testable); rpm-on-Fedora stays explicitly untested (§3 table).

## 5. Push auth / remote evidence

- `git ls-remote origin HEAD` → OK (read auth; `bf5dfd4…`).
- `git push --dry-run origin closure/opencode-packaging` → exit 0,
  `* [new branch] closure/opencode-packaging -> closure/opencode-packaging`
  (write auth present; dry-run creates no refs, triggers no CI).
- **Pushed anything? No — nothing pushed** (per lane constraint; orchestrator
  decides push/merge). No remote run state fetched; all ✅ above are
  config-coverage claims, not observed-green claims.

## 6. Known gaps (ranked)

1. No `publish` job — release artifacts die with the workflow run (30d
   retention); needs `contents: write` + tag-policy decision (survey §5.1).
2. No signing/notarization on any OS (secret-gated; Electron `release.yml`
   is the reference implementation to mirror).
3. No installer install-and-launch anywhere (N1–N4); archive inspection
   (MANIFEST.md) is the current ceiling.
4. No Tauri E2E / packaged launch check (N6); only Electron has E2E.
5. Fedora/RHEL: no runner, rpm cross-distro untested (N4).
6. `shellcheck` re-run pending where installed (§1).
7. `desktop-tauri.yml` still has no backend staging (by design — release-only);
   any future PR-check smoke must be scoped deliberately, not bolted on.
