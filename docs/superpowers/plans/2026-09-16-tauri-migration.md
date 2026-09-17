# Veyra Tauri Desktop Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Each phase requires implementation, tests, a runnable feature check, an audit, and a commit before the next phase.

**Goal:** Replace the Electron shell with a secure Tauri 2 desktop product while preserving the existing Svelte/Three.js/uPlot UI and Python/C++ runtime.

**Architecture:** A Rust Tauri application owns one typed Veyra Control API and supervises the existing Python runtime and C++ mapper. The Svelte frontend, CLI, and MCP server call that API through narrow adapters; none owns runtime truth or arbitrary process/filesystem access.

**Tech Stack:** Tauri 2, Rust, Svelte 5, TypeScript, Vite, Three.js, uPlot, Python, C++20, JSON-lines protocol, GitHub Actions.

**Spec:** `/home/arjun/.codex/attachments/a1842be5-cb76-46d6-af00-086d08bf1b92/pasted-text-1.txt`

## Global Constraints

- Preserve the current Svelte visual language and existing Python/C++ mapping/perception implementations.
- Tauri capabilities use least privilege; no arbitrary shell, filesystem, or process APIs reach the frontend.
- Keep Electron only as a temporary behavioral reference and remove it only after verified parity.
- Do not commit datasets, model weights, generated maps, secrets, or platform signing credentials.
- Linux validation may be executed locally; Windows and macOS claims require actual CI or host evidence.
- Every phase must have production wiring, meaningful tests, a runnable check, explicit error handling, documentation, and CI coverage before commit.

## Phase Map

### Phase 1: Electron inventory and migration contract

**Files:** `docs/desktop-electron-audit.md`, `apps/desktop/src/{main,preload,supervisor,api,core,packaging}.ts`, `runtime/service.py`, `runtime/protocol.py`, `apps/desktop/src/renderer/*`.

Trace every visible control through IPC, supervisor, Python runtime, C++ mapper, event, and renderer state. Record KEEP, REIMPLEMENT, FIX, and REMOVE decisions, protocol fields, error states, and parity tests. Run the current Electron app and existing desktop tests. Do not alter Electron behavior in this phase.

### Phase 2: Tauri shell and preserved renderer

**Create:** `src-tauri/Cargo.toml`, `src-tauri/src/main.rs`, `src-tauri/src/commands/mod.rs`, `src-tauri/capabilities/default.json`, `src-tauri/tauri.conf.json`.

Configure Tauri 2 with the existing Vite/Svelte output, a least-privilege capability manifest, development and packaged resource paths, and a Linux boot smoke test. The renderer must load without Electron globals and must have an explicit adapter boundary for native commands.

### Phase 3: Shared typed Control API

**Create:** `src-tauri/src/control/{mod.rs,types.rs,state.rs}`, `src-tauri/src/services/{dataset,playback,policy,layer,telemetry,diagnostics,benchmark}.rs`, `src-tauri/src/commands/*.rs`.

Define versioned request/response/error types and controllers for status, dataset, playback, policies, layers, metrics, diagnostics, and benchmarks. Add Rust unit tests for state transitions, impossible commands, validation, bounded payloads, and missing evidence. Tauri commands must be thin calls into this service layer.

### Phase 4: Rust runtime supervision and protocol

**Create:** `src-tauri/src/supervisor/{mod.rs,process.rs,protocol.rs,errors.rs}`.

Implement scoped child-process startup, health checks, PID/process identity, stdout/stderr capture, bounded command timeouts, crash detection, restart policy, duplicate-start prevention, protocol-version checks, and platform-aware termination. Test with fixture child processes for crash, hang, malformed response, invalid dataset, startup failure, and clean shutdown. Keep Python and C++ unchanged except for explicitly versioned protocol compatibility fixes.

### Phase 5: Frontend adapter and state-driven controls

**Modify:** `apps/desktop/src/renderer/{App.svelte,Dashboard.svelte,MapCanvas.svelte,Chart.svelte,dashboard.ts}`, `apps/desktop/src/api.ts`, `apps/desktop/src/core.ts`.

Replace direct Electron preload calls with a typed Tauri adapter. Make controls derive availability from canonical backend state, add loading/recovering/stopped/error states, preserve real first-frame behavior, and expose unavailable metrics honestly. Add frontend tests and Tauri integration tests for every control family.

### Phase 6: Telemetry, diagnostics, and rendering hardening

**Create/modify:** `src-tauri/src/telemetry/*`, `src-tauri/src/diagnostics/*`, `runtime/telemetry.py`, `runtime/protocol.py`, `apps/desktop/src/renderer/*`.

Implement the versioned `TelemetryFrame` contract with validation, bounded histories, staleness, explicit unavailable values, separate UI/Python/C++/map memory, stage timing, queue/drop/deadline metrics, and exportable redacted diagnostics. Harden Three.js context loss, resize/high-DPI, resource reuse, sampling disclosure, and layer/policy transitions with deterministic browser tests where possible.

### Phase 7: Platform abstraction and packaging

**Create:** `src-tauri/src/platform/*`, `release/*`, platform packaging configuration.

Remove hard-coded developer paths and Linux-only assumptions from production paths. Add resource/config/log/temp directory resolution, sidecar lookup, termination, environment, and hardware telemetry abstractions. Configure Linux deb/rpm/AppImage, Windows NSIS/MSI, and macOS app/dmg workflows; emit a checksum-bearing release manifest. Each unsupported host capability must fail clearly rather than claim validation.

### Phase 8: CLI and MCP adapters

**Create:** `crates/veyra-cli/*` or `tools/veyra-cli/*`, `mcp/*`.

Expose the same Control API through `veyra` commands and a thin safe MCP server. Provide JSON output for every command, typed argument validation, bounded responses, and no arbitrary shell/filesystem/process tools. Add unit and integration tests proving CLI/MCP calls produce the same state transitions as Tauri commands.

### Phase 9: CI, end-to-end, soak, and Electron removal

**Modify/create:** `.github/workflows/*`, `apps/desktop/tests/*`, `tests/*`, `scripts/soak/*`, `docs/desktop-electron-audit.md`.

Add Ubuntu/Fedora/Windows/macOS checks for Rust, frontend, Python/C++, packaging, and smoke launch. Add full launch/load/play/pause/seek/policy/layer/error/recovery/shutdown E2E coverage, long replay RSS/queue/render/process-growth measurements, and artifact uploads. Remove Electron only after the parity matrix is fully green; make that removal a separate commit.

## Phase Gate

For each phase, record the following before committing:

```text
PHASE AUDIT
Functionality:       100% of phase scope
Integration:         production path exercised
Tests:               targeted tests pass
Error handling:      failure paths verified
Cross-platform:      supported claims evidenced or explicitly blocked
Overall phase:       PASS TO COMMIT only when no in-scope gap remains
```

Known cross-platform or signing limitations must be reported as checkpoints, never hidden behind successful Linux builds.
