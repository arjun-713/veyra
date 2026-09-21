# Phase B packaged-runtime evidence

This evidence was generated on 2026-09-20 from the Phase B worktree after
staging the backend with `scripts/stage_tauri_backend.py`.

## Staged bundle

- Platform/architecture: Linux x64
- Product/version: `veyra` / `0.1.0`
- Location: `src-tauri/resources/backend`
- Manifest: schema 1 with product, version, platform, architecture, byte
  sizes, and SHA-256 entries
- Files: 5,638
- Staged size: approximately 284 MB
- External assets: SemanticPOSS data and model weights are not packaged

## Real packaged-layout session

Command:

```bash
VEYRA_E2E_REPO="$PWD/src-tauri/resources/backend" \
VEYRA_E2E_DATASET_ROOT=/home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset \
VEYRA_E2E_PYTHON="$PWD/src-tauri/resources/backend/python/bin/python3" \
cargo test --manifest-path src-tauri/Cargo.toml --lib \
  packaged_e2e::packaged_tauri_session_runs_a_real_semanticposs_flow -- --nocapture
```

Result: PASS.

- Dataset: real SemanticPOSS sequence `00`, 488 frames
- Catalog and configure: PASS
- Real step: PASS; 37,250 active map cells and 2,936,872 visualization bytes
- Telemetry: PASS; live map cells, Ground Truth provider, point count, health,
  and fresh-telemetry assertions
- Seek: PASS
- Policy switch to Uniform40: PASS
- Layer switch to LOD: PASS
- Playback speed: PASS (2x)
- Governor control: PASS (automatic)
- Session validation: PASS
- Play/pause: PASS
- Clean stop and child reaping: PASS
- Restart and reprocess after stop: PASS
- Observed test duration: 25.73 s
- Process check after the run: no staged `veyra_runtime` or runtime child
  remained

This is the packaged backend/control-plane proof. The Rust test drives the same
Tauri control service and staged resource resolution used by the desktop shell;
the visual WebView itself remains a separate renderer test surface.

## Native package inspection

`npm run tauri:build -- --bundles deb` produced
`src-tauri/target/release/bundle/deb/Veyra_0.1.0_amd64.deb` (about 90 MB).
The package was extracted and independently inspected; it contains the
application binary plus:

```text
usr/lib/Veyra/resources/backend/manifest.json
usr/lib/Veyra/resources/backend/bin/veyra_runtime
usr/lib/Veyra/resources/backend/python/bin/python3
usr/lib/Veyra/resources/backend/runtime/__main__.py
```

The extracted package binary launched on the current X11 display and exposed a
Veyra window. It was then terminated cleanly by the smoke harness. The
headless WebView emitted only host Mesa/dconf warnings; no application startup
error was reported.
