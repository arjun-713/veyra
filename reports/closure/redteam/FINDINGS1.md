# Red-team findings 1 — SemanticPOSS `_frame_index`, daemon EPIPE, MCP validation

Worktree: `worktrees/redteam1`, branch `agent/redteam1`, base `demo-readiness`
(`8cb0bbd`; includes `aafa045` adapter fix and `5ff1712` daemon EPIPE fix).
Scope: reads + targeted fast Python probes only. No cargo/cmake builds.

## Target 1 — `datasets/semanticposs/adapter.py` `_frame_index` (post-`aafa045`)

24 ad-hoc probes, all verdict PASS (useful error or correct value; no silent
wrong-line, no crash, no hang). Probe script was throwaway (not committed);
representative cases below. `P*` = adapter, `M*` = MCP.

| Probe | Input | Expected | Observed | Verdict |
|---|---|---|---|---|
| P1 bad labels | label `999` (unmapped) | unknown class, no crash | `semantic_class=[0]`, conf `0.0` | PASS |
| P2 corrupt scan | 3×float32 (12 B, `≠16`) | `ValueError` useful | `scan does not contain complete XYZ/intensity records` | PASS |
| P2b truncated scan | 12 zero bytes, label 1 pt | `ValueError` useful | same XYZ/intensity message | PASS |
| P3/P3b truncated timestamps | 2 refs, 1-line file | frame1 `ValueError`, frame0 ok | `timestamp file has no value for 00/1`; frame0 `ts=1.0` | PASS |
| P4 truncated poses | 2 refs, 1-line `poses.txt` | `ValueError` useful | `pose file has no value for 00/1` | PASS |
| P5 invalid timestamp | `not-a-time` | `ValueError` + line no | `invalid timestamp at …:1` | PASS |
| P5b trailing junk | `4.25 extra-junk` | lenient-first-token (noted) | `ts=4.25` | PASS (lenient, harmless) |
| P6/P6b/P6c bad poses | alpha / 11 vals / scale-2 matrix | `ValueError` useful | `invalid pose …:1` / `must contain 12 values` / `rotation must be rigid` | PASS |
| P7 non-numeric ids | `abc`,`def` + 2-line ts | refs-position, no crash | `7.0`,`8.0` | PASS |
| P8 negative id | `-1.bin` + 1-line ts | refs-position, no crash | `ts=9.0` | PASS |
| P9 missing files | no ts/pose files | absent/identity, no error | `timestamp absent`, `pose identity_absent` | PASS |
| P10 missing scan dir | no `velodyne/` | `FileNotFoundError` | `scan directory does not exist` | PASS |
| P11 missing frame | `load_frame("00","999")` | `FileNotFoundError` | `frame 00/999 does not exist` | PASS |
| P12 label mismatch | 2 pts / 1 label | `ValueError` useful | `scan/label length mismatch … 2 != 1` | PASS |
| P13 non-finite scan | `inf` point | `ValueError` useful | `scan contains non-finite XYZI values` | PASS |
| P14/P14b blank lines | stray `\n` in per-present and absolute ts files | no silent shift | values correct (`40.0`); blanks carry no values so filtered index == value index | PASS (no bug) |
| P15 missing frame in `_frame_index` | unknown id | `FileNotFoundError` | `frame 00/nope does not exist` | PASS |
| P15b `total_lines=None` | refs `2`,`10` | doc said refs-position, code said numeric | code returns `10` (historical numeric) — **doc was wrong, fixed** | PASS w/ doc fix |
| P16 absolute beyond EOF | frame `999`, 3-line file | `ValueError` useful | `timestamp file has no value for 00/999` | PASS |
| P17 empty scan+label | 0-byte `.bin` + `.label` | empty frame, no crash | `N=0` frame | PASS (accepted) |

Observations reported, not fixed:
- `_timestamp` keeps `if frame_index is None: return None, "absent"`, but
  `_frame_index` is typed `-> int` and never returns `None` (raises instead).
  Dead branch, harmless; left untouched to keep the diff minimal.
- Timestamp parsing takes the first whitespace token, so trailing junk on a
  line is silently ignored. Lenient but reasonable (tolerates comments);
  poses are strict (exactly 12 values), which is the safety-relevant path.

## Target 2 — `src-tauri/src/control/daemon.rs` EPIPE fix (read-only)

