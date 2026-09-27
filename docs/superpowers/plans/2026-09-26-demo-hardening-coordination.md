# Demo Hardening Coordination Implementation Plan

> **For agentic workers:** Implement one approved PR scope at a time. Use the repository's test-driven-development and verification-before-completion skills. Do not begin implementation, create branches, commit, push, or post coordination changes from this planning task.

**Goal:** Complete Arjun's issues #56, #57, #60, and #62 through small, independently testable changes without colliding with teammate work or refactoring the application.

**Architecture:** Preserve the existing mapping, observation, control, and desktop paths. Extend physical-layer inspection additively, instrument production UtilityLOD before correcting signals, then evaluate unchanged inputs. Publish final measurements only after approved implementation and desktop fixes are integrated.

**Tech Stack:** C++20/CMake, Python, Rust/Tauri, Svelte/TypeScript, existing benchmark tooling.

**Spec:** GitHub issues #53–#62 in arjun-713/veyra. Planning baseline: main at 59f2a0332239e490fe16b5acf4119b9ac95a2774; clean primary checkout. Recheck before execution.

## Global constraints

- No UtilityLOD V2 integration. No production default-policy change or DistanceLOD behavior change.
- No routing/layout redesign, file-wide formatting, dependency upgrades, map-storage refactor, or broad cleanup.
- Preserve frozen challenge selections and existing evidence. Never tune against the final evaluation cases.
- Keep datasets, checkpoints, raw maps, and huge traces external; retain compact provenance/results under repository conventions.
- Same configuration and observations must yield deterministic topology/allocation where expected.
- Unknown/unavailable values must not be converted into invented zero measurements.
- A benchmark or test that did not execute is not a PASS.
- Submit narrow PRs; no single team-integration mega-PR.

## Verified ownership

| Owner | Issues | Responsibility |
|---|---|---|
| Arjun / arjun-713 | #56 P0.4, #57 P0.6, #60 P0.5, #62 P0.7 | Physical-layer exposure; production Utility signals; independent policy proof; final evidence |
| Samay / samay43 | #53 P0.1, #54 P0.2, #55 P0.3 | Real neural demo; temporal/ghost prevention; traversability colors |
| Vinay / bmvinay7 | #58 P0.8, #59 P0.9, #61 P0.10 | Report contracts; comparison presentation; packaged macOS acceptance |

Ownership is a proposed coordination agreement, not an exclusive Git lock. Confirm it with teammates before implementation.

## Shared-file rules

| Shared area | Primary writer | Required coordination |
|---|---|---|
| App.svelte, dashboard/report extraction, ComparisonEvidence.svelte | Vinay | Arjun supplies required fields/fixtures; Vinay applies App wiring. No concurrent App edits. |
| colors.ts | Samay for #55 first | Merge signed traversability fix before any related physical-layer rendering changes. |
| MapCanvas.svelte | Arjun during #56 | Vinay waits on renderer edits or submits isolated changes after #56 merges. |
| perception/pipeline.py and provider/runtime defaults | Samay | Arjun documents signal-quality requirements; Samay applies any shared quality-boundary change in an agreed slice. |
| engine.cpp | Arjun for layer serialization/Utility; Samay for ghost clearing | Serialize these editing windows. Other owner works on tests/perception until the shared-file PR merges. |
| core.ts, runtime/visualization.py, src-tauri/src/telemetry.rs | Arjun for #56 visualization extension | One atomic producer/validator/consumer PR. Coordinate any temporal transport additions before either owner edits. |
| runtime/service.py, runtime config/state | Samay/Vinay by issue scope | Arjun avoids editing; submit narrow integration needs to the current writer. |
| benchmark report field names and units | Vinay consumer, Arjun producer | Agree the canonical existing contract before edits; producer changes must ship with consumer tests. |
| frozen challenge manifest | No changes | All owners preserve it. |
| deployment/package/supervision code | Vinay | Arjun does not absorb #61 into mapping work. |

