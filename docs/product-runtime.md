# Product runtime and desktop

Veyra's long-running product path is separate from the batch benchmark while
sharing the same observation mapping and C++ engine implementation.

```text
dataset adapter -> perception pipeline -> binary ObservationFrame
  -> C++ adaptive map + resource governor -> bounded telemetry + typed visuals
  -> Tauri commands/events -> Svelte renderer
```

`python -m runtime` owns replay state, the bounded command queue, perception,
map child supervision, telemetry windows and benchmark jobs. The mapper runs as
`build/apps/runtime/veyra_runtime --engine`; the desktop shell never performs
perception or map work. Renderer backpressure replaces an obsolete pending visual frame
with the newest frame and counts that replacement. Control responses remain
ordered and bounded.

The local protocol starts each message with a 16-byte little-endian `VYRA`
header containing version, message kind, JSON metadata length and typed payload
length. Observation points cross Python to C++ in a packed binary frame. UI
visualization schema 3 uses 17 little-endian float32 values per displayed point
and 17 per map cell (68 bytes each). An optional physical-layer section adds
15 floats per displayed cell. The desktop also accepts older schema-2 visuals.
Telemetry, full benchmark artifacts and sampled visualization data remain
separate products; see [physical-layer transport](physical-layer-inspection.md).

## Run

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cd apps/desktop
npm ci
VEYRA_PYTHON="$VIRTUAL_ENV/bin/python" npm run tauri:dev
```

Choose a dataset root in the desktop, select its adapter and sequence, validate
the configuration, then start or step playback. The mapper executable is set by the Tauri shell's trusted Rust
supervisor; imported configuration cannot launch another
program. Missing semantic models fail startup with an explicit perception
error rather than fabricated labels.

## Raw LiDAR accumulation (display only)

The Raw LiDAR view can overlay a bounded number of recent pose-aligned scans
(`apps/desktop/src/renderer/accumulation.ts`). It never feeds back into the
mapper, which still ingests one scan per frame. Only world-frame scans
accumulate; seeking backwards or changing sequence resets the history, and
older scans drop classes 1–8 (vehicles, riders, people) so moving traffic
does not smear. Cell display selection is bounded separately: the engine can
return recent leaves or fold them to coarser display cells, reporting the
selection mode and native-resolution radius in visualization metadata.

## Measurement scope

The runtime reports perception, binary bridge, C++ mapping, visualization
preparation and renderer timing independently. Process RSS is reported where
the host exposes it; unavailable OS/GPU counters remain null. Latency history is
limited to 600 frames in Python and map percentiles are limited to 600 samples
in C++. Live desktop charts retain a trailing 60 seconds with a 3,600-sample cap.
No target in the UI is presented as achieved until a named-machine benchmark
measures it.

Performance, Balanced and Quality profiles set playback/visual budgets and the
governor's active-cell, logical-memory, RSS and frame-time limits. Automatic,
disabled and conserve modes are explicit runtime controls. Every report exposes
the current budget and intervention counters.

## Packaging boundary

Tauri creates the OS-specific shell (see `apps/desktop/README.md`). `scripts/package_backend.py`
creates the versioned `backend/` contract documented in
`apps/desktop/README.md` from a native C++ runtime and a prepared, relocatable
Python environment. Datasets and model weights stay external and are never
bundled or committed. The release workflow produces checksums and conditionally
signs/notarizes when repository credentials are configured; it never substitutes
dummy credentials or reports an unsigned artifact as signed.
