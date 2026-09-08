# Perception, Terrain, Temporal — Veyra

Source: `AGENTS.md` §§9–11 and `README.md` Perception / Dynamic /
Terrain Understanding.

## Semantic provider (interface, not architecture)

```cpp
class SemanticProvider {
public:
    virtual SemanticFrame infer(const LidarFrame& scan) = 0;
};
```

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
