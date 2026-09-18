# Ruff triage — closure lintfix (agent/lintfix)

Base: `demo-readiness` @ `38ec56b`. Runners: CI-pinned `ruff==0.8.0`
(`requirements-dev.txt`) for check + format; spot-verified identical
results under local `ruff 0.16.2`.

CI gates (`/.github/workflows/ci.yml:45-59`):

- `ruff check benchmarks perception datasets viewer/runtime.py viewer/server.py scripts/fetch_semantic_model.py scripts/validate_perception.py tests/test_perception_pipeline.py tests/test_salsanext.py tests/test_taxonomy.py --ignore SIM117,I001`
- `ruff format --check viewer/runtime.py viewer/server.py datasets/generic perception/semantic/salsanext.py scripts/validate_perception.py tests/test_generic_adapter.py tests/test_viewer_adapter_integration.py tests/test_viewer_runtime_http.py` — **passes, untouched**

## Fixed on agent/lintfix (closure-touched, verified via git blame)

Check (`ruff check benchmarks perception datasets` → **All checks passed**):

- `benchmarks/baseline_3d.py` — F401 (`import resource` removed, unused),
  RUF100 x3 (unused `# noqa: E402` removed), F541 (stray `f` prefix),
  ISC004 x5 (parenthesized implicit concatenations). Blame: all lines
  `beb74a2` (agent/baseline-3d, 2026-09-18).
- `perception/pipeline.py:266` — BLE001. Deliberate failure-safe fallback:
  kept, with targeted `# noqa: BLE001` + justification comment. Repo has
  no prior `noqa: BLE001` convention — every other `except Exception`
  site (`cenet.py`, `salsanext.py`, `semantic_provider.py`) re-raises a
  typed error, which this site must not do (fallback contract: never
  crash, return ground_truth + reason; backend ctor exception types vary
  by release). Narrowing would reintroduce crashes. Blame: `8222ee9`
  (agent/cenet-wireup, 2026-09-18).
- `perception/temporal/evaluator.py:209` — RUF007 (`zip` →
  `itertools.pairwise`, semantics identical on py3.12+). Blame: `dd83660`
  (agent/temporal2, 2026-09-18).

Format (`ruff format`, applied ONLY to the files above plus):

- `benchmarks/test_baseline_3d.py` — blame `beb74a2` (agent/baseline-3d).
- `benchmarks/run_benchmark.py` — failing lines blame `70a20c1`
  (agent/utility-lod) and `77abb56` (closure utility-rerun, 2026-09-18).
- `perception/terrain/features.py` — failing lines blame `28352fb` and
  `2c26bba` (agent/terrain).

## Pre-existing — DO NOT touch here, owner suggestion

Check (CI `ruff check` exact still reports these 3; out of lintfix scope):

- `scripts/validate_perception.py:8` — RUF100, unused `# noqa: E402`
  (from `a16fdc5`, 2026-09-15). Owner: perception/CI gate owner
  (file last meaningfully touched `9e61133`).
- `scripts/validate_perception.py:296` — TRY004, `ValueError` for
  non-mapping `quality_gate` should be `TypeError` (from `3830feb`).
  Owner: perception validation owner.
- `scripts/validate_perception.py:322` — TRY004, `ValueError` for
  non-numeric threshold should be `TypeError` (from `3830feb`).
  Owner: perception validation owner.

Format (`ruff format --check benchmarks perception datasets` still lists
these 4; failing lines predate the 2026-09-18 closure wave):

- `datasets/semanticposs/adapter.py:318` — blame `aafa045`
  (2026-09-17). Owner: datasets adapter owner.
- `perception/semantic/cenet.py` (many hunks, e.g. `:106`) — blame
  `35be56f` (agent/semantic-finetune survey, 2026-09-17).
  Owner: agent/semantic-finetune.
- `perception/semantic/pandora.py` (e.g. `:38`) — blame `35be56f`.
  Owner: agent/semantic-finetune.
- `perception/temporal/tracker.py:527` — blame `1490269`
  (2026-09-17; file later touched by closure `dd83660` but the failing
  lines predate it). Owner: temporal tracker owner.

Note: whole-repo `ruff format --check .` lists 27 files (includes
`mcp/`, `runtime/`, `scripts/measure_*`, several `tests/`); only the
subset above is in CI-adjacent scope. CI's own 9-file format gate
passes and was left untouched.

## Targeted tests (nice -n 19, timeout 300)

- `benchmarks/test_baseline_3d.py` (covers `baseline_3d.py`):
  **8 passed**
- `tests/test_perception_pipeline.py` (covers `pipeline.py`):
  **19 passed, 1 skipped** (skip: requires local SemanticPOSS+RELLIS data)
- `tests/test_temporal_tracker.py` (covers `temporal/evaluator.py`):
  **38 passed, 11 skipped** (skips: SemanticKITTI seq08 checkout unavailable)
- `tests/test_terrain_features.py` (covers `terrain/features.py`):
  **21 passed, 1 skipped** (skip: local SemanticPOSS data unavailable)
- `benchmarks/test_product_benchmark.py` (imports `run_benchmark.py`):
  **17 passed, 1 skipped, 2 failed — both failures reproduce on pristine
  `demo-readiness` HEAD (`38ec56b`), i.e. pre-existing and unrelated to
  this format-only change**: (a) ablation-membership expectation drift
  (extra `ablation_traversability` member), (b) missing
  `.venv/bin/python` interpreter in worktree environments.
