# Phase B Desktop Control and Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Tauri desktop app a real, state-aware control and visualization surface for the existing Veyra Python/C++ pipeline without redesigning the established UI.

**Architecture:** Keep the shared Control API and backend as the source of truth. Extend the Tauri bridge only for missing safe operations, bind Svelte controls to validated commands/events, and expose real telemetry/provenance. Keep Electron untouched until parity is independently proven.

**Tech Stack:** Rust/Tauri 2, Svelte 5, TypeScript, Vite, Three.js, existing Python runtime, existing C++ mapper, Node test suite, Rust tests.

**Spec:** Phase B requires no dead controls, legal state transitions, real dataset/runtime control, real layers and policies, authoritative telemetry, validation/benchmark actions, renderer sampling visibility, E2E coverage, and packaged-app evidence where locally possible.

## Global Constraints

- Work only in `.worktrees/phase-b-complete` on `phase-b/desktop-complete`.
- Preserve the existing visual language and backend interfaces.
- Do not fabricate metrics or silently turn unavailable data into zero.
- Do not modify core map topology, UtilityLOD, release packaging, or unrelated CI.
- Every user-visible action must either execute a real backend operation or be disabled with an explanation.
- Add focused tests before/alongside implementation and run the relevant gates before claiming completion.

## Tasks

- [x] Trace and close the shared command surface: layer, stop/start/restart, validation, dataset safety checks, and typed Tauri wrappers.
- [x] Add an explicit Setup/Runtime flow with truthful capabilities, health, legal playback controls, and error/recovery states.
- [x] Bind layers and policy changes to backend commands; expose current policy and resolution distribution from telemetry.
- [x] Add perception/performance/memory provenance panels and remove stale Electron/unavailable wording.
- [x] Expand benchmark/validation actions and results with measured/analytical/unavailable labels and export paths.
- [x] Make renderer sampling and WebGL failure/recovery visible and testable.
- [x] Add focused UI/core/Tauri integration coverage and run the full Phase A gate plus Tauri build/evidence.

## Verification Gate

- [ ] `npm test`, `npm run check`, `npm run build` in `apps/desktop`.
- [ ] Rust fmt/test/clippy and Tauri no-bundle build.
- [ ] Existing C++/Python/validation gates remain green.
- [ ] Worktree contains no generated build artifacts or unrelated edits.
