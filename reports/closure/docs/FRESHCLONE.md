# FRESHCLONE — clean-clone setup/build smoke (docs-driven)

Date (UTC): 2026-09-18. Operator: docs-demo subagent (bounded mission, <25 min).
Scope: setup + build smoke ONLY. No benchmark runs, no ctest execution.

- Source: local path clone `git clone /home/arjun/Captain/SIH/Lidar /tmp/opencode/veyra-freshclone` (no network for git).
- Clone HEAD: `50acb84` on `demo-readiness` (matches main-checkout tip at mission start).
- Report checkout: `worktrees/docs-demo` (`agent/docs-demo`), FF-merged `demo-readiness` 880af2a..50acb84 before writing (clean FF, exit 0).
- Clone left uncommitted in `/tmp` (outside repo; not committed by design).

Docs followed, in order: `README.md` Quick start, `AGENTS.md` Stack & commands,
`CONTRIBUTING.md` toolchain/preset, `docs/product-runtime.md` Run,
`CMakePresets.json` (single `dev` preset), `requirements.txt` /
`requirements-dev.txt` headers.

## Command log (all in `/tmp/opencode/veyra-freshclone`, exit codes honest)

| # | Command | Exit | Result |
| - | ------- | ---: | ------ |
| 1 | `git clone /home/arjun/Captain/SIH/Lidar /tmp/opencode/veyra-freshclone` | 0 | clean clone at 50acb84, branch demo-readiness |
| 2 | `gcc --version` / `cmake --version` / `ninja --version` / `python3 --version` | 0 each | GCC 16.2.1, CMake 4.3.0, Ninja 1.13.2, Python 3.14.7 |
| 3 | `python3 -m venv .venv` | 0 | venv created (Python 3.14.7, pip 26.0.1) |
| 4 | `.venv/bin/pip install -r requirements.txt -r requirements-dev.txt` (foreground) | TIMEOUT (>120 s, killed by tool) | no packages installed; only `pip` in venv afterwards |
| 5 | same pip install relaunched with `nohup ... &` (PID 133453) | bg | progressed only to `Collecting numpy==2.2.6` → `Using cached numpy-2.2.6.tar.gz` → stuck in `Preparing metadata (pyproject.toml)` (source build, no cp314 wheel); killed after all other gates done; log `/tmp/opencode/pip-freshclone.log` (in /tmp, not repo) |
| 6 | `cmake --preset dev` (CONTRIBUTING-documented preset) | 0 | configure OK, `Found Python3: /usr/bin/python3.14 (3.14.7)` |
| 7 | `cmake -S . -B /tmp/opencode/veyra-default-config -DCMAKE_BUILD_TYPE=Release` (README flags; dir substituted to avoid clobbering preset `build/`) | 0 | configure OK |
| 8 | `cmake -S . -B /tmp/opencode/veyra-strict-config -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS='-Wall -Wextra -Wpedantic -Werror'` (strict flags from `docs/superpowers/plans/2026-09-10-perception-acceptance.md`; NO strict preset exists — see deviations) | 0 | configure OK (compile under -Werror NOT attempted; out of scope) |
| 9 | `cmake --build build -j2` | 0 | **57/57 targets, full build green** (incl. all test executables, `veyra_runtime`, `veyra_live`, `veyra_benchmark`, `veyra_player`) |
| 10 | `python3 -m pytest --collect-only -q` (system pytest 8.4.2; venv has no pytest — see deviations) | 0 | **383 tests collected** in ~1 s |
| 11 | `python3 scripts/check_docs_links.py` | 0 | `docs links OK` |
| 12 | `python3 scripts/validate_submission_closure.py` | 0 | `submission closure scorecard: 0/48 rows closed` |

Build time: Ninja `-j2` completed inside the default tool window (well under the 900 s budget; no timeout hit).

## Docs-vs-reality deviations

