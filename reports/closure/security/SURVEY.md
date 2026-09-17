# Security Slice 1 — Survey (Tauri + control plane + MCP + CLI)

- Worktree: `worktrees/security`, branch `agent/security`, base `demo-readiness` @ `1ad1388`.
- Scope: Tauri capabilities + filesystem scopes, CSP, sidecar invocation,
  path traversal (dataset roots, config paths), command injection
  (policy/layer/seek args), MCP input validation, CLI validation,
  secrets in logs/temp files.
- Constraint respected: `src-tauri/src/control/*` protocol untouched
  (owned by control-api); only additive, non-protocol fixes there
  (none needed — daemon allowlists/bounds already solid).

## Fixed in this slice (with regression tests)

1. **MCP input validation was daemon-or-nothing** (`mcp/server.py`).
   `set_policy`/`set_layer` accepted arbitrary strings, `seek.index` had no
   upper bound, `run_benchmark.count` had no bounds, and no string length
   caps existed — every malformed value became a daemon round-trip.
   Fix: per-schema `maxLength`/`minimum`/`maximum` enforced generically in
   `_validate_arguments`, plus fail-fast allowlists `SUPPORTED_POLICIES` /
   `SUPPORTED_LAYERS` mirroring the daemon. Daemon remains authoritative.
   Tests: `test_oversized_root_is_rejected_before_daemon_contact`,
   `test_unknown_policy_and_layer_are_rejected_before_daemon_contact`,
   `test_out_of_range_seek_and_benchmark_counts_are_rejected`
   (all assert zero daemon requests).
2. **CLI config file read was unbounded** (`src-tauri/src/bin/veyra-cli.rs`
   `read_json`). `fs::read_to_string` on an attacker-named path could OOM
   the CLI. Fix: 1 MiB size gate via metadata before reading.
   Test: `oversized_config_file_is_rejected_before_parsing`.
3. **Tauri `choose_dataset` accepted any dataset string** (`src-tauri/src/commands.rs`).
   CLI/MCP both allowlist (`rellis3d|semanticposs|semantickitti|generic`);
   the renderer path did not. Fix: `choose_dataset_allowlist_check` before
   filesystem access (fail-fast; daemon still validates).
   Test: `dataset_format_is_allowlisted_before_filesystem_access`.
4. **Standalone daemon read its secret without permission checks**
   (`src-tauri/src/bin/veyra-control.rs` `read_secret`). The client
   (`control/client.rs`) and host (`control_host/mod.rs`) both enforce
   0600-only token files; the daemon side did not (size cap only).
   Fix: regular-file + unix `0o077`-denied permission check, matching client.
   Tests: `control_secret_is_rejected_without_a_bounded_token`,
   `control_secret_rejects_group_or_world_readable_token_files`.

## Reported (not fixed — severity + fix plan)

- **R1 Medium — Tauri fs capability has no explicit `scope`.**
  `capabilities/default.json` grants `fs:allow-read-text-file`,
  `fs:allow-write-text-file`, `fs:allow-write-file` with no `scope` map, so
  renderer file access is not confined to dialog-chosen paths
  (the `lib.rs` test only asserts absence of broad `$HOME/**`-style scopes,
  which does not prove confinement). Mitigations in place: all reads/writes
  go through dialog-chosen paths (`tauri-api.ts`), 16 MiB caps, and
  `map.executable` is stripped renderer-side AND overwritten server-side
  (`inject_mapper`). Fix plan: add an explicit `scope` (e.g. `$APPCONFIG`,
  user-selected dirs) or move file IO behind Tauri commands; extend the
  `lib.rs` test to assert the scope block exists.
- **R2 Low — CSP keeps `script-src 'unsafe-inline'`** (`tauri.conf.json:24`).
  The `index.html` meta CSP is stricter (`script-src 'self'`). Fix plan:
  drop `'unsafe-inline'` from `script-src` in `tauri.conf.json`, verify the
  Vite production build renders; keep `'unsafe-inline'` for `style-src` only.
