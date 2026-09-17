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
