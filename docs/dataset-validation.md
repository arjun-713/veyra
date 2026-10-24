# Dataset adapter validation

This document records the metadata truth and validation boundary for the three
dataset adapters. Adapters accept an already-present local root; they do not
download or synthesize timestamps, poses, or calibration.

## Metadata contract

- **RELLIS-3D:** numeric scan filenames are frame identifiers, not timestamps.
  Optional pose/time metadata must have a valid association to the selected
  scans; missing metadata remains `absent` or `identity_absent` in provenance.
- **SemanticPOSS:** pose, calibration and timestamp files are consumed when
  supplied. Missing timestamps stay absent. Metadata association is validated
  against frame IDs and available rows; malformed or non-finite values fail.
- **SemanticKITTI:** the adapter supports `sequences/<id>/velodyne`, `labels`,
  `poses.txt`, `calib.txt`, and `times.txt`, plus the `timestamps.txt` conversion
  name. Available subsets must retain their real frame IDs and metadata rows.

Local availability is not a repository guarantee. The commands below inspect
the supplied root. Historical [RELLIS validation](../reports/closure/rellis/RESULT.md)
and [SemanticKITTI temporal evidence](../reports/closure/temporal/RESULT.md)
retain the exact inputs and limitations of those experiments.

Official RELLIS pose metadata was acquired on 2026-09-10 after approval:
<https://drive.google.com/file/d/1V3PT_NJhA41N7TBLp5AbW31d0ztQDQOX/view>.
The downloaded archive was 609,344 compressed bytes and contains only
`Rellis-3D/<sequence>/poses.txt` plus `calib.txt` for sequences `00000`--`00004`.
The official archive retrieved on 2026-09-17 has SHA-256
`6deaf38a9cac3a480cfdb70fa9a1d9278f25c36f5efd2487a3c4a6a400250f67`.
It has no timestamps, frame IDs, or filename association. Its pose-row counts
are 2,847/2,319/4,147/2,184/2,059, while local Velodyne scan counts are
2,842/2,315/4,139/2,180/2,056. Because counts differ, the adapter accepts an
explicit `metadata_root` but rejects positional association instead of silently
truncating or inventing a mapping. The RELLIS README also exposes small
Velodyne-to-Ouster and camera-to-Ouster calibration archives; those contain
`vel2os1.yaml` and `transforms.yaml`, not timing.

## Cache and replay contract

Each adapter builds one explicit numeric frame index per sequence and caches it
with a bounded LRU-style sequence cache (`max_cached_sequences`, default 8).
Pose, timestamp, and calibration text are parsed at most once per cached
sequence; the implementation uses an explicit key check because Python
`dict.setdefault` evaluates its default argument eagerly. Eviction drops both
frame and metadata indexes, so a changed or malformed file is observed after
the sequence is re-indexed. Replay uses the cached sorted references;
`start`, `end`, and `stride` are validated before loading frames. Point
ordering is preserved, and range filtering is applied in the sensor frame
before any pose transform.

## Coordinate and extrinsic evidence

The official RELLIS-3D README describes `poses.txt` as poses for every scan and
`calib.txt` as Velodyne-versus-camera calibration needed for camera projection.
It does not establish that this calibration is a LiDAR-to-world transform, so
the adapter must not use RELLIS calibration to alter its world pose.

For SemanticKITTI, the API documentation describes `poses.txt` as annotation
poses in the camera frame. Its documented `Tr` calibration is the
Velodyne-to-camera chain, and the API conversion is
`T_world_lidar = Tr^-1 @ T_world_camera @ Tr`. The resulting
`ObservationFrame.pose` is the sensor-to-world transform expected by the main
pipeline when it inverts that pose. This conversion is enabled only for the
SemanticKITTI subclass.

For SemanticPOSS, the original paper establishes only that the release follows
the SemanticKITTI format and that GPS/IMU localization plus calibration were
used during annotation. It does not establish whether `poses.txt` is camera-
to-world, LiDAR-to-world, or another convention, nor the direction of `Tr`.
The local supplied `calib.txt` has five KITTI-style 3x4 rows (`P0`--`P3` and
`Tr`) embedded as homogeneous 4x4 matrices; `Tr` is identity in sequences
`00`--`05`. The adapter default is explicitly
`convert_camera_pose_with_calibration = False`: it preserves SemanticPOSS pose
rows as supplied and records the convention as unresolved rather than applying
a camera-pose correction by analogy. `SemanticKITTIDataset` overrides that flag
to `True` because its separate official API convention supports the
conjugation.

Every parsed calibration transform is independently validated as a rigid
homogeneous SE(3) matrix before either adapter can use or record it. This
prevents a nonrigid calibration from being masked by `C^-1 @ I @ C` when a
pose happens to be identity.

Primary references checked on 2026-09-10:

- RELLIS-3D upstream README:
  <https://github.com/unmannedlab/RELLIS-3D/blob/main/README.md>
- SemanticKITTI dataset page:
  <https://semantic-kitti.org/dataset.html>
- SemanticKITTI API README and calibration pose conversion:
  <https://github.com/PRBonn/semantic-kitti-api/blob/master/README.md>
  and the API's documented camera-frame pose convention
- SemanticPOSS API layout/pose note:
  <https://github.com/Theia-4869/semantic-poss-api>
- SemanticPOSS original paper:
  <https://arxiv.org/abs/2002.09147>

## Validation commands

Focused adapter checks:

```bash
python -m pytest -q tests/test_rellis_adapter.py tests/test_semanticposs_adapter.py tests/test_semantickitti_adapter.py
```

Real-data checks are conditional on local assets. The bounded machine-readable
report is produced with:

```bash
python scripts/validate_dataset_capabilities.py --dataset semanticposs \
  --root data/raw/semanticposs/dataset --sample-limit 3
python scripts/validate_dataset_capabilities.py --dataset rellis3d \
  --root data/raw/rellis3d/Rellis-3D --sample-limit 3
python scripts/validate_dataset_capabilities.py --dataset semantickitti \
  --root data/raw/semantickitti/dataset --sample-limit 3
```

Inspect the generated report's status, counts, point/label alignment, intensity,
taxonomy, replay and provenance checks for the current root. An unavailable
local asset is reported explicitly; fixture coverage is not real-data evidence.
