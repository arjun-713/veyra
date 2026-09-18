# Red-team findings 2 — `mode:cenet` fallback, viewer checkpoint resolution, rehearsal drivers

Worktree: `worktrees/redteam2`, branch `agent/redteam2`, base `7239417`
(demo-readiness + run3a integration; includes `8222ee9` cenet wiring and
`6bd185d` demo rehearsal script).
Scope: reads + targeted fast hermetic Python only (`nice -n 19`,
timeout 120). No builds, no full pytest, no inference runs (all neural
selection cases use a NumPy-only fake or a mocked constructor; the single
real-constructor probe uses a 16-byte bogus file and asserts fallback, no
forward pass).

## Target 1 — `perception/pipeline.py` `_cenet_provider` fallback

Requirement: `mode:cenet` with missing/bad weights, bogus path, bad sha,
bad threads, or torch absent must fall back to `ground_truth` with
provenance (`semantic_fallback_reason` + per-frame diagnostics) — never
crash, never silent neural (`status.semantic == "model"` only when CENet
actually runs).

All verdicts PASS. Probes are hermetic; throwaway script not committed
(`/tmp/opencode/rt2_probes.py`).

| Probe | Input | Expected | Observed | Verdict |
|---|---|---|---|---|
| T1a missing checkpoint | `{mode:cenet}` (no key, env unset) | fallback + "no checkpoint configured" | `GroundTruthSemanticProvider`, `req=cenet`, reason `no checkpoint configured … fell back to ground_truth` | PASS |
| T1b bogus path | `checkpoint=/nonexistent/rt2-x.bin` | fallback + "weights absent" naming source | reason `config checkpoint weights absent: /nonexistent/rt2-x.bin; fell back…` | PASS |
| T1c directory | `checkpoint=<tmpdir>` | fallback (is_file False), no crash | `weights absent: /tmp/tmporg3ib0h` | PASS |
| T1d non-string type | `checkpoint=123` | no crash; fallback | `no checkpoint configured` (non-str treated as unset) | PASS w/ note (see O1) |
| T1e wrong sha | real temp file + `sha=0*64` | fallback + "sha256 verification" | reason `… failed sha256 verification: <path>; fell back…` | PASS |
| T1f sha non-string | `checkpoint_sha256=12345` | raise config error | `PerceptionConfigurationError: cenet checkpoint_sha256 must be a hex string` | PASS |
| T1g sha normalization | correct digest upper-case + padded | verification passes (then mocked neural selected) | `FakeOK`, `fallback=None`, threads honored | PASS |
| T1h bad threads | `0, -1, "4", True, 2.5, None` | raise config error each | all six raise `cenet threads must be a positive integer` (bool explicitly rejected) | PASS |
| T1i backend ValueError (torch-missing shape) | temp file + ctor raises `ValueError(torch is required…)` | fallback + "backend unavailable (ValueError…)" | `GroundTruth…`, reason names `ValueError` + message | PASS |
| T1j provider import blocked | `sys.modules[perception.semantic.cenet]=None` | fallback + "provider is unavailable (ImportError…)" | reason `… provider is unavailable (import … halted; None in sys.modules); fell back…` | PASS |
| T1k bogus content, real ctor | 16-byte file, no mock (torch present here) | fallback, never crash | `backend unavailable (ValueError: cannot load CENet checkpoint: invalid load key, 'n'.)` | PASS (no forward pass) |
| T1l env whitespace | `VEYRA_CENET_CHECKPOINT="   "`, config bogus | env treated as empty, config used, source=config | reason cites `config checkpoint … /nonexistent/cfg.bin`, no env mention | PASS |
| T1m diagnostics provenance | fallback pipeline `.process(frame)` | `status.semantic=ground_truth` + diagnostic names cenet→ground_truth | `status=ground_truth`, diag `semantic fallback to ground_truth: mode 'cenet' requested but …` | PASS |
| T1n model_path alias | `model_path=<real tmp file>`, ctor raises RuntimeError | alias honored, fallback + backend reason | reason `config checkpoint backend unavailable (RuntimeError: boom-backend)` | PASS |
| T1o empty/junk sha | `checkpoint_sha256=""` / `"zzz"` | `""` skips verification (falsy); junk fails verification | `""`→neural selected (mocked); `"zzz"`→fallback sha failure | PASS w/ note (see O2) |

