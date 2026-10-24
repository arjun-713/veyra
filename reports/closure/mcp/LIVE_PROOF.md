# MCP Live Proof — all 18 tools against a running Veyra instance

- Worktree: `worktrees/mcp-live`, branch `agent/mcp-live`, base `demo-readiness` @ `c3e2275`.
- Date (UTC): 2026-09-18. Host: `mallik-fedora`. Python 3.14.7, pytest 8.4.2.
- No builds. No changes to `src-tauri/src/control/*` (read-only), `perception/*`, `src/map/*`.
- Machine-readable transcript: `reports/closure/mcp/live_results.json` (this file is the summary).
- Status: **PASS with one blocking gap found and fixed** (see Gaps).

## What ran

- **Control daemon**: Python harness (`/tmp/opencode/mcp-live/fake_daemon.py`, not committed)
  speaking the exact wire protocol of `src-tauri/src/control/daemon.rs`
  (`schema_version`/`id`/`authorization`/`command`/`args` per `\n`-framed JSON;
  `{ok,id,result}` | `{ok:false,id,error:{code,message[,details]}}`), bound to
  `127.0.0.1:<ephemeral>`, temp 0600 token file. Faithful bounds mirrored,
  including the 64 B `required_string` cap recorded in the historical survey.
- **Product runtime**: the REAL `runtime/service.py:ProductRuntime` (import 0.17 s,
  init ~0 s — lightweight, no mapper spawn). `status`/`diagnostics`/`datasets`/
  `config_validate` answered by real product code; playback commands
  (`start`/`pause`/`seek`/`policy`/`benchmark`) delegated to `ProductRuntime.handle`
  with no session configured, so the runtime's own typed errors came back live.
- **Real local data**: `<repo-root>/data/raw/semanticposs/dataset`
  (59 B path, fits the daemon's 64 B bound). 6 sequences (`00`–`05`, 488–500
  frames each, labels 1:1, poses world-frame, **timestamps absent → catalog
  `status: "partial"`**, a real-data observation, not a failure).
- **Driver**: every tool invoked through the real `mcp/server.py:McpServer.handle`
  over a real TCP loopback round-trip (no `socket.create_connection` mocking —
  this is what caught the gap below).

## Valid calls — per-tool results (18/18 exercised)

| # | Tool | Daemon command | Result | Evidence |
|---|------|----------------|--------|----------|
| 1 | `get_runtime_status` | `status` | OK (3.1 ms) | real runtime status, `state: unconfigured` |
| 2 | `start_runtime` | `command:start` | Typed ERR | `CONTROLLER_ERROR` "configure a dataset before playback" (real runtime) |
| 3 | `stop_runtime` | `stop` | OK (1.1 ms) | daemon stays up; later calls succeed (stop ≠ shutdown) |
| 4 | `restart_runtime` | `command:restart` | OK (0.8 ms) | status, no session to reset |
| 5 | `open_dataset` | `open_dataset` | OK (292 ms) | real catalog: 6 seqs, `selected_sequence: "00"`; configure stubbed (D1) |
| 6 | `get_dataset_info` | `datasets` | OK (295 ms) | real `inspect_dataset`, `status: "partial"` (timestamps absent) |
| 7 | `play` | `command:start` | Typed ERR | same real-runtime `CONTROLLER_ERROR` as #2 |
| 8 | `pause` | `command:pause` | Typed ERR | `CONTROLLER_ERROR` "configure a dataset before playback" |
| 9 | `seek` | `command:seek{index:0}` | Typed ERR | same (error precedes bounds: no session) |
| 10 | `set_policy` | `command:policy` | Typed ERR | same (no session) |
| 11 | `set_layer` | `command:layer{lod}` | OK (0.6 ms) | local layer switch, `{"status": {...}}` |
| 12 | `get_metrics` | `status` | OK (0.5 ms) | runtime status; `layer` now `lod` (state carried across calls) |
| 13 | `get_map_statistics` | `diagnostics` | OK (0.6 ms) | `application: veyra`, real python/platform payload |
| 14 | `get_perception_statistics` | `diagnostics` | OK (0.5 ms) | same channel |
| 15 | `run_validation` | `config_validate` | Typed ERR | `CONTROLLER_ERROR` "mapper executable does not exist: …/worktrees/mcp-live/build/apps/runtime/veyra_runtime" — honest no-builds outcome from REAL `validate_config(check_paths=True)` |
| 16 | `run_benchmark` | `command:benchmark` | Typed ERR | `CONTROLLER_ERROR` "configure a dataset before playback" |
| 17 | `get_recent_errors` | `diagnostics` | OK (0.6 ms) | same channel |
| 18 | `export_diagnostics` | `diagnostics` | OK (0.5 ms) | same channel |

