# Ground and terrain evidence

This checkout uses `scripts/validate_perception.py` with evaluator version
`ground-terrain-evaluator-v1` for bounded perception evidence. The report
records the dataset, sequence, selected frame range, configuration SHA-256,
Patchwork++ ground ratio, point counts, and binary ground precision, recall,
F1, and IoU when a documented reference exists.

## Reference contract

SemanticPOSS v1.0 raw label `22` is documented by its `LABEL_DICT` as
`ground`. It is therefore the only local dataset mapping currently accepted
for pointwise Patchwork++ ground quality. The evaluator compares the predicted
Patchwork++ mask with `raw_semantic_class == 22` and preserves unknown labels
through the valid-reference mask.

RELLIS-3D labels describe classes/materials including dirt, mud, grass,
asphalt, rubble, and concrete. Those labels do not constitute a documented
pointwise ground-support reference for this pipeline, and dirt/mud cannot be
silently promoted to ground. RELLIS ground precision/recall/F1/IoU therefore
remain unavailable unless a separately documented ground-reference mapping is
added.

Neither SemanticPOSS nor RELLIS-3D supplies the production labels
`drivable`, `non_drivable`, and `unknown`. Terrain reports consequently expose
the three predicted-state counts and fractions but mark terrain quality as
unavailable. `unknown` is never counted as drivable.

## Bounded local run status — 2026-09-17

The requested real-data command shape is:

```bash
.venv/bin/python -m scripts.validate_perception \
  --dataset semanticposs --root data/raw/semanticposs/dataset \
  --sequence 00 --start 0 --count 3 --config configs/perception.yaml \
  --output benchmark-results/ground-terrain-semanticposs-00-0-3.json

.venv/bin/python -m scripts.validate_perception \
  --dataset rellis3d --root data/raw/rellis3d/Rellis-3D \
  --sequence 00000 --start 0 --count 3 --config configs/perception.yaml \
  --output benchmark-results/ground-terrain-rellis-00000-0-3.json
```

Both roots were present locally and the commands completed on exactly three
frames each. The machine-readable outputs were written to
`/tmp/ground-terrain-semanticposs-00-0-3.json` and
`/tmp/ground-terrain-rellis-00000-0-3.json`.

SemanticPOSS `00`, frames `[0, 3)`, 198,105 evaluated points:

| precision | recall | F1 | IoU | predicted ground ratio | reference ground ratio |
|---:|---:|---:|---:|---:|---:|
| 0.784167 | 0.949608 | 0.858994 | 0.752840 | 0.333227 | 0.275172 |

Counts were TP 51,766, FP 14,248, FN 2,747, TN 129,344. Range-binned F1 was
0.874330 (0–10 m), 0.903797 (10–30 m), 0.572707 (30–60 m), and 0.072754
(60–100 m). The result is a three-frame sample, not an exhaustive sequence
score or a deployment threshold.

Its separate terrain output counts were drivable 48,007, non-drivable 16,811,
and unknown 133,287 of 198,105 points. These are production predictions only;
terrain quality is unavailable because the dataset has no documented
drivability labels.

RELLIS-3D `00000`, frames `[0, 3)`, 109,031 evaluated points:

- Ground reference status: unavailable; no ground metrics were emitted and
  `ground_evaluation.overall` is `null`.
- Ground ratios by frame were 0.413848, 0.414595, and 0.478617.
- Terrain prediction counts were drivable 11,228, non-drivable 35,829, and
  unknown 61,974.
- Terrain quality status: unavailable; RELLIS labels do not document the
  three production traversability states.

Both runs executed the installed official `pypatchworkpp` backend and the
production terrain analyzer. They used `configs/perception.yaml`, whose
SHA-256 was
`6779fd71872fcc6b9c7b449fe52c293536e79b9f6963b1b27c646c504b113551`.
The validator also recorded per-stage timings, point-order preservation, and
dataset provenance in each JSON artifact. No quality threshold was invented;
the 60–100 m SemanticPOSS ground degradation is retained as measured.

## Terrain closure — 10-frame quality + latency (2026-09-17, agent/terrain)

Analyzer: `perception/terrain/features.py` (integral-image box sums;
complexity = `tanh` of local height std; neighbor steps over supported cells
only). Two real quality bugs were fixed and are pinned by regression tests in
`tests/test_terrain_features.py`:

- Height spread used the raw second moment, so flat ground at z = 5 m scored
  ~1.0. Now elevation-invariant (centered variance). Reference-ground
  complexity p50 0.112 -> 0.017.
- Neighbor steps compared real heights against the zero fill of empty cells,
  fabricating metre-scale phantom steps at support edges. Only supported
  cells now participate. RELLIS predicted-ground step p50 0.93 m -> 0.069 m.

Numerics vs the pre-fix implementation on real frames: step bitwise
identical, slope/roughness within 1.2e-7, 100% drivable-label agreement
before the intentional step fix.

SemanticPOSS `00`, frames `[0, 10)`, 659,737 evaluated points
(config SHA-256 unchanged, `6779fd71...1351`):

| precision | recall | F1 | IoU | predicted ground ratio | reference ground ratio |
|---:|---:|---:|---:|---:|---:|
| 0.776200 | 0.950371 | 0.854500 | 0.745963 | 0.343172 | 0.280280 |

Terrain has no documented point labels, so P/R/F1/IoU stay unavailable.
Measured proxies: P(drivable | ref ground) 0.911, P(unknown | ref ground)
0.052, P(drivable | ref non-ground) 0.036 (bounded by ground false
positives), P(unknown | ref non-ground) 0.901 — unknown is never free.
Trusted-ground features: slope p50/p95 0.014/0.097 rad, roughness
0.008/0.060 m, step 0.018/0.126 m, spread 0.017/0.091. Per-raw-label split:
ground (22) 91.1% drivable; every other raw class <= 12.8% drivable.

RELLIS-3D `00000`, frames `[0, 10)`, 363,503 evaluated points: terrain
33.3% drivable / 10.3% non-drivable / 56.4% unknown; predicted-ground
features slope p50/p95 0.053/0.359 rad, roughness 0.035/0.202 m, step
0.069/0.401 m.

Latency (Intel i5-8350U, Fedora Linux 7.2.5, Python 3.13.15, contended box):
RELLIS terrain p50/p95 130.8/177.8 ms -> 77.7/94.3 ms; interleaved same-frame
A/B median speedup 1.35x (SemanticPOSS 66k pts) and 1.31x (RELLIS 36k pts).
Ground Patchwork++ p95 measured 74.5 ms (SemanticPOSS) and 18.6 ms (RELLIS)
on those runs; the ground stage was not modified. Full tables:
`reports/closure/terrain/terrain-latency.json`; quality proxies:
`reports/closure/terrain/terrain-quality.json`.
