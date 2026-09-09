# RELLIS-3D adapter — placeholder

Canonical data root (local-only, see `configs/datasets.yaml`):

```text
data/raw/rellis3d/Rellis-3D/{00000..00004}/
  vel_cloud_node_kitti_bin/*.bin
  vel_cloud_node_semantickitti_label_id/*.label
```

Scans and labels share one dataset root so the future adapter can pair
`<id>.bin` with `<id>.label` per sequence. No loader is implemented here
until the common `ObservationFrame` interface in `datasets/common/` exists.
