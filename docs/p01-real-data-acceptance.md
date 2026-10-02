# P01 Real-Data Acceptance (SemanticPOSS + CENet, CPU-only)

Factual acceptance record for #53 finalization. Only orchestrator-verified
facts are listed below. Interpretive notes are explicitly labelled.

## 1. Dataset

- Dataset: SemanticPOSS, local layout `SemanticPOSS_dataset/dataset`.
- Local dataset directory is untracked and NOT committed.
- Sequence 00: 488 `.bin` scans + 488 `.label` files.
- Production SemanticPOSS adapter is compatible with this layout.

## 2. Model

- Model file: `SENet_valid_best`.
- Size: 54393487 bytes, verified via `sha256sum`.
- SHA-256: `9c07ceadcd005a11bddc6c92b61d6f7724339f9519ef177afdebc3c59ffbb0ce`.
- Bundle: 291128300 bytes, verified via `sha256sum`.
- Bundle SHA-256: `d466d387a69933ce87d380e106b3f4d3d45734bf236391280d2894b09bc416c2`.
- Weights are NOT committed and are kept outside git.

## 3. Environment

- OS: Linux, CPU-only.
- Interpreter: `.venv` Python 3.14.4.
- Torch: `2.14.0+cpu` (CPU build; CUDA unavailable).
- Provider-verified device: `cpu`.

## 4. Inference (frame 000000, real data)

- Points in: 66658; aligned points out: 66658.
- Inference time: 4033.8 ms.
- Confidence mean: 0.9438.
- Agreement with independent ground-truth labels: 0.8654.
- Interpretation (labelled): the agreement figure compares neural output
  against independent GT labels; it is not a GT-vs-GT comparison.
- Reported mode: `model`.

## 5. Pipeline (frames 000000 / 000001)

- Semantic stage: `model`.
- Requested backend: `cenet`; actual backend: `model`.
- Fallback field: `null` (no fallback taken).
- Model field: verified checkpoint path.
- Execution device: `cpu`.
- Ground / terrain stages: `unavailable`, with an explicit diagnostic that
  the Patchwork++ binding (`pypatchworkpp`) is missing.
- Frame 000000 total: 4078.0 ms (semantic 4069.1 ms).
- Frame 000001 total: 2014.8 ms (semantic 2009.2 ms).

## 6. Truthfulness labelling

- Neural path reports neural (`model`) status.
- Ground-truth paths report `ground_truth` with bypassed-model marking and
  DEBUG/EVAL designation.
- A fallback path, when taken, is bannered as fallback and never as neural.
- The model field is null on non-neural paths.

## 7. Limitations

- CPU-only execution is non-realtime at the timings above.
- Patchwork++ is unavailable in this environment, so ground/terrain stages
  are unavailable and the full real-data validation gate is blocked.
- Interpretation (labelled): the `--full` blockage is environmental and
  separate from the #53 semantic scope.
- Scratch artifacts from the validation run were not committed and are not
  independently reviewable from git.
- Positive / negative real terrain classes were unobserved in this env.

## 8. P0.1-final — real neural E2E (seq00 000000/000001, CENet + Patchwork++, CPU)

Final P0.1 acceptance state (Phases 9-10). Supersedes the §5/§7
"Patchwork++ missing / gate blocked" limitation: ground/terrain are now
proven on real data with the approved fail-closed config. Earlier
sections (§1-§7) are preserved as the historical record.

### 8.1 Supported environment

- OS: Linux, CPU-only (AMD Ryzen 7 7840HS, 16 logical CPUs).
- Interpreter: `.venv` Python 3.14.4, torch `2.14.0+cpu`, onnxruntime `1.30.0`.
- Ground backend: `pypatchworkpp` 1.4.1, built from git tag `v1.4.1`:
  `git clone --branch v1.4.1 --depth 1 https://github.com/url-kaist/patchwork-plusplus.git`
  then `.venv/bin/pip install ./python/`.
- Reason for tag-build: no cp314 wheels on PyPI; the sdist FetchContent
  path is broken (empty version resolves to a `v.tar.gz` 404).

### 8.2 Checkpoint and approved config

- Checkpoint (explicitly supplied asset, git-ignored, never committed):
  `data/cache/models/cenet-poss/SENet_valid_best`, size 54393487 bytes,
  SHA-256 `9c07ceadcd005a11bddc6c92b61d6f7724339f9519ef177afdebc3c59ffbb0ce`.
- Approved config: `configs/perception-cenet-semantic.yaml` — mode `cenet`,
  `allow_fallback_to_ground_truth: false` (fail-closed), ground + terrain
  enabled, `required_stages: [semantic, ground, terrain]`, quality gate
  `min_model_fov_mean_iou 0.30 / min_model_fov_coverage_fraction 0.90 /
  min_ground_f1 0.75`.
- Hermetic acceptance: `tests/test_p01_neural_acceptance.py` (9 tests:
  approved-config shape, fail-closed, missing-dependency, model disclosure,
  mapper alignment, runtime preservation; no dataset/checkpoint/torch).

### 8.3 Real-run evidence (seq00, 2 frames)

| Item | Frame 000000 | Frame 000001 |
| --- | --- | --- |
| Points in | 66021 | 66049 |
| Semantic | `model` (requested `cenet`, execution `cpu`) | same |
| Ground | `pypatchworkpp.patchworkpp` | same |
| Terrain | `available` | same |
| Fallback | `null` (none taken) | `null` |
| Semantic ms | 1528.5 | 1533.6 |
| Ground ms | 25.8 | 23.2 |
| Terrain ms | 18.4 | 14.6 |
| Total ms | 1577.8 | 1575.3 |
| Ground fraction (predicted) | 0.3312 | 0.3330 |

- Quality gate: `passed` — mIoU 0.6092 >= 0.30, coverage 1.0 >= 0.90,
  ground F1 0.858 >= 0.75 (evaluated points 132070 over 2 frames).
- Mapper: 37195 active leaves (L0 6940 / L1 19297 / L2 8656 / L3 2302);
  mapping ~47.36 ms (viewer proof frame 000000).
- Viewer proof (schema v3): 13205 shown points (stride 5) / 10000 cells,
  payload 1577940 bytes; layers semantic `model`, ground
  `pypatchworkpp.patchworkpp`, terrain `available`; telemetry backend
  `model`, provider `cenet`, execution `cpu`; validation mirror `pass`.
- Artifacts (reference only, not moved into repo):
  `/tmp/opencode/p01-neural-e2e.json`,
  `/tmp/opencode/p01-viewer-proof.json`.

### 8.4 Repro

```bash
.venv/bin/python -m scripts.validate_perception --dataset semanticposs --root SemanticPOSS_dataset/dataset --sequence 00 --count 2 --config configs/perception-cenet-semantic.yaml --output /tmp/opencode/p01-neural-e2e.json
.venv/bin/python -m pytest tests/test_p01_neural_acceptance.py tests/test_neural_demo_failclosed.py tests/test_perception_pipeline.py -q
```

### 8.5 Limitations

- GUI confirmation via `scripts/desktop_flow_smoke.py` remains external
  (needs WebKitWebDriver + Tauri WebView); runtime/replay path is proven,
  desktop GUI is not claimed.
- CPU latency ~1.5 s/frame semantic (≈1.58 s end-to-end) is not real-time;
  mapping (~47 ms) and visualization (~1.2 ms) are the fast stages.
- Weights are local-only (`data/cache/`, git-ignored); repro requires the
  explicitly supplied `SENet_valid_best` asset at the SHA above.
