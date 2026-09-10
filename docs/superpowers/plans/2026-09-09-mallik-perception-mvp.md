# Mallik Perception MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a real-data, mapper-facing perception MVP for RELLIS-3D and
SemanticPOSS: replayed LiDAR becomes an enriched `ObservationFrame` carrying
semantic, ground, terrain, and temporal-motion evidence.

**Architecture:** Dataset adapters remain responsible only for parsing and
world-frame replay. Independent perception stages emit small evidence objects
without mutating adapters. A final pipeline composes those stages and is the
only code allowed to enrich the common `ObservationFrame`, keeping mapper and
viewer consumers independent of individual datasets and model backends.

**Tech Stack:** Python 3, NumPy, PyYAML, optional ONNX Runtime, optional
Patchwork++ backend, C++20/CMake core, existing Three.js viewer.

**Spec:** `docs/perception-terrain-temporal.md`, GitHub issues #4, #5, and #10.

## Global Constraints

- Use the original local RELLIS-3D and SemanticPOSS files under ignored
  `data/raw/`; never add a dataset, model weight, map dump, or generated cloud
  to Git.
- Synthetic fixtures are test-only and must verify parsing/geometry behavior;
  they are not runtime data substitutes.
- No custom semantic-model training and no fabricated inference output.
- Ground truth remains an explicit supported semantic mode; model mode requires
  a supplied ONNX model and reports configuration errors when unavailable.
- Patchwork++ is a real optional backend: do not label a heuristic as
  Patchwork++. If its dependency is unavailable, surface that state explicitly.
- `semantic_class` and motion state remain separate; unknown terrain is never
  treated as drivable.
- Preserve the mapper’s dependency-free C++ build and fixed-world-map
  invariants; perception Python code must not alter map ownership.
- Every production behavior starts with a focused failing test and ends with a
  focused passing test plus the relevant regression suite.

---

### Task 1: RELLIS-3D adapter and unified taxonomy input

**Files:**
- Create: `datasets/rellis/__init__.py`
- Create: `datasets/rellis/adapter.py`
- Create: `tests/test_rellis_adapter.py`
- Modify: `datasets/rellis/README.md`

**Interfaces:**
- Consumes: `datasets.common.ObservationFrame`, `PoseSE3`,
  `map_dataset_labels`.
- Produces: `Rellis3DDataset.list_sequences()`, `list_frames(sequence)`,
  `load_frame(sequence, frame_id, ...)`, and `replay(sequence, ...)`.

- [ ] **Step 1: Write failing adapter tests** for numeric ordering, `.bin` /
  `.label` pairing, `uint32 & 0xFFFF` labels, crop, malformed-record rejection,
  deterministic replay, and the actual configured RELLIS root when it exists.
- [ ] **Step 2: Run the focused tests** and confirm they fail because the
  RELLIS adapter is absent.
- [ ] **Step 3: Implement the adapter** using the same sequence/replay contract
  as SemanticPOSS, with identity pose when RELLIS pose metadata is not present
  in the selected local layout.
- [ ] **Step 4: Run focused tests and the existing dataset tests** until green.
- [ ] **Step 5: Commit only the listed files** using a RELLIS-specific commit.

### Task 2: Semantic provider boundary and real ground-truth/model modes

**Files:**
- Create: `perception/semantic/__init__.py`
- Create: `perception/semantic/provider.py`
- Create: `tests/test_semantic_provider.py`
- Modify: `perception/semantic/semantic_provider.hpp`
- Modify: `perception/README.md`

**Interfaces:**
- Consumes: XYZ/intensity arrays and dataset ground-truth labels.
- Produces: `SemanticResult(class_ids, confidence, mode)` and providers
  `GroundTruthSemanticProvider` and `OnnxSemanticProvider`.

- [ ] **Step 1: Write failing tests** proving ground truth preserves supplied
  mapped labels with confidence 1.0, model mode rejects a missing model/runtime,
  and a supplied ONNX session’s class/confidence result is shape-aligned.
- [ ] **Step 2: Run the focused test file** and confirm it fails because the
  providers do not exist.
- [ ] **Step 3: Implement only the provider boundary and optional ONNX adapter**;
  do not download weights or manufacture a prediction when an ONNX dependency
  or model path is absent.
- [ ] **Step 4: Run provider and dataset tests** until green.
- [ ] **Step 5: Commit only the listed files** using a semantic-provider commit.

### Task 3: Patchwork++ ground evidence boundary

**Files:**
- Create: `perception/ground/__init__.py`
- Create: `perception/ground/patchworkpp.py`
- Create: `tests/test_patchworkpp_ground.py`
- Modify: `perception/README.md`

**Interfaces:**
- Consumes: world-frame XYZ/intensity points.
- Produces: `GroundEvidence(mask, confidence, backend)` from
  `PatchworkPPGroundSegmenter.segment(points)`.

- [ ] **Step 1: Write failing tests** for aligned mask/confidence output and
  explicit unavailable-backend behavior; if Patchwork++ is installed, add an
  integration test against an original local RELLIS frame without committing it.
