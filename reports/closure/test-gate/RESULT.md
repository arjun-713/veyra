# Test-gate closure — agent/test-gate

- Base: `demo-readiness` @ `6e3cece` (verified via `git log`)
- Branch: `agent/test-gate` in worktree `worktrees/test-gate`
- Gate: `python -m pytest tests/ -q` AND `cmake -S . -B build && cmake --build build -j && ctest --test-dir build --output-on-failure`
- Status: **GREEN** — both suites terminate deterministically, no test removed, no new skip.

## Verdict on the reported stall

The gate did **not** deadlock. The historic pipe deadlock (one malformed `P`
record emitting one error per remaining record while Python was still writing
the frame) is already fixed in `src/runtime/engine.cpp` (`drain until next
frame/command boundary`, exactly one `unavailable` line) and its regression
test is green. What read as "stalls at python_unittest":

1. **Redundant work (primary):** each of the 5 `RuntimeMapBridgeTests`
   reconfigured CMake and rebuilt `veyra_benchmark` from scratch in a fresh
   temp dir — 10 unbounded `subprocess.run(["cmake", ...])` calls with **no
   timeout**. Measured 197 s of the 211 s suite (93%). Any harness with a
   bounded observation window sees a stall at `python_unittest`.
2. **Missing timeouts (secondary):** 5 more unbounded `subprocess.run` calls
   (`c++` compile + run in `test_player_cli.py`, `--help` in
   `test_perception_validation.py`, 2 validator runs in
   `test_submission_closure.py`). A stuck child would hang the gate forever.

Ruled out with evidence: no infinite loop (full suite passes), no network
(dataset tests skip fast on missing `data/`; `fetch` uses `file://` fixtures
with `timeout=60`), no child/thread leak (no stray `veyra_*`/`hung.py`
processes after runs; `close()`/`terminate` paths bounded), no dataset scan
(all adapter tests skip in ms when data is absent).

## Stalling tests (before fix, `pytest --durations`)

| test | time |
|---|---|
| `test_persistent_engine_accumulates_resets_and_exposes_all_real_policies` | 62.25 s |
| `test_engine_map_cells_match_snapshot_topology` | 41.12 s |
| `test_persistent_engine_keeps_calibrated_crop_boundary_points` | 36.08 s |
| `test_real_benchmark_v2_report_is_exposed_without_synthetic_metrics` | 28.87 s |
| `test_malformed_record_aborts_frame_with_single_response` | 28.73 s |

All five are `tests/test_runtime_map_bridge.py::RuntimeMapBridgeTests` —
each stall is one full CMake configure + `veyra_benchmark` build.

## Fix (files changed)

- `tests/test_runtime_map_bridge.py` — one session-shared `_benchmark_binary()`:
  `$VEYRA_BENCHMARK_BINARY` (explicit override, same convention as
  `benchmarks/test_runtime.py`) → in-repo `build/` → else a single
  configure+build cached in a session temp dir (atexit cleanup), with generous
  finite bounds (`_CONFIGURE_TIMEOUT_S=300`, `_BUILD_TIMEOUT_S=600`, ~10x the
  measured single-target build). All 5 tests reuse it; all assertions
  unchanged; a failure message (`, one`) added to the first status assert so a
  future spawn failure reports its reason instead of a bare mismatch.
- `tests/CMakeLists.txt` — CTest passes
  `VEYRA_BENCHMARK_BINARY=$<TARGET_FILE:veyra_benchmark>` (same pattern as
  `apps/benchmark/CMakeLists.txt` for `benchmark_runtime`, guarded by
  `if(TARGET ...)`) so `python_unittest` performs zero rebuilds; plus
  `TIMEOUT 600` backstop (~35x the measured post-fix `python_unittest`
  duration — a bound, not masking: in-test engine bounds are untouched).
- `tests/test_player_cli.py` — `timeout=300` (compile), `timeout=60` (run).
- `tests/test_perception_validation.py` — `timeout=120` (`--help`).
- `tests/test_submission_closure.py` — `timeout=120` (both validator runs).

Untouched per ownership: `src-tauri/src/control/*`,
`perception/semantic/salsanext.py`, `datasets/*/adapter.py`, `viewer/*`.
No test removed (247 collected before and after), no new skip (19 before and
after under standalone pytest; 13 under CTest because 6 more tests *run*:
5 `engine_service` + 1 real-dataset `product_runtime`, all passing).

## Before / after timing (8-core, 15 GB box)

| suite | before | after |
|---|---|---|
| `pytest tests/ -q` | 228 passed, 19 skipped in **210.69 s** | 228 passed, 19 skipped in **20.29 s** (~10x) |
| `python -m unittest discover -s tests` | 247 tests OK in **157.57 s** | covered by CTest below |
| `ctest --test-dir build` | never finished inside bounded windows | **18/18 in 16.78 s** (`python_unittest` ~8 s, zero rebuilds) |

Slowest post-fix test: `test_engine_map_cells_match_snapshot_topology`
12.83 s (amortizes the one shared standalone build); every other bridge test
0.02–0.22 s.

## Transients observed (environmental, not product)

- Two `accumulates` failures (`'unavailable' != 'available'` on the first
  frame, fast — i.e. at spawn, not via the 30 s engine bound) while box load
  was 11–14 from concurrent builds; green on retry with no code change.
  Mitigated for diagnosis by the added assert message.
- One CTest `python_unittest` error: `OSError: [Errno 122] Disk quota
  exceeded` on a bytes-small `np.save` into `/tmp` (shared 7.7 GB tmpfs at
  79% with other agents writing); the identical test passed minutes earlier
  under pytest. Full `ctest` re-run: **18/18 green**. No repo change made for
  this; other agents' `/tmp` artifacts were not touched.
