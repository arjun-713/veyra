# Datasets — code in Git, data outside Git (see `.gitignore`).

```text
datasets/        -> loaders, adapters, taxonomy mappings, dataset-specific code (TRACKED)
data/raw/        -> immutable original dataset files (LOCAL-ONLY, never committed)
data/processed/  -> derived/normalized artifacts (LOCAL-ONLY, never committed)
data/cache/      -> temporary local cache (LOCAL-ONLY, never committed)
```

## Local datasets

- **RELLIS-3D** — off-road validation. Root: `data/raw/rellis3d/Rellis-3D/`,
  sequences `00000`–`00004`, scans in `vel_cloud_node_kitti_bin/`, labels in
  `vel_cloud_node_semantickitti_label_id/`. Adapter: `rellis/`.
- **SemanticPOSS** — structured validation. Root:
  `data/raw/semanticposs/dataset/`, sequences `00`–`05` with
  `velodyne/` + `labels/` (+ `calib.txt`, `poses.txt`). Adapter
  implementation: `semanticposs/`.
- **SemanticKITTI v1.1** — sequential urban development/evaluation. The
  adapter is supported by code and fixtures, but is **unvalidated locally in
  this checkout** because no local asset is present. Root:
  `data/raw/semantickitti/dataset/`, with `sequences/<id>/velodyne/`, optional
  `labels/`, `poses.txt`, `times.txt`, and `calib.txt`. Use
  `datasets/download_semantickitti.sh --help` with authenticated official
  archive URLs; it never embeds credentials or overwrites an existing root.

Paths configured in `configs/datasets.yaml` (repository-relative).
`data/` is local-only and must never be committed.
See `docs/datasets-benchmarks.md`.

Run `python scripts/validate_dataset_capabilities.py --dataset <name>` for a
bounded JSON report. It exercises adapter code paths on local files, records
representative counts and observed intensity bounds, and reports unavailable
pose/timestamp/calibration metadata explicitly. It never downloads, rewrites,
or uploads dataset files.

## Common adapter contract

Dataset readers expose `list_sequences()`, `list_frames(sequence)`, and
`replay(sequence, ...)`. Replay yields the NumPy-backed `ObservationFrame`
defined in `datasets/common/`; downstream code does not depend on a dataset's
directory structure. All adapters set `ObservationFrame.provenance`: missing
metadata is `absent` or `identity_absent`, never a claimed measurement. They
apply the configurable XY range crop in the LiDAR frame before any transform.
