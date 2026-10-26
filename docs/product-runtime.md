# Product runtime

The desktop and batch benchmarks share the C++ map engine and
[observation protocol](architecture.md#observation-protocol). `python -m runtime`
owns dataset replay, perception, a bounded command queue, mapper supervision,
telemetry and benchmark jobs. It starts `build/apps/runtime/veyra_runtime --engine`;
Tauri forwards commands/events to the Svelte renderer.

Build/run and native packaging commands live in the
[desktop guide](../apps/desktop/README.md). Imported config cannot replace the
trusted mapper executable. Models and datasets remain external assets.

## Live processing

```text
dataset frame → perception → mapper → telemetry → visualization
```

One serial backend worker processes one frame at a time. Live playback advances
at actual compute speed; source rate and replay rate are not achieved-throughput
claims. Slow consumers receive the latest pending visual frame, with replacements
counted; map ingestion and ordered control responses remain separate.

Performance/Balanced/Quality profiles set playback/display budgets and governor
limits for cells, logical memory, RSS and frame time. Automatic/disabled/conserve
are explicit governor controls. Reports include budgets and intervention counters.

## Visualization contract

Runtime messages have a 16-byte little-endian `VYRA` header: version, kind,
JSON length and typed-payload length. Visualization schema 3 uses 17 float32
values per point and 17 per cell (68 bytes each); older schema-2 cells have nine
floats. Missing evidence stays unavailable. Complete benchmark artifacts travel
separately from bounded telemetry and display payloads.

Physical layers use an additive section:

- Engine handshake: `physical_layers_version: 1`.
- `MB`: existing sampled 17-float cell rows; `ML`: the same rows followed by
  ground/obstacle/overhead statistics in the identical sampled order.
- Each layer section row contains 15 float32 values (60 bytes): count, mean Z,
  min Z, max Z and population variance for each of the three layers.
- Empty layers have count zero and NaN statistics (null in JSON).
- Python requests `ML` only when advertised, otherwise uses `MB`.
- Visualization metadata supplies layer version/count/offset/stride. Validation
  rejects incompatible, overlapping or truncated sections and count mismatches.

The Rust bridge accepts visualization schemas 2/3. Inspection uses the last
painted frame. [Desktop inspection](../apps/desktop/README.md#judge-view-and-cell-inspection)
explains how to view the layers. Focused transport verification uses fresh
`VEYRA_RUNTIME_BINARY` / `VEYRA_BENCHMARK_BINARY` and the engine-service,
visualization, bridge, desktop physical-layer and Rust telemetry tests; fixtures
check alignment, missing support and malformed sections, not scene quality.

## Display sampling and accumulation

`apps/desktop/src/renderer/accumulation.ts` overlays bounded recent scans only
in world coordinates. Seeking backward or changing sequence resets history;
older scans drop classes 1–8 to limit traffic smearing. Replay defaults to five
accumulated scans. Accumulation never feeds the mapper.

Cell selection reports all/recent/folded/folded-nearest modes and a native
resolution radius. The renderer also clamps to GPU capacity. These display
budgets do not change the accepted input or internal map resolution.

## Telemetry

Perception, binary bridge, C++ mapping, visualization preparation and renderer
timing have separate scopes. Host-supported RSS is measured; missing OS/GPU
counters stay null. Python latency and C++ map percentile windows are bounded
to 600 samples. Live desktop charts use a trailing 60 seconds and at most 3,600
samples, freeze when paused and reset with the session. Sampling follows
processed frames and bridge coalescing. Full definitions and Performance versus
Evaluation behavior are in the [benchmark contract](benchmark-contract.md).

## Smooth replay

```text
processed visualization cache → decode → GPU buffers → display
```

Replay presents previously processed snapshots without rerunning perception or
mapping. Its selected FPS is presentation rate. The UI badges `REPLAY · CACHED`;
cached measurements are `RECORDED`, and absent processing measurements show
`N/A DURING REPLAY` rather than stale live values.

The desktop defaults to a full-sequence session at 30 FPS, preparing or reusing
a compatible cache after the first preview. Progress appears beside playback;
Play uses the ready cache and loops until Pause. Session rates include
10/15/30/60 FPS; an open cache accepts `replay_rate` at 15/30/60. For example,
488 snapshots nominally take 16.3 s at 30 FPS or 8.1 s at 60 FPS; disk, IPC and
renderer capacity determine actual presentation. The render loop uses
`requestAnimationFrame`; interpolation may affect camera/ego pose, never map data.

### Cache format and preparation

The schema-1 `*.veyra-replay` container is an indexed file:

```text
VYRAREPL | u32 schema | u32 header_len | header JSON | u32 nframes |
index(frame_id, lengths, offsets, sha256) | metadata/payload blobs
```

Payloads match live visualization rows, including optional physical layers.
Provenance records dataset/sequence/frame selection, code SHA, configuration and
perception digests, policy, provider, display budgets and protocol/schema versions.
Policy/config mismatch invalidates reuse. CLI caches live under ignored
`data/cache/replays/`; desktop automatic preparation uses `~/.cache/veyra/replays/`.

```bash
python3 scripts/prepare_replay_cache.py \
  --dataset semanticposs --sequence 00 --start 0 --count 488 \
  --policy utility_lod --preset Quality --fps 30
python3 scripts/verify_replay_cache.py data/cache/replays/<file>.veyra-replay
```

Every source frame must first pass through the pipeline; preparation can take
time. Failure leaves Live available. Generated caches stay outside Git.

### Commands and backpressure

`replay_open {path, fps}`, `replay_close`, and `replay_status` manage the cache.
`start/pause/step/seek/speed` operate on cached frames; restart seeks to zero.
`reset/sequence/policy` are rejected while the cache is open. A rate change is:

```json
{"id":"rate-1","command":"replay_rate","args":{"fps":60}}
```

It works paused or running, retains position/generation and returns replay
status with selected `fps` and `effective_fps = fps × speed`. Opening accepts
1–60 FPS; changing rate accepts 15/30/60. Play makes the next snapshot eligible
immediately. Speed/rate changes set the next deadline one interval ahead.

Play schedules background prefetch and returns promptly. Ticks consume ready
frames; cold reads delay ordered delivery instead of skipping/catch-up bursts.
Seek/step may synchronously read one frame using a separate file handle. The
worker's idle wait cap is 20 ms, not a minimum interval at 60 FPS.

Prefetch is bounded to 128 MiB / 64 frames, counting exact encoded bytes for
ready and in-flight reads. Status exposes `prefetch_bytes`,
`prefetch_in_flight_bytes`, hits and underruns; these are not RSS measurements.
A cold position counts one underrun across retries. Backward seek evicts farther
look-ahead data if needed. Errors surface at consumption; controls remain
available to close/reopen. Close cancels admission without waiting for an OS
read and prevents retired frames reaching a replacement session.

The backend publishes positions in order and marks the final snapshot ended;
the desktop may loop. Transport/viewer retain the latest frame, so displayed
snapshots can be dropped when consumers lag. `visualization_dropped` discloses
those presentation drops separately from backend processing drops.

### Offline capture

```bash
python3 scripts/export_demo_clip.py --replay <file>.veyra-replay --out demo/
```

This exports deterministic PPM frames and a 30 FPS H.264 clip via ffmpeg from
real cached snapshots. It adds no inferred intermediate point clouds.

Implementation: `runtime/{service,replay_cache,visualization}.py`,
`apps/desktop/src/renderer/replay-clock.ts`, and `App.svelte` / `MapCanvas.svelte`.
Regression tests: `tests/test_replay_cache.py`, `tests/test_replay_runtime.py`,
and `apps/desktop/tests/replay.test.ts`.
