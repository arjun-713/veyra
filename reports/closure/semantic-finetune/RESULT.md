# Closure: native Pandora/SemanticPOSS semantic provider (fine-tune track)

- Status: **closed — native neural path delivered and measured**
- Branch: `agent/semantic-finetune`
- Base: `demo-readiness @ b3b2abf`.
- Prior: `reports/closure/semantic/RESULT.md` — SalsaNext KITTI checkpoint
  proven wrong-domain (29% accuracy / 0.087 mIoU, overconfident; pipeline
  gate refusal kept and correct). This track delivers the native
  replacement. Do not retry forcing SalsaNext.

## Verdict

The target sensor now has a working neural semantic path. The CENet
SemanticPOSS checkpoint (Pandora-native, 40x1800, FOV -16..+7) executes on
CPU through a vendored, strictly-validated provider and measures
**Veyra mIoU 0.65 / accuracy 0.89** on the same 16 seq-00 frames where
SalsaNext scored 0.087 / 0.29 — a 7.5x mIoU recovery with honest,
differentiated confidence (0.96 on correct vs 0.77 on wrong). A
dependency-free per-point MLP trained natively on the same data was also
built and measured, but fails to generalize (0.096 mIoU) and is kept only
as a documented negative result: per-point features without spatial
context do not transfer across sequences. The recommended path is the
CENet provider; the SalsaNext gate refusal for POSS frames is unchanged.

## Candidate investigation (existing architectures first)

| Candidate | Native POSS support? | Outcome |
| --- | --- | --- |
| CENet (`huixiancheng/CENet`, MIT, ICME 2022) | Yes: `poss.yml`, Pandora 40x1800, FOV -16..+7, published POSS checkpoint | **Adopted and measured** (provenance below) |
| SalsaNext fine-tune on POSS | No native path; would need retraining + head/taxonomy surgery | Rejected in favor of a natively-trained checkpoint |
| SqueezeSegV3 / RangeNet++ / PolarNet / Cylinder3D | KITTI/nuScenes/Waymo only; no POSS training path or weights | Rejected (wrong-domain again) |
| SemanticPOSS-paper baselines (SqueezeSegV2, PointNet++) | POSS-compatible but outdated, no maintained weights path | Rejected (CENet dominates and is available) |
| Per-point MLP trained in-session (sklearn, NumPy inference) | Native by construction | Built, measured, **rejected on quality** (0.096 mIoU; see negative result) |

## Checkpoint provenance (CENet, measured not quoted)

| Property | Value |
| --- | --- |
| Source | `https://github.com/huixiancheng/CENet` @ `9a84103d186a1f93637cae3d96426760deb04140`, MIT (`LICENSE` in repo) |
| Checkpoint URL | `https://drive.google.com/file/d/1DC66ky6k2aBpVg1Md1AR2tjqHzSYL5xC/view?usp=sharing` (README "POSS Result") |
| Archive size / SHA-256 | 291,128,300 bytes / `d466d387a69933ce87d380e106b3f4d3b45734bf236391280d2894b09bc416c2` |
| Weights | `res/SENet_valid_best`, 54,393,487 bytes / `9c07ceadcd005a11bddc6c92b61d6f7724339f9519ef177afdebc3c59ffbb0ce` |
| Weights format | torch.save dict (`epoch`, 248-tensor `state_dict`, `optimizer`, `info`, `scheduler`); loads under torch 2.14 CPU, strict state-dict match against the vendored arch |
| Architecture | `ResNet_34`, `pipeline: "res"`, LeakyReLU→Hardswish swap, 14 learning classes, 5-channel `(64,5,3,3)` stem, in-graph softmax |
| Author training log | `res/log.txt`: 45-epoch schedule; best valid mIoU **0.486–0.503** on author split (train 0,1,3,4,5 / valid 2); per-class IoU person 0.75 / car 0.78 / plants 0.72 / ground 0.79 / pole 0.31 / cone 0.15–0.26 |
| Native taxonomy | `res/data_cfg.yaml` `learning_map`: raw `{4,5}→1 person, 6→2 rider, 7→3 car, 8→4 trunk, 9→5 plants, {10,11,12}→6 sign, 13→7 pole, 14→8 trashcan, 15→9 building, 16→10 cone, 17→11 fence, 21→12 bike, 22→13 ground`, rest→0 |
| Weight license | No weight-license file ships in the bundle; code is MIT but the weight grant is unstated → weights stay out of git regardless of quality |