No one should independently invent another wire format, report schema, observation-quality definition, or metrics store.

## Work and merge order

1. Samay can start #55 immediately and develop #53. Vinay can start #58 against existing report fixtures. Arjun inspects/contracts/tests for #56 and #57 without competing shared-file edits.
2. Merge #55. Review the physical-layer transport/inspection contract with Samay and Vinay.
3. Arjun PR A: #56 physical-layer inspection/visibility. Reserve its engine/renderer/transport editing window.
4. Arjun PR B: #57 optional Utility diagnostics. Behavior stays unchanged. This is a separate reviewable deliverable; it does not close #57.
5. Merge Samay's relevant provider/quality work and temporal engine changes before Arjun's competing engine edits. Arjun PR C corrects signals from diagnostics and closes #57 only when its criteria are met.
6. Vinay merges #58 then #59. Arjun can collect bounded backend #60 evidence beforehand, but complete the application proof only after #56/#57/#59 are integrated.
7. Arjun PR D completes #60 evaluation and demonstration if benefit is genuinely established. If not, record NO-GO; do not invent a winning result or silently expand this into an algorithm rebuild.
8. Vinay completes #61 packaged macOS verification after integrated app fixes. Early packaging diagnosis can proceed independently.
9. Arjun PR E produces #62 final current-main evidence after all required approved fixes merge. Record the clean execution SHA before generating results.

There is no cyclic acceptance dependency: #61 can exercise bounded benchmark smoke before #62; #62 provides the final canonical evidence afterward.

## PR A — Physical-layer exposure (#56)

**Proposed branch:** fix/physical-layer-visibility, from updated main at execution time.

**Owned implementation:** sampled cell-layer serialization in src/runtime/engine.cpp; runtime/visualization.py; apps/desktop/src/core.ts; src-tauri/src/telemetry.rs only if validation requires it; MapCanvas.svelte and a small inspection component if needed.

**Tests:** tests/test_runtime_visualization.py, tests/test_layered_end_to_end.py, desktop visualization/inspection tests, relevant Rust telemetry tests.

**Interface:** Preserve pack_visualization(frame, cells, generation), the existing point layout, and all 17 existing v3 cell fields. Prefer an optional, separately described physical_layers binary section aligned to the already-sampled cell order. Declare its layout/version/count/offset/stride, validate its bounds, and keep old frames readable. If implementation constraints require another design, approve that contract before coding; never silently overwrite pooled z or existing field meanings.

**Scope:** Inspection-first exposure of actual ground/obstacle/overhead count, height/extents, and supported statistics. Empty layers are explicitly absent; unknown ground stays unknown. Optional separate surface display follows only if it fits this PR. No new permanent CellStats fields, default changes, routes, or observation-wire redesign.

- [ ] Write failing producer/consumer tests for three distinct surfaces, empty layers, absent optional section, and malformed section bounds.
- [ ] Confirm tests fail for missing functionality, not unavailable dependencies.
- [ ] Implement the bounded additive transport and inspection display as one coherent change.
- [ ] Have Vinay apply any necessary App wiring in the reserved window; keep it a localized hunk.
- [ ] Verify sampled row alignment and missing/NaN handling; show no invented pooled surface as a layer measurement.
- [ ] Run targeted transport/layer tests, C++ build/CTest, frontend tests/check/build, and relevant Rust tests.
- [ ] Exercise a real layered scene if available; disclose unavailable data rather than calling synthetic evidence real.
- [ ] Review the diff for accidental formatting and unrelated files.
- [ ] Commit implementation and regression tests together: feat(viewer): expose physical map layers in cell inspection.
- [ ] Optional second scoped commit: test(viewer): document real layered inspection acceptance.

## PR B — Utility diagnostics (#57, partial)

**Proposed branch:** feat/utility-signal-diagnostics, from updated main.

