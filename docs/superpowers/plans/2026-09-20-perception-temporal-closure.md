# Perception, Dataset, and Temporal Closure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close neural semantic, real-dataset, and real temporal evidence for the Mallik perception lane without changing the core map or desktop ownership.

**Architecture:** Preserve the canonical `ObservationFrame` boundary. Dataset adapters produce canonical frames; semantic, ground, terrain, and temporal providers enrich them; evaluation scripts persist reproducible evidence. C++ map code is consumed through existing bridge contracts only.

**Tech Stack:** Python 3.13, NumPy, ONNX Runtime/provider adapters, Patchwork++, unittest/pytest-style repository tests, existing C++20 bridge and benchmark tools.

**Spec:** User-provided perception/data/temporal closure specification in the task request.

## Global Constraints

- Do not modify Tauri, release packaging, Windows/macOS/Fedora packaging, or measured 3D baseline files.
- Do not add fake data, fake model outputs, or GT-vs-GT claims as neural quality.
- Keep dataset-specific logic inside adapters/evaluators; preserve `ObservationFrame` and bridge interfaces.
- Every behavior change requires a failing test before implementation and a real-data artifact where applicable.
- Real model/dataset credentials or large downloads must be reported as explicit checkpoints.

### Task 1: Neural provider and semantic quality contract

**Files:** `perception/`, `configs/`, `scripts/validate_perception.py`, `benchmarks/`, `tests/test_salsanext.py`, new focused semantic tests.

**Acceptance:** A supported real checkpoint executes on its compatible dataset; projection/unprojection preserves point order; confidence and taxonomy are bounded; quality output includes confusion matrix, IoU/precision/recall/F1, range bins, hashes, provider, hardware, and frame/point counts. Incompatible datasets fail closed.

### Task 2: Real dataset adapters

**Files:** `datasets/rellis.py`, `datasets/semantickitti.py`, `datasets/common/`, adapter tests and dataset validation scripts only.

**Acceptance:** Existing local layouts are discovered with actionable diagnostics; representative real frames load with labels/calibration/pose/timestamps where present; malformed or mismatched files fail closed; no mapper changes.

### Task 3: Temporal real-sequence evaluation

**Files:** `perception/temporal.py`, `scripts/validate_temporal.py`, `scripts/profile_temporal.py`, temporal tests and evidence helpers only.

**Acceptance:** A trustworthy posed/timestamped sequence exercises ego-motion compensation, association, parked/static and moving cases, skipped frames, stale cleanup, and dynamic ghosting. Missing metadata is explicitly unproven or fail-closed, never silently promoted.

### Task 4: Independent red-team/evidence checks

**Files:** new tests/evaluation utilities under `tests/` and `scripts/` only; no production ownership overlap with Tasks 1–3.

**Acceptance:** Tests catch point-order drift, invalid model output, taxonomy narrowing, NaN/Inf, missing pose/time, label misalignment, and provenance omissions. Results are reproducible and do not weaken existing assertions.

### Integration gate

Run affected tests, real-data smoke/evaluation, ruff/format, C++ bridge tests, and the repository gate where feasible. Review each diff for scope violations, duplicate providers, silent fallbacks, and unsupported 100% claims before scoped commits.
