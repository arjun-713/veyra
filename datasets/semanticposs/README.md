# SemanticPOSS adapter — placeholder

Canonical data root (local-only, see `configs/datasets.yaml`):

```text
data/raw/semanticposs/dataset/sequences/{00..05}/{velodyne,labels,calib.txt,...}
```

No common loader interface exists yet in `datasets/common/`, so no loader
is implemented here. When the `ObservationFrame` adapter interface lands,
this directory will hold the SemanticPOSS reader + taxonomy mapping
following the same pattern as `datasets/rellis/`.
