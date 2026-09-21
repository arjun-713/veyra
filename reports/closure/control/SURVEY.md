# Shared-Control-API Slice 1 — Contract Audit (SURVEY)

Worktree: `worktrees/control-api` (branch `agent/control-api`), base `1ad1388` (demo-readiness HEAD, contains `6e3cece` shared `open_dataset`).
Sources read: `src-tauri/src/control/controller.rs`, `src-tauri/src/control/daemon.rs`,
`src-tauri/src/control/client.rs`, `src-tauri/src/control_host/mod.rs`,
`src-tauri/src/desktop_control/mod.rs`, `src-tauri/src/commands.rs`, `src-tauri/src/lib.rs`,
`src-tauri/src/bin/veyra-cli.rs`, `mcp/server.py`, `mcp/control_client.py`, `tests/test_mcp_server.py`.

## Q1 — Do CLI / MCP / desktop all route through the daemon? YES, single ownership

- Daemon owns the only `RuntimeController` (+ `RuntimeSupervisor`): `daemon.rs:28,44-65`
  (`serve` / `serve_listener_with_event_sink`). Sequential connections share that one instance
  (test `sequential_requests_share_the_daemon_controller_state`, `daemon.rs:476`).
- CLI (`bin/veyra-cli.rs:22-26`): only `ControlClient::from_env()` + `client.request(...)`.
  No `RuntimeSupervisor` / `RuntimeController` / `Command::new` (only `std::process::exit` for exit code).
- MCP (`mcp/server.py:174`, `control_client.py`): only `ControlClient.from_env()` over loopback TCP.
  Imports are `json/sys/pathlib/typing` — no `subprocess`, no shell, no fs writes, no process spawn.
  `McpServer.__init__` explicitly discards `repo` ("the daemon owns repository state").
  Test `test_server_has_no_direct_product_runtime_ownership` guards this.
- Desktop (`desktop_control/mod.rs:40-50`, `control_host/mod.rs:87-184`): `DesktopControlService`
  holds only a `ControlClient`; the daemon thread (`serve_listener_with_event_sink` +
  one `RuntimeController::new(repo)`) is owned by `ControlHost`, or an external daemon is reused
  via `VEYRA_CONTROL_ENDPOINT`/`VEYRA_CONTROL_TOKEN_FILE`. All 7 Tauri commands in `commands.rs`
  funnel through `request_for` → `DesktopControlService::request` → daemon. No duplicate runtime ownership.
- Protocol hardening (all three clients): loopback-only bind/connect, 32–256 byte printable-ASCII
  secret with constant-time compare, `schema_version == 1`, 64 KiB frames, bounded id/command/args,
  `additionalProperties: false` on MCP schemas, `stop` keeps daemon alive (`daemon.rs:289-300`).

## Q2 — Per-command table: daemon route + CLI `--json` machine-readable output

CLI `main` (`veyra-cli.rs:6-15`) always prints a JSON envelope
(`{"ok":true,"result":…}` / `{"ok":false,"error":{"code","message"}}`) and exits non-zero on error.
So machine-readable output exists for every command; the gap was flag acceptance:
only `metrics --json` was accepted, `status --json` (or any other command + `--json`) hit the usage error.
FIX APPLIED (slice 1): `run()` strips one trailing `--json` before `parse_args`; output was already
JSON so the flag is now accepted uniformly and remains a no-op. Unit test added.

| CLI command | Daemon op | `--json` before → after |
|---|---|---|
| `status` | `status {}` | rejected → accepted (output always JSON) |
| `metrics [--json]` | `status {}` (alias) | accepted → accepted |
| `runtime start` | `command start` | rejected → accepted |
| `runtime stop` | `stop` (daemon stays up) | rejected → accepted |
| `runtime restart` | `command restart` | rejected → accepted |
| `configure <json>` | `configure {config}` | rejected → accepted |
| `config validate <json>` | `config_validate {config}` | rejected → accepted |
| `dataset info <format> <root>` | `datasets` | rejected → accepted |
| `dataset open <format> <root> [sequence]` | `open_dataset` (shared op, `controller.rs:85-99`) | rejected → accepted |
| `playback play` / `pause` / `seek <frame>` | `command start/pause/seek` | rejected → accepted |
| `policy set <policy>` | `command policy` (allowlist-validated) | rejected → accepted |
| `layer set <layer>` | `command layer` (allowlist-validated) | rejected → accepted |
| `diagnostics` | `diagnostics` | rejected → accepted |
| `benchmark run` | `command benchmark` | rejected → accepted (usage line also fixed to list it) |

