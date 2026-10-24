# Historical Tauri runtime acceptance

Two Linux experiments are recorded here: the `agent/tauri2` work based on
`demo-readiness` at `b3b2abf`, and Phase B staged-package verification on
2026-09-20. Prior code was preserved from `8050591` and UI state from
`6d81f18`. These records establish their stated source/bundle behavior;
they are not current-release or cross-platform acceptance.

Host: Intel i5-8350U, 15 GiB RAM, Fedora, Cargo 1.98.1, Node 24 and Python 3.13,
shared with other jobs. Input: SemanticPOSS seq00, 488 available frames, GT
semantics with ground/terrain. GT was not presented as neural inference.

## Initial control-plane experiment

The real product runtime and mapper were driven through the same Tauri control
service used by the UI. Code inspection and binary visualization delivery were
not treated as a full pixel-rendering proof.

| Capability | Recorded evidence |
| --- | --- |
| Dataset/configure | `open_dataset` catalogued six sequences and configured 488 frames. |
| Real processing | First step: 37250 active cells, 2936872 visualization bytes. |
| Telemetry | Native event relay delivered live backend metrics. |
| Playback | Start, pause, seek, 2× speed and policy/layer controls reached the backend. |
| Policy/layer | Uniform40 selected; seven frontend layers had renderer wiring. |
| Inspection | `onInspect` wired the cell panel; this is code evidence, not standalone GUI acceptance. |
| Stop/restart | Closing stdin after shutdown enabled graceful exit/reap and removed the restart race. |

Logs in this directory preserve the original results:

- `cargo-test-full.log`: 49 library + 7 bin tests, zero failures; packaged tests
  skip without `VEYRA_E2E_*` fixtures.
- `cargo-test-units.log`: 47 units passed; environment overrides were scoped
  separately because resolution tests inspect defaults.
- `e2e-dev-layout.log`: 2 real-data tests passed.
- `e2e-packaged-layout.log`: 2 real-data tests passed in 22.82 s, using staged
  Python/mapper auto-resolution without development overrides.
- `frontend-tests.log`: 28 frontend tests passed; Svelte check/build succeeded.
- `mapper-build.log`:native mapper build exited 0.
- `tauri-build-no-bundle.log`:production no-bundle build passed in 10m32s.
- `e2e-stop-defect-discovery.log`:captures the initial control-daemon failure.

The first staged Linux/x64 manifest had 5625 files. This is distinct from the
later Phase B bundle below.

## Failure analysis recorded at that revision

1. A timed-out/disconnected client caused `serde_json::to_writer(TcpStream)`
   to wrap BrokenPipe as InvalidData and terminate the daemon's serve loop.
   It was routed to the control owner; the discovery log preserves the fault.
2. Python acknowledged shutdown but remained in stdin `readline`. Closing
   stdin in the supervisor reduced measured stop from 2.02 s to 0.1 s; synchronous
   child reaping removed the immediate-restart dead-pipe race.
3. A control-controller `is_none_or` call exceeded the then-declared Rust 1.77
   MSRV and was routed separately. This report does not assert it is still open.

Those findings describe the historical run. Current behavior must be checked
against the current source/tests, rather than inferred from old owner notes.

## Phase B packaged runtime

Date: 2026-09-20, Linux x64, product `veyra` version 0.1.0. Staging with
`scripts/stage_tauri_backend.py` produced a schema-1 manifest containing product,
version, platform, architecture, file sizes and SHA-256 values. The staged
backend listed 5638 files and about 284 MB; datasets/model weights stayed external.
The original Phase B note did not record a source SHA.

```bash
VEYRA_E2E_REPO="$PWD/src-tauri/resources/backend" \
VEYRA_E2E_DATASET_ROOT="$PWD/data/raw/semanticposs/dataset" \
VEYRA_E2E_PYTHON="$PWD/src-tauri/resources/backend/python/bin/python3" \
cargo test --manifest-path src-tauri/Cargo.toml --lib \
  packaged_e2e::packaged_tauri_session_runs_a_real_semanticposs_flow -- --nocapture
```

The test passed in 25.73 s. It catalogued/configured real seq00, stepped with
37250 cells and 2936872 visual bytes, checked GT-labelled fresh telemetry,
sought, selected Uniform40 and the LOD layer, set 2× speed and automatic governor,
validated the session, played/paused, stopped/reaped, then restarted and
reprocessed. No staged mapper/runtime child remained afterward. This verifies
packaged backend/control behavior; the WebView is a separate renderer surface.

A native deb build produced `Veyra_0.1.0_amd64.deb` (about 90 MB). Extraction
showed the app, backend manifest, `bin/veyra_runtime`, `python/bin/python3`, and
`runtime/__main__.py` under `usr/lib/Veyra/resources/backend/`. The extracted
app launched a Veyra window on the experiment's X11 display and was terminated
cleanly; the harness reported only host Mesa/dconf warnings. That observation
has no accompanying committed screenshot and does not prove interactive
controls or another platform.

## Scope and reproduction

Repeat the commands against the intended staged resources and genuine local
data. The named tests exercise real backend paths; frontend layer wiring,
control-plane assertions and visible pixel acceptance are separate evidence.
All timings above are historical shared-host observations, not benchmark tails.

Current [desktop instructions](../../../apps/desktop/README.md) own build and
operator flow. The [separate package inspection](../platform/MANIFEST.md)
records exact Linux installer hashes. Windows/macOS, installer launch,
signing/notarization and a current end-to-end demo need their own acceptance.