**Owned implementation:** src/runtime/engine.cpp Utility adapter only; src/policy/policy.cpp; include/veyra/policy/policy.hpp only for bounded opt-in telemetry; small benchmark trace extraction.

**Tests:** tests/test_policy.cpp, tests/test_policy_adapter.cpp, benchmark attribution tests.

**Interface:** Existing policy decisions and ObservationFrame stay unchanged. Diagnostics are explicitly enabled and bounded; default execution does not allocate large per-point trace histories. Preserve report fields already agreed with Vinay.

- [ ] Test that diagnostics on/off produce identical accepted points, levels, and map topology.
- [ ] Record measured raw/normalized signals, effective weights, quality gates, score margin, and actual decision reasons at the decision site.
- [ ] Test object versus ground confidence coupling, current density behavior, and semantic-only reachability without modifying thresholds.
- [ ] Use deterministic spatial fixtures to confirm candidate/cell identities match world regions.
- [ ] Run targeted tests and a bounded diagnostic replay; finish all subagents before benchmarks/tests if any are used.
- [ ] Capture the demonstrated root causes and their frequency; do not infer actual admissions from the heatmap.
- [ ] Commit: feat(policy): add opt-in production utility signal diagnostics.

This PR may merge even if Utility effectiveness is poor; its acceptance is trustworthy observability without behavior change.

## PR C — Signal correction (#57 completion)

**Proposed branch:** fix/utility-observation-signals, from main containing PR B and approved relevant Samay changes.

**Owned implementation:** Utility adapter, policy helpers/config; localized tests. Samay owns perception/pipeline.py edits unless an explicit handoff transfers that function.

**Interface:** Keep existing policy identifiers and defaults. Define class importance in documented taxonomy-aware configuration. Quality must describe support relevant to the signal; missing ground fit alone cannot invalidate a valid non-ground object. Density must be measured and range-aware, not fabricated.

- [ ] Write failing spatial tests for same-range flat background/critical object, valid non-ground semantics, low confidence, sparse far uncertainty, and unavailable motion.
- [ ] Select the smallest correction supported by PR B evidence; document formulas, ranges, missing-data behavior, and why intended critical signals have a reachable gate.
- [ ] Implement class importance and real support/density without expanding permanent leaves or rescanning the full map per point.
- [ ] Integrate the agreed quality-boundary correction from Samay; no duplicated provider/terrain logic.
- [ ] Preserve governor protection, hysteresis, point ownership, conservation, and DistanceLOD behavior.
- [ ] Run targeted tests, full C++ tests, relevant Python tests, and bounded real smoke; stop if spatial support/attribution remains broken.
- [ ] Commit: fix(policy): use measured support and selective semantic importance.
- [ ] Separate further fixes only when independently testable; no catch-all tuning commit.

Changing refinement architecture, replaying raw support, or redesigning the governor requires a separately reviewed scope, not silent additions to this PR.

## PR D — Independent Utility benefit proof (#60)

**Proposed branch:** feat/utility-benefit-evidence, from approved integrated main.

**Owned files:** benchmark challenge/evaluation/report modules, targeted benchmark tests, compact reports and plots. Do not edit production policy/config to improve results in this PR.

**Interfaces:** Existing frozen manifest and policy names; identical ObservationFrame input digests; canonical quality_resource.comparison_rows(report) field meanings. Vinay owns the presentation of those results.

- [ ] Write/verify a deterministic world-coordinate spatial-overlap fixture before interpreting promotion precision/recall.
- [ ] Freeze exact comparison inputs before observing policy outcomes; keep GT-potential and actual neural modes distinct.
- [ ] Run bounded DistanceLOD/Utility comparisons first; evaluate critical completion/accuracy/retention and background quality jointly.
- [ ] Record actual promotions, spatial support, resource cost, churn, missing support, and rejection reasons.
- [ ] Proceed to larger runs only when the bounded result justifies the expense.
- [ ] Repeat the selected comparison; report sampling limitations and timing variance.
- [ ] Exercise the integrated viewer without changing challenge selection to produce a prettier example.
- [ ] Run benchmark-specific and relevant regression tests.
- [ ] Commit harness corrections/tests separately if needed: fix(benchmarks): verify spatial utility attribution.
- [ ] Commit compact results: docs(benchmarks): record production utility quality-resource evidence.

