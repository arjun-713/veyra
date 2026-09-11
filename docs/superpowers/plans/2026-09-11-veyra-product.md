# Veyra Product Implementation Plan

> **For agentic workers:** Execute the assigned subsystem with test-driven development, then perform integration review and verification. The user explicitly selected parallel agents.

**Goal:** Turn existing perception and mapping engines into a supervised desktop product with bounded runtime state, honest telemetry, adaptive controls, and reproducible benchmarks.

**Architecture:** Electron owns lifecycle and a narrow validated preload bridge. A separate Python runtime owns dataset/perception scheduling and a dedicated C++ process owns mapping. Versioned bounded messages separate controls/telemetry from typed visualization buffers; the browser viewer and benchmark interfaces remain supported.

**Tech Stack:** C++20/CMake; Python 3.13; Electron, Svelte 5, TypeScript, Vite, Electron Forge, Three.js, uPlot.

**Spec:** User-provided Vinay ownership and P0–P3 product backlog, 2026-09-11; existing `docs/architecture.md`, `docs/map-correctness.md`, `docs/development.md`.

## Global constraints

- Preserve perception and grid ownership and public interfaces; do not rebuild their algorithms.
- Keep the 5/10/20/40 cm world lattice and safety floor; no fabricated measurements or unavailable evidence.
- Keep computation outside Electron, queues/history bounded, imported paths/configs untrusted, and datasets/models outside Git.
- Preserve existing CLI and CI benchmark schema. Signing, publication, model downloads and dataset acquisition require their actual external assets/credentials.
- Workspace: current checkout on `feat/veyra-product`; each agent owns disjoint files. Existing untracked Markdown is untouched.

## Architecture checklist

1. Requirement: user explicitly requests a desktop runtime, adaptive control, transport, telemetry, benchmark workspaces and packaging.
2. Existing components: reuse DatasetAdapter/ObservationFrame/PerceptionPipeline, Map/LOD/governor, V2 benchmark protocol, and Three.js visualization conventions.
3. Invariants: storage/fusion internals remain owned by the grid contributor; governor verifies complete sibling-group protection before requesting a merge.
4. Memory delta: no cell fields added for UI; runtime buffers have explicit size/history limits, measured separately from logical map bytes.
5. Frame allocations: remove point JSON at product visualization boundary; reuse GPU buffers; cap command/output queues and telemetry retention.
6. Benchmark: C++ invariant suite, runtime protocol/lifecycle regression tests, desktop IPC/buffer tests, real fixture integration, representative long-run tests and package smoke checks.
7. Baseline: preserve all four policy comparisons; correct reconstruction quality measurement before judging UtilityLOD, include signal ablations.
8. Isolation: new runtime package and desktop application consume existing subsystem boundaries; policy changes remain in policy/adapter code.

## Task 1 — Supervised runtime (runtime agent)

Files: create `runtime/`, `tests/test_product_runtime.py`; modify `viewer/runtime.py` and runtime playback tests.
Interfaces: `python -m runtime --repo PATH`; NDJSON requests `{id,command,args}`. Framed stdout uses `<4sHHII`, magic `VYRA`, version 1, JSON kind 1 or visualization kind 2, metadata length then binary payload length. Commands configure/start/pause/step/seek/reset/sequence/policy/speed/status/shutdown; bounded input and latest visualization output.

- [x] Add failing tests for forward seek integrating every intermediate frame and invalid sequence preserving current state.
- [x] Add failing tests for frame bounds, malformed requests, queue pressure, lifecycle, EOF shutdown and unavailable backend status.
- [x] Implement controller, framed service, binary visualization, dataset/config validation and replay.
- [x] Verify with `python -m unittest tests.test_product_runtime tests.test_runtime_player tests.test_runtime_map_bridge -v` and a real subprocess fixture.

## Task 2 — Desktop product (desktop agent)

Files: create `apps/desktop/`; own package/Forge/Vite/Svelte files, preload/main supervision, renderer components and desktop tests.
Interfaces: runtime Task 1 wire contract; typed allowlisted preload methods; native file pickers own filesystem selection and trusted backend executable paths.

- [x] Add failing tests for unsafe commands, malformed frames, bounded telemetry retention and process failure/restart.
- [x] Implement Map/Performance/Benchmarks/Configuration workspaces, dataset playback controls and diagnostics.
- [x] Reuse Three.js layer conventions with reusable typed buffers and instanced cells; render unavailable evidence explicitly; chart rolling samples with uPlot.
- [x] Configure Forge platform makers, CSP, context isolation, sandboxed preload and navigation denial.
- [x] Verify type checks, unit tests, production bundle and Electron E2E/package smoke tests where host permits.

## Task 3 — Adaptive controls (policy agent)

Files: `include/veyra/policy/policy.hpp`, `src/policy/policy.cpp`, `tests/test_policy.cpp`, policy configs, and `apps/benchmark/main.cpp` MapPolicyAdapter section only.
Interfaces: explicit `LodPolicy::begin_frame`, bounded state lifecycle, governor status; existing map API stays unchanged.

- [x] Add failing tests for point-count-independent frame hysteresis, promotion depth, cooldown/state eviction and noisy prediction.
- [x] Implement stable frame keys and bounded policy state.
- [x] Add failing tests for sustained overload/recovery, distant-low-value priority, sibling safety and action caps.
- [x] Implement budget/governor telemetry, presets and intervention accounting; provide adapter integration hooks.
- [x] Verify C++ tests and measure changed policy behavior without asserting unmeasured quality gains.

## Task 4 — Backend/transport/integration (root)

Files: shared engine extraction under `src/runtime/`, `apps/runtime/`, CMake; metrics bounded retention; benchmark quality/ablation tests; product CI/docs/config integration.
Interfaces: dedicated `veyra_runtime` executable reuses the same engine implementation as benchmark; legacy V2 preserved, versioned binary full-observation transport added behind explicit protocol selection.

- [x] Add a failing subprocess test proving a dedicated engine starts and handles malformed/valid session commands.
- [x] Extract shared engine entrypoint, leaving benchmark and runtime thin executables; integrate adapter edits before moving files.
- [x] Test and bound engine telemetry retention and subprocess shutdown; profile/record IPC separately.
- [x] Add hand-derived quality fixtures where coarse-cell averaging must lose detail; implement reconstruction RMSE/coverage and four-policy/ablation comparisons.
- [x] Run complete backend/Python/desktop checks; exercise integrated product against temporary deterministic dataset fixtures and record actual results.
- [x] Add product CI, platform packaging contracts and documentation that distinguish verified functionality from external signing/platform/data checkpoints.

## Acceptance tracking

P0: runtime, desktop, map integration, replay, task-manager telemetry, layers, policy controls and supervised errors.
P1: validated policy mechanics, governor, budgets, benchmark UI/schema, transport and renderer efficiency; representative quality gain must be established by actual datasets.
P2: long-run/error tests, config/dataset management, diagnostics, E2E, packaging/security.
P3: configurable signing/release/update mechanisms; no claim of signed releases without certificates or unrun platform results.
