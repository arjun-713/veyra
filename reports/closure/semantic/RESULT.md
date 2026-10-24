# Closure: neural semantic segmentation correctness (SalsaNext)

- Status: **closed with root cause proven; checkpoint rejected for Pandora data**
- Branch: `agent/perception-semantic` @ `c1b6b8f36d55661278fc7858185f9c218e8e825e`
  (code + `reports/closure/semantic/salsanext-poss-metrics.json`); this report
  follows in the same branch.
- Base: `demo-readiness` @ `6e3cece`.

## Verdict

The ~25%-class neural path failure is **not a code bug**. Projection,
normalization, tensor layout, learning map, class IDs, ignored-label
handling, confidence zeroing, point order, and the ONNX export all verify
exactly against the checkpoint's training sources. The pinned SalsaNext
checkpoint is a SemanticKITTI / Velodyne-HDL-64E model and is fundamentally
incompatible with SemanticPOSS / Hesai-Pandora scans on geometry (FOV,
vertical resolution), input distribution (intensity, range), and taxonomy
(single `ground` class, no `other-vehicle`). No geometry or taxonomy "fix"
can recover it; the honest fix is a native Pandora checkpoint (spec below).
The pipeline dataset gate already refuses POSS frames, and that refusal is
kept.

## Root cause (measured, not suspected)

1. **Vertical FOV mismatch (hard):** Pandora spans -15.54..+7.30 deg
   (nominal -16..+7); checkpoint covers -25..+3. Only 90.5% of returns are
   projectable; the whole upper band of every scan is forced unknown.
2. **Vertical resolution mismatch (hard):** 40 Pandora beams fill 30/64
   range-image rows; 34 rows are always blank — far outside training data.
3. **Remission shift:** POSS byte intensity 1..255, mean/255 = 0.05 vs
   training mean 0.21 (~-1 std); range mean 26.2 m vs 12.12 m (~+1.1 std),
   extremes to 15 sigma after normalization.
4. **Taxonomy collision (unfixable without retraining):** POSS `ground`
   (297,541 GT points) maps to other-ground (12) while the model predicts
   road (245,782 predictions, IoU 0.00); POSS has no other-vehicle class
   while the model predicts 150,650 of them; rider/bike/people splits do
   not align.
5. **Overconfidence:** mean 0.86 / p50 0.97 confidence on predicted-known
   at 29.3% accuracy. Unknown stays failure-safe at 0, but raw confidence
   must not feed downstream weighting cross-domain.

## Files

- `perception/semantic/salsanext.py` — unchanged (verified correct).
- `perception/semantic/semantic_provider.py` — unchanged.
- `scripts/measure_salsanext_cross_domain.py` — new reproducible
  measurement (direct provider inference on sensor-frame points; records
  its pipeline-gate bypass in the artifact).
- `tests/test_salsanext.py` — extended (upstream-formula cross-check,
  determinism/tie-break, round-trip order, collisions, channel layout,
  learning-map pin, FOV boundaries, ONNX-present inference, real-frame
  sensor pins).
- `tests/test_semantic_provider.py` — extended (unknown->0 confidence
  despite backend value; known passthrough).
- Historical semantic-evidence documentation; current provider contract:
  [perception, terrain and temporal processing](../../../docs/perception-terrain-temporal.md).
- `reports/closure/semantic/salsanext-poss-metrics.json` — raw artifact.
- Untouched per ownership: `src/map/*`, `src-tauri/src/control/*`,
  `datasets/*/adapter.py`, `viewer/*`.

## Tests

- `pytest tests/test_salsanext.py tests/test_semantic_provider.py`:
  **33 passed** with `VEYRA_SALSANEXT_MODEL` + `VEYRA_SEMANTICPOSS_ROOT`
  pointed at the shared checkout's assets (31 passed, 2 skipped without).
- Related suites: `test_taxonomy`, `test_semantickitti_adapter`,
  `test_semanticposs_adapter`, `test_perception_pipeline`,
  `test_perception_validation`: all pass.
- C++ `ctest`: Python-only change set; no C++ files touched, so existing
  build results are unaffected (no new build run; no map code in scope).

## Real data

- Dataset: SemanticPOSS v1.0, `data/raw/semanticposs/dataset`, sequence
  `00`, frames `000000`-`000015` (first 16), 1,065,314 labelled points.
- Checkpoint: `salsanext.onnx` sha256
  `067086f8...b9d8b298804b548`, companion `7d3f1993...3ad5a2e52f`
  (match pinned manifest).
- Hardware: Intel i5-8350U CPU, 15 GB RAM, shared host (load ~16);
  ORT 1.30.0, threads 2, intensity_scale 255.
- Result: all-return mIoU **0.0872**, model-FOV mIoU **0.0941**, labelled
  accuracy **0.2931**; per-class IoU car 0.454 / building 0.393 /
  vegetation 0.166 / fence 0.164 / rider 0.117 / other-ground 0.064 /
  road 0.000; near-field 0-10 m mIoU 0.065; prediction histogram spans 15
  classes (executes correctly, answers the wrong sensor's question).
- Bench: per-frame latency p50 **3.0 s** / p95 **4.4 s** (includes session
  steady state; first timed frame 6.4 s), peak process RSS **783 MB**
  (+666 MB over pre-inference). Prior 1.96/2.07 s was a quieter host;
  either way, ~2-4 s/frame CPU is not real-time capable for the mapper.

## Gaps / fine-tune spec (do not train here — separate agent)

1. Native Pandora checkpoint (e.g. CENet SemanticPOSS path, MIT source):
   contract must be `40 x 1800`, FOV `-16..+7`, native POSS labels +
   explicit POSS->Veyra projection, KNN policy documented; record source
   URL/revision, license, archive + weight sha256, and re-run this report's
   metric set (native 14-class + projected mIoU, range bins, critical
   classes, point-order/collision proof, p50/p95/p99 + RSS) before enabling.
2. If fine-tuning SalsaNext instead: retrain or adapt the head on POSS
   with the POSS learning map, 40x1800 (or 64x2048 with Pandora masking
   documented), byte-intensity normalization recomputed on POSS stats, and
   a `ground`-aware taxonomy decision (split vs other-ground) recorded;
   quality gate stays model-FOV mIoU >= 0.30 / coverage >= 0.90 /
   ground F1 >= 0.75.
3. Add confidence calibration (or cap cross-domain confidence) before any
   checkpoint's confidence weights traversability; unknown-at-0 is kept
   regardless.
