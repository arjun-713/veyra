# Green Development Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove deterministic local build, test, lint, formatting, and tooling regressions from the integrated `demo-readiness` baseline without weakening quality gates.

**Architecture:** Keep the existing C++ mapper, Python runtime, Rust control layer, and Svelte/Tauri application unchanged except where an observed compatibility or contract defect is the direct cause of a failing gate. Fix each failure at its owning layer, then run the complete repository gate from a clean build state.

**Tech Stack:** C++20/CMake/CTest, Python 3.11+/unittest/Ruff, Rust 1.77+/Cargo/Clippy, Node/Svelte/Vite, Tauri 2.

**Spec:** `AGENTS.md` and this Phase A request.

## Global Constraints

- Preserve `-Wall -Wextra -Wpedantic -Werror` for C++ checks.
- Preserve Rust MSRV `1.77`; do not raise it to fix Clippy.
- Do not delete, weaken, skip, or xfail failing tests.
- Do not modify teammate work outside the focused fixes.
- Do not add major product features or change map/perception architecture.
- Every fix must have a fresh focused verification and the final full gate.

---

### Task 1: Establish a failure inventory

**Files:**
- Inspect only initially: `CMakePresets.json`, `CMakeLists.txt`, `requirements*.txt`, `apps/desktop/package.json`, `src-tauri/Cargo.toml`, and the project validation script.
- Test/build output: temporary directories under `/tmp` or ignored build directories.

**Interfaces:**
- Preserve all existing commands and test discovery.

- [ ] Run the strict C++ Release build and CTest from a clean temporary build directory.
- [ ] Run Python unit/benchmark discovery with a bounded diagnostic wrapper and record any hang without hiding it.
- [ ] Run Ruff check/format, Rust fmt/test/clippy, frontend tests/check/build, CLI/MCP tests, and validation smoke commands.
- [ ] Classify failures by owning subsystem and avoid editing until the actual failure and source contract are identified.

### Task 2: Resolve the benchmark contract regression

**Files:**
- Inspect/modify: `benchmarks/test_product_benchmark.py`.
- Inspect only: benchmark report implementation and downstream consumers identified by symbol search.

**Interfaces:**
- Preserve `utility_ablation_report` status/member semantics and the explicit traversability field if it is the current product contract.

- [ ] Reproduce the stale `missing_members` failure against the current implementation.
- [ ] Trace the report schema and consumer expectations; determine whether the test or runtime is stale.
- [ ] Add the smallest contract-correct test/data adjustment, or fix the runtime if it violates the current schema.
- [ ] Run the focused benchmark test and the complete benchmark suite.

### Task 3: Restore Python formatting and lint correctness

**Files:**
- Modify only: `scripts/validate_perception.py` and any other file proven by the full Ruff output.

**Interfaces:**
- Preserve direct-script and module invocation behavior, including the `sys.path` bootstrap.

- [ ] Run repository-configured `ruff check .` and `ruff format --check .` to capture exact failures.
- [ ] Apply Ruff’s formatting mechanically without changing runtime behavior.
- [ ] Run targeted perception tests, Ruff check, and Ruff format check.

### Task 4: Preserve Rust MSRV while satisfying Clippy

**Files:**
- Modify only: `src-tauri/src/control/controller.rs` and any Rust file named by the fresh Clippy output.

**Interfaces:**
- Preserve `select_openable_sequence` behavior for requested and automatic sequence selection.
- Keep declared `rust-version = "1.77"` unchanged.

- [ ] Reproduce the Clippy/MSRV failure with repository-equivalent commands.
- [ ] Replace unsupported convenience APIs with an equivalent Rust-1.77-compatible expression.
- [ ] Run `cargo fmt --check`, `cargo test`, and `cargo clippy --all-targets --all-features -- -D warnings`.

### Task 5: Fix C++ range-loop warnings correctly

**Files:**
- Modify only the map-test files named by strict GCC output.

**Interfaces:**
- Preserve test values and ownership semantics; use `const auto&` only where iteration does not require a copy, and retain value iteration where mutation/copying is intentional.

- [ ] Reproduce the strict warning with `cmake --preset strict` in a clean build directory.
- [ ] Correct each loop according to object lifetime and copy cost; do not disable warnings.
- [ ] Rebuild and run CTest with output on failure.

### Task 6: Final full-gate audit and clean handoff

**Files:**
- No implementation files beyond Tasks 2–5 unless a newly reproduced deterministic failure directly requires it.

- [ ] Run C++ Release/Debug as required, CTest, Python and benchmark suites, Ruff check/format, Rust fmt/test/clippy, CLI/MCP, frontend tests/check/build, Tauri tests/build, and validation smoke.
- [ ] Verify Python discovery terminates and leaves no child processes.
- [ ] Run `git diff --check`, inspect the diff, and verify the worktree is clean after commit.
- [ ] Commit each logical fix narrowly, then report exact commands and outcomes.

## Self-review checklist

- [ ] Every reported failure has a source-level root cause and focused fix or an explicit external-only blocker.
- [ ] No test/assertion/gate was weakened or unconditionally skipped.
- [ ] The final status distinguishes unavailable external/hardware checks from local failures.
- [ ] Phase B application work has not started.
