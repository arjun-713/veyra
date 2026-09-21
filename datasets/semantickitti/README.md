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

Validation status (see `reports/closure/kitti/RESULT.md`):
official `data_odometry_labels.zip` sequence 08 (val split, 4071 labels +
4071 SuMa poses) is verified for label format, v1.1 taxonomy coverage
(including moving IDs 252-254/259), pose rigidity, and smooth sequential
motion through the adapter's pose parser. Velodyne scans, `calib.txt`, and
`times.txt` remain gated on KITTI benchmark login, so full scan replay and
dataset timestamps stay honestly absent — never generated. Sequential replay
mechanics (ordering, world-frame provenance, determinism) are proven on the
same KITTI-contract adapter path with local SemanticPOSS sequence 00.
