# Perception — Mallik (arjun-713)

- `semantic/` — `SemanticProvider` interface + pretrained ONNX backends.
- `ground/` — Patchwork++ integration, ground evidence.
- `terrain/` — local geometric slope, roughness, step and traversability
  evidence.
- `temporal/` — world-frame cluster association and motion evidence.
- `pipeline.py` — composes these stages into `PipelineOutput`, containing one
  aligned `ObservationFrame` plus explicit backend status. Missing optional
  Patchwork++/ONNX backends remain `unavailable`; no fallback evidence is
  fabricated.

`configs/perception.yaml` is the checked-in production-safe default: it uses
dataset ground truth and explicitly disables optional stages. Load it with
`load_perception_pipeline(path)`. To enable ONNX, configure a local model path
and an explicit raw-ID mapping; the provider never downloads weights. To enable
Patchwork++, explicitly install a binding with `Parameters`/`patchworkpp`, then
set `ground.enabled: true`; its availability diagnostic is fail-closed.

The pinned CPU runtime is Python 3.13 with `numpy==2.2.6`,
`pypatchworkpp==1.4.1`, and `onnxruntime==1.22.0` (plus `pyyaml==6.0.2`).
Install with `uv pip install -r requirements.txt`; use a writable
`UV_CACHE_DIR` in managed environments. Patchwork++ needs no model asset.
ONNX inference still requires a compatible local semantic `.onnx` checkpoint;
weights are not downloaded or replaced when that asset is absent.
Terrain requires enabled ground, and temporal evidence requires both a dataset
timestamp and world-frame provenance.

`TemporalTracker` resets when an enabled pipeline changes dataset/sequence.
Semantic class only prevents incompatible association: a vehicle class does not
imply motion. Terrain stays `unknown` without valid ground support.

The viewer exposes the same aligned fields when present. Ground, terrain and
motion layers are intentionally rendered as unavailable when their backend
status says unavailable. See `docs/perception-terrain-temporal.md`.