`torch absent` path: `cenet.py` keeps torch lazy (no top-level import),
so `from perception.semantic.cenet import CENetSemanticProvider` succeeds
without torch; the missing-torch `ValueError` surfaces from the
constructor and is caught by the generic `except Exception` fallback
(T1i shape). The `except ImportError` branch covers a genuinely
unimportable provider module (T1j). Both keep provenance; neither crashes
nor reports `model`.

## Target 2 — `viewer/runtime.py` checkpoint path resolution

Code under test (`build_pipeline`, post-`8222ee9`): relative `model_path` /
`checkpoint` joined against `repo_root`; absolute left alone.

| Probe | Input | Expected | Observed | Verdict |
|---|---|---|---|---|
| T2a relative | `checkpoint=rel/x.bin`, root `/tmp/RT2` | joined | reason cites `/tmp/RT2/rel/x.bin` | PASS |
| T2b absolute | `checkpoint=/tmp/abs.bin`, root `/tmp/RT2` | untouched | reason cites `/tmp/abs.bin` | PASS |
| T2c traversal | `checkpoint=../../etc/passwd`, root `/tmp/RT2/sub` | joined verbatim, no jail | reason cites `/tmp/RT2/sub/../../etc/passwd` (escapes root if followed) | PASS w/ note (see O3) |
| T2d root None | `checkpoint=rel/y.bin`, root `None` | stays relative (CWD-relative at `is_file`) | reason cites `rel/y.bin` | PASS (documented; `RuntimeSession` always passes a resolved root) |
| T2e non-string | `checkpoint=123`, root set | untouched → pipeline "no checkpoint configured" | `no checkpoint configured` | PASS (consistent w/ T1d) |
| T2f blank string (pre-fix) | `checkpoint=""`, root `/tmp/RT2` | should read "no checkpoint configured" | **was** `weights absent: /tmp/RT2` (`Path("")=="."` joined to root) — misleading provenance | FAIL → FIXED (see fix) |
| T2f blank string (post-fix) | same | "no checkpoint configured" | `no checkpoint configured` for `""` and `"   "`; relative still joins | PASS |
| T2g model_path alias | `model_path=relm/z.bin`, root `/tmp/RT2` | joined like checkpoint | reason cites `/tmp/RT2/relm/z.bin` | PASS |

## Target 3 — `scripts/demo_rehearsal.sh` embedded drivers (read-only)

Reviewed full script (763 lines) plus both heredoc drivers; no execution
(benchmark matrix running on this box).

| Probe | Area | Expected | Observed | Verdict |
|---|---|---|---|---|
| T3a NDJSON/framing | `drive_headless.py rpc()` writes `json.dumps({id,command,args})+"\n"` + flush; reads via `runtime.protocol.read_message` (VYRA frames) | stdout framing correct, not raw NDJSON | matches `runtime/__main__` contract; per-RPC `select` deadline (60–300 s); `proc.poll()` early-exit check; `!ok` raises; unknown broadcasts (`status`) ignored, `telemetry`/`visualization` tracked | PASS |
| T3b malformed engine output | `read_message` raises (`ValueError`/`EOFError`) inside `rpc()` | fail closed, no silent PASS | exception escapes driver → nonzero exit → shell records `headless.session FAIL` (no `session.json` written; summary handles absence) | PASS |
| T3c shutdown/reap | `rpc("shutdown")` → `stdin.close()` → `wait(20)` → `kill`+`wait(10)` → raise on timeout; `stop_returncode`/`reaped` only on clean path | reaped on all paths, no false clean-stop | kill path raises `RuntimeError(…not reaped…)` → FAIL recorded, never reported PASS; shell `if driver; then PASS else FAIL` + `tail` evidence | PASS |
| T3d `set -euo pipefail` | fallible steps must be guarded (`if …`, `\|\| true`, `\|\| log`) | no abort on honest FAIL/SKIP | driver/neural/policy-table/`dpkg-deb`/`tail` all guarded; `while read` loops end with `\|\| true`; `nullglob` toggled around globs; `step_summary` fail encoded as return 1 with explicit `step_summary \|\| exit "$?"` in `main` | PASS |
| T3e preflight gating | downstream steps refuse to run without proven prerequisites | SKIP, not run | headless + neural both `SKIP` when `PREFLIGHT_OK != 1`; neural additionally `FAIL`s honestly when weights/torch missing under `--neural` | PASS |
| T3f neural honesty | probe asserts `mode == "model"`, never feeds map | no relabel, no contamination | `probe_cenet.py` raises on `mode != "model"`; map session config pinned `ground_truth`; rehearsal never mixes the two | PASS |

