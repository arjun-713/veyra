# Smooth replay (demo-grade cached playback)

Veyra has two explicitly different playback modes. They share the viewer but
nothing else.

## LIVE PROCESSING (truthful pipeline)

Dataset frame → perception → mapper → telemetry → visualization.

Playback speed is constrained by actual computation. This is where the real
numbers come from:

- processing FPS (completed backend frames/sec)
- perception latency, map latency, end-to-end latency
- mapper RSS / map memory

These metrics are never faked or altered. The next dataset frame strictly
waits for full backend processing (single serial worker, one frame in
flight), so live playback advances at compute speed with latest-only
coalescing on bursts.

## SMOOTH REPLAY / DEMO MODE (precomputed presentation)

Frames were already processed once. Replay never reruns neural inference,
ground segmentation, terrain processing or mapping per visible frame:

precomputed real visualization snapshot → lightweight decode → GPU buffers → display

- Renderer: 60 Hz via `requestAnimationFrame` (unchanged render loop).
- Dataset presentation rate: default **30 snapshots/sec** (~33.333 ms each).
  At 60 Hz that is roughly two render refreshes per LiDAR frame.
- 488 SemanticPOSS-00 frames at 30 FPS ≈ **16.3 s** of demo playback.
- At 60 FPS, the same 488 frames take ≈ **8.1 s** per pass. Cached replay
  loops through the real sequence until Pause is pressed.
- The desktop session defaults to the full sequence at 30 FPS. After its
  first-frame preview, Veyra prepares the full replay in the background or
  reuses a compatible cache. Progress appears beside the controls. When it
  reads `frames ready`, the ordinary Play button opens that cache and plays
  until Pause; the sequence loops at the end.
- The Playback rate selector accepts 10 / 15 / 30 / 60 FPS. Smooth Replay
  presents at the selected 15/30/60 rate, and its rate selector can override
  the session rate.
- **Replay FPS is a presentation rate, NOT processing throughput.** The UI
  labels it `REPLAY · CACHED · 30 FPS`, processing reads `N/A DURING REPLAY`
  (`RECORDED` where historical values are shown), and each cached frame
  carries `recorded_telemetry` from the cache build.

### Latest frame wins

The backend serves cache positions in order. If the UI stalls, the desktop
transport retains only the newest snapshot rather than queueing large late
frames. Coalesced snapshots count as transport/presentation drops, not backend
processing drops. Displaying every snapshot at the selected rate still requires
sufficient disk, IPC and renderer capacity.

### Cache format (`*.veyra-replay`, schema v1)

Single file, `mmap`-friendly, under git-ignored `data/cache/replays/` for
the CLI or `~/.cache/veyra/replays/` for automatic desktop preparation:

```
VYRAREPL | u32 schema | u32 header_len | header JSON | u32 nframes |
nframes × (frame_index, meta_len, payload_len, meta_off, payload_off, sha256) |
per-frame metadata JSON + payload bytes
```

Per-frame payloads are byte-identical to live `pack_visualization` output
(17-float points, 17-float cells, optional 15-float physical layers), so the
existing `schema_version 2|3` viewer validation consumes them unchanged.

Provenance (fail-closed): dataset, sequence, frame range, code SHA,
config digest, perception digest, policy, semantic provider, budgets,
protocol/viz schema versions. A policy or config mismatch invalidates the
cache — prepare one cache per policy, or close the replay and rebuild.

### Preparing a cache

The desktop prepares automatically after a full-sequence preview and reuses
an exact configuration match on later sessions. This may take time because
all source frames must pass through perception and mapping once. A failed
preparation leaves Live processing available. To prepare manually:

```bash
python3 scripts/prepare_replay_cache.py \
  --dataset semanticposs --sequence 00 --start 0 --count 488 \
  --policy utility_lod --preset Quality --fps 30
python3 scripts/verify_replay_cache.py data/cache/replays/<file>.veyra-replay
```

