# Historical Linux package inspection

This combines the 2026-09-18 rebuild and 2026-09-20 archive inspection.
Host: Fedora, Linux 7.2.5-200.fc44.x86_64, unprivileged user. It is evidence
for the exact packages below, not acceptance of a current release. Current
build/install instructions are in the [desktop guide](../../../apps/desktop/README.md#packaging).

## Provenance

The rebuild used `demo-readiness` at `7d3b116`, branch `agent/bundle-rebuild`.
The inspection used `closure/opencode-packaging` from
`closure/opencode-product` at `cf9e71d`. Between those revisions, only
`apps/desktop/src/renderer/App.svelte` changed among the inspected backend,
mapper, Rust and packaging inputs. Packages therefore match that backend,
while their frontend predates the workspace fix. No rebuild ran in the
inspection lane; manifest/checksum commands used copies in
`/tmp/opencode/veyra-bundles/`.

## Build and launch record

On Sep 18, `cmake --build build --config Release -j4` was a no-op with apps
enabled. Mapper `build/apps/runtime/veyra_runtime` was 313,472 bytes, SHA-256
`1bf465d1…82075b299eb`. Staging used `scripts/stage_tauri_backend.py` with
`--mapper`, `--python-runtime .venv`, `--platform linux` and `--arch x64`.
The venv used Python 3.13.15. Staged manifest schema 1 listed 5,638 files,
with SHA-256 `0c6377ba1d6894d4c3127e1b79706d96f833aeeac72ff3376c0c9a6cf4e63b8d`.

`npm run tauri:build -- --bundles deb,rpm` rebuilt frontend in 5.98 s and Rust
release in 2m51s; deb/rpm were emitted after staging. AppImage was not built.
`cargo test --release` passed 63 tests (52 library, 9 CLI, 2 control); dataset
E2E self-skips without assets. No new C++ run was claimed for the no-op mapper build.

Extracted-package checks found no missing shared libraries. CLI/control sidecars
printed usage. A display-isolated GUI launch exited 101 at GTK initialization,
which only establishes loading up to an absent display, not a successful UI.
No Veyra process remained. No installed or live-window acceptance was claimed.

## Package hashes

Both packages are version 0.1.0, Linux x64. Hashes were produced by
`scripts/release_manifest.py`, then `scripts/release_checksums.py` so
`SHA256SUMS` also covers the manifest.

| Package | Bytes | SHA-256 |
| --- | ---: | --- |
| `Veyra_0.1.0_amd64.deb` | 91606314 | `9913e3fca7d35e7e1fc4e4da4cb1e10d00861662a7dc31737118f7cf9b325b32` |
| `Veyra-0.1.0-1.x86_64.rpm` | 91937474 | `614a20c9104d1bf3e841ac207563e72a9ce64b99264404b5fee894d48fbcbf62` |

## Archive verification

| Check | Recorded result |
| --- | --- |
| deb structure | `debian-binary`, control/data tarballs, control and md5sums present. |
| Launchers | `usr/bin/veyra`, `veyra-cli`, `veyra-control` present. |
| Backend | Manifest and `runtime/__main__.py` present; no bare `.gitkeep`. |
| Mapper identity | deb/rpm mapper hashes match the built mapper above. |
| Manifest identity | Same SHA-256 in staged tree, deb and extracted rpm. |
| Payload entries | deb backend 6,179 including directories; rpm payload 5,649, of which backend 5,639 = 5,638 files plus root. |
| rpm metadata | Unsigned `veyra-0.1.0-1.x86_64`, built Sep 18. |
| Checksums | 3/3 pass (deb, rpm, release manifest); manifest entries independently rehashed. |

## Reproduce archive checks

Use copies of those exact historical bundles; current builds will have different
hashes. The original manifest/checksum files were temporary outputs, so their
location is a reproduction recipe, not a committed artifact.

```bash
mkdir -p /tmp/opencode/veyra-bundles
cp <historical-deb> <historical-rpm> /tmp/opencode/veyra-bundles/
python3 scripts/release_manifest.py /tmp/opencode/veyra-bundles \
  --output /tmp/opencode/veyra-bundles/release-manifest.json \
  --version 0.1.0 --target linux-x64
python3 scripts/release_checksums.py /tmp/opencode/veyra-bundles
(cd /tmp/opencode/veyra-bundles && sha256sum -c SHA256SUMS)
```

## Limits

No `dpkg`/`rpm` installation was performed. AppImage, Windows NSIS and macOS
DMGs were not inspected or install-launched in this experiment. A valid Linux
backend payload does not prove another installer wrapper or OS works. The
Ubuntu-built rpm was not installed on Fedora/RHEL. Signing/notarization and
native GUI acceptance remain separate from archive/checksum verification.
