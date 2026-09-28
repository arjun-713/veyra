# Realtime Performance and Evaluation Charts Implementation Plan

> **For agentic workers:** Execute the checked tasks in order; test-first is required for behavior changes.

**Goal:** Make Performance charts use bounded monotonic live telemetry and make Evaluation expose honest reconstruction-quality/resource comparisons from existing benchmark artifacts.

**Architecture:** Keep runtime telemetry and completed benchmark results as separate contracts. Add monotonic elapsed milliseconds to runtime telemetry while retaining the wall-clock timestamp only for freshness/provenance. Convert running telemetry events into a typed 60-second history and render relative-second x values. Extend the existing accepted benchmark row adapter and quality-tradeoff component; do not add another report schema or recompute benchmark metrics in the UI.

**Tech Stack:** Python runtime telemetry, TypeScript/Svelte, uPlot, existing Python benchmark reconstruction and quality-resource reports.

**Spec:** User request dated 2026-09-28; issues #78, #79, #80.

## Global Constraints

- Do not show calendar dates on Performance charts.
- Do not mix live telemetry samples with completed benchmark/evaluation rows.
- Do not fabricate unavailable benchmark metrics or live values.
- Preserve the existing Veyra visual language and the current report schema.
- Keep the pending P02 work preserved outside this PR; do not stage `:memory:.ses`.
- Create commits, push once after local verification, and open a PR closing #78, #79, and #80.

---

### Task 1: Specify live telemetry elapsed-time contract

**Files:** `runtime/telemetry.py`, `tests/test_runtime_telemetry.py`.

**Interfaces:** `Telemetry.report(...)` adds numeric `elapsed_ms`, monotonic since that `Telemetry` instance was created. Existing `timestamp` remains Unix wall-clock seconds for freshness only.

- [x] Add a deterministic test that pins `elapsed_ms` to a mocked monotonic clock and verifies wall timestamp remains a separate field.
- [x] Run the focused Python test and confirm it fails because `elapsed_ms` is absent.
- [x] Add instance start time and derive elapsed milliseconds from the already sampled monotonic clock in `report`.
- [x] Run the focused test, then `python -m unittest tests.test_runtime_telemetry`.

### Task 2: Build bounded live chart history and regression tests

**Files:** Create `apps/desktop/src/renderer/live-telemetry.ts`; create `apps/desktop/tests/live-telemetry.test.ts`; modify `apps/desktop/src/renderer/App.svelte` and `Chart.svelte`.

**Interfaces:** `LiveTelemetrySample` contains elapsed time, frame, FPS, rolling E2E p95, runtime+mapper RSS, mapper p50/p95, perception latency, and active cells as finite numbers or `null`. `LiveTelemetryHistory` accepts only running samples, trims samples older than 60 seconds, caps storage, and resets per new session. `relativeChartSeries(samples, key)` emits x values in `[-60, 0]` seconds and no wall-clock values.

- [x] Add tests for relative-second x values, 60-second trimming, maximum sample cap, pause rejection, resume, reset, and null metrics.
- [x] Run the new tests and verify expected failures before implementation.
- [x] Implement the typed history; leave wall-clock `timestamp` out of chart samples.
- [x] Wire App telemetry events to append only when runtime telemetry says `running`; reset the history wherever `clearSessionView()` resets session state.
- [x] Configure uPlot with numeric x scale, fixed `-60..0` range, explicit relative tick labels, and resize cleanup.
- [x] Show Throughput, E2E p95, backend RSS, mapper p95, perception latency, and active-cell charts; missing values stay gaps.
- [x] Run the focused tests, full desktop tests, Svelte check, and Vite build.

### Task 3: Extend the existing Evaluation plots from canonical benchmark rows

**Files:** `apps/desktop/src/renderer/benchmark-report.ts`, `benchmark-quality.ts`, `QualityTradeoff.svelte`, `ComparisonEvidence.svelte`; tests in `benchmark-quality.test.ts` and `benchmark-report.test.ts`.

**Interfaces:** Extend the existing `QualityResourceRow`-based plot helper to resource axes `rss`, `latency`, and `activeCells`, and quality metrics already serialized in benchmark rows. Plot Accuracy, Completion distance, and Chamfer-L1 from the existing `reconstruction` report against accepted input points; retain the separate high-resolution surface-support metrics and label them distinctly. Use `null` for missing values and require verified identical input before describing a Pareto frontier.

- [x] Add tests proving resource x values use measured peak RSS/active cells/valid map latency and reconstruction metrics come only from available report fields.
- [x] Run focused tests and confirm they fail for absent RSS/active-cell plots and reconstruction plot fields.
- [x] Add the minimal typed adapters and four scatter plots: quality vs RSS, quality vs map-update latency, Chamfer vs RSS, and quality vs active cells.
- [x] Use explicit metric units/directions and tooltips; never label logical bytes as RSS.
- [x] Ensure Pareto rings are omitted unless the accepted report says all four policies used identical input; do not compute or imply a frontier for partial reports.
- [x] Run focused tests and render-component checks, then desktop tests/check/build.

### Task 4: Document definitions, regression-check, and prepare PR

**Files:** `docs/benchmark-contract.md`; this plan file.

- [x] Document telemetry sampling source/cadence, monotonic elapsed time, 60-second window, pause/resume/reset, and the wall-clock freshness timestamp distinction.
- [x] Document reconstruction Accuracy (map→accepted-input nearest-neighbor mean), Completion (accepted-input→map nearest-neighbor mean), Chamfer-L1 (mean of directed distances), units, coordinate frame, same-frame constraint, and the fact that this reference is accepted input rather than surveyed truth.
- [x] Run all relevant Python and desktop checks plus `git diff --check`.
- [ ] Review the final diff and stage only feature files; do not stage preserved P02 files or `:memory:.ses`.
- [ ] Commit in focused chunks, push the feature branch, observe its PR checks, and create the requested PR with closing keywords for #78, #79, and #80.