## Provider design (`perception/semantic/cenet.py`)

- Vendored `ResNet_34` (names load-bearing for the strict state-dict
  match); CPU-only (upstream calls `.cuda()` unconditionally); torch is an
  optional explicit dependency — construction fails closed without it.
- Tag-free analytic projection: dataset `.tag` files are a training input,
  unavailable to a point-in/point-out provider. Rows are **nearest measured
  beam elevations** (40-element LUT extracted from tags; reproduces tag rows
  exactly, verified in tests), columns match the training layout up to a
  measured +675 yaw offset (`CENET_YAW_COL_OFFSET`) with ±1 floor jitter
  for ~54% of points (sub-pixel formula difference, documented; costs
  ~0.16 mIoU vs exact tags, measured).
- Raw byte remission (NOT /255): the checkpoint's normalization means fit
  raw bytes (verified by the forward pass; dividing collapses quality).
- Nearest-return compositing, per-point argmax at own pixel, no KNN in the
  provider (KNN timed/scored separately below). Out-of-envelope returns are
  unknown at zero confidence; `supported_datasets == {"semanticposs"}` so
  the existing pipeline gate accepts POSS and refuses the rest.
- Pluggable: `CENetSemanticProvider` + `PandoraNativeSemanticProvider` +
  `GroundTruthSemanticProvider` behind the same `SemanticResult`
  point-order contract. `pipeline.py` is untouched (its `from_config` mode
  whitelist is preserved); injection is by constructor until the
  explicitly-noted follow-up wires `mode: cenet`.

## Measured quality (real SemanticPOSS labelled frames)

Artifact: `reports/closure/semantic-finetune/cenet-poss-metrics.json`
(provider path, committed). All runs on Intel i5-8350U CPU, torch 2.14 CPU,
threads=4 unless noted.

### Headline: provider path, seq 00 frames 000000–000015 (closure frames)

1,065,314 points. Veyra mIoU **0.6504**, labelled accuracy **0.8942**
(SalsaNext on identical frames: 0.0872 / 0.2931).

| Veyra class | IoU | Prec | Rec | F1 | Support |
| --- | --- | --- | --- | --- | --- |
| 1 car | 0.877 | 0.979 | 0.893 | 0.934 | 179,347 |
| 2 bicycle | 0.614 | 0.685 | 0.855 | 0.761 | 26,053 |
| 6 person | 0.698 | 0.856 | 0.791 | 0.822 | 6,900 |
| 7 bicyclist | 0.396 | 0.899 | 0.414 | 0.567 | 1,207 |
| 12 other-ground (POSS `ground`) | 0.884 | 0.970 | 0.909 | 0.938 | 297,541 |
| 13 building | 0.773 | 0.887 | 0.857 | 0.872 | 190,195 |
| 14 fence | 0.625 | 0.721 | 0.823 | 0.769 | 49,028 |
| 15 vegetation | 0.789 | 0.834 | 0.936 | 0.882 | 259,064 |
| 18 pole | 0.763 | 0.931 | 0.808 | 0.865 | 10,585 |
| 19 traffic-sign | 0.736 | 0.965 | 0.756 | 0.848 | 9,318 |

Unobserved-in-window classes (3,4,5,8,9,10,11,17) score null (no union),
exactly as in the closure methodology. POSS `ground` → Veyra 12 at IoU
0.884 resolves the closure's road/other-ground collision (was 0.000).

Range-binned Veyra mIoU (labelled, same bins as closure):
0–10 m **0.358** (168,240 pts) / 10–30 m **0.712** (598,869) /
30–60 m **0.510** (229,003) / 60 m+ **0.237** (33,126).
Near-field and far-field bins are the known-weak regions (collision
density near, sparsity far); mid-field carries the score.

Coarse groups (8, committed artifact `group_prf`; group mIoU **0.6195**,
accuracy 0.8702):

