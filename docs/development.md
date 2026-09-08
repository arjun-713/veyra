# Development — Veyra

Source: `AGENTS.md` §§12,14,18–21,23–25 and `README.md` Engineering
Priorities / Technology / Build / Status / What Veyra Is Not.

## Build order

```text
Dataset loader → Uniform 5 cm map → height statistics → DistanceLOD
→ split/merge tests → semantic + terrain → temporal → UtilityLOD
→ optimization → resource governor → advanced features
```

No advanced features before adaptive mapper + benchmarks work.

## Ownership

- **Perception & Scene Intelligence** — replay, transforms,
  Patchwork++, semantics, terrain geometry, temporal/motion.
  Output: `LiDAR → enriched observations`.
- **2.5D Mapping & Grid Engine** — cells/tiles, world-aligned
  hierarchy, fusion, split/merge, DistanceLOD, rolling map, cleanup,
  snapshots. Output: `observations → correct adaptive map`.
- **Adaptive Intelligence, Runtime & Presentation** — UtilityLOD,
  importance, hysteresis, prediction, governor, metrics, viewer.
  Output: `map → decisions + measured behavior`.

Cross-domain changes must preserve interfaces.

## Standards

Core `C++20`, CMake. Prefer RAII, value semantics, `std::span`,
`steady_clock`, explicit units, small interfaces, bounded hot-path
allocs. Avoid globals, hidden frame-loop allocs, raw owning pointers,
arch-specific map core, Python in map updates. Python for training,
data prep, plotting, eval.

Core mapper must run without CUDA (precomputed semantics OK).
Ecosystem: PyTorch, ONNX Runtime, Patchwork++, PCL/Open3D, ROS2
adapters, CUDA/TensorRT optional.

## Scope

Pose is external input. Out of scope: SLAM, planning, control, camera
fusion, LLM/chatbot, custom foundation models, cloud infra.

## Architecture-change checklist

1. Which requirement? 2. Existing component? 3. Invariant impact?
4. Memory/cell delta? 5. Frame-time allocs? 6. Benchmark? 7. Which
baseline shows gain? 8. Isolatable behind interface? If unanswerable,
skip the change.

## Definition of Done

Works + tests pass + invariants hold + no generated data committed +
perf-sensitive changes measured + docs/config updated. Adaptive
features additionally need baseline comparison + measurable benefit.

## Guiding principle

> Spend resolution where losing information matters while keeping the
> representation bounded, deterministic, and real-time capable.
> Correctness → measured performance → adaptive intelligence →
> presentation.
