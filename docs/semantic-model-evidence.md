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
