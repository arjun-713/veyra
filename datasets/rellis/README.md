# RELLIS-3D adapter

Canonical data root (local-only, see `configs/datasets.yaml`):

```text
data/raw/rellis3d/Rellis-3D/{00000..00004}/
  vel_cloud_node_kitti_bin/*.bin
  vel_cloud_node_semantickitti_label_id/*.label
```

Use `Rellis3DDataset` to pair `<id>.bin` with `<id>.label` and expose replayed
frames as the common `ObservationFrame` contract. The adapter reads only the
original local data root at runtime; data, weights, and generated maps must not
be committed.

Optional metadata is read from `poses/{sequence}.txt`, `timestamps/{sequence}.txt`,
or per-sequence `poses.txt`/`timestamps.txt`. Calibration is read from
`calib/{sequence}.txt` or per-sequence `calib.txt` when a `Tr:` or
`Tr_velo_to_cam:` transform is present. Without real metadata, provenance says
`identity_absent`/`absent` and points remain in the LiDAR frame; no world pose
or timestamp is inferred. RELLIS-3D v1.1 raw IDs map through the official
learning map, while original IDs remain attached to each frame.
