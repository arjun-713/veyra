# Viewer Playback Implementation Plan

> **For agentic workers:** Execute these checked steps inline in the current checkout. The user wants this checkout updated for immediate testing.

**Goal:** Make Judge View select semantic display and range rings without moving the camera, and make the full dataset available for continuous 30/60 FPS cached playback.

**Architecture:** Keep live processing and cached replay distinct. Use the existing replay reader for timed presentation; never report replay rate as mapping throughput. Keep the desktop session's full sequence available, while the standalone runtime's low resource defaults remain bounded.

**Tech Stack:** Svelte/TypeScript viewer, Python runtime, Node and Python unit tests.

**Spec:** User request in this conversation; `docs/smooth-replay.md` describes the existing cache contract.

## Global Constraints

- Preserve the map and perception interfaces and the existing replay cache format.
- No new dependencies or fabricated performance claims.
- Preserve the user's untracked files.

---

### Task 1: Judge View selection

**Files:** `apps/desktop/tests/judge-clarity.test.ts`, `apps/desktop/src/renderer/judge-view.ts`, `apps/desktop/src/renderer/App.svelte`

**Interface:** `enterJudgeView(current, session)` returns a display state; the viewer applies it.

- [ ] Change the state test to start from `view: 'driver'`, `viewMode: 'both'`, `follow: false`, and `boundaries: false`; require those fields unchanged, `mode: 'semantic'`, and `showRings: true`.
- [ ] Run `node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test tests/judge-clarity.test.ts` from `apps/desktop` and confirm the new assertion fails.
- [ ] Make the preset copy the current camera and display fields, changing only semantic mode and rings; update the button description.
- [ ] Rerun the targeted test.

### Task 2: Full sequence and replay rate

**Files:** `apps/desktop/tests/runtime-config.test.ts`, `apps/desktop/tests/replay-clock.test.ts`, `apps/desktop/src/renderer/runtime-config.ts`, `apps/desktop/src/renderer/replay-clock.ts`, `apps/desktop/src/renderer/App.svelte`

**Interfaces:** Desktop default session config supplies `playback.full_sequence` and `playback.fps`; `resolveReplayFps` chooses the explicit replay selection.

- [ ] Add tests requiring desktop preview status to cover the full sequence with 30 FPS selected by default, and an explicit 60 FPS replay selection to win over session settings.
- [ ] Run the targeted Node tests and confirm the assertions fail.
- [ ] Update desktop defaults and replay selection logic. Keep the mode labels honest about cached presentation versus compute-bound live processing.
- [ ] Rerun targeted Node tests.

### Task 3: Continuous cached playback

**Files:** `tests/test_replay_runtime.py`, `runtime/service.py`

**Interface:** `ProductRuntime.tick()` serves cached frames at `replay_fps` and wraps after the final frame until `pause`.

- [ ] Add a test opening a three-frame real cache, advancing scheduled ticks through the end, asserting the next tick returns to index 0 with a new generation, and asserting pause holds the frame.
- [ ] Run `python -m unittest tests.test_replay_runtime` and confirm that assertion fails.
- [ ] Wrap cached playback at the sequence end and preserve the configured presentation cadence.
- [ ] Rerun the replay runtime tests.

### Task 4: Verification and demo readiness

**Files:** `docs/smooth-replay.md`

- [ ] Document full desktop sequence selection, replay looping, and 488-frame duration at 30 and 60 FPS.
- [ ] Run desktop tests/check/build and Python replay tests, then the complete CTest suite if sandbox permits loopback binds.
- [ ] Check whether a local 488-frame cache exists; if absent, report that preparation is required before a 30/60 FPS demo.

### Task 5: Connect ordinary Play to prepared replay

The existing implementation leaves Live as the default even after a full
dataset is configured. A live mapper cannot guarantee 30 or 60 processed
frames per second, so Play needs a prepared snapshot sequence for smooth
presentation. The UI must label cached presentation clearly.

Architecture-change checklist from `docs/development.md`:

1. **Requirement:** Ordinary Play should advance the configured full sequence
   at 30 or 60 presentation FPS until Pause.
2. **Existing component:** Reuse `ReplayWriter`, `ReplayReader`,
   `ProductRuntime` replay commands, and the existing visualization packer.
3. **Invariant impact:** No map-cell, resolution, occupancy, or safety-floor
   changes. Preparation invokes the same map pipeline once per source frame.
4. **Memory/cell delta:** No new cells. Replay prefetch stays bounded at
   128 MiB; the measured 488-frame LowResource demo cache is about 1.0 GiB
   on disk.
5. **Frame-time allocations:** Cache generation runs before smooth playback.
   The replay serving path keeps its existing bounded prefetch behavior.
6. **Benchmark:** Measure preparation time, cache bytes, and replay frame
   cadence on the real 488-frame sequence; retain recorded mapping metrics.
7. **Baseline:** Compare against current compute-bound Live playback and the
   existing replay backend timing check. Never present cached FPS as mapping
   throughput.
8. **Interface:** Keep preparation and replay behind replay cache/runtime
   interfaces. The UI can show progress and use the existing Play/Pause path.