## Q3 — Per-tool table: MCP typed schemas, no arbitrary shell/fs/process

All 18 tools: `inputSchema.type == "object"`, `additionalProperties == false`, argument types
restricted to `string` / `integer` (+`minimum: 0`) / `object`; unknown args rejected, missing required
rejected (`server.py:252-276`). No tool exposes shell, fs, or process control. All tools call
`ControlClient.request(...)` only.

| MCP tool | Daemon op | Schema | Notes |
|---|---|---|---|
| `get_runtime_status` | `status` | `{}` | typed ✓ |
| `start_runtime` / `play` | `command start` | `{}` | dup alias, harmless |
| `stop_runtime` | `stop` | `{}` | does NOT shut down daemon ✓ (test-guarded) |
| `restart_runtime` | `command restart` | `{}` | typed ✓ |
| `pause` | `command pause` | `{}` | typed ✓ |
| `seek` | `command seek` | `{index: integer ≥ 0}` required | typed ✓ |
| `set_policy` | `command policy` | `{policy: string}` required | typed, no `enum` (daemon allowlists) — see fix list |
| `set_layer` | `command layer` | `{layer: string}` required | typed, no `enum` — see fix list |
| `open_dataset` | `open_dataset` | `{dataset, root: string; sequence?: string}` | allowlist-checked pre-IPC ✓, shared op ✓ (test-guarded) |
| `get_dataset_info` | `datasets` | `{dataset, root: string}` | allowlist-checked pre-IPC ✓ |
| `get_metrics` | `status` | `{}` | alias of status |
| `get_map_statistics` / `get_perception_statistics` / `get_recent_errors` / `export_diagnostics` | `diagnostics` | `{}` | 4 aliases, same op |
| `run_validation` | `config_validate` | `{config: object}` required | typed ✓ |
| `run_benchmark` | `command benchmark` | `{dataset, sequence: string; count: integer}` required | typed, but args are merged into benchmark passthrough — see fix list |

## Fix list

- [x] (slice 1, applied) CLI: accept trailing `--json` on every command (`veyra-cli.rs::run`).
- [ ] Desktop: no `open_dataset` Tauri command; `request_for` allowlist lacks `open_dataset` and `stop`
  (`desktop_control/mod.rs:81-93`, `commands.rs`). Desktop can inspect (`choose_dataset`) but cannot
  open via the shared op, and cannot stop runtime without `shutdown` (which kills the daemon thread).
  The `17cd9f8` wip branch has a partial attempt — needs a follow-up slice, not a drive-by.
- [ ] MCP schemas: `set_policy` / `set_layer` / `open_dataset.dataset` accept any string at the schema
  layer (fail-late at the daemon); consider `enum` + `maxLength: 64` in `_tool` schemas with enforcement
  in `_validate_arguments` (fail-fast, less IPC round-trip). Cosmetic-only enums without validator
  enforcement would be worse than none — do both or neither.
- [ ] MCP `run_benchmark` requires `dataset/sequence/count` but merges them into the benchmark command's
  passthrough args; confirm the supervisor's benchmark op consumes them, else the required fields are
  misleading (make optional or drop).
- [ ] MCP alias sprawl (`start_runtime`/`play`, 4× `diagnostics` aliases) is intentional compat surface;
  keep, but pin in `tools/list` golden test if clients codegen from it.
- [ ] Daemon `required_string` caps `dataset`/`root` at 64 bytes (`daemon.rs:380-385`); absolute dataset
  roots longer than 64 chars are rejected with `INVALID_ARGS`. Fine for now, but document the bound
  in SURVEY/CLI usage if datasets live under deep paths.

## Verification

- `cargo test -p veyra control` (daemon/controller/client/cli/desktop_control/control_host tests).
- `pytest tests/test_mcp_server.py` (daemon-routing, schema, open_dataset, error-preservation tests).
