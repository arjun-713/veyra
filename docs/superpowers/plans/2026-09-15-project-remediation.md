# Veyra MVP Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the merged Veyra checkout from a functional prototype to a measured, honest MVP without changing ownership of the core map hierarchy or adaptive policy engine.

**Architecture:** Preserve the existing canonical `ObservationFrame` boundary. Dataset adapters produce validated frames; `PerceptionPipeline` runs semantics, Patchwork++, terrain and optional temporal evidence; the existing V2 protocol carries aligned evidence into the C++ mapper; benchmark and desktop consumers use the same runtime outputs. Fix root causes at the owning boundary instead of adding silent fallbacks.

**Tech Stack:** C++20/CMake, Python 3.12+, NumPy/SciPy, ONNX Runtime CPU, pypatchworkpp, Svelte 5, TypeScript, Electron 40, Vite, Three.js, uPlot, CTest, unittest/pytest, Playwright, GitHub Actions.

**Spec:** `/home/arjun/.codex/attachments/943285f2-b692-443d-8f8f-44081b67bfb3/pasted-text-1.txt`; repository contracts in `AGENTS.md`, `docs/perception-acceptance.md`, `docs/map-correctness.md`, and `docs/benchmark-contract.md`.

## Global Constraints

- Never treat unavailable, unknown, or skipped evidence as a successful result.
- Do not modify the other contributors’ map hierarchy, UtilityLOD, governor, or renderer internals except for a minimal integration fix.
- Do not commit datasets, model weights, generated benchmark output, or secrets.
- Every behavior change requires a regression test; real-data claims require a reproducible command and measured output.
- Keep semantic class and motion state separate; unknown terrain is not drivable.
- Preserve world-aligned coordinates and the existing `ObservationFrame`/V2 protocol contracts.

---

### Task 1: Establish the branch baseline and CI failure inventory

**Files:**
- Inspect only: `.github/workflows/*.yml`, `CMakeLists.txt`, `tests/`, `apps/desktop/package.json`, `runtime/`, `perception/`, `datasets/`.
- Create/update only if needed: `docs/superpowers/plans/2026-09-15-project-remediation.md`.

**Acceptance:** Record current CTest, Python, desktop, formatting, and benchmark outcomes. Identify the exact failing GitHub job and command before editing its workflow. Do not alter tests to make the baseline green.

- [ ] Run `cmake --build build --parallel 4 && ctest --test-dir build --output-on-failure`.
- [ ] Run the available Python and desktop checks using their project environments.
- [ ] Inspect recent GitHub workflow runs and preserve unrelated `site/` work.

### Task 2: Make supported dataset declarations consistent

**Files:**
- Modify: `viewer/runtime.py`, `runtime/config.py`, `scripts/validate_perception.py` only where the public supported-dataset contract differs.
- Test: `tests/test_viewer_runtime.py`, adapter/runtime tests covering generic, SemanticPOSS, RELLIS-3D and SemanticKITTI.

**Interfaces:** All supported adapters must yield `ObservationFrame` with explicit pose/timestamp/provenance and deterministic ordering. Unsupported metadata must remain explicit.

**Acceptance:** The same dataset list and validation semantics are exposed by runtime, viewer and validator; each locally available adapter executes on real files; malformed paths/labels fail clearly.

- [ ] Add a failing consistency test.
- [ ] Run it red before implementation.
- [ ] Implement the smallest shared declaration/validation fix.
- [ ] Run adapter and runtime tests plus one real frame per available dataset.

### Task 3: Fix and validate Patchwork++ ground evidence

**Files:**
- Modify: `perception/ground/patchworkpp.py`, `perception/pipeline.py`, dataset-specific perception config only when the measured sensor convention requires it.
- Test: `tests/test_patchworkpp.py`, `tests/test_perception_pipeline.py`, real-data validation fixtures/scripts.

**Acceptance:** Patchwork++ output is validated for shape, index bounds, ground ratio, and failure behavior on representative RELLIS and SemanticPOSS frames. A zero-ground result must fail required validation or be reported as invalid, never silently become valid terrain evidence. Report precision/recall/F1/IoU where labels can be compared.

- [ ] Write tests for zero-ground rejection and valid mask alignment; verify red.
- [ ] Inspect sensor coordinates, mounting conventions, parameters and range filtering.
- [ ] Implement the measured correction without adding a fake fallback.
- [ ] Run real RELLIS and SemanticPOSS samples and record metrics.

### Task 4: Quantitatively validate SalsaNext semantics

**Files:**
- Modify: `perception/semantic/salsanext.py`, `perception/semantic/semantic_provider.py`, `scripts/validate_perception.py` only for correctness/measurement gaps.
- Test: semantic provider and pipeline tests; add range-binned real-data regression coverage without committing data.