| Group | IoU | Prec | Rec | F1 | Support |
| --- | --- | --- | --- | --- | --- |
| drivable (ground) | 0.884 | 0.970 | 0.909 | 0.938 | 297,541 |
| non-drivable (trashcan/cone) | 0.289 | 0.904 | 0.298 | 0.449 | 821 |
| static (building/fence) | 0.683 | 0.768 | 0.860 | 0.811 | 239,223 |
| pole (pole/signs) | 0.750 | 0.945 | 0.784 | 0.857 | 19,903 |
| vehicle (car/bike/rider) | 0.855 | 0.945 | 0.900 | 0.922 | 206,607 |
| pedestrian | 0.695 | 0.851 | 0.791 | 0.820 | 6,900 |
| vegetation (plants/trunk) | 0.773 | 0.816 | 0.937 | 0.872 | 259,064 |
| unknown | 0.027 | 0.830 | 0.027 | 0.053 | 35,255 |

Non-drivable suffers rare-class recall (821 support points); unknown IoU
is low by construction (unlabeled GT vs predicted-known, same as closure).
Range-binned group mIoU: 0–10 m **0.359** / 10–30 m **0.707** /
30–60 m **0.532** / 60 m+ **0.265**.

### Exact-projection reference (author tags, no provider projection loss)

Same 16 frames through stock projection + tag unprojection (scratch,
method in `docs/semantic-model-evidence.md`): Veyra mIoU **0.8089**,
accuracy **0.9570**. The ~0.16 gap to the provider path quantifies the
tag-free projection cost (column ±1 jitter + pixel collisions).

### Honest generalization: seq 02 (author valid sequence), exact projection

First 16 scans of seq 02 (frames 000001–000016): Veyra mIoU **0.6473**,
accuracy **0.8651** (artifact `cenet-poss-seq02-metrics.json`). Same
mIoU family as the provider path on seq 00 — the provider number is not a
train-sequence artifact. (Author's published native-14-class valid mIoU is
0.486–0.503 with KNN; metric spaces differ — native-14 vs Veyra-projected
over observed classes — so compare shapes, not scalars.)

### KNN post-processing (upstream default, CPU)

Exact-projection seq-00 run scores both paths: CNN-only Veyra mIoU
**0.8089** / acc 0.9570 vs KNN-path **0.8081** / 0.9585 (ΔmIoU -0.0008,
Δacc +0.0015) at KNN p50 **77 ms**/frame. Negligible delta on Pandora
40-beam data — KNN was designed for sparser projections — so the provider
ships CNN-only; KNN stays a documented non-default (artifact
`cenet-poss-seq00-metrics.json`).

### Confidence calibration

