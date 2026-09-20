# Veyra desktop bundles — artifact manifest + verify log (closure packaging lane)

Branch: `closure/opencode-packaging` (from `closure/opencode-product @ cf9e71d`).
Date: 2026-09-20. Host: Fedora (Linux-7.2.5-200.fc44.x86_64), uid=1000, no root.
Scope: **inspection + provenance only — no rebuilds.** deb/rpm artifacts are the
Sep 18 rebuild from the main checkout (same machine); the worktree holds only
evidence + workflow hardening. No cmake/cargo/npm invocations in this lane.

## 1. Provenance

- Bundles built in main checkout at `7d3b116` (see `platform/REBUILD.md`);
  main checkout is now at `cf9e71d` (same commit as this worktree's base).
- `git diff --name-only 7d3b116..cf9e71d` filtered to
  `runtime/ src/ apps/ scripts/package_backend* scripts/stage_tauri_backend* src-tauri/src benchmarks/ perception/`:
  **only `apps/desktop/src/renderer/App.svelte` changed** (frontend
  statically-always-true workspace fix, no packaging impact). Mapper binary,
  Python runtime, staging scripts, and Rust side are byte-identical inputs —
  the Sep 18 bundles remain representative of the backend/mapper payload at
  `cf9e71d`. Frontend content differs by that one Svelte fix; CI release legs
  rebuild the frontend from source, so this caveat is local-only.
- Inspection was read-only against the main checkout; manifest/checksum
  provenance was produced against **copies** in `/tmp/opencode/veyra-bundles/`
  (never wrote into either checkout's `src-tauri/target/`).

## 2. Artifact table (version 0.1.0, platform linux, arch x64)

Produced by `scripts/release_manifest.py … --version 0.1.0 --target linux-x64`
then `scripts/release_checksums.py` (canonical order: manifest first,
SHA256SUMS covers the manifest). Full JSON: `/tmp/opencode/veyra-bundles/`
(`release-manifest.json`, `SHA256SUMS`); rerun deterministically from the
copies with the two commands in §4.

| Version | Platform | Arch | Filename | Size (B) | SHA-256 |
|---|---|---|---|---|---|
| 0.1.0 | linux | x64 | `Veyra_0.1.0_amd64.deb` | 91606314 | `9913e3fca7d35e7e1fc4e4da4cb1e10d00861662a7dc31737118f7cf9b325b32` |
| 0.1.0 | linux | x64 | `Veyra-0.1.0-1.x86_64.rpm` | 91937474 | `614a20c9104d1bf3e841ac207563e72a9ce64b99264404b5fee894d48fbcbf62` |

## 3. Verify log (all PASS)

| Check | Method | Result |
|---|---|---|
| deb member layout | `ar x` → `debian-binary` + `control.tar.gz` + `data.tar.gz` | PASS |
| deb control | `tar tzf control.tar.gz` → `control`, `md5sums` | PASS |
| deb launchers | `usr/bin/veyra`, `veyra-cli`, `veyra-control` in `data.tar.gz` | PASS, all three |
| deb backend manifest | `…/resources/backend/manifest.json` present, `schema_version=1`, `platform=linux`, `arch=x64`, 5638 files | PASS, sha256 `0c6377ba…9cf4e63b8d` == REBUILD.md staged-manifest hash |
| deb mapper identity | `…/backend/bin/veyra_runtime` sha256 `1bf465d1…82075b299eb` == `build/apps/runtime/veyra_runtime` | PASS (exact match) |
| deb backend entry count | `tar tzf data.tar.gz \| grep -c resources/backend/` | 6179 == REBUILD.md §2 |
| deb gitkeep | `grep -c backend/.gitkeep` → 0 | PASS (absent, staged payload only) |
| deb runtime entry | `…/backend/runtime/__main__.py` present | PASS |
| rpm payload | `rpm -qlp` → 5649 entries; `/usr/bin/veyra{,-cli,-control}` + `/usr/lib/Veyra` tree | PASS |
| rpm backend slice | entries under `resources/backend/` | 5639 (= 5638 manifest files + dir) == REBUILD.md §2 |
| rpm manifest identity | `rpm2cpio \| cpio -idm` (unprivileged) → manifest sha256 | `0c6377ba…9cf4e63b8d` == deb-embedded manifest (deb↔rpm match) |
| rpm mapper identity | extracted `bin/veyra_runtime` sha256 | `1bf465d1…82075b299eb` == built mapper (deb↔rpm↔build match) |
| rpm metadata | `rpm -qip` → `veyra-0.1.0-1.x86_64`, unsigned (`Signature: (none)`), built Sep 18 | recorded (unsigned by design, no secrets in lane) |
| checksum self-verify | `sha256sum -c SHA256SUMS` on the copies dir | 3/3 OK (deb, rpm, release-manifest.json) |
| manifest self-consistency | independent python re-hash vs `release-manifest.json` entries | all MATCH; `schema_version=1`, `version=0.1.0`, `target=linux-x64` |

## 4. Reproduction (no build required)

```bash
mkdir -p /tmp/opencode/veyra-bundles
cp <main-checkout>/src-tauri/target/release/bundle/deb/Veyra_0.1.0_amd64.deb \
   <main-checkout>/src-tauri/target/release/bundle/rpm/Veyra-0.1.0-1.x86_64.rpm \
   /tmp/opencode/veyra-bundles/
python3 scripts/release_manifest.py /tmp/opencode/veyra-bundles \
  --output /tmp/opencode/veyra-bundles/release-manifest.json \
  --version 0.1.0 --target linux-x64
python3 scripts/release_checksums.py /tmp/opencode/veyra-bundles
(cd /tmp/opencode/veyra-bundles && sha256sum -c SHA256SUMS)
```

## 5. AppImage feasibility note

- **Declared? Yes, in both places that matter:** `src-tauri/tauri.conf.json`
  `"targets": ["deb", "rpm", "appimage", "nsis", "dmg"]`, and the CI Linux leg
  builds `--bundles "deb,rpm,appimage"` (`release-tauri.yml` matrix). No repo
  change is needed to *declare* it.
- **Built locally? No — deliberately.** REBUILD.md D3: local rebuild used
  `--bundles "deb,rpm"` only. AppImage stays a CI-side property: it needs the
  `ubuntu-24.04` runner toolchain (plus FUSE/libfuse2 at *test* time, which
  this Fedora host cannot provide without root), and no AppImage has ever been
  install-launched anywhere in this repo.
- **Why deb/rpm suffice for local evidence:** both are full installer payloads
  embedding the identical staged backend (proven byte-identical above:
  manifest `0c6377ba…`, mapper `1bf465d1…` in both). The bundler-specific
  wrapper (AppImage runtime squashfs) adds no new backend content; what is
  unproven about AppImage is the *wrapper* (mount + launch), which only a
  native Ubuntu runner with FUSE can exercise anyway.
- **Gap recorded:** no AppImage artifact exists locally; AppImage mount/launch
  is untested on every OS (see CI-STATUS.md native-runner checklist). Do NOT
  add a local AppImage build to this lane — it would need root/FUSE and would
  still not be install-tested. The correct fix is the CI bundle-assertion step
  (added this lane: fails the Linux leg if any of deb/rpm/appimage is missing)
  plus a future native launch check.

## 6. Known limits of this evidence

1. Bundles predate the `App.svelte` workspace fix by frontend content only
   (§1); backend/mapper payload is current.
2. No install (dpkg/rpm -i) was performed — no root on this host; payload
   verified by archive inspection only.
3. Windows (`nsis`) and macOS (`dmg`) bundles do not exist anywhere in-repo;
   only native CI runners can produce them (CI-STATUS.md §3).
4. rpm is Ubuntu-built, never install-tested on Fedora/RHEL (no Fedora runner
   anywhere; dnf-install test remains open).
