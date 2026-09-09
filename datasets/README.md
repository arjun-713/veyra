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
  `vel_cloud_node_semantickitti_label_id/`. Adapter placeholder: `rellis/`.
- **SemanticPOSS** — structured validation. Root:
  `data/raw/semanticposs/dataset/`, sequences `00`–`05` with
  `velodyne/` + `labels/` (+ `calib.txt`, `poses.txt`). Adapter
  placeholder: `semanticposs/`.

Paths configured in `configs/datasets.yaml` (repository-relative).
`data/` is local-only and must never be committed.
See `docs/datasets-benchmarks.md`.