The CLI prints `Preparing smooth replay… n / N`; the desktop shows the same
count in its viewer. Generated caches are never committed to Git.

### Runtime replay commands

`replay_open {path, fps}` / `replay_close` / `replay_status`, plus the usual
`start / pause / step / seek / speed` for cached playback (restart = seek 0,
no mapper rebuild). Play schedules background prefetch and returns without
filling the cache on the control worker. Playback ticks consume ready frames;
a cold frame is retried in order while Pause and other controls remain
available. Explicit seek/step may synchronously read one cold snapshot,
using a separate file handle from the prefetch worker.
`reset / sequence / policy` are rejected while a replay is open — the cache
belongs to its recorded policy/config.

After opening, change the presentation rate with:

```json
{"id":"rate-1","command":"replay_rate","args":{"fps":60}}
```

`replay_rate` accepts numeric **15 / 30 / 60 FPS** and requires an open
cache. It works while paused or running, preserves position and generation,
and never recomputes snapshots. The result is `{ "replay": { ... } }`,
including `fps` (selected rate) and `effective_fps` (`fps × speed`). A rate
or speed change schedules the next tick one new interval from the command;
resuming with Play makes the next snapshot immediately eligible. The legacy
`replay_open` FPS range remains 1–60 (including the configured 10 FPS option).

The worker waits on the command queue until the next playback deadline,
capped at 20 ms when idle; it does not impose a 20 ms floor on 60 FPS.
The backend publishes every cache position in order, including all 488
positions of a 488-frame cache, and reports `ended` with the final snapshot.
Disk underruns delay that sequence rather than skipping frames or emitting
a catch-up burst. The transport/viewer remain latest-only, so actual display
of every publication still depends on consumer capacity; transport drops
remain visible in `visualization_dropped`.

The serve path is instrumented: `replay_serve_ms` per frame, byte-bounded
look-ahead ring (128 MiB / 64 frames max), `underruns` vs `prefetch_hits`
counters in `replay_status`. Admission and eviction use exact encoded
metadata + payload sizes from the frame table; the byte cap includes an
in-flight read (`prefetch_in_flight_bytes`) as well as ready snapshots
(`prefetch_bytes`). These counters are not a measurement of process RSS or
Python object overhead. Repeated retries of the same cold position count as
one underrun. Prefetch read errors become a replay error at that position;
after a backward seek, farther-ahead frames yield byte budget to the next
required frame so retained data cannot starve playback. On a read error,
the control worker stays available to close/reopen the cache. Close cancels
prefetch without waiting for an OS read, prevents retired data from entering
a replacement cache, and leaves live playback paused (or unconfigured when
there is no live session).

### Accumulation in replay

`Accumulate N scans` remains display-only and pose-aligned (world frame);
sensor-frame scans never accumulate. For demo, 5 scans is the default
preset — 20 scans smears motion. Points change only when the next real
cached scan is presented; only camera/ego presentation transforms may
interpolate between poses, never map data or observations.

### Offline demo capture (fallback)

If WebView playback ever stalls for platform reasons:

```bash
python3 scripts/export_demo_clip.py --replay <file>.veyra-replay --out demo/
```

renders real cached snapshots deterministically (`frame_000001.ppm` …) and
encodes 30 FPS H.264 1080p with ffmpeg. No intermediate point clouds are
fabricated.

### Files

- `runtime/replay_cache.py` — format, provenance, reader/writer
- `runtime/service.py` — replay mode (`replay_open/close/status`, cached tick)
- `scripts/prepare_replay_cache.py`, `scripts/verify_replay_cache.py`
- `scripts/export_demo_clip.py` — offline capture fallback
- `apps/desktop/src/renderer/replay-clock.ts` — presentation clock
- `apps/desktop/src/renderer/{App,MapCanvas}.svelte` — mode UI, hot-path fixes
- `tests/test_replay_{cache,runtime}.py`, `apps/desktop/tests/replay-clock.test.ts`
