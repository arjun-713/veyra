# Project Submission Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every verified project gap with implementation, real-data evidence, reproducible benchmarks, platform proof, and an independent final audit.

**Architecture:** Work in dependency waves: establish an authoritative scorecard and reproducible validation harness; repair perception quality and real sequential validation; prove map/LOD/resource behavior; complete Tauri and the shared control surface; then obtain native CI/package evidence. `reports/submission_closure.{md,json}` is the only completion authority and must retain every capability until its evidence is current.

**Tech Stack:** C++20/CMake, Python/ONNX Runtime/Patchwork++, Rust/Tauri 2, Svelte/TypeScript/Three.js, GitHub Actions.

**Spec:** `/home/arjun/.codex/attachments/a806a086-805f-44aa-bf7c-1217192f160c/pasted-text-1.txt`

## Global Constraints

- A score reaches 100 only with production-path, real-input, regression, failure-handling, measured, and documented evidence.
- Never substitute ground-truth output for neural semantic-model evidence.
- Never label analytical 3D memory as measured memory.
- Never fabricate timestamps, motion, telemetry, or unsupported platform evidence.
- Do not commit datasets, weights, generated maps, package payloads, or secrets.
- Every production change begins with a focused failing regression test and ends with fresh verification.

---

### Task 1: Establish closure authority and baseline evidence

**Files:**
- Create: `reports/submission_closure.md`
- Create: `reports/submission_closure.json`
- Modify: the project validation script
- Test: `benchmarks/test_product_benchmark.py`

**Interfaces:**
- `submission_closure.json` exposes one object per capability with `capability`, `current_percent`, `target_percent`, `acceptance_criteria`, `tests_required`, `real_data_evidence_required`, `benchmark_required`, `platform_evidence_required`, `status`, `blocking_issue`, `evidence_artifact`, and `closing_commit`.
- The project validation script must fail when required evidence is absent rather than emit a synthetic pass.

- [ ] Write a failing test that rejects a scorecard with missing capability rows or a claimed-100 row without evidence.
- [ ] Run the focused test and confirm the missing validator contract fails.
- [ ] Implement scorecard schema validation and an honest baseline report.
- [ ] Run scorecard/validator regression tests and commit the closure authority.

### Task 2: Repair and measure dataset-native semantic inference

**Files:**
- Modify: `perception/semantic/salsanext.py`, `perception/semantic/*`, `configs/perception-salsanext.yaml`
- Modify: `scripts/validate_perception.py`, `benchmarks/run_benchmark.py`
- Test: `tests/test_salsanext.py`, `tests/test_perception_validation.py`

**Interfaces:**
- `SemanticProvider.predict(frame)` returns point-order-aligned semantic IDs and confidences.
- Evaluation emits overall and range-binned accuracy, mIoU, class IoU, precision, recall, and F1 with model/config/dataset provenance.

- [ ] Write failing projection/unprojection alignment tests using controlled point indices and duplicate pixels.
- [ ] Run the tests to show the existing failure or missing guarantee.
- [ ] Correct preprocessing/model tensor/layout/taxonomy behavior without changing the canonical `ObservationFrame` contract.
- [ ] Run real SemanticPOSS and RELLIS evaluation over a documented non-trivial frame range; record measured evidence.
- [ ] Commit semantic correctness, then separately commit performance work if profiling demonstrates a bottleneck.

### Task 3: Validate ground, terrain, and semantic retention end-to-end

**Files:**
- Modify: `perception/ground/`, `perception/terrain/`, `runtime/`, `benchmarks/`
- Test: `tests/test_patchworkpp_ground.py`, `tests/test_terrain_features.py`, `tests/test_runtime_map_bridge.py`

**Interfaces:**
- `ObservationFrame` preserves semantic class/confidence, ground state, traversability, terrain evidence, motion state, pose, and timestamp through the C++ bridge.

- [ ] Write failing tests for unknown traversability preservation and critical-class retention across the bridge.
- [ ] Run them red, implement only the missing contract behavior, then run green.
- [ ] Execute Patchwork++ and terrain evaluation on representative real SemanticPOSS and RELLIS frames with class/ground metrics.
- [ ] Commit only when measured output and regression artifacts exist.

### Task 4: Prove real temporal behavior and dataset metadata

**Files:**
- Modify: `datasets/semantickitti/`, `perception/temporal/`, `scripts/validate_temporal.py`
- Test: `tests/test_temporal_tracker.py`, `tests/test_validate_temporal.py`

**Interfaces:**
- Temporal validation consumes real pose/timestamp provenance and reports fail-closed status when metadata is missing or untrusted.

- [ ] Write failing tests for parked/static objects, stale cleanup, skipped frames, and invalid metadata.
- [ ] Obtain a legal real sequential posed/timestamped dataset subset before any real-motion claim.
- [ ] Run and record motion, ghosting, association, and cleanup metrics over a documented sequence.
- [ ] Commit real temporal validation with its reproducibility metadata.

### Task 5: Close map/LOD/governor/3D-baseline proof gaps

**Files:**
- Modify: `src/map/`, `include/veyra/map/`, `src/policy/`, `benchmarks/`
- Test: `tests/test_*map*.cpp`, `tests/test_split_merge.cpp`, `tests/test_rolling_window.cpp`, `tests/policy_microbenchmark.cpp`

**Interfaces:**
- All policies process the same streamed observations and expose measured map/quality/resource metrics.

- [ ] Write randomized invariant/property tests before map changes.
- [ ] Add bounded reversible-detail cache only if it is implemented and benchmarked as a shipping capability.
- [ ] Add a measured sparse 5 cm 3D reference distinct from analytical estimates.
- [ ] Run long repeated-policy and stress benchmarks with real data; record all tails and quality metrics.
- [ ] Commit each independent map proof/fix separately.

### Task 6: Complete Tauri, shared control API, CLI, MCP, and security

**Files:**
- Modify: `src-tauri/`, `apps/desktop/`, `mcp/`, `runtime/`, `scripts/`
- Test: Rust unit/integration tests, desktop tests, CLI tests, MCP tests.

**Interfaces:**
- Desktop, CLI, and MCP use one persistent control authority; UI state derives from backend state and typed errors.

- [ ] Write failing command/state/security tests for each missing public control operation.
- [ ] Implement shared control semantics and least-privilege capability restrictions.
- [ ] Run a real backend Tauri flow: dataset open, start, play, pause, seek, policy/layer change, telemetry, stop, and crash recovery.
- [ ] Remove Electron only after Tauri parity is measured and tested.
- [ ] Commit Tauri parity, control API unification, and Electron removal separately.

### Task 7: Prove cross-platform packaging, CI, reproducibility, and demo

**Files:**
- Modify: `.github/workflows/`, `scripts/`, `docs/`, `reports/`
- Test: packaging/validator/release-manifest tests and native CI artifacts.

**Interfaces:**
- CI emits native package and smoke evidence for Debian/Ubuntu, Fedora/RPM, Windows, and macOS.

- [ ] Write validator tests that fail on missing artifacts, mismatched provenance, and skipped required stages.
- [ ] Make release/desktop workflows stage and smoke the real sidecar per platform.
- [ ] Verify package contents, manifest checksums, and installer launch evidence from native CI.
- [ ] Run the scripted demo rehearsal and update only measured documentation claims.
- [ ] Request an independent red-team audit; turn every non-100 finding into a new scorecard task.