- [ ] **Step 2: Run the focused test file** and confirm the new behavior fails.
- [ ] **Step 3: Implement the actual Patchwork++ binding/adapter** using a
  supported installed binding or configured executable. The implementation must
  raise `PatchworkPPUnavailableError` rather than substitute an unnamed
  heuristic when the dependency cannot be located.
- [ ] **Step 4: Run ground and dataset tests** until green.
- [ ] **Step 5: Commit only the listed files** using a Patchwork++-boundary
  commit.

### Task 4: Terrain geometry and traversability evidence

**Files:**
- Create: `perception/terrain/__init__.py`
- Create: `perception/terrain/features.py`
- Create: `tests/test_terrain_features.py`

**Interfaces:**
- Consumes: points and `GroundEvidence`.
- Produces: `TerrainEvidence(slope, roughness, height_complexity, step,
  drivable, confidence)` from `TerrainAnalyzer.analyze(points, ground)`.

- [ ] **Step 1: Write failing synthetic-scene tests** showing a flat ground
  patch is drivable, a steep/rough patch is non-drivable, insufficient evidence
  stays unknown, and a height discontinuity produces a step indicator.
- [ ] **Step 2: Run the focused test file** and confirm it fails because terrain
  analysis is absent.
- [ ] **Step 3: Implement local-neighborhood geometric features** with
  configurable radii/thresholds and explicit unknown output for sparse points.
- [ ] **Step 4: Run terrain, ground, and dataset tests** until green.
- [ ] **Step 5: Commit only the listed files** using a terrain-evidence commit.

### Task 5: Ego-motion-compensated temporal association

**Files:**
- Create: `perception/temporal/__init__.py`
- Create: `perception/temporal/tracker.py`
- Create: `tests/test_temporal_tracker.py`

**Interfaces:**
- Consumes: consecutive world-frame points, semantic classes, timestamps, and
  poses.
- Produces: `MotionEvidence(probability, velocity_xy, state, persistence)` from
  `TemporalTracker.update(...)`.

- [ ] **Step 1: Write failing tests** for a static object under ego translation,
  a genuinely translated same-class cluster, a parked vehicle remaining static,
  motion confidence, and stale-track decay.
- [ ] **Step 2: Run the focused test file** and confirm it fails because the
  tracker is absent.
- [ ] **Step 3: Implement deterministic class-aware centroid association** in
  world coordinates, with configurable distance, persistence, and
  static/possibly-moving/moving thresholds.
- [ ] **Step 4: Run temporal and all perception tests** until green.
- [ ] **Step 5: Commit only the listed files** using a temporal-evidence commit.

### Task 6: Pipeline integration, ObservationFrame enrichment, viewer layers,
and verification

**Files:**
- Create: `perception/pipeline.py`
- Create: `tests/test_perception_pipeline.py`
- Modify: `datasets/common/observation.py`
- Modify: `datasets/common/__init__.py`
- Modify: `viewer/server.py`
- Modify: `viewer/static/app.js`
- Modify: `viewer/static/index.html`
- Modify: `viewer/static/styles.css`
- Modify: `configs/datasets.yaml`
- Modify: `datasets/README.md`, `viewer/README.md`,
  `docs/perception-terrain-temporal.md`

**Interfaces:**
- Consumes: a dataset `ObservationFrame`, `SemanticResult`, `GroundEvidence`,
  `TerrainEvidence`, and `MotionEvidence`.
- Produces: `PerceptionPipeline.process(frame) -> ObservationFrame` and viewer
  payload fields for raw, semantic, height, ground, traversability, and motion
  layers.

- [ ] **Step 1: Write failing end-to-end tests** against a temporary fixture and
  one optional original local SemanticPOSS frame: all point-wise fields are
  aligned; ground-truth mode remains deterministic; unavailable Patchwork++ /
  ONNX are represented honestly; motion does not overwrite semantic class.
- [ ] **Step 2: Run the focused pipeline test** and confirm it fails because the
  pipeline does not exist.
- [ ] **Step 3: Implement the composition layer and only then extend the common
  contract** with explicit motion state, step, observation quality, and terrain
  confidence fields where needed.
- [ ] **Step 4: Add viewer controls/readouts for only data actually present**;
  raw, semantic, and height remain available, while unavailable ground/model/
  motion layers state why they are unavailable.
- [ ] **Step 5: Run all Python tests, Ruff, JavaScript syntax checks, CMake
  build, CTest, and real-data smoke checks on original SemanticPOSS and RELLIS
  sequences.**
- [ ] **Step 6: Commit integration only after the full verification evidence is
  green.**

## Integration checklist

- [ ] RELLIS and SemanticPOSS both replay through a dataset-independent
  `ObservationFrame`.
- [ ] Original local data is used for smoke tests; no data/weights were staged.
- [ ] Ground truth and optional ONNX semantic modes are distinguishable.
- [ ] Patchwork++ is either genuinely invoked or explicitly unavailable.
- [ ] Terrain never converts unknown to drivable.
- [ ] Motion state is independent of semantic class and includes XY velocity
  only when associated across frames.
- [ ] Viewer reports real layer provenance rather than invented measurements.
- [ ] C++ mapping build remains green.
