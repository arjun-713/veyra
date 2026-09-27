# Production UtilityLOD retention and current-source benchmark

**Goal:** Resolve #60's scan-order retention defect and produce honest #62 quality/resource evidence.

**Architecture:** Use the existing buffered ObservationFrame to resolve the minimum requested level per world-aligned 40 cm adaptation region before fusion. Retain support counts and planned levels in one bounded table. No historical point cache, new mapping algorithm, protocol change, UI refactor, or V2 import.

**Tech stack:** C++20 runtime adapter, existing Python benchmark/report tools.

## Constraints

- Preserve DistanceLOD, production defaults, frozen challenge manifest and teammate work.
- No tuning of weights, thresholds or governor budgets to obtain a favourable result.
- Main-only acceptance cannot be claimed for an unmerged implementation commit.
- Preserve unrelated `:memory:.ses`; disclose whole-tree dirtiness separately from source cleanliness.
- Use GT semantics explicitly for policy-potential evidence, not neural accuracy evidence.

## Task 1 — Reproduce and fix frame-local topology churn

Files: `tests/test_policy_adapter.cpp`, `src/runtime/engine.cpp`.

- [ ] Add mixed road/person scan in one 40 cm region, plus equal-distance road control. Assert physical ownership, point support, no overlap, forward/reverse equality, and no repeated split/merge within the fused scan.
- [ ] Build `test_policy_adapter`; run it and confirm the current implementation fails.
- [ ] Extend existing bounded support entries with a planned level. During `prepare_frame`, count support then resolve requests before any point updates. Fusion uses the committed frame plan. Keep the unbuffered fallback, safety floor and governor restrictions.
- [ ] Run adapter, policy, map conservation/topology tests and full Release/CTest.
- [ ] Commit runtime fix and tests separately from results.

## Task 2 — Verify unchanged real selection

Files: benchmark test/report helpers only if an actual evidence gap needs repair; outputs under `reports/utility-production-acceptance/`.

- [ ] Run SemanticPOSS 00 frames 0:2 on all four policies using fresh binaries and the same retained observation stream.
- [ ] Evaluate the existing frozen semantic masks with `regional_comparison`; do not modify selections.
- [ ] Stop and report NO-GO if useful critical benefit is not measured.
- [ ] If useful, run 00 frames 0:30 twice with the unchanged production perception/governor configurations. Record reliable sample counts, digests, binary/config hashes and code SHA; source is committed before execution.
- [ ] Produce canonical JSON/CSV/quality-resource plots; disclose GT semantics, temporal-off scope, reference limitations, memory and background-quality costs.

## Task 3 — PR handoff

- [ ] Check report consistency, changed-file lint and diff, preservation of DistanceLOD/defaults/manifest.
- [ ] Commit evidence narrowly; push once and raise PR against main.
- [ ] Reference #60/#62 without auto-closing unmet app or post-merge main acceptance criteria. Do not merge this PR.
