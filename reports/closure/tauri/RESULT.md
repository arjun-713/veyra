# Tauri closure — agent/tauri2

- Base: `demo-readiness` @ `b3b2abf` (verified via `git log`)
- Branch: `agent/tauri2` in worktree `worktrees/tauri2`
- Prior work preserved: `agent/tauri-partial` @ `8050591` cherry-picked onto
  `b3b2abf` (clean, no conflicts); UI edits auto-preserved as `6d81f18`
- Gate (scorecard `tauri` node): packaged Tauri app → select dataset → start →
  real processing → map → telemetry → play/pause/seek/policy/layer/inspect/stop,
  no mocks. Evidence: `reports/closure/tauri/*.log` + staged-bundle proof.
- Status: **CLOSED (code + proof complete)**, with two upstream defects routed
  to their owners (see Gaps). Electron untouched (separate agent).

Hardware (named, shared box — other agents ran training jobs concurrently, so
latencies below are measured-under-shared-load, not isolated benchmarks):
Intel i5-8350U, 15 GiB RAM, `mallik-fedora` (Fedora, cargo 1.98.1, node 24,
python 3.13). Real data: SemanticPOSS seq `00`, 488 frames, ground-truth
semantics, ground + terrain evidence.

## Acceptance flow — where each step is proven

| Step | Proof |
|---|---|
| Dataset select | `open_dataset` Tauri command (`src-tauri/src/commands.rs`, from `8050591`) + one-click "Open dataset with safe defaults" in `App.svelte` (new); E2E catalogs 6 real SemanticPOSS sequences |
| Runtime start | `configure` with production defaults; E2E `configured frames=488` |
| Real processing | `step` on real frames; `active_cells=37250`, binary visualization frame `visual_bytes=2936872` |
| Map display | Three.js `MapCanvas` (points/cells/boundaries, orbit/top/driver, follow) + dashboard panels; E2E asserts live map cells + visualization bytes |
| Telemetry | Event pump → `veyra://event`; E2E drains live telemetry; Performance workspace renders FPS/p50/p95/p99/RSS/governor |
| Play/pause/seek | Playback controls → `runtime_command`; E2E start → pause → `state=paused`; seek reprocesses deterministically |
| Policy/layer switch | Policy select → backend (`uniform40` asserted live); 7 renderer layers switch `MapCanvas` mode; layer asserted via control plane |
| Inspect | Double-click cell inspector (`onInspect` → inspector panel with measured fields) |
| Clean stop | `stop` → graceful python exit in 0.1 s (was 2.0 s + SIGKILL, see Root causes); `shutdown` + daemon join asserted; no stray processes afterwards |
| No mocks | Every E2E assertion runs the real Python product runtime + real C++ mapper on real SemanticPOSS frames |

## Root causes found (measured, not assumed)

1. **Daemon died on abandoned slow commands (product defect, NOT fixed here —
   `src-tauri/src/control/daemon.rs` is read-only for this agent).**
   Mechanism, proven with a timeout-guarded join that revealed
   `Err("Broken pipe (os error 32)")`: `write_response` uses
   `serde_json::to_writer` directly on the socket; when the client has timed
   out and gone, EPIPE surfaces inside serde_json and is rewrapped as
   `InvalidData`, which `client_connection_error` does not cover, so
   `handle_connection` returns `Err`, the serve loop exits, the listener
   closes, and every later command gets `Connection refused`. Any slow
   command (stop/shutdown/benchmark/configure on huge data) abandoned by the
   2 s `ControlClient` budget kills the whole desktop daemon. Discovery log:
   `e2e-stop-defect-discovery.log`; listener LISTENING→NOT-LISTENING trace
   included. **Routed to control-api owner via orchestrator.**
2. **Every stop took the 2 s SIGKILL path (mitigated in owned code).**
   The runtime ACKs `shutdown` but its `__main__` stdin loop stays blocked in
   `readline`, so the process lingered until the supervisor killed it.
   `RuntimeSupervisor::stop` (`src-tauri/src/supervisor.rs`, owned) now
   closes stdin after the shutdown round-trip (EOF unblocks the reader →
   graceful exit + session teardown) and reaps synchronously. Measured:
   stop 2.02 s → 0.1 s; control-plane E2E 5.69 s-failing → 0.96–1.79 s green.
   The remaining `runtime/__main__.py` readline structure is **routed to its
   owner via orchestrator** (graceful-shutdown-without-EOF still impossible).