Observations reported, not fixed (out of one-line scope or by design):

- O4 `drive_headless.py` keeps `err_stream = open(STDERR_PATH, "wb")` open
  for the session lifetime (no explicit `close()`; flushed at interpreter
  exit). Evidence file is still complete; FD hygiene only. Left untouched.
- O5 no `trap` cleanup for the spawned `python -m runtime` child if the
  rehearsal script itself is SIGINT/SIGTERM-killed mid-session (normal
  Ctrl-C during a long headless run could orphan the runtime child).
  Acceptable for a manual evaluator script; noted for a future `trap
  'kill …' EXIT/INT/TERM` if desired. Left untouched.
- O6 preflight torch sniff runs `python3 -c "import torch; import sys;
  …"` (imports `sys` after `torch`; harmless) then re-checks with
  `PYTHONPATH`. Redundant but read-only and correct. Left untouched.

Cross-target observations reported, not fixed:

- O1 `checkpoint` wrong-type (e.g. int, T1d/T2e) falls back as "no
  checkpoint configured" instead of raising like `threads`/`sha` type
  errors do. Provenance is present (never silent neural), but the message
  hides that a key exists with the wrong type. Raising would be a behavior
  change (fallback→error); left for the owner to decide.
- O2 `checkpoint_sha256: ""` is falsy and silently disables verification
  (T1o). Same class as O1: fail-closed (falls back on any later error) but
  an explicit empty string probably deserves a config error. Validation
  change; reported only.
- O3 no path jail: `../../etc` joins verbatim and `is_file()` follows it
  (T2c). Consistent with the rest of the local runtime (`executable`,
  dataset `root`, `model_path` all accept absolute/out-of-tree paths;
  `Popen` uses argv lists, no shell), and the config is evaluator-owned,
  not attacker-controlled — so this is a documented non-boundary, not a
  vulnerability. Reported for the record; no change.

## Fix applied (one-line-safe + test)

- `viewer/runtime.py` (`build_pipeline`): skip blank `model_path` /
  `checkpoint` values during `repo_root` joining —
  `isinstance(value, str)` → `isinstance(value, str) and value.strip()`.
  Blank no longer resolves to the repo root directory (T2f); the
  pipeline's own `checkpoint.strip()` empty check then reports the honest
  "no checkpoint configured" provenance. Relative/absolute handling
  unchanged (T2a/T2b/T2g re-verified post-fix).
- `tests/test_perception_pipeline.py` (`CenetModeTests`):
  `test_cenet_build_pipeline_keeps_blank_checkpoint_unresolved` locks
  `""`/`"   "` → `GroundTruthSemanticProvider` + "no checkpoint
  configured" via `build_pipeline(..., repo_root="/tmp/RT2")`.

## Tests run

- `nice -n 19 python3 -m pytest tests/test_perception_pipeline.py -q -k
  "Cenet or cenet or fallback"` → **5 passed, 15 deselected** in ~0.4 s
  (4 pre-existing cenet tests + 1 new blank-checkpoint test).
- Ad-hoc hermetic probes (T1a–T1o, T2a–T2g): all PASS post-fix (T2f FAIL
  pre-fix, PASS post-fix). Throwaway script, not committed.
- No cmake/cargo/npm builds; no dataset/inference runs.
