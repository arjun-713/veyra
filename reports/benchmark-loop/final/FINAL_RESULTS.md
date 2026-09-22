# FINAL benchmark results — fixed-benchmarks @ 764957b, i5-8350U, GCC 16.2.1 Release

Selection: SemanticPOSS 00 frames 0–9, warmup 2, 2 reps/round × 2 independent rounds,
identical digest `a5d6ea7c…`. Perception: ground_truth + Patchwork++ + terrain.
Machine-readable: FINAL_RESULTS.json/csv. N/A = unmeasured, never zero.

## Policy table (final round 1, rep 0; round 2 bit-identical on logical/RMSE/cells)

| Policy | Logical | Peak RSS | Active cells | Map p50 | Map p95 | E2E p95 | FPS | RMSE | Bands 0–10/10–30/30–60/60–100 | Sem | Haz | Ped | Pole | Veh |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Uniform5 | 53.2 MB | 262.8 MB | 303,205 | 546 ms | 906 ms | 906 ms | 0.77 | 0.0000 | 0/0/0/0 | .995 | .933 | .968 | .964 | .991 |
| Uniform40 | 4.5 MB | 33.4 MB | 25,375 | 245 ms | 254 ms | 376 ms | 2.99 | 0.5638 | .11/.42/.81/.72 | .945 | .844 | .748 | .938 | .977 |
| DistanceLOD | 25.8 MB | 139.5 MB | 145,671 | 213 ms | 228 ms | 393 ms | 2.97 | 0.4321 | .02/.24/.63/.72 | .972 | .890 | .860 | .955 | .971 |
| UtilityLOD | 27.5 MB | 151.7 MB | 152,883 | 275 ms | 286 ms | 485 ms | 2.40 | 0.4344 | .02/.24/.63/.73 | .959 | .848 | .859 | .938 | .953 |
| 3D sparse MEASURED | 15.1 MB acct | 355.5 MB¹ | 494,113 vox | 21.9 ms | 36.0 ms | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 3D dense ANALYTICAL | 117,351 MB est | n/a | 7.33B est | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

¹ incl. interpreter + retained frames; accounted bytes are the comparator.

## Range-binned perception (CENet native, POSS 00, 8 fr, ORT n/a — torch CPU)

| Range | Points | mIoU | Car | Person | Note |
|---|---|---|---|---|---|
| 0–10 m | 80,842 | 0.355 | 0.973 | 0.000 | near-field small-class weakness |
| 10–30 m | 301,150 | 0.686 | 0.875 | 0.764 | best operating band |
| 30–60 m | 116,293 | 0.503 | 0.642 | 0.458 | degrading |
| 60 m+ | 17,002 | 0.225 | 0.023 | 0.025 | far-field collapse |

Overall: mIoU 0.628, accuracy 0.891, latency p50 5.4 s (non-real-time, proven floor).

## UtilityLOD conclusion
DISTANCELOD BETTER on this selection (retention + memory + churn on every axis).
Headline production policy: DistanceLOD. UtilityLOD experimental. Ablation matrix in
iteration-04 (every signal +1.7 MB, −retention vs pure distance; 1024 churn actions vs 0).