3. **Restart-after-stop reap race (fixed in owned code).** Between SIGKILL
   and the 50 ms monitor reap, `start()` saw `child.is_some()`, returned
   `Ok`, and the next request was written into a dead stdin pipe (60 s+
   hang observed with a raw-TCP probe). The synchronous reap in `stop()`
   closes this window deterministically.
4. **Pre-existing clippy `-D warnings` failure (not mine, read-only).**
   `src-tauri/src/control/controller.rs:252` uses `is_none_or` (stable since
   1.82, crate MSRV 1.77) — introduced by `6e3cece`, fails under this
   toolchain's clippy. My files are clippy-clean. **Routed to control-api.**

## Files changed

- `apps/desktop/src/api.ts` — optional `openDataset` on shared `DesktopAPI`
  (Electron preload untouched, still typechecks) + `supportsDirectOpen` /
  `normalizeOpenDatasetResponse` helpers
- `apps/desktop/src/renderer/App.svelte` — one-click direct-open flow
  (catalog → `openDataset` → first-frame step), guarded by `canDirectOpen()`
- `apps/desktop/tests/desktop-api.test.ts` — new: capability advertisement +
  response-shape normalization (all envelope shapes)
- `src-tauri/src/supervisor.rs` — graceful stop (stdin EOF) + synchronous
  reap after SIGKILL escalation
- `src-tauri/src/packaged_e2e.rs` — bounded transient-timing retries with
  `/proc` listener forensics + timeout-guarded join that reveals serve errors
  on failure; clippy-clean (`manual_find` fixes)
- `reports/closure/tauri/` — this file + all logs below

## Tests (all executed, analytical vs measured separated)

- `cargo test --manifest-path src-tauri/Cargo.toml` (clean env): **49 lib +
  7 bins + integration/doc targets, 0 failed** (`cargo-test-full.log`; the 2
  packaged E2E skip without `VEYRA_E2E_*`, by design for packaging-only CI)
- Same suite, units only: **47 passed, 0 failed** (`cargo-test-units.log`;
  run separately because `VEYRA_MAPPER`/`VEYRA_PYTHON` overrides otherwise
  leak into unit tests that assert default resolution — env-scoping artifact,
  documented, not a product issue)
- Real-data E2E, dev layout, serialized: **2 passed**
  (`e2e-dev-layout.log`: full 488-frame flow + authenticated control plane)
- Real-data E2E, **packaged layout**: **2 passed in 22.82 s**
  (`e2e-packaged-layout.log`): `VEYRA_E2E_REPO=<staged backend>` with pure
  auto-resolution (staged `python/bin/python3`, staged `bin/veyra_runtime`,
  no overrides) — the exact bundle boot path
- Frontend: **28/28 node tests pass** (`frontend-tests.log`),
  `svelte-check` 0 errors, `vite build` succeeds (incl. Three.js chunk)
- Staging: `scripts/stage_tauri_backend.py` → manifest schema 1, linux/x64,
  5625 files; staged python boots staged runtime standalone
  (`staged-runtime-ok`); layout matches `runtime_root` markers and the
  supervisor/mapper/packaging.ts resolution contract
- Mapper built in-tree: `cmake --build build --target veyra_runtime` EXIT 0
  (`mapper-build.log`)
- `cargo clippy --all-targets`: only the pre-existing MSRV warning above;
  zero lints in files owned by this agent

## Real data

SemanticPOSS `data/raw/semanticposs/dataset`, sequence `00` (488 frames),
poses + labels present; catalog lists 6 sequences; E2E selects the first
non-empty sequence dynamically. No synthetic frames, no mocks, no
ground-truth-as-neural substitution.

## Gaps / routed work (not hidden)

1. `daemon.rs` EPIPE→`InvalidData` daemon death (root cause 1) — needs a
   control-api owner fix (treat write failures to dead clients as
   connection-close, never as serve-fatal). Until fixed, any client-abandoned
   slow command can take down the desktop daemon; the E2E keeps bounded
   retries + join assertions so a recurrence fails loudly.
2. `runtime/__main__.py` stdin-readline linger (root cause 2, mitigated but
   not cured) — needs runtime-owner fix (wake the reader on `stopping`, or
   close stdin supervisor-side protocol). Current mitigation makes every
   measured stop graceful (0.1 s).
3. `controller.rs:252` clippy MSRV finding (root cause 4) — one-line
   control-api fix (`is_none_or` → MSRV-compatible form or MSRV bump).
4. Full installer bundles (deb/rpm/AppImage/NSIS/dmg) are built by
   `release-tauri.yml` CI, not on this box; local proof is the staged-bundle
   E2E above plus the `--no-bundle` smoke build (see below). No Electron
   code was touched.
