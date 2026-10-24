# Dataset adapters

Dataset code and metadata belong in Git; scans, labels, models and generated maps
belong under ignored `data/raw/`, `data/processed/` and `data/cache/`. Default
roots, sequence banks and range limits are in `configs/datasets.yaml`.

## Supported inputs

| Input | Adapter | Default local root | Scan / label directories |
| --- | --- | --- | --- |
| SemanticPOSS | `SemanticPOSSDataset` | `data/raw/semanticposs/dataset` | `sequences/<id>/velodyne` / `labels` |
| SemanticKITTI | `SemanticKITTIDataset` | `data/raw/semantickitti/dataset` | `sequences/<id>/velodyne` / `labels` |
| RELLIS-3D | `Rellis3DDataset` | `data/raw/rellis3d/Rellis-3D` | `<id>/vel_cloud_node_kitti_bin` / `vel_cloud_node_semantickitti_label_id` |
| Generic manifest | `ManifestDataset` | User-selected root | Paths declared in `manifest.json` |
| PandaSet | Convert to generic manifest | `data/raw/pandaset/veyra` | Converted XYZI and labels |

## Common frame contract

Adapters expose `list_sequences()`, `list_frames(sequence)` and
`replay(sequence, ...)`. Replay yields a NumPy-backed `ObservationFrame` with
point-aligned arrays. The types live in `datasets/common/`:

- `PoseSE3`: validated rigid 4×4 LiDAR-to-world transform.
- `LidarFrame`: ordered XYZI and dataset identity.
- `SemanticFrame`: class IDs, confidence and source mode.
- `ObservationFrame`: semantics, ground, terrain and motion evidence beside points.
- `FrameProvenance`: source of pose, time, calibration and labels, plus coordinate frame.

Missing metadata remains `absent` or `identity_absent`; it never becomes a
measurement. Range filtering uses sensor-frame XY before pose transformation
and preserves point/label ordering. Original semantic IDs and instance bits
remain separate from mapped classes. The common taxonomy is
`veyra-semantic-kitti-learning-v1`; each dataset has its own versioned mapping
in `datasets/common/taxonomy.py`. Unmapped IDs stay unknown.

## SemanticPOSS

The canonical layout is `sequences/{00..05}/{velodyne,labels,poses.txt,calib.txt}`;
the adapter also accepts a direct `<root>/<sequence>/` layout. Labels are
required by default. With `require_labels=False`, absent labels produce class
0, confidence 0 and `label_source: absent`, not ground truth.

```python
from datasets.semanticposs import SemanticPOSSDataset

dataset = SemanticPOSSDataset('data/raw/semanticposs/dataset')
for frame in dataset.replay('00', max_range_m=100.0):
    consume(frame)
```

Available poses produce world-frame points. Missing timestamp files stay
missing. Raw v1.0 `LABEL_DICT` classes map into the common taxonomy.

## SemanticKITTI

The v1.1 layout uses `sequences/<id>/velodyne/*.bin`, matching `labels/*.label`,
optional `poses.txt`, `calib.txt` and `times.txt` (or `timestamps.txt`). Packed
labels use low 16 bits for semantics; upper bits are instance IDs.

`datasets/download_semantickitti.sh --help` describes authenticated official
archive installation without embedded credentials or overwriting an existing
root. Historical evidence includes an [official label/pose check](../reports/closure/kitti/RESULT.md)
and a [220-scan seq08 temporal experiment](../reports/closure/temporal/RESULT.md)
with real calibration/timestamps and frame gaps. Neither is full-sequence acceptance.

## RELLIS-3D

Sequences are `00000`–`00004`; scans and labels pair by stem. Optional metadata
comes from per-sequence `poses.txt` / `timestamps.txt` or
`poses/<sequence>.txt` / `timestamps/<sequence>.txt`. Calibration may be in
`calib/<sequence>.txt` or per-sequence `calib.txt`, with `Tr:` or
`Tr_velo_to_cam:`. Numeric filenames are frame identifiers, not timestamps.
Absent poses leave points in LiDAR coordinates. Raw v1.1 learning-map IDs and
original labels are preserved separately. [Recorded local validation](../reports/closure/rellis/RESULT.md)
is tied to its original inputs.

## Generic manifest

`datasets.generic.ManifestDataset` consumes an explicit schema-1
`manifest.json`. The producer declares frame order, coordinate convention,
intensity meaning, label mapping and metadata provenance; this adapter does
not guess a manifest from a native dataset directory.

- Points: finite little-endian XYZI as `xyzi_f32_bin` or `xyzi_f32_npy`.
- Optional labels: `uint32_label` (low 16-bit semantics) or `integer_npy`.
- Paths: relative to the dataset root, with escapes rejected.
- Frame IDs: explicit, unique and deterministically sorted.
- Pose: rigid 4×4 sensor-to-world matrix; timestamp: explicit seconds.
- Missing labels: class 0 and confidence 0. Missing time/pose stays unavailable.

