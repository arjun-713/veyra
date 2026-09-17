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
