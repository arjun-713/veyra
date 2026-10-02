# Common dataset contract

Dataset-specific readers produce a common, NumPy-backed interface for the
mapper, benchmark tools, and visualizer:

- `PoseSE3` stores a validated 4×4 LiDAR-to-world transform.
- `LidarFrame` stores ordered XYZ/intensity points and dataset metadata.
- `SemanticFrame` stores aligned class IDs, confidence, and source mode.
- `ObservationFrame` stores the stable perception-to-mapping boundary. Every
  per-point array has the same length as `points`; fields not computed yet are
  explicit unknown/default values.
- `FrameProvenance` records whether timestamp, pose, and calibration came from
  the dataset or were absent, plus whether points are `world`, `lidar`, or
  `calibrated_lidar` coordinates. Temporal motion only consumes world-frame
  observations with a dataset timestamp.
- `DatasetAdapter` exposes sequence discovery, frame discovery, and replay
  without leaking a dataset's directory layout.

Dataset adapters and perception currently produce this contract in Python;
the runtime passes the resulting observation frame to the C++ mapper. The
language-neutral fields keep mapping independent of SemanticPOSS internals.

The target semantic IDs are versioned as `veyra-semantic-kitti-learning-v1`.
SemanticKITTI v1.1, SemanticPOSS v1.0, and RELLIS-3D v1.1 mappings are named
separately; raw labels remain attached to frames and unmapped IDs stay unknown.

Real datasets belong under ignored `data/raw/`. Tests use tiny synthetic
fixtures only for malformed and geometric edge cases and never add data to Git.
