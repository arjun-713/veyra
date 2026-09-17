# Semantic model evidence

This record separates an executable semantic backend from a backend that is
appropriate for a particular sensor and dataset. It is deliberately not a
model leaderboard or a release claim.

## Current pinned backend

`configs/perception-salsanext.yaml` uses Qualcomm's SalsaNext ONNX export. It
is a real CPU ONNX Runtime backend with a pinned payload, but its training
contract is SemanticKITTI:

| Property | Current SalsaNext asset |
| --- | --- |
| Input | `1 x 5 x 64 x 2048` range/XYZ/remission |
| Vertical FOV | `-25` to `+3` degrees |
| Classes | 20 SemanticKITTI learning IDs / Veyra canonical IDs |
| Local model SHA-256 | `067086f808985de376e19c174e249190b7c97996cd54be1dbb9d8b298804b548` |
| Local companion-data SHA-256 | `7d3f19934ea73190e67b2550f52d3ce9eedeca55203eb115f8412c3ad5a2e52f` |

On 16 real SemanticPOSS sequence-00 frames (1,029,238 labelled points), this
asset measured **8.74% all-return Veyra-taxonomy mIoU** and **29.41% accuracy**.
It also measured SalsaNext p50/p95 inference latency of **1.96 s / 2.07 s per
frame** on the local CPU. This is an observed cross-domain baseline, not a
quality result suitable for an SIH semantic-model claim.

`scripts/validate_perception.py` now writes the full measurement artifact and
then fails when the configured `quality_gate` is missed. The SalsaNext config
requires model-FOV mIoU >= 0.30, FOV coverage >= 0.90, and overall ground F1
>= 0.75. The current SemanticPOSS run fails the semantic mIoU floor, as it
should.

## Closure verification: geometry is correct, checkpoint is wrong-domain

`agent/perception-semantic` verified every suspected mismatch dimension
against the training sources and closed the neural-correctness question as a
sensor/taxonomy incompatibility, not a projection bug. Raw artifact:
`reports/closure/semantic/salsanext-poss-metrics.json`, reproduced with
`python3 scripts/measure_salsanext_cross_domain.py`.

