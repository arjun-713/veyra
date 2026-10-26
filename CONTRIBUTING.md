# Contributing to Veyra

## No "works on my machine"

- Use a C++20 compiler, CMake ≥3.22, and Ninja for the checked-in presets.
- Build via preset: `cmake --preset dev && cmake --build build` (fallback in PR template).
- Use a Python venv with the platform-compatible `requirements*.txt` dependencies. Never commit data/weights/maps (see `.gitignore`).
- LF line endings enforced by `.gitattributes` + pre-commit. Run `pre-commit install` once.

## Test suites

Tests are grouped by subsystem. Add cases to the relevant suite rather than
creating a separate file for every bug or issue.

Each test should name an observable failure. Prefer named input/expected tables
for the same validation contract; keep topology, conservation, safety and
playback/concurrency regressions independently diagnosable. Avoid tests of
test-double behavior, static prose or source-code spelling when a real execution
test already covers the contract. Shared line coverage alone does not prove two
tests are redundant: different terrain or safety inputs can execute the same
lines and still protect different outcomes.

| Area | Location |
| --- | --- |
| Map topology, storage, conservation, properties, terrain and clearing | `tests/test_map_*.cpp`, `tests/test_visibility_clearing.cpp`, `tests/test_ghost_prevention.cpp` |
| Resolution policy and adapter | `tests/test_resolution_policy.cpp` |
| Dataset formats, metadata and taxonomy | `tests/test_dataset_adapters.py`, `tests/test_dataset_contract.py` |
| Perception, neural-source acceptance, terrain and tracking | `tests/test_perception_*.py`, `tests/test_semantic_provider.py`, `tests/test_neural_acceptance.py`, `tests/test_terrain_features.py`, `tests/test_temporal_tracker.py` |
| Runtime, replay, engine, packaging and control | Corresponding `tests/test_*.py` suites |
| Benchmark quality, storage, policy challenges and reports | `benchmarks/test_*.py` |
| Release preparation, staging and smoke checks | `tests/scripts/test_tauri_release.py` |
| Desktop contracts, telemetry, replay, evaluation and rendering | `apps/desktop/tests/*.test.ts` |

```bash
python -m pytest tests benchmarks
cmake --build build -j 4
ctest --test-dir build --output-on-failure
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
```

CTest retains individual case names, so `ctest --test-dir build -R
'^point_conservation$' --output-on-failure` still selects only conservation.
Merged native binaries take the CTest case name as their argument. Allocation
instrumentation in `test_boundary_neighbors.cpp` and `test_snapshot.cpp` remains
in separate executables. Desktop `describe` sections isolate local fixtures and
hooks; the browser-backed map-canvas suite remains separate.

## Branches + PRs

- Never push to `main`. Branch: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- One concern per PR. Fill the PR template and include local verification results.
- Rebase on `main` before merge (linear history). Squash-merge. Require 1 review from any teammate.
- Map changes must cite `docs/map-correctness.md`; adaptive changes need a baseline (`DistanceLOD vs UtilityLOD`).

## Issues

- Templates only (bug / feature / task). Replace `needs-triage` with an owner + priority within 48h.
- Reproduce build or test issues from a clean checkout and paste the relevant logs.

## Protect `main` (repo Settings → Branches)

Require: PR before merging, 1 approval, no force-push, stale-review dismissal on.