No new issues. Verified by grep (no cargo build per mission):
- Single production socket-write funnel: both `handle_connection` call sites
  (normal reply ~L121 and `Frame::TooLarge` reply ~L103) route through
  `write_response` → `write_response_to`. No missed `write`/`to_writer` sites;
  test-only `write_all`s are client-side helpers.
- Partial writes: `write_all` loops internally, so short writes are retried;
  `flush` error propagates with its native kind (`BrokenPipe`, …), which
  `client_connection_error` maps to close-connection, not kill-loop.
- `TooLarge` path has the same `client_connection_error` mapping as the normal
  path — coverage complete.
- Serialization (`serde_json::to_vec`) happens pre-socket on a `Value`
  (infallible in practice), so `InvalidData` can no longer masquerade as a
  fatal serve-loop error. `client_connection_error` kinds
  (TimedOut/WouldBlock/BrokenPipe/Aborted/Reset/NotConnected) are the right
  set for an established-connection write.
- Pre-existing (not from this fix, reported only): `set_read_timeout` /
  `set_write_timeout` / `try_clone` failures in `handle_connection` use `?`
  and would exit the whole serve loop for a per-connection setup error. These
  syscalls effectively never fail on an accepted socket; no change made.

## Target 3 — `mcp/server.py` validation (post-`e2f218f`)

29 ad-hoc handler probes (FakeDaemon pattern from `tests/test_mcp_server.py`),
all verdict PASS: every malformed input returns `isError` with a useful
message and never contacts the daemon; every valid input passes through.

| Probe | Input | Expected | Observed | Verdict |
|---|---|---|---|---|
| M1–M5 oversized strings | dataset 33 B, root 5000 B, sequence 65 B, policy/layer 33 B | `isError`, maxLength msg, no daemon | `tool argument <n> exceeds maximum length` | PASS |
| M6 boundary | root exactly 4096 B | passes MCP schema (daemon re-validates) | forwarded; daemon-side 64 B bound rejects | PASS (defense in depth) |
| M7/M8 unknown args | extra `evil` on `set_layer` / `get_runtime_status` | `isError`, no daemon | `unknown tool argument: evil` | PASS |
| M9–M13 wrong types | index `"5"`/`True`/`2.5`, config `"nope"`, policy `5` | `isError` type msg, no daemon | `must be integer/object/string` (bool ≠ int) | PASS |
| M14–M16 unsupported values | `turbo`, `../../etc`, `unsafe` | allowlist `isError`, no daemon | `unsupported map policy/layer/dataset format` | PASS |
| M17 empty policy `""` | passes schema (no minLength) | caught by allowlist | `unsupported map policy` | PASS |
| M18/M19 missing required | `seek {}`, benchmark w/o count | `isError`, no daemon | `missing tool argument: index/count` | PASS |
| M20–M23 bounds | seek `-1`/`1e10`, count `0`/`1e9` | `isError`, no daemon | `below minimum`/`exceeds maximum` | PASS |
| M24 unknown tool | `execute_shell` | `isError` | `unsupported Veyra tool` | PASS |
| M25/M26 malformed envelope | args list, empty params | `isError`, never raise | `isError=True`, no daemon contact | PASS |
| M27–M29 valid | `lod`, `seek 0`, count `100000` | forwarded | `isError=False`, daemon contacted | PASS |

No MCP gaps found. `minLength` is absent on string fields, but the
policy/layer/dataset allowlists make empty-string bypass impossible, and the
daemon re-validates lengths anyway.

## Fix applied (trivially safe)

- `datasets/semanticposs/adapter.py`: corrected `_frame_index` docstring —
  `total_lines=None` keeps historical *numeric* behavior (code was right, doc
  was wrong; no caller passes `None`). Doc-only, zero behavior change.
- `tests/test_semanticposs_adapter.py`: added
  `test_frame_index_without_total_lines_keeps_historical_numeric_behavior`
  locking `None → numeric` and short-file `→ refs-position`.

## Tests run

- `nice -n 19 python3 -m pytest tests/test_semanticposs_adapter.py tests/test_mcp_server.py -q`
  → **32 passed, 2 skipped** (skips: original local SemanticPOSS data
  unavailable — pre-existing, environment-dependent). Elapsed <1 s.
- No cmake/cargo/npm builds; ad-hoc probe scripts were throwaway (`/tmp`),
  not committed.
