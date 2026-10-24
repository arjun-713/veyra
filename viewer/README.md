# Viewer — Veyra Scope

Local dataset visualizer. Real files only: it serves decimated observations
from the repository's dataset adapters. SemanticPOSS flows through
`datasets.semanticposs.SemanticPOSSDataset`, so pose transforms, timestamps,
label pairing, and the 100 m crop are the same inputs the mapper will consume.
RELLIS-3D and SemanticPOSS both use their repository dataset adapters.

## Run

From the repo root:

```bash
python3 viewer/server.py
# Veyra viewer  repo=...  ->  http://127.0.0.1:8765/
```

Requires `numpy` (`requirements.txt`). `pyyaml` used when present.

## Configured player runtime

The viewer can run one selected local sequence through the configured public
`PerceptionPipeline`, rather than serving adapter defaults:

```bash
./build/apps/player/veyra_player --runtime-config viewer/runtime.example.json
# or: python3 -m viewer.server --runtime-config viewer/runtime.example.json
```

`runtime.example.json` is viewer-owned. It selects the dataset/sequence and
enables real perception stages; `configs/datasets.yaml` remains read-only and
continues to own dataset roots, sequence banks, and range limits. Build the
example's player and persistent mapper before running it:

```bash
cmake -S . -B build -DVEYRA_BUILD_APPS=ON
cmake --build build --target veyra_player veyra_benchmark -j
```

`RuntimeSession` runs `PerceptionPipeline.process()` on every full source frame
before display sampling. Its config supports `ground_truth`, `cenet`,
`salsanext`, and `onnx` semantic modes; neural modes require a compatible local
checkpoint and dataset. Missing ground or temporal prerequisites are reported
as unavailable with diagnostics. Missing evidence is never synthesized.

The persistent mapper uses `VEYRA_ENGINE 4`, matching the canonical V4
observation stream. Session reset clears perception and map state together;
shutdown closes the mapper. A malformed frame returns one unavailable response
and is drained to the next command boundary. See the [field contract](../docs/field-mapping.md)
and [product runtime](../docs/product-runtime.md) for protocol and metric details.

## What it does

- Dataset switch (RELLIS-3D / SemanticPOSS) from `configs/datasets.yaml`
- Sequence banks, frame scrubber + step strip, RUN playback with tempo
- Color modes: semantic / elevation / intensity / ground / terrain / motion;
  views: orbit / top / driver
  (top view adds 10/30/50 m survey rings plus an ego mark at the sensor origin)
- Readouts: frame id, point counts, class histogram, scan↔label pairing LED
- RUN plays a clip capped at 15 s (tempo 1X/2X/4X, base 10 fps), then auto-stops,
  timestamp, world-pose availability, and range-crop provenance
- Keyboard: `←/→` step (`shift` ×10), `space` run, `1`–`6` color, `O/T/D` view
- Deep links: `#d=rellis3d&s=00000&i=42`

Viz latency stays separate from map-update latency by design: the browser
renders decimated frames, Python does all file I/O.

Ground, traversability and motion are aligned payload fields. The viewer shows
their backend status and renders them as unavailable when the optional
Patchwork++ or temporal stage has not run; it does not turn default values into
invented measurements.

Map, LOD, FPS, map p95, and RSS readouts remain `UNAVAILABLE` unless the
configured map executable returned those actual fields. They are never derived
from browser timing or placeholder values.

SemanticPOSS returns both `labels` (raw dataset IDs for the current legend) and
`semantic_labels` (Veyra taxonomy IDs). The adapter supplies its versioned
dataset mapping by default; unmapped IDs remain class `0` (unknown).
