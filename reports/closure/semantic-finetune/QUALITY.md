# Semantic quality, range-binned (CENet provider, SemanticPOSS seq00)

Source: `cenet-poss-metrics.json` (provider path, 16 frames 000000–000015,
1,065,314 pts, 1,029,238 labelled). Consolidated view:
`quality-ranges.json`. Hardware: Intel i5-8350U CPU, torch 2.14 CPU.

## Overall (labelled)

Accuracy **0.8942**, Veyra mIoU **0.6504**; group accuracy 0.8702
(all returns), group mIoU **0.6195**.

| Group | IoU | Prec | Rec | F1 | Support |
| --- | --- | --- | --- | --- | --- |
| drivable (ground) | 0.884 | 0.970 | 0.909 | 0.938 | 297,541 |
| non-drivable (trashcan/cone) | 0.289 | 0.904 | 0.298 | 0.449 | 821 |
| static (building/fence) | 0.683 | 0.768 | 0.860 | 0.811 | 239,223 |
| pole/thin | 0.750 | 0.945 | 0.784 | 0.857 | 19,903 |
| vehicle (car/bike/rider) | 0.855 | 0.945 | 0.900 | 0.922 | 206,607 |
| pedestrian (person; rider is grouped under vehicle) | 0.695 | 0.851 | 0.791 | 0.820 | 6,900 |
| vegetation (plants/trunk) | 0.773 | 0.816 | 0.937 | 0.872 | 259,064 |
| unknown (GT unlabeled; low IoU by construction) | 0.027 | 0.830 | 0.027 | 0.053 | 35,255 |

## Range bins (labelled-only masks; per-bin accuracy derived exactly)

| Bin | Pts | Acc | Veyra mIoU | Group mIoU | Weak groups |
| --- | --- | --- | --- | --- | --- |
| 0–10 m | 168,240 | 0.945 | 0.358 | 0.359 | static 0.629; pedestrian/vegetation/unknown unobserved (null/0) |
| 10–30 m | 598,869 | 0.907 | 0.712 | 0.707 | all observed groups ≥ 0.79 |
| 30–60 m | 229,003 | 0.852 | 0.510 | 0.532 | pole 0.400, pedestrian 0.458 |
| 60 m+ | 33,126 | 0.692 | 0.237 | 0.265 | vehicle 0.070, drivable 0.091, pedestrian 0.016 |

Near field is collision-dense, far field is sparse; mid-field carries the
score. `60m+` includes a 100 m+ tail (10,660 raw returns, ~1%); splitting
60–100 needs per-point re-inference.

## Generalization reference (NOT provider path)

Exact-projection (author tags) seq02 valid split: accuracy 0.8651, mIoU
0.6473; bins 0–10 m 0.364 / 10–30 m 0.678 / 30–60 m 0.397 / 60 m+ 0.271.
Upper reference only — same mIoU family as the provider path on seq00.

## Gaps

Provider-path seq02/04/05 sweep, 60–100/100+ split, per-bin confidence
calibration, and accelerator numbers are all still open (RESULT.md gap 4).