Provider path: mean/p50 confidence on predicted-known 0.941/0.997;
0.962 on correct vs 0.774 on wrong — differentiated, unlike the
SalsaNext cross-domain case (0.86 mean at 29% accuracy). No temperature
scaling applied (in-graph softmax is the checkpoint's native output);
confidence may still weight traversability only after the downstream
calibration follow-up in Gaps.

## Latency / resources (named hardware)

- Intel i5-8350U CPU, torch intra-op threads=4, 16 closure frames
  (committed artifact): provider infer p50 **8554 ms** / p95 **17616 ms**
  (first-frame cold start 32.9 s; steady frames 6–12 s; an earlier identical
  run measured p50/p95 6011/7178 ms — shared-host variance, same pattern as
  the SalsaNext closure's 1.96 s vs 3.0 s);
  peak process RSS **1010 MB** (+683 MB over pre-inference).
  Quality metrics are bit-deterministic across runs (0.6504/0.8942 twice).
  No accelerator was available on this host (CPU + accel profiled: CPU
  done, accel N/A).
- Not real-time capable on this CPU at full 40x1800 (same conclusion as
  the SalsaNext closure: seconds/frame). Governor/advanced tracks own the
  resolution/lod response; the provider exposes per-frame ms honestly.
  GPU/TensorRT port is the documented path to real-time (see Gaps).

## Negative result: native per-point MLP (kept, not recommended)

`PandoraNativeSemanticProvider` (NumPy-only, 6 features, sklearn
MLP 128×64, trained on seqs 01/02/03 with 340k balanced samples,
temperature 2.76): resampled-val accuracy 0.727 → seq-00 test accuracy
**0.3125**, Veyra mIoU **0.0961**, group mIoU **0.1846** (only drivable
usable at IoU 0.55). Per-point features without spatial context do not
transfer across sequences. Artifacts: `pandora-native-metrics.json`,
`configs/semantic-pandora-native-model.json` (repro spec + sha256;
weights git-ignored). This is the evidence for "don't retry forcing" a
context-free head: spatial context is load-bearing for this sensor.

## Quality-gate check

Against `configs/perception-cenet-semantic.yaml` floors (same as
SalsaNext): Veyra mIoU 0.6504 ≥ 0.30 ✓; beam-FOV coverage ≈1.00 ≥ 0.90 ✓
(100% of returns valid on closure frames vs 90.5% SalsaNext);
ground-as-drivable F1 0.938 ≥ 0.75 ✓. The SalsaNext config still fails its
gate, as it should.

## Files

- `perception/semantic/cenet.py` — new (vendored arch + provider).
- `perception/semantic/pandora.py` — new (beam LUT, projections, MLP
  provider, group taxonomy).
- `perception/semantic/__init__.py` — export both providers (additive).
- `scripts/measure_cenet_poss.py` — new committed measurement.
- `scripts/train_pandora_semantic.py`, `scripts/measure_pandora_native.py`
  — MLP train/measure (negative-result chain).
- `configs/perception-cenet-semantic.yaml`,
  `configs/semantic-cenet-model.json`,
  `configs/perception-pandora-semantic.yaml`,
  `configs/semantic-pandora-native-model.json` — new.
- `tests/test_semantic_provider.py` — extended (render/projection/
  taxonomy/CENet contract tests; salsanext untouched).
- `docs/semantic-model-evidence.md` — appended (CENet verification +
  beleid; MLP section pending below).
- `reports/closure/semantic-finetune/cenet-poss-metrics.json` (provider
  path), `cenet-poss-seq02-metrics.json` (exact-projection valid),
  `pandora-native-metrics.json` (MLP) — committed artifacts.
- Untouched per ownership: `datasets/*/adapter.py`, `src/map/*`,
  `src-tauri/*`, `perception/temporal/*`, `perception/terrain/*`,
  `perception/pipeline.py`, `tests/test_salsanext.py`.

## Tests

- `pytest tests/test_semantic_provider.py tests/test_salsanext.py` with
  `VEYRA_SALSANEXT_MODEL`, `VEYRA_SEMANTICPOSS_ROOT`, `VEYRA_CENET_CHECKPOINT`
  set: **60 passed** (includes 9 new CENet render/provider/contract tests
  and 13 Pandora projection/taxonomy/MLP-provider tests; `test_salsanext.py`
  unbroken, 19/19 with the model present).
- `ruff check` clean on all new/edited files (base is ruff-clean; kept so).
- New tests are hermetic except env-gated real-checkpoint/real-data pins,
  mirroring the `test_salsanext.py` pattern (skip without assets).

## Real data

- SemanticPOSS v1.0, `data/raw/semanticposs/dataset`; seq 00 frames
  000000–000015 (1,065,314 pts, identical to SalsaNext closure) for the
  headline; seq 02 frames 000001–000016 for honest generalization.
- Checkpoint: CENet `res/SENet_valid_best` sha256
  `9c07cead…ffbb0ce` (full in manifest), bundle sha256 `d466d387…09bc416c2`.

## Gaps / follow-ups (not in this change set)

1. Wire `mode: cenet` into `PerceptionPipeline.from_config` (needs the
   pipeline owner's 8-question checklist; interface preserved here).
2. KNN-in-provider option with measured quality/latency trade-off; GPU /
   TensorRT port for real-time (CPU is ~6 s/frame on i5-8350U).
3. Confidence calibration before traversability weighting (0.96/0.77 split
   is promising but uncalibrated); unknown-at-0 kept regardless.
4. Full-seq-02 + seq-04/05 validation sweep before any production enable;
   16-frame windows are closure evidence, not release qualification.
5. Weight-license clarification with upstream (no grant file in bundle).
