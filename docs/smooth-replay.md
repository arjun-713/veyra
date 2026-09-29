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
- **Replay FPS is a presentation rate, NOT processing throughput.** The UI
  labels it `REPLAY · CACHED · 30 FPS`, processing reads `N/A DURING REPLAY`
  (`RECORDED` where historical values are shown), and each cached frame
  carries `recorded_telemetry` from the cache build.

### Latest frame wins

If the UI stalls, replay jumps to the snapshot for the current replay time
instead of queueing late frames. Skipped snapshots count as
`presentation_drops` — a presentation metric, unrelated to backend
processing drops. The backend `Outbox` and the desktop `EventRelay` were
already latest-only; the replay clock (`renderer/replay-clock.ts`) makes the
policy explicit and measurable.

### Cache format (`*.veyra-replay`, schema v1)

Single file, `mmap`-friendly, under git-ignored `data/cache/replays/`:

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

### Preparing a cache (once, before the demo)

```bash
python3 scripts/prepare_replay_cache.py \
  --dataset semanticposs --sequence 00 --start 0 --count 488 \
  --policy utility_lod --preset Quality
python3 scripts/verify_replay_cache.py data/cache/replays/<file>.veyra-replay
```

Preparation runs the full live pipeline and may take a long time; that cost
is paid once, never during playback. Progress prints `Preparing smooth
replay… n / N`.

### Runtime replay commands

`replay_open {path, fps}` / `replay_close` / `replay_status`, plus the usual
`start / pause / step / seek / speed` which serve cached snapshots instantly
in replay mode (seek <100 ms typical, restart = seek 0, no mapper rebuild).
`reset / sequence / policy` are rejected while a replay is open — the cache
belongs to its recorded policy/config.

The serve path is instrumented: `replay_serve_ms` per frame, byte-bounded
look-ahead ring (128 MiB / 64 frames max), `underruns` vs `prefetch_hits`
counters in `replay_status`.

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