1. **No strict preset exists.** Mission asked for "default and strict presets if documented".
   `CMakePresets.json` contains exactly one preset (`dev`: Ninja + Release).
   No `-Werror`/`-Wall` flags in `CMakeLists.txt`, `README.md`, `CONTRIBUTING.md`,
   `docs/development.md`, or `docs/product-runtime.md`. The only documented strict
   flags (`-Wall -Wextra -Wpedantic -Werror` to a `/tmp` build dir) live in a
   historical plan (`docs/superpowers/plans/2026-09-10-perception-acceptance.md`),
   not in setup docs. Strict *configure* with those flags passes (step 8), but a
   strict *build* is undocumented and untested here.
2. **Python version triple-mismatch; pinned `pip install` does not complete on this host.**
   `requirements.txt` header targets Python 3.13; `CONTRIBUTING.md` says 3.11;
   host provides Python 3.14.7 only. `numpy==2.2.6` ships no cp314 wheel, so pip
   falls back to a `numpy-2.2.6.tar.gz` source build and stalls in metadata prep
   (>5 min, killed). A fresh contributor on this host cannot reach a working
   `.venv` by following docs verbatim. Evidence: `/tmp/opencode/pip-freshclone.log`
   lines 1–2 (`Using cached numpy-2.2.6.tar.gz`, repeated `Preparing metadata …
   still running...`).
3. **`pytest` is not installable from pinned requirements.** Neither
   `requirements.txt` nor `requirements-dev.txt` (ruff + pre-commit only) provides
   pytest, yet `docs/dataset-validation.md` and plan docs invoke `pytest`.
   Collect-only above used ambient system pytest 8.4.2 — an undocumented dependency.
4. **README vs CONTRIBUTING build-order conflict (minor).** README lists
   `cmake … && cmake --build … && ctest …` *before* `python -m venv`;
   `docs/product-runtime.md` lists `cmake` → build → venv → `pip install -r
   requirements.txt -r requirements-dev.txt`. Mission order (venv/pip before cmake)
   matches neither exactly; cmake does not need the venv (it found system Python 3.14),
   so order is immaterial for configure/build but matters for any Python-gated step.
5. **README references `docs/product-runtime.md` and `docs/benchmark-contract.md`; both
   exist — no staleness.** `check_docs_links.py` passes on the fresh clone.
   (`AGENTS.md` docs index omits several real docs files, but the link checker only
   validates targets, not index completeness — not a failure, noted for docs-demo.)
6. **`.gitignore` does not cover `/tmp/opencode/*`.** Mission asserted "/tmp stays
   gitignored"; `grep tmp/opencode .gitignore` has no match. True in effect (clone is
   outside the repo so it cannot be committed accidentally), but not literally gitignored.
   No action needed unless clones move inside the worktree (`worktrees/` itself shows as
   untracked `?? worktrees/` on the main checkout).

## Gates reached

- [x] Prerequisites check (all present, versions recorded)
- [x] venv creation
- [x] cmake configure: `dev` preset, README default flags, strict-flags variant — all exit 0
- [x] cmake build `-j2`: 57/57, exit 0
- [x] pytest collect-only: 383 tests, exit 0
- [x] `check_docs_links.py`: pass
- [x] `validate_submission_closure.py`: exit 0 (`0/48 rows closed` — validator runs; closure itself is 0, as expected pre-benchmark)

## Gaps (explicitly NOT done — out of scope or blocked)

- `pip install` never completed (blocked by deviation #2); `.venv` in the clone is bare pip.
  Nothing downstream that needs venv packages (pytest run, perception validators, desktop)
  was attempted.
- `ctest` not executed (build-smoke only; mission stops before heavy runs).
- No strict-flags *build*, no `--preset dev` build variant beyond default `build/` (same dir).
- No benchmark, dataset, or desktop steps (explicitly out of scope).
- `validate_sih.sh --ci/--full` not run (out of scope; `--ci` would additionally need the venv).

## Bottom line

C++ side is fresh-clone reproducible exactly as documented: configure (preset + README
flags) and full `-j2` build pass wall-clean, pytest collects 383 tests, docs links pass,
closure validator runs. Python side is NOT reproducible on this host by docs alone:
pinned numpy has no Python 3.14 wheel and the docs name two different older Pythons.
Recommend pinning the supported Python version in one place (CONTRIBUTING + requirements
header agree) or relaxing `numpy`/`scipy` pins for 3.14.
