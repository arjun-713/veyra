# Common dataset contract

Dataset-specific readers produce a common, NumPy-backed interface for the
mapper, benchmark tools, and visualizer:

- `PoseSE3` stores a validated 4×4 LiDAR-to-world transform.
- `LidarFrame` stores ordered XYZ/intensity points and dataset metadata.
- `SemanticFrame` stores aligned class IDs, confidence, and source mode.
- `ObservationFrame` stores the stable perception-to-mapping boundary. Every
  per-point array has the same length as `points`; fields not computed yet are
  explicit unknown/default values.
- `DatasetAdapter` exposes sequence discovery, frame discovery, and replay
  without leaking a dataset's directory layout.

The initial implementation is Python-first because the dataset visualizer and
local data tools use Python and NumPy. The contract is language-neutral so the
C++ mapper can consume an equivalent representation later without depending on
SemanticPOSS internals.

Real datasets belong under ignored `data/raw/`. Tests use tiny synthetic
fixtures and must never add dataset files to Git.
