# Perception, Terrain, Temporal — Veyra

Implementation: `perception/pipeline.py` and the `semantic/`, `ground/`,
`terrain/` and `temporal/` packages under `perception/`.

## Semantic provider

The provider boundary is the Python `perception.semantic.SemanticProvider`
protocol. It consumes XYZI arrays plus optional dataset labels and returns an
aligned `SemanticResult` containing unified class IDs, confidence, and backend
mode. The config factory supports ground truth, PyTorch CENet, ONNX SalsaNext,
and an ONNX model with an explicit raw-class mapping. Ground-truth labels are
an explicit data/evaluation provider, not neural inference. The mapper consumes
the aligned result fields and does not depend on a network-specific model.

CENet (`mode: cenet`) takes `device: auto | cpu | mps` (default `cpu`).
`auto` runs the unchanged fp32 graph on Apple-silicon MPS only after a
fixed-seed CPU-parity probe passes; otherwise, or if MPS fails mid-run, it
stays on CPU and records why in `pipeline_status.semantic_device_fallback_reason`
(also in telemetry and diagnostics). `mps` fails closed. A device fallback
still runs the model; it is never a `ground_truth` fallback.

The ONNX boundary allows compatible model providers; model availability and
dataset suitability depend on the installed checkpoint and configuration.
Custom LiDAR training is not part of the mapper runtime.

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