| Dimension | Training spec (verified source) | Local finding | Verdict |
| --- | --- | --- | --- |
| Yaw/row projection | `yaw=-atan2(y,x)`, `row=floor((1-(pitch-down)/(up-down))*H)` (`TiagoCortinhal/SalsaNext` `train/common/laserscan.py`, MIT) | `project_scan` matches pixel-for-pixel on 500 seeded in-FOV points; nearest return wins; stable tie-break keeps first input return | Correct |
| Tensor layout | `1x5x64x2048` range/XYZ/remission, `(x-means)/stds`, `*=mask` (`qualcomm/ai-hub-models` `salsanext/app.py` v0.62.1) | Channel order, means `[12.12, 10.88, 0.23, -1.04, 0.21]`, stds `[12.32, 11.47, 6.91, 0.86, 0.16]`, empty pixels exactly zero | Correct |
| Unprojection | `argmax[p_y, p_x]` per point, no KNN (same `app.py`) | `unproject_scores` reads each point's own pixel in input order; collisions share the nearest return's prediction; no second softmax | Correct |
| ONNX export | Input `lidar [1,5,64,2048]`, output `predict [1,20,64,2048]` float | Runtime metadata matches; outputs are probabilities summing to 1; sha `067086f8...` | Matches |
| Learning map / class IDs | `semantic-kitti.yaml` `learning_map` + `learning_map_inv` order | `datasets/common/taxonomy.py` equals upstream map entry-for-entry; 20 channel names equal `learning_map_inv` order; class 0 is the training-ignored label and is reported at zero confidence | Correct |
| Sensor vertical FOV | KITTI HDL-64E training FOV `-25` to `+3` deg | 16 real POSS frames span `-15.54` to `+7.30` deg (Pandora nominal `-16` to `+7`); only **90.5%** of returns fall inside the model FOV, the upper band is forced unknown | **Mismatch** |
| Vertical resolution | 64 rows over 28 deg (`0.44` deg/row) | 40-beam Pandora fills only **30/64 rows**; 34 rows are always empty | **Mismatch** |
| Intensity | KITTI float remission, training mean 0.21 | POSS byte `1..255` (255 distinct values); `/255` mean `0.05`, i.e. ~1 std below training mean | **Shift** (scale handled, distribution not) |
| Range | KITTI training mean 12.12 m | POSS mean 26.2 m, max 199 m (`+1.1` std on the range channel; normalized extremes to `15` sigma) | **Shift** |
| Taxonomy | 20 KITTI learning classes incl. road/parking/sidewalk split | POSS has one `ground` class mapped to other-ground (12): 245,782 model `road` predictions score IoU `0.0`; POSS has no other-vehicle class while the model predicts 150,650 of them; raw 20 (don't-care) maps to unknown | **Collision** (unfixable without retraining) |
| Confidence | Softmax probabilities, uncalibrated cross-domain | Mean **0.86** / p50 **0.97** on predicted-known at 29% accuracy | Overconfident; unknown stays failure-safe at 0 |
| Point order | Original order via `proj_x`/`proj_y` | Round-trip tests pin per-point order through projection and unprojection | Correct |

Closure run (SemanticPOSS v1.0, sequence 00, frames 000000-000015,
1,065,314 points; i5-8350U CPU, ORT 1.30.0, threads 2, shared host under
load average ~16): **all-return mIoU 8.72%**, **model-FOV mIoU 9.41%**,
**labelled accuracy 29.3%**, per-class IoU car 0.45 / building 0.39 /
road 0.00 / other-ground 0.06, near-field (0-10 m) mIoU 0.065,
latency p50/p95 **3.0 s / 4.4 s** per frame, peak RSS 783 MB. The
prediction histogram spans 15 classes (not degenerate), so the backend
executes correctly; it is simply answering a different sensor's question.

Deliberate deviations from upstream, kept: out-of-FOV and zero-range
returns are explicit unknown at zero confidence (upstream clamps them to
edge rows); point index 0 is included in the valid mask (upstream's
`proj_idx > 0` mask drops it); over-range intensity raises instead of
silently shifting the remission channel. The pipeline dataset gate
(`supported_datasets == {"semantickitti"}`) continues to refuse POSS
frames; the closure measurement calls the provider directly and records
that bypass in its artifact.

## Native SemanticPOSS candidate under review

[CENet](https://github.com/huixiancheng/CENet) at source commit
`9a84103d186a1f93637cae3d96426760deb04140` is MIT-licensed and includes a
SemanticPOSS training/inference path. Its published `poss.yml` contract is
closer to the local Pandora scans:

| Property | CENet SemanticPOSS configuration |
| --- | --- |
| Input | `40 x 1800` range image |
| Vertical FOV | `-16` to `+7` degrees |
| Sensor | Pandora |
| Classes | Native SemanticPOSS labels, requiring an explicit Veyra projection |
| Post-processing | Optional KNN projection |

The repository links a SemanticPOSS checkpoint hosted externally. The
checkpoint's license, immutable archive digest, extracted-weight digest, and
numerical compatibility with the current source have **not** been verified.
It is therefore not downloaded, packaged, enabled, or represented as a Veyra
backend yet.

## Native checkpoint verification (`agent/semantic-finetune`)

The externally hosted CENet SemanticPOSS bundle was downloaded and verified
against the pinned source. All digests below are measured, not quoted.

| Property | Verified value |
| --- | --- |
| Source | `https://github.com/huixiancheng/CENet` @ `9a84103d186a1f93637cae3d96426760deb04140` (MIT, `LICENSE` in repo) |
| Checkpoint URL | `https://drive.google.com/file/d/1DC66ky6k2aBpVg1Md1AR2tjqHzSYL5xC/view?usp=sharing` (README "POSS Result") |
| Archive size | 291,128,300 bytes |
| Archive SHA-256 | `d466d387a69933ce87d380e106b3f4d3b45734bf236391280d2894b09bc416c2` |
| Weights file | `res/SENet_valid_best`, 54,393,487 bytes, SHA-256 `9c07ceadcd005a11bddc6c92b61d6f7724339f9519ef177afdebc3c59ffbb0ce` |
| Weights format | torch.save dict (`epoch`, `state_dict` with 248 tensors, `optimizer`, `info`, `scheduler`); loads under torch 2.14 CPU |
| Architecture | `ResNet_34` (`modules/network/ResNet.py`), `pipeline: "res"`, LeakyReLU→Hardswish swap, 14 learning classes, 5-channel `(64,5,3,3)` stem |
| Training log | `res/log.txt`: 45-epoch schedule, best valid mIoU **0.486–0.503** on the author's split (train `0,1,3,4,5` / valid `2`), per-class IoU person 0.75 / car 0.78 / plants 0.72 / ground 0.79 / pole 0.31 / cone 0.15–0.26 |
| Native taxonomy | `res/data_cfg.yaml` `learning_map`: raw `{4,5}→1 person, 6→2 rider, 7→3 car, 8→4 trunk, 9→5 plants, {10,11,12}→6 sign, 13→7 pole, 14→8 trashcan, 15→9 building, 16→10 cone, 17→11 fence, 21→12 bike, 22→13 ground`, rest→0 |
| Local data fit | Local `sequences/00/tag/*.tag` files satisfy the parser's tag requirement; local `read_data.py` `LABEL_DICT` matches the bundle labels |

Porting notes (measured while executing the checkpoint on CPU): the 2021
code uses removed NumPy aliases (`np.float`, `np.bool` in
`common/posslaserscan.py`) and unconditionally calls `.cuda()` in
`infer_subset`; both need a CPU-port patch before the stock script runs on
the current stack. The KNN post-processor (`postproc/KNN.py`) itself is
device-agnostic. No weight license file ships inside the bundle; the code
is MIT but the weight grant is unstated, so the weights stay out of git
regardless of quality.

Measured local quality: `reports/closure/semantic-finetune/cenet-poss-metrics.json`
(same 16 seq-00 frames as the SalsaNext closure; CNN-only and KNN paths
scored separately). Because seq 00 is the checkpoint author's *training*
sequence, those numbers are a compatibility proof, not a generalization
claim; the fine-tune spec below requires a seq-02 (author-valid) run
before any enable decision.

### Native-provider verdict: CENet measured, SalsaNext refusal stands (`agent/semantic-finetune` integration)

On the same 16 seq-00 frames where SalsaNext scored 0.087 / 0.29, the
vendored CPU CENet provider (`perception/semantic/cenet.py`, tag-free beam
projection, per-point argmax, no KNN) measures **Veyra mIoU 0.6504 /
labelled accuracy 0.8942** (1,065,314 pts; group mIoU 0.6195; confidence
0.962 on correct vs 0.774 on wrong) — a 7.5x mIoU recovery that passes the
`configs/perception-cenet-semantic.yaml` floors (mIoU >= 0.30, FOV coverage
≈ 1.00, ground-as-drivable F1 0.938). Range-binned Veyra mIoU: 0–10 m
**0.358** / 10–30 m **0.712** / 30–60 m **0.510** / 60 m+ **0.237**;
near-field and far-field bins are the known-weak regions. Evidence:
`reports/closure/semantic-finetune/RESULT.md` +
`reports/closure/semantic-finetune/quality-ranges.json` (committed
`cenet-poss-metrics.json`). The seq-02 exact-projection reference
(author-valid split, different method) holds the same mIoU family (0.6473 /
0.8651), so the number is not a train-sequence artifact — but 16-frame
windows are closure evidence, not release qualification (full seq-02/04/05
sweep pending). The SalsaNext gate refusal for POSS frames is unchanged:
SalsaNext stays wrong-domain (geometry correct, sensor/taxonomy mismatch)
and is never retried by forcing. CPU-only cost on i5-8350U is
seconds/frame (provider infer p50 ~8.6 s, RSS +683 MB), so real-time needs
the documented GPU/TensorRT port; weights stay out of git (no
weight-license grant in the bundle).

## Native lightweight baseline: per-point MLP (`agent/semantic-finetune`)

A dependency-free MLP (`perception/semantic/pandora.py`,
`PandoraNativeSemanticProvider`, NumPy-only inference) was trained
natively on SemanticPOSS seqs 01/02/03 (340k balanced samples, 6
per-point features, sklearn MLP 128x64, temperature 2.76) and measured on
the closure frames (`reports/closure/semantic-finetune/
pandora-native-metrics.json`, repro spec + sha256 in
`configs/semantic-pandora-native-model.json`):

| Metric | Value |
| --- | --- |
| Resampled-val accuracy (train distribution) | 0.727 |
| Seq-00 test accuracy / Veyra mIoU | 0.3125 / **0.0961** |
| Group mIoU (only drivable usable, IoU 0.55) | 0.1846 |
| Quality gate (mIoU >= 0.30) | **FAIL** |

Per-point features without spatial context do not transfer across
sequences. This negative result is kept as evidence (not a backend): it
bounds the lightweight option and justifies the CENet (spatial-context)
path above. The provider remains in-tree as a tested, reproducible,
dependency-free fallback, explicitly marked not-recommended.

## Acceptance before enabling a native checkpoint

1. Record source URL, source revision, asset license/provenance, archive size,
   archive SHA-256, and extracted-weight SHA-256.
2. Validate native 14-class and Veyra-projected taxonomy outputs on held-out
   SemanticPOSS frames, including range-binned mIoU and critical classes.
3. Prove point-order/point-alignment behavior, including range-image collisions
   and any KNN post-processing.
4. Record CPU p50/p95/p99 latency and peak RSS on named hardware.
5. Make the model manifest and runtime configuration fail closed when any
   contract, payload, or quality gate is invalid.
