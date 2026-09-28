# Perception, Terrain, Temporal — Veyra

Source: `AGENTS.md` §§9–11 and `README.md` Perception / Dynamic /
Terrain Understanding.

## Semantic provider

The live provider boundary is the Python `perception.semantic.SemanticProvider`
protocol. It consumes XYZI arrays plus optional dataset labels and returns an
aligned `SemanticResult` containing unified class IDs, confidence, and backend
mode. Implementations currently include `GroundTruthSemanticProvider`,
`OnnxSemanticProvider`, and the SalsaNext adapter; the mapper consumes only the
result fields and does not depend on a network-specific implementation.

CENet (`mode: cenet`) takes `device: auto | cpu | mps` (default `cpu`).
`auto` runs the unchanged fp32 graph on Apple-silicon MPS only after a
fixed-seed CPU-parity probe passes; otherwise, or if MPS fails mid-run, it
stays on CPU and records why in `pipeline_status.semantic_device_fallback_reason`
(also in telemetry and diagnostics). `mps` fails closed. A device fallback
still runs the model; it is never a `ground_truth` fallback.

Mapper must not depend on one network. Candidates: SalsaNext, FRNet,
Cylinder3D, compatible ONNX models. Pretrained first; custom LiDAR
training is out of scope.

## Terrain

Reuse Patchwork++ for ground segmentation. Combine geometric +
semantic evidence. Geometric features: slope, roughness, height
spread, step response, local elevation gradient. Output:
`drivable / non-drivable / unknown`. `unknown` must never silently
become free/drivable.

## Temporal (class ≠ motion)

Keep `semantic_class` separate from `motion_probability /
motion_state`. Class `car` / `pedestrian` does not imply moving.
Initial pipeline: semantic cluster → ego-motion compensation →
association → centroid displacement → `STATIC / POSSIBLY_MOVING /
MOVING`. Dynamic observations must not permanently contaminate the
persistent terrain map.
