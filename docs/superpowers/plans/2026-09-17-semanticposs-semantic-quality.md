# SemanticPOSS Neural Semantic Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace the incompatible SemanticKITTI SalsaNext evidence path with a reproducible point-aligned neural SemanticPOSS provider and a real-data quality report.

**Architecture:** Keep `SemanticProvider` and `ObservationFrame` stable. A provider must declare the sensor geometry and taxonomy for which its pinned model was trained; incompatible datasets are rejected before inference. A native provider returns class and confidence arrays in original point order.

**Tech Stack:** Python 3.14, NumPy, ONNX Runtime CPU, SemanticPOSS labels, existing pipeline and evaluator.

**Spec:** `/home/arjun/.codex/attachments/a806a086-805f-44aa-bf7c-1217192f160c/pasted-text-1.txt`

## Global Constraints

- Ground-truth labels are debug/benchmark-only, never neural-model evidence.
- Do not download an unpinned checkpoint; source URL, source revision, license and every SHA-256 must be in a manifest first.
- A pass requires real labelled frames, critical class metrics, all four distance bins, model/config/dataset provenance and a passing quality gate.
- Do not run long model evaluation before the model contract is verified.

### Task 1: Reject incompatible model geometry

**Files:**
- Modify: `perception/semantic/salsanext.py`
- Modify: `perception/pipeline.py`
- Test: `tests/test_salsanext.py`

**Interfaces:**
- Produces: an explicit error if the 64x2048, +3/-25 degree SemanticKITTI SalsaNext contract is requested for SemanticPOSS.

- [ ] Write a failing test:

```python
def test_semantickitti_salsanext_is_rejected_for_semanticposs():
    with self.assertRaisesRegex(ValueError, "incompatible.*SemanticPOSS"):
        SalsaNextSemanticProvider.for_dataset(model_path, "semanticposs")
```

- [ ] Run: `.venv/bin/python -m pytest -q tests/test_salsanext.py -k semanticposs`
- [ ] Implement a dataset/sensor-contract compatibility check before session creation.
- [ ] Re-run: `.venv/bin/python -m pytest -q tests/test_salsanext.py`
- [ ] Commit: `git commit -m "fix(semantic): reject incompatible SalsaNext dataset geometry"`

### Task 2: Require native model provenance

**Files:**
- Create: `configs/semanticposs-model.json`
- Modify: `scripts/fetch_semantic_model.py`
- Test: `tests/test_perception_validation.py`

**Interfaces:**
- Consumes: dataset ID, source URL/revision, license URL, archive SHA-256, per-file SHA-256, sensor contract, taxonomy revision.
- Produces: a validated model manifest; fetch rejects missing or altered provenance.

- [ ] Write a failing test:

```python
def test_native_manifest_rejects_missing_source_license_or_digest(self):
    with self.assertRaisesRegex(ValueError, "license|sha256"):
        validate_model_manifest({"dataset": "semanticposs", "model": "model.onnx"})
```

- [ ] Run: `.venv/bin/python -m pytest -q tests/test_perception_validation.py -k native_manifest`
- [ ] Implement exact required-key and SHA-256 validation.
- [ ] Re-run: `.venv/bin/python -m pytest -q tests/test_perception_validation.py`
- [ ] Commit: `git commit -m "feat(semantic): require native model provenance manifests"`

### Task 3: Implement point-aligned native inference

**Files:**
- Create: `perception/semantic/semanticposs_provider.py`
- Modify: `perception/pipeline.py`
- Create: `configs/perception-semanticposs.yaml`
- Test: `tests/test_semanticposs_provider.py`

**Interfaces:**
- Consumes: `points: ndarray[(N,4)]` and a validated native manifest.
- Produces: `SemanticResult(classes: ndarray[(N,)], confidence: ndarray[(N,)], source="model")` aligned to each original input index.

- [ ] Write a failing test:

```python
def test_provider_restores_original_point_order_after_projection():
    result = provider.infer(points)
    assert result.classes.shape == (len(points),)
    np.testing.assert_array_equal(result.input_indices, np.arange(len(points)))
```

- [ ] Run: `.venv/bin/python -m pytest -q tests/test_semanticposs_provider.py -k original_point_order`
- [ ] Implement preprocessing, inference, output validation, unprojection and unified-taxonomy mapping. Reject nonfinite, unaligned and out-of-range output.
- [ ] Re-run: `.venv/bin/python -m pytest -q tests/test_semanticposs_provider.py tests/test_perception_pipeline.py`
- [ ] Commit: `git commit -m "feat(semantic): add aligned SemanticPOSS neural provider"`

### Task 4: Gate a real quality result

**Files:**
- Modify: `scripts/validate_perception.py`
- Modify: `configs/perception-semanticposs.yaml`
- Modify: `tests/test_perception_validation.py`
- Modify: `reports/submission_closure.json`

**Interfaces:**
- Produces: machine-readable accuracy, mIoU, per-class IoU/precision/recall/F1, range bins 0–10/10–30/30–60/60–100 m and provenance.

- [ ] Write a failing test requiring finite metrics for drivable ground, static structure, pole, vehicle, pedestrian and vegetation plus every range bin.
- [ ] Run: `.venv/bin/python -m pytest -q tests/test_perception_validation.py -k critical_class_metrics`
- [ ] Implement required critical-class/range gates; do not treat absent class evidence as zero or pass.
- [ ] After pinned model acquisition, run:

```bash
.venv/bin/python scripts/validate_perception.py --dataset semanticposs --root data/raw/semanticposs/dataset --sequence 00 --count 100 --perception-config configs/perception-semanticposs.yaml --output benchmark-results/semanticposs-native-quality.json
```

- [ ] Close the scorecard row only when the report and quality gate pass.

## Self-Review

This plan covers the current P0 incompatibility, provenance, alignment, critical classes and range-binned real-data evidence. CUDA/TensorRT work follows a correct CPU provider; it cannot substitute for model compatibility.