- **R3 Low — Daemon string bound is one-size-fits-all (control-api owned).**
  `daemon.rs` `required_string` caps dataset/root/sequence at 64 bytes, so
  legitimate deep dataset roots are rejected (availability/UX, not
  exploitable). Fix plan (control-api): per-field bounds (e.g. root 4096)
  plus server-side canonicalize + `is_dir` check in
  `RuntimeController::datasets`/`open_dataset`.
- **R4 Low — No server-side path canonicalization (control-api owned).**
  Daemon accepts any non-empty ≤64B root; only the Tauri command layer
  canonicalizes. MCP/CLI paths reach the daemon uncanonicalized. Contained
  by loopback + 32–256B secret auth, `validate_config` `is_dir` check, and
  read-only `inspect_dataset`. Fix plan: same as R3.
- **R5 Low — Env-controlled executable redirection.**
  `VEYRA_PYTHON` (supervisor), `VEYRA_MAPPER` (controller), and PATH
  fallback to `python3` let anyone controlling the process environment
  redirect execution. Standard local-trust assumption, no remote vector.
  Fix plan: log the resolved interpreter/mapper at startup; prefer the
  packaged `python/` runtime; document the trust assumption.
- **R6 Low — Dev-only `connect-src http://127.0.0.1:1420` ships in prod CSP.**
  Fix plan: split dev/prod CSP or remove the dev entry from release config.
- **R7 Info — Electron legacy `apps/desktop/src/main.ts` spawns python via
  node `spawn` with `shell:false` and a fixed argv.** Checked OK; legacy
  surface, no change proposed (Tauri migration reference:
  `docs/desktop-electron-audit.md`).

## Checked OK (no action)

- No `shell=True` / `system()` / shell spawns anywhere; all subprocess
  invocations (`supervisor.rs`, `service.py` benchmark, `viewer/runtime.py`
  mapper, Electron supervisor) use argv arrays, `shell:false`, no shell.
- Policy/layer/seek/speed/governor args allowlisted or numerically bounded
  at every layer (daemon `is_supported_controller_command`,
  `controller.command` layer list, `service._execute`, `config.number()`).
- `runtime_command` forwards arbitrary renderer command names, but the
  daemon allowlists them; unknown → `UNKNOWN_COMMAND`. `request_for` panics
  on unknown (unreachable by construction, tested mapping).
- Mapper executable cannot be steered remotely: renderer value stripped in
  two frontends, `inject_mapper` overwrites server-side, `validate_config`
  constrains it inside the repo.
- No secret/token/auth logging found (grep over `src-tauri/src`,
  `runtime/`, `mcp/`). Token errors never echo token contents (tested).
  Discovery record `control.json` contains no secret (tested).
  Diagnostics (`controller.diagnostics`, `service diagnostics`) expose
  repo/mapper paths and bounded stderr only — no credentials.
- Temp artifacts: `TemporaryDirectory(prefix="veyra-session-")` (0700
  default) holds `crash.json` (status + digest), benchmark log/csv/json,
  `perception.json` — no secrets. Token test fixtures live in `temp_dir`
  but never assert real-secret confidentiality (test-only).
- `run_benchmark` `hardware_profile` is length-capped (128) and passed as
  exec argv, never a shell — safe.
- CLI `dataset open` 4-arg vs 5-arg arms are both reachable (slice-length
  dispatch); `sequence` length-bounded (≤64).

## Tests run

- `python3 -m pytest tests/test_mcp_server.py -q` → **11 passed**
  (8 existing + 3 new).
- `cargo test --lib control` → **34 passed** (client/daemon/controller/
  state/host/desktop_control; protocol untouched, still green).
- `cargo test --lib commands` → **3 passed** (incl. new allowlist test).
- `cargo test --bin veyra-cli` → **8 passed** (incl. new size-cap test).
- `cargo test --bin veyra-control` → **2 passed** (new).
- NOT run (out of scope): full `cargo test --lib` (includes supervisor
  live-runtime spawn test), C++ `ctest`, other Python suites.

## Gaps / follow-ups

- R1 scope confinement and R2 CSP need a frontend build check (not done here).
- R3/R4 need control-api sign-off (protocol-adjacent bounds).
- No end-to-end Tauri `cargo test` of the full lib suite from this slice;
  CI covers it.