If benefit is not established, preserve truthful failure evidence and keep #60 open or explicitly blocked by the demonstrated limitation. Do not label lack of evidence as success.

## PR E — Final current-main evidence (#62)

**Proposed branch:** evidence/current-main-benchmark, from main after required implementation and packaged-app acceptance.

**Owned files:** compact benchmark JSON/CSV/plots, reproduction documentation, narrow benchmark fixes only if independently reviewed. No product code changes bundled with final results.

**Interfaces:** All four production policies share identical observations; complete canonical report loads/exports through Vinay's integrated UI.

- [ ] Verify clean main, build identity, dataset/model availability, configurations, and hardware.
- [ ] Record the exact clean execution SHA before running. The later evidence-commit SHA is distinct and must not replace the execution SHA.
- [ ] Run equal-input four-policy comparison with clear neural/GT mode, map/perception timing scopes, memory scopes, and quality reference definitions.
- [ ] Collect >=20 samples for defensible p95 and >=100 before claiming reliable p99; otherwise explicitly mark limitations.
- [ ] Repeat the canonical comparison and report variability/determinism.
- [ ] Verify JSON/CSV consistency, provenance, units, missing values, and report loading/export in the packaged app.
- [ ] Keep large traces/scans/weights external; include compact evidence plus commands and input digests.
- [ ] Commit: docs(benchmarks): publish reproducible integrated-main comparison.

## Commit, review, and regression policy

- Each PR branches from latest approved main when its execution begins. Avoid long-lived stacked branches for this collaboration.
- One primary writer per shared file at a time; others prepare tests/analysis in disjoint files.
- Each commit is coherent and includes its regression tests. Prefer 1–3 focused commits per PR, not separate broken test-only commits.
- Aim for roughly 300–600 manually authored changed lines per PR. This is a review target, not a reason to omit required tests. Split larger scopes at independently working boundaries; compact generated evidence is reviewed separately.
- A transport producer and consumer must merge atomically; do not split a schema migration into temporarily incompatible PRs.
- Before opening a PR: inspect git diff --stat, git diff --check, source changes, interface compatibility, test results, and real-path evidence where required.
- For map/policy changes: Release build, CTest, ownership/conservation/topology tests, relevant Python protocol/runtime tests, and bounded performance checks.
- For renderer/transport changes: frontend tests/check/build, relevant Python visual tests and Rust telemetry/control tests; desktop real-backend acceptance where available.
- For benchmark-only changes: benchmark suite, provenance/schema/metric tests, report loading, and relevant underlying map regressions; no unrelated expensive full datasets.
- Run a combined regression gate after each integrated wave. Record skips and external-only blockers rather than presenting them as local passes.
- Integrate approved PRs one at a time. Review conflicts against both owners' intended behavior, not just syntactic resolution. Never resolve shared-interface conflicts by blindly keeping one side.
- Request explicit authorization before commits/pushes/PR creation during execution. This planning step creates no Git branches, commits, pushes, or GitHub comments.

## Completion / no-go conditions

The four issues are complete only when their individual acceptance criteria are satisfied on integrated code. #56 visibility does not prove #57 signal correctness; #57 correctness does not prove #60 benefit; #60 bounded evidence does not replace #62 final current-main measurements.

If no useful Utility advantage is measured, or split support prevents fidelity, report that limitation and request a new scoped decision. Do not widen these PRs into V2 integration, a map rewrite, or benchmark manipulation.
