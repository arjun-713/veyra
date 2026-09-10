# Veyra Forensic Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven development for every behavior change. Each workstream is independently owned and reviewed before integration.

**Goal:** Close every incomplete, partial, scaffolded, broken, missing, or unverified item identified by the 2026-09-09 forensic audit and produce a correct, measurable SIH MVP.

**Architecture:** Preserve the stable `ObservationFrame` boundary and world-aligned dyadic map. Implement perception, policy, mapping, metrics, and runtime as separate production components, then connect them through one versioned runtime protocol and verify with original local datasets.

**Tech Stack:** C++20, CMake/CTest, Python 3, NumPy, optional official Patchwork++ Python bindings, optional ONNX Runtime, local RELLIS-3D and SemanticPOSS datasets.

**Spec:** `AGENTS.md`, `docs/map-correctness.md`, `docs/resolution-policies.md`, `docs/perception-terrain-temporal.md`, `docs/datasets-benchmarks.md`, and the forensic audit delivered in this thread.

## Global Constraints

- Do not fabricate inference, metrics, poses, timestamps, or dataset content.
- Do not commit datasets, model weights, build outputs, benchmark dumps, or secrets.
- Every behavior change follows red-green-refactor and exercises production code.
- Uniform5, Uniform40, DistanceLOD, and UtilityLOD must receive equivalent inputs.
- Logical allocation, actual current RSS, and peak RSS remain separate metrics.
- Unknown terrain is never treated as free or drivable.
- UtilityLOD may promote relative to DistanceLOD but may not violate the near-field safety floor.
- No raw historical point retention inside map cells.

## Workstream 1: Map correctness and storage

**Owns:** `include/veyra/core/types.hpp`, `include/veyra/map/map.hpp`, `src/map/**`, map tests.

- [ ] Add failing invariant tests for exact ownership, seams, negative boundaries, split/merge cycles, rolling identity, exact eviction, and statistical conservation.
- [ ] Replace arbitrary parent-stat redistribution during split with mathematically honest topology semantics.
- [ ] Implement real sparse tiled allocation and measured allocation accounting.
- [ ] Add Uniform40 through the common map-policy surface.
- [ ] Verify strict Debug/Release builds and representative-frame performance.

## Workstream 2: Perception and datasets

**Owns:** `datasets/**`, `perception/**`, perception tests and configuration.

- [ ] Add failing tests for SemanticKITTI calibration/pose/time loading and deterministic replay.
- [ ] Complete authoritative taxonomy mappings and preserve raw labels.
- [ ] Make Patchwork++ and ONNX providers configurable, explicit, and fail-closed.
- [ ] Harden terrain and temporal behavior for empty, malformed, dense, and multi-frame inputs.
- [ ] Verify real local SemanticPOSS and RELLIS multi-frame execution and measure stage cost.

## Workstream 3: Adaptive policy and governor

**Owns:** `include/veyra/policy/**`, `src/policy/**`, policy configs/tests.

- [ ] Add failing tests for DistanceLOD baseline, utility promotion, quality gating, hysteresis, cooldown, prediction, and pressure safety.
- [ ] Implement deterministic policy decisions independent of map storage.
- [ ] Validate every policy and governor configuration field.
- [ ] Prove protected near-field and hazard preservation under simulated pressure.

## Workstream 4: Benchmarking and metrics

**Owns:** `include/veyra/metrics/**`, `src/metrics/**`, `apps/benchmark/**`, `benchmarks/**`, benchmark tests/config.

- [ ] Add failing protocol tests for timestamps, poses, and all enriched observation fields.
- [ ] Add multi-frame warmup/repetition and consistent percentile calculation.
- [ ] Report stage latency, FPS, current/peak RSS, allocation, cells/level, churn, and late/dropped frames.
- [ ] Capture schema/config/hardware provenance and run all fair policy baselines.
- [ ] Register benchmark runtime tests with CTest and verify real multi-frame runs.

## Workstream 5: Runtime and visualization

**Owns:** `apps/player/**`, `apps/live/**`, `viewer/**`, runtime/viewer tests/docs.

- [ ] Replace print-only player/live targets with real runtime behavior or explicit capability-gated entry points.
- [ ] Run configured perception from the player and expose honest stage status.
- [ ] Reset temporal state on sequence/reset operations.
- [ ] Render only real raw, semantic, terrain, motion, map, LOD, and metrics layers.
- [ ] Verify malformed config, missing backend/data, empty frame, and sustained playback behavior.

## Integration and independent verification

- [ ] Review every workstream diff for file ownership and duplicate implementations.
- [ ] Resolve shared protocol/types only in integration after worker completion.
- [ ] Run strict Debug/Release, CTest, Python, benchmark, static, sanitizer-when-available, and JavaScript checks.
- [ ] Run representative multi-frame RELLIS-3D and SemanticPOSS end-to-end executions.
- [ ] Re-audit every original BLOCKER/HIGH/P0/P1 finding and record PASS, FAIL, or environment-blocked evidence.
