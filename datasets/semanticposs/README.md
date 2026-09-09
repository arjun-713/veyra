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

The adapter currently uses ground-truth labels. Pretrained model inference,
Patchwork++ ground segmentation, terrain features, and temporal motion remain
later perception stages. Unmapped labels are represented by Veyra class `0`
(`unknown`) rather than guessed.