Malformed records, unaligned labels, duplicate keys, non-finite values and
invalid transforms fail closed. Range cropping precedes the pose transform.

```python
from datasets.generic import ManifestDataset

for frame in ManifestDataset('/path/to/export').replay('sequence-01', max_range_m=100.0):
    consume(frame)
```

## PandaSet conversion

PandaSet is an urban showcase source (Hesai + Scale AI, CC BY 4.0): Pandar64
and forward PandarGT scans, GPS/IMU poses, 80 sweeps at 10 Hz per sequence,
pointwise semantic labels for 76 of 103 sequences. Conversion feeds the generic
adapter; select `generic` and `data/raw/pandaset/veyra` in the desktop.

```bash
python -m datasets.pandaset.download --list-labelled
python -m datasets.pandaset.download --sequences 011 021 039
pip install pandas  # conversion-only dependency
python -m datasets.pandaset.convert
```

Conversion moves source world-frame sweeps into the Pandar64 frame and keeps
motion in the manifest pose. Pandar64 is the default; `--sensors both` adds
PandarGT and breaks the single-origin assumption used by visibility clearing.
The beam-origin offset is estimated, not sensor ground truth: the converter
uses a pooled 1.55 m from ring-sharpness estimates of 1.30/1.60/1.75 m for
sequences 021/011/039. Provenance records
`sensor_origin.source: estimated_from_beam_ring_sharpness`; override with
`--origin-offset`. `PANDASET_LABELS` leaves unsupported classes such as smoke,
reflection, scooters, animals and cones unknown. Selected showcase sequences:
011 (Embarcadero), 021 (palm-lined boulevard), 039 (downtown).

## Metadata and validation

Each adapter caches a numeric frame index and parsed metadata per sequence,
with a bounded cache (`max_cached_sequences`, default 8). Eviction removes
both indexes; replay validates start/end/stride and retains source ordering.
Metadata rows must associate with the selected frame IDs; they are never
silently truncated to fit a subset.

Coordinate conventions differ:

- **SemanticKITTI:** official camera-frame poses use
  `T_world_lidar = Tr^-1 @ T_world_camera @ Tr`.
- **SemanticPOSS:** the upstream format does not resolve pose/`Tr` direction.
  `convert_camera_pose_with_calibration=False` preserves supplied pose rows;
  the inspected release's `Tr` was identity in sequences 00–05. Do not infer
  KITTI's pose conversion solely from a similar directory layout.
- **RELLIS:** camera-projection calibration does not establish a LiDAR-to-world
  transform and is not composed into world poses. An explicit `metadata_root`
  is supported, but ambiguous positional association is rejected.

Every calibration is independently checked as rigid SE(3), including when the
pose is identity. Temporal processing needs world-frame coordinates and real
dataset pose/time provenance.

The historical [official RELLIS metadata archive](https://drive.google.com/file/d/1V3PT_NJhA41N7TBLp5AbW31d0ztQDQOX/view)
was 609,344 compressed bytes, SHA-256
`6deaf38a9cac3a480cfdb70fa9a1d9278f25c36f5efd2487a3c4a6a400250f67`.
It contains poses/calibration without times or frame association. Pose counts
2,847/2,319/4,147/2,184/2,059 differ from the inspected Velodyne scan counts
2,842/2,315/4,139/2,180/2,056; accepting row truncation would invent alignment.
The separate `vel2os1.yaml` / `transforms.yaml` archives do not supply timing.

Run bounded checks against the current local assets:

```bash
python scripts/validate_dataset_capabilities.py --dataset semanticposs --root data/raw/semanticposs/dataset --sample-limit 3
python scripts/validate_dataset_capabilities.py --dataset rellis3d --root data/raw/rellis3d/Rellis-3D --sample-limit 3
python scripts/validate_dataset_capabilities.py --dataset semantickitti --root data/raw/semantickitti/dataset --sample-limit 3
python -m pytest -q tests/test_rellis_adapter.py tests/test_semanticposs_adapter.py tests/test_semantickitti_adapter.py
```

Reports disclose counts, alignment, finite intensity, taxonomy, replay and
metadata availability. They do not download or rewrite data. A skipped fixture
or absent root is not real-data acceptance. Evaluation definitions are in the
[benchmark contract](../docs/benchmark-contract.md).

Primary format references: [RELLIS](https://github.com/unmannedlab/RELLIS-3D/blob/main/README.md),
[SemanticKITTI API](https://github.com/PRBonn/semantic-kitti-api/blob/master/README.md),
[SemanticKITTI datasets](https://semantic-kitti.org/dataset.html),
[SemanticPOSS API](https://github.com/Theia-4869/semantic-poss-api) and
[SemanticPOSS paper](https://arxiv.org/abs/2002.09147).