**Acceptance:** CPU ONNX inference produces aligned point-wise IDs/confidence for a meaningful real sample. Report confusion matrix, mIoU and range-binned mIoU; validate unknown/invalid model behavior and class mapping. Ground-truth mode must not be mislabeled as model accuracy.

- [ ] Add failing tests for output shape, confidence bounds, and range metrics.
- [ ] Run red, implement, then run green.
- [ ] Run a deterministic real SemanticPOSS/RELLIS sample with the pinned model.

### Task 5: Complete terrain and temporal evidence validation

**Files:**
- Modify: `perception/terrain/features.py`, `perception/temporal/tracker.py`, configs only when needed to express real metadata requirements.
- Test: terrain/temporal tests and real-data validation scripts.

**Acceptance:** Drivable/non-drivable/unknown is explicitly represented and measured against labelled data where possible. Static, moving, parked and stale behavior is tested on a real timestamped/posed sequence; if no such local data exists, create an exact heavy-work checkpoint rather than claiming completion. Profile full-frame terrain and temporal stages before optimizing.

- [ ] Add tests for terrain class metrics and fail-closed missing support.
- [ ] Add/verify real temporal provenance checks and regression tests for ego motion, parked vehicles and stale tracks.
- [ ] Measure p50/p95/p99 for terrain and temporal on representative frames.
- [ ] Optimize only measured hot paths, preserving behavior tests.

### Task 6: Prove field preservation through the bridge

**Files:**
- Inspect/modify only: `benchmarks/protocol.py`, `src/runtime/engine.cpp`, `include/veyra/map/observation.hpp`, `tests/test_runtime_map_bridge.py`, related map snapshot tests.

**Acceptance:** Semantic ID/raw ID, confidence, ground, drivable state, terrain evidence, motion state/velocity, timestamp and pose provenance are either preserved or explicitly documented as intentionally non-cell state. Invalid values fail closed. Tests inspect actual serialized records and C++ runtime/map output.

- [ ] Add a failing end-to-end preservation test.
- [ ] Verify red against the current narrowing/default behavior.
- [ ] Implement the minimal protocol/map integration correction.
- [ ] Run bridge, runtime and snapshot tests on real perception output.

### Task 7: Make benchmark evidence meaningful and CI-safe

**Files:**
- Modify: `benchmarks/run_benchmark.py`, `benchmarks/render_report.py`, `.github/workflows/ci.yml`, `.github/workflows/benchmark.yml`, `.github/workflows/benchmark-report.yml`.
- Test: `tests/test_benchmark*.py`, workflow shell/config validation.

**Acceptance:** Four policies use the same real input stream; benchmark runs have meaningful sample counts, correctness gates, provenance, cache integrity, and concise Actions/PR reports. Ordinary PR CI remains deterministic; heavier SemanticPOSS runs are explicitly tiered. Existing benchmark failures are fixed at their root cause, not hidden by retries or fallback data.

- [ ] Reproduce the current failure locally or isolate it from the workflow logs.
- [ ] Add regression coverage for corrupt cache/checksum, missing artifacts, and correctness failure.
- [ ] Run a representative multi-frame real SemanticPOSS benchmark and report p50/p95/p99, FPS, RSS, logical bytes, leaves, churn and quality metrics.

### Task 8: Harden desktop runtime and visualization acceptance

**Files:**
- Modify: `apps/desktop/src/renderer/MapCanvas.svelte`, `apps/desktop/src/renderer/App.svelte`, `apps/desktop/src/renderer/Dashboard.svelte`, IPC/supervisor files only if required by failing tests.
- Test: `apps/desktop/tests/*.test.ts`, Playwright tests, Svelte check/build.

**Acceptance:** Electron displays actual runtime fields, distinguishes unavailable from computed values, keeps memory categories separate, and passes headless smoke tests. WebGL failure behavior is explicit and usable; no synthetic cloud or fabricated metric is introduced.

- [ ] Add/adjust a failing smoke assertion for the observed failure.
- [ ] Run red, fix the root cause, and run unit/Svelte/E2E checks.
- [ ] Verify a real runtime frame and map payload through the desktop IPC path where local assets permit.

### Task 9: Final validation, documentation cleanup and commits

**Files:**
- Modify only documentation that contradicts verified behavior, including stale `structure.md` if still misleading.
- Add a validation script only if the existing commands cannot provide one reproducible entry point.

**Acceptance:** Debug/Release builds, CTest, Python, formatting, compilation, desktop checks, real-data perception/map smoke and representative benchmark pass. ASan/UBSan are run when the toolchain is available. Every requirement is scored from evidence; unresolved external-heavy work is reported as a checkpoint, not marked 100%.

- [ ] Run the full affordable validation command set.
- [ ] Check `git diff --check`, tracked files, generated artifacts and `git status`.
- [ ] Commit each completed phase separately with a descriptive message; never commit the unrelated `site/` directory.
