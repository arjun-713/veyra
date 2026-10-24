# Perception, terrain and temporal processing

`perception/pipeline.py` composes the `semantic/`, `ground/`, `terrain/` and
`temporal/` packages into `PipelineOutput`: an aligned `ObservationFrame`,
backend status, diagnostics and stage timings. Dataset/type conventions are
in the [dataset guide](../datasets/README.md); the mapper receives the same
contract regardless of provider.

## Configuration and semantics

Load `configs/perception.yaml` with `load_perception_pipeline(path)`. Its
checked-in defaults use dataset ground truth, enable ground/terrain, and disable
temporal processing. The `SemanticProvider` consumes XYZI plus optional labels
and returns mapped class IDs, confidence and source mode in `SemanticResult`.

| Mode | Backend / requirement |
| --- | --- |
| `ground_truth` | Mapped dataset labels; an oracle/evaluation source, not model inference. |
| `cenet` | PyTorch CENet, compatible SemanticPOSS checkpoint. |
| `salsanext` | Compatible local SalsaNext ONNX checkpoint. |
| `onnx` | Local ONNX model plus explicit raw-ID mapping and execution providers. |

Configured neural backends must initialize; they do not download or fabricate
weights. CENet's explicit ground-truth fallback option is separate from device
fallback and must remain visible in status.

CENet accepts `device: auto | cpu | mps` (default `cpu`). `auto` uses Apple
Silicon MPS only after a fixed-seed CPU-parity probe; a failed probe or mid-run
MPS failure records `pipeline_status.semantic_device_fallback_reason` and runs
CPU inference. Explicit `mps` fails closed. Dataset compatibility and checkpoint
availability must be validated before interpreting predictions.

## Ground and terrain

Patchwork++ supplies ground evidence through an installed binding exposing
`Parameters` / `patchworkpp`; it needs no model asset. The default config sets
its range explicitly to the mapper's 100 m envelope. Missing binding support is
reported as unavailable. Terrain needs enabled ground and combines semantic
and geometric evidence: slope, roughness, height spread, steps and local ground
gradients. Its output is `drivable / non_drivable / unknown`; missing ground
support leaves terrain unknown. The mapper's layer/occupancy rules are in
[map correctness](map-correctness.md).

## Temporal evidence

The tracker uses semantic clusters, ego-motion compensation, association and
centroid displacement. `semantic_class` is separate from `motion_probability`
and `motion_state` (`static / possibly_moving / moving / unknown`): a car or
person class alone does not establish motion.

Processing requires world-frame coordinates and genuine dataset pose/timestamp
provenance; unavailable metadata is reported rather than inferred. Enabled
trackers reset when dataset/sequence changes. Dynamic observations must not
permanently contaminate terrain. Ground, terrain and motion UI layers follow
the reported backend availability.

## Dependencies and packaging

Install the platform-selected `requirements.txt` dependencies into a venv.
Packaged Python is 3.13, except Windows x64 uses 3.12 for the published
Patchwork++ wheel. Intel macOS omits Patchwork++ because no upstream wheel is
available; ground/terrain remain unavailable there. ONNX still needs a supplied
compatible model. Torch is an explicit optional CENet dependency.

The runtime is headless; Tauri owns the UI. macOS staging omits unused Tcl/Tk
and `tkinter`. If using `uv`, select a writable `UV_CACHE_DIR` in managed
environments. Build and release instructions live in the
[desktop guide](../apps/desktop/README.md#packaging).
