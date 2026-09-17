# SemanticKITTI adapter

`SemanticKITTIDataset` supports the original SemanticKITTI v1.1 KITTI layout:

```text
data/raw/semantickitti/dataset/sequences/00/
  velodyne/000000.bin
  labels/000000.label          # required for ground-truth semantic mode
  times.txt                    # optional; absent stays absent
  poses.txt                    # optional; absent keeps LiDAR coordinates
  calib.txt                    # optional `Tr:` LiDAR-to-pose transform
```

Packed labels use the low 16 bits for the semantic ID. The adapter applies the
official v1.1 `learning_map`, preserves the raw ID, consumes available time,
pose, and calibration in sorted frame order, and rejects malformed records or
scan/label mismatches. It never creates a timestamp, pose, calibration, label,
or model prediction.

Use `datasets/download_semantickitti.sh --help` to install authenticated
official archives into the ignored local root. The real-data smoke test skips
only when that root is absent.

The adapter is **not validated on real SemanticKITTI data in this checkout**:
`data/raw/semantickitti/dataset` is absent. Fixture tests cover the expected
layout, deterministic ordering, calibration/pose/timestamp parsing, and
malformed-record failures; this is not a real-data support claim.
