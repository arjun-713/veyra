# Fast GitHub Actions CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce routine GitHub Actions usage by keeping a path-aware Linux fast gate on pull requests while preserving full dataset, cross-platform, and release validation as explicit workflows.

**Architecture:** Keep one canonical fast `CI` workflow with a small path classifier and three meaningful jobs: C++ core, Python/perception, and desktop Rust/frontend. Run only affected jobs, with one Release C++ build and no installer packaging. Convert SemanticPOSS and cross-platform desktop workflows to manual-only validation, retain benchmark reporting for manually triggered benchmark runs, and add concurrency cancellation to obsolete runs.

**Tech Stack:** GitHub Actions YAML, `dorny/paths-filter`, CMake/CTest, Python/Ruff/unittest, npm/Svelte/Vite, Rust/Cargo/Tauri.

**Spec:** User-provided GitHub Actions cost-reduction requirements in the task request.

## Global Constraints

- Do not delete full SemanticPOSS, cross-platform, or release validation; move expensive triggers to explicit/manual execution.
- Do not change product/runtime implementation or tests.
- Do not add network downloads or dataset execution to fast PR CI.
- Preserve stable workflow names and document any status-check changes.
- Use concurrency cancellation for branch/PR validation, but never cancel a release already in progress.

### Task 1: Path-aware fast CI

**Files:** `.github/workflows/ci.yml`, `.github/workflows/desktop-tauri.yml`

**Acceptance:** Documentation-only changes do not trigger CI; source changes classify into C++, Python, desktop, or shared paths; affected fast jobs run once on Ubuntu; C++ uses one Release build; desktop checks do not package Tauri; all fast jobs have bounded concurrency.

- [ ] Replace the C++ Debug/Release matrix with one strict Release job and all safe CTest checks.
- [ ] Add a path classifier and job conditions for C++, Python, and desktop/shared changes.
- [ ] Keep Python test/static checks together in one job with the existing pinned dependencies.
- [ ] Add frontend/Rust checks without the Tauri packaging build.
- [ ] Add workflow-level concurrency cancellation.

### Task 2: Gate heavy validation

**Files:** `.github/workflows/benchmark.yml`, `.github/workflows/benchmark-report.yml`

**Acceptance:** SemanticPOSS never runs on ordinary pull requests or schedules; manual dispatch retains sequence/count/policy/provider controls; benchmark artifacts and PR upsert reporting remain available; benchmark workflow has safe cancellation for repeated manual runs.

- [ ] Remove `pull_request` and `schedule` triggers from the benchmark workflow.
- [ ] Add a manual input for optional PR association only if required by the existing report path.
- [ ] Preserve official archive verification, caching, provenance, quality gates, and four-policy execution.
- [ ] Add concurrency cancellation for the same manual target without cancelling unrelated runs.

### Task 3: Gate cross-platform validation

**Files:** `.github/workflows/desktop-tauri.yml`

**Acceptance:** The Ubuntu/Windows/macOS Tauri matrix remains manually dispatchable and unchanged in coverage; it does not consume minutes on ordinary push/PR events.

- [ ] Change triggers to `workflow_dispatch` only.
- [ ] Preserve the existing matrix, Rust/frontend checks, and no-bundle smoke build.
- [ ] Add a bounded concurrency group for manual validation.

### Task 4: Local validation and documentation

**Files:** `.github/workflows/ci.yml`, `.github/workflows/benchmark.yml`, `.github/workflows/desktop-tauri.yml`, `docs/ci-fast-actions.md`

**Acceptance:** Workflow YAML parses, shell blocks pass syntax checks, actionlint is used if available, path groups are auditable, and the repository documents before/after triggers and expected cost without fabricated timings.

- [ ] Validate all workflow YAML and embedded shell syntax locally.
- [ ] Inspect the final diff for duplicate triggers and branch-protection implications.
- [ ] Document historical run evidence and clearly label future savings as estimates.
- [ ] Run the cheapest relevant repository checks, commit the CI-only changes, push once, and inspect the resulting PR run.