Daemon-side command counts at shutdown prove the footprint exactly:
`{status:2, command:8, stop:1, open_dataset:1, datasets:1, diagnostics:4,
config_validate:1}` = 18 commands for 18 valid calls, i.e. **all 17 invalid
calls below made zero daemon contact** (MCP-layer rejection).

## Invalid calls — all rejected at the MCP layer, zero daemon contact (17/17)

Bad dataset (`open_dataset`, `get_dataset_info`) → `unsupported dataset format`;
missing `root`/`count` → `missing tool argument: …`; oversized
dataset/root/sequence → `tool argument … exceeds maximum length`; bad
policy/layer → `unsupported map policy` / `unsupported layer`; `seek -1` /
`10**10`, `count 0` / `10**9` → below-minimum / exceeds-maximum; unknown tool →
`unsupported Veyra tool: do_anything`; unknown arg → `unknown tool argument:
bogus`; wrong type → `tool argument index must be integer`. All `isError: true`.

## Typed-error preservation (live)

- Daemon `CONTROLLER_ERROR` (code + message, plus `details` where the runtime
  supplied them, e.g. `{"runtime_code":"runtime_error"}`) arrives verbatim as the
  MCP tool-error text: `{"code": "CONTROLLER_ERROR", "message": "…", "details": …}`.
- Negative-auth probe with a wrong token file returned live:
  `{"code": "UNAUTHORIZED", "message": "control authorization failed"}`,
  `isError: true` — no crash, typed code preserved end to end.

## Known harness deviations (not product claims)

- D1 `open_dataset` configure step stubbed after real inspect + real sequence
  selection (spawning the mapper binary is out of scope; no builds per mission).
- D2 `config_validate` runs real `validate_config` but skips the viewer
  `build_pipeline` step (needs the viewer stack; documented, not silent).
- D3 supervisor fields (`runtime_running`/`runtime_pid`) are static stubs; the
  harness daemon provably stays alive across `stop` (later calls succeed).

## Gaps

1. **FOUND + FIXED (blocking): `mcp/control_client.py` could never talk to a real
   daemon.** `_parse_endpoint` returns `(ipaddress, port)` but `request` passed
   that tuple straight into `socket.create_connection`, whose host must be `str`
   → `TypeError: getaddrinfo() argument 1 must be string or None` on the FIRST
   live call. Every existing test patches `socket.create_connection`, so unit
   tests could never see it — this is exactly what the live run was for. Fix
   (one line, no redesign): connect to `(str(host), port)`. Regression test added:
   `test_tool_call_reaches_a_live_loopback_daemon` in `tests/test_mcp_server.py`
   (real TCP loopback, no socket mocking; fails loudly pre-fix).
2. **Observed, not fixed (pre-existing data trait):** SemanticPOSS catalog reports
   `status: "partial"` because frames carry no timestamps (`timestamps: false`;
   poses are world-frame, labels 1:1). Downstream consumers must treat
   `partial ≠ invalid` (the daemon's `select_openable_sequence` already does).
3. **Out of scope:** full playback/benchmark with a configured session needs the
   mapper binary + viewer stack (no builds per mission); R3/R4 daemon bound
   follow-ups remain with control-api.

## Tests run

- `python3 -m pytest tests/test_mcp_server.py tests/test_mcp_control_client.py -q`
  → **19 passed** (12 MCP-server incl. the new live-loopback regression +
  7 control-client). The new test was verified to fail on the pre-fix client
  (`TypeError` in `getaddrinfo`) and pass after.
- NOT run: cargo/C++ suites (no builds per mission), other Python suites.
