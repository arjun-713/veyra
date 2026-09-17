# Control daemon EPIPE fix — agent/control-api

- Branch: `agent/control-api` (worktree `worktrees/control-api`, base `8bb38fb` verified via `git log`)
- Owner file: `src-tauri/src/control/daemon.rs` (only file changed, plus this report)
- Routed from: tauri2 E2E closure, `worktrees/tauri2/reports/closure/tauri/RESULT.md` root cause 1
  + `e2e-stop-defect-discovery.log` (`Err("Broken pipe (os error 32)")` via timeout-guarded join)

Hardware (named, shared box): Intel i5-8350U, 15 GiB RAM, `mallik-fedora`
(Fedora, cargo 1.98.1). All results below are measured on this box.

## Root cause (confirmed in code, reproduced in test)

`write_response` used `serde_json::to_writer` directly on the `TcpStream`.
When the client had timed out (2 s `ControlClient` budget) and gone away,
EPIPE surfaced *inside* serde_json and was rewrapped as
`io::ErrorKind::InvalidData`. `client_connection_error` only covers
`TimedOut | WouldBlock | BrokenPipe | ConnectionAborted | ConnectionReset |
NotConnected`, so the write error fell through to `return Err(error)` in
`handle_connection`, the `serve_listener` loop exited via `?`, the listener
closed, and every later command got `Connection refused`. Any slow command
abandoned by the client budget (stop/shutdown/benchmark/configure on huge
data) killed the whole desktop daemon. A second, identical hole existed on
the `Frame::TooLarge` path, which used `write_response(...)?` with no
client-disconnect classification at all.

## Fix (`src-tauri/src/control/daemon.rs`, no interface changes)

1. `write_response` now serializes to a `Vec` first (`serde_json::to_vec`),
   then `write_all` + `flush` (new generic helper `write_response_to`).
   A dead peer now surfaces as its native transport error (`BrokenPipe` /
   `ConnectionReset` / `TimedOut`), which `client_connection_error` already
   covers — no serde-internals downcasting, no new deps. Per-response
   allocation is a few KB at ~1 connection per request; negligible.
2. Both write sites (`Frame::TooLarge` reply and normal replies) map
   client-connection errors to "log (`eprintln!`) + close that connection
   (`Ok(false)`) + keep serving". Genuine internal errors (e.g. a
   serialization bug, now the only source of `InvalidData`) still propagate
   as `Err` and fail loudly, preserving the debuggability that caught this
   defect.
3. `stop`-keeps-daemon-alive contract untouched (`shutdown: false` on the
   `stop` path; existing `runtime_stop_keeps_the_control_daemon_available`
   test still green).

## Regression tests (both fail pre-fix, pass post-fix)

- `write_failure_to_a_dead_client_is_a_disconnect_not_a_serve_failure`:
  a `Write` impl that always returns `BrokenPipe` through the real
  `write_response_to` path; asserts kind stays `BrokenPipe` (was
  `InvalidData`) and `client_connection_error` holds. Deterministic unit
  guard on the exact rewrapping mechanism.
- `abandoned_command_keeps_daemon_alive_for_the_next_client`: live
  `serve_listener` on `127.0.0.1:0`; client 1 sends `stop` then drops the
  socket unread (2 s-budget-abandonment analogue); client 2 must still get
  `ok:true` `diagnostics` (no `Connection refused`); then `stop` → still
  alive → `shutdown` → clean thread join. (`diagnostics` is the liveness
  probe because `status` legitimately returns `ok:false` without an open
  dataset; `stop` re-verifies the keep-alive contract.)
- Pre-fix verification: with the old `to_writer` impl temporarily restored,
  both new tests fail (2 failed); with the fix, all pass.

## Tests run (measured)

- `cargo test --manifest-path src-tauri/Cargo.toml --lib control::`:
  **30 passed, 0 failed** (includes the 2 new tests + all pre-existing
  daemon/client/controller/state/desktop_control tests).
- `cargo test --manifest-path src-tauri/Cargo.toml --bin veyra-cli`:
  **8 passed, 0 failed** — CLI `--json` fix from `8bb38fb`
  (`trailing_json_flag_is_stripped_from_every_command`) still green.
- `cargo fmt -- --check`: `daemon.rs` clean (remaining diffs in the tree,
  e.g. `veyra-cli.rs`, are pre-existing and untouched).
- Scope kept to the mission: control module + CLI bin only; full
  `cargo test` (which needs `VEYRA_E2E_*` packaged fixtures) not run here.

## Gaps / not done

1. `controller.rs:252` `is_none_or` clippy MSRV finding (tauri2 RESULT.md
   root cause 4, same owned dir) deliberately left untouched — outside this
   mission's scope; one-line fix or MSRV bump still open for control-api.
2. `runtime/__main__.py` stdin-readline linger (tauri2 root cause 2) is a
   runtime-owner issue; the supervisor-side EOF mitigation already lives in
   tauri2-owned `supervisor.rs`.
3. No load/stress or real-hardware timing claims are made here; latencies
   are unit-test scale only. Re-running the tauri2 packaged E2E
   (`packaged_control_plane_serves_authenticated_fast_commands`, the test
   that originally exposed this) is the recommended downstream confirmation
   and belongs to the tauri2 owner.
