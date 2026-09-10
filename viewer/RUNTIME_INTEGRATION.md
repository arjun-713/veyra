# Runtime and map integration contract

`viewer/runtime.py` is the local dataset-player composition point. It consumes
the repository's dataset settings read-only, constructs the public dataset
adapter, and calls `PerceptionPipeline.process()` once per source frame. The
browser receives only a decimated payload; pipeline execution retains the full
point-aligned frame.

Run the selected sequence from the repository root after configuring the app:

```bash
./build/apps/player/veyra_player --runtime-config viewer/runtime.example.json
```

The example deliberately enables the real optional Patchwork++ and temporal
stages. If Patchwork++ is absent, the pipeline reports `ground: unavailable`
with its backend diagnostic; terrain remains unavailable. No fallback ground,
terrain, or motion field is fabricated. An ONNX semantic backend is also not
mocked: the current public provider requires an explicitly created ONNX
session, so this player supports `semantic.mode: ground_truth` until a session
factory is supplied by the perception integration owner.

## Persistent map engine

If `map.executable` names `veyra_benchmark`, the runtime starts one
`VEYRA_ENGINE 2` process for the selected playback session. It sends the same
canonical V2 `F`/`P`/`E` records as offline benchmarks; no viewer-specific
observation conversion exists. The C++ map consumes semantic class/confidence,
tri-state traversability, ground/terrain confidence, motion probability,
geometry complexity, observation quality, and last-seen timestamp as bounded
cell sufficient statistics. Raw point history is never retained.

The engine supports this process-lifetime API:

1. `open(config)` starts `VEYRA_ENGINE 2` and acknowledges its protocol version.
2. `reset()` clears the engine before a
   sequence switch or explicit reset; it must acknowledge completion.
3. `process_frame(frame_id, timestamp, pose, observations)` accepts point
   observations containing `xyz`, `semantic_class`, `semantic_confidence`, and
   a tri-state traversability value (`drivable`, `non_drivable`, `unknown`).
   `unknown` must be representable, not collapsed to the current binary field.
   Per-point velocity feeds the policy's radial range rate for predictive
   refinement; see `docs/field-mapping.md`.
4. The per-frame response returns actual level counts, tile/point counts,
   logical and allocator-accounted map bytes, topology changes, map-update
   percentiles, current/peak process RSS, and the `rejected_out_of_window`
   count for points that parsed but fell outside the active window.
5. `M [budget]` returns up to `budget` live leaves
   (`l, ix, iy, z, c, m, q, d` with `cell_count`/`total_leaves`) for map-layer
   rendering without advancing map state. The viewer MAP ELEV / MAP SEM /
   MAP MOTION / MAP LOD modes consume it on demand.
6. A malformed record aborts its frame with exactly one `unavailable` line;
   the engine then drains the rest of that frame silently until the next
   frame/command boundary, so an error storm can never deadlock the bridge.
7. `status()` and every error response identify unavailable backends and
   rejected frames without substituting output. `close()` releases the engine.

`RuntimeSession` serializes ordered playback, resets its perception pipeline
and engine together, and closes the engine on shutdown. Browser payloads remain
decimated separately from map ingestion.

Build the player and the real bridge target before using the example path:

```bash
cmake -S . -B build -DVEYRA_BUILD_APPS=ON
cmake --build build --target veyra_player veyra_benchmark -j
```
