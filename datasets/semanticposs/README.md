# SemanticPOSS adapter

Canonical data root (local-only, see `configs/datasets.yaml`):

```text
data/raw/semanticposs/dataset/sequences/{00..05}/{velodyne,labels,calib.txt,...}
```

`SemanticPOSSDataset` implements the common dataset adapter. It supports both
the direct `<root>/<sequence>/` fixture layout and the canonical
`<root>/sequences/<sequence>/` KITTI layout.

Example:

```python
from datasets.semanticposs import SemanticPOSSDataset

dataset = SemanticPOSSDataset("data/raw/semanticposs/dataset")
for frame in dataset.replay("00", max_range_m=100.0):
    consume(frame)  # datasets.common.ObservationFrame
```

The adapter consumes the original per-sequence `poses.txt` and `calib.txt` when
present, publishes world-frame points, and marks the absence of a timestamp
file explicitly in frame provenance. SemanticPOSS v1.0 raw labels are mapped
through its published `LABEL_DICT` into the versioned Veyra taxonomy; unmapped
classes remain class `0` (`unknown`) rather than guessed. The range crop happens
in the input LiDAR frame before applying a pose.
