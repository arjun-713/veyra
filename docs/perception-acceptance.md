# Mallik perception acceptance

## Requirement and ownership

The [official SIH26053 statement](https://www.sih.gov.in/sih2026PS), inspected on 2026-09-10, requires learned point-cloud semantics, terrain drivability, distance-dependent 2.5D mapping, visualization and accuracy/latency evidence across distances. Its 5 cm near/50 cm distant cells are examples, not a mandate for a non-dyadic hierarchy.

Mallik owns replay/transforms, ground, semantics, taxonomy, terrain, temporal evidence and ObservationFrame. The other contributors own map storage/fusion/topology and LOD/governor/renderer/telemetry. These PRs modify perception and its validation; downstream findings are handoffs, not permission to change those engines.

## Real pretrained semantics

```bash
.venv/bin/python -m scripts.fetch_semantic_model
.venv/bin/python -m scripts.validate_perception \
  --dataset semanticposs --root data/raw/semanticposs/dataset --sequence 00 \
  --count 10 --config configs/perception-salsanext.yaml \
  --output benchmark-results/poss-model.json
```

The model manifest pins the publisher release, download size, archive and extracted-file SHA-256. Runtime never downloads weights implicitly. The 25 MB Qualcomm float SalsaNext export loads with CPU ONNX Runtime 1.22.0. Its 20 SemanticKITTI learning IDs already match the canonical Veyra taxonomy; applying the raw SemanticKITTI label conversion a second time would corrupt them.

Projection follows [the publisher's preprocessing](https://github.com/qualcomm/ai-hub-models/blob/v0.62.1/src/qai_hub_models/models/salsanext/app.py): range/XYZ/remission, 64×2048, field of view −25° to +3°, fixed channel normalization. Sensor coordinates are recovered from the adapter's transform before inference/Patchwork++; terrain and output coordinates stay in their existing frame. Nearest-return pixel collisions share predictions without KNN. Zero-range/out-of-FOV returns are unknown with zero confidence. Model probabilities are not calibrated confidence on different sensors/environments.

Local SemanticPOSS and RELLIS intensities use byte-scale values, so their model configuration explicitly uses `intensity_scale: 255`. KITTI-normalized remission needs `intensity_scale: 1`. Incorrect ranges fail validation rather than being guessed.

## Validation meaning

The validation command requires semantic, Patchwork++ and terrain stages to execute, verifies point order/coordinates, and reports each stage's latency, overall FPS and peak process RSS. It compares model predictions to mapped dataset labels per distance band. GT mode is labeled passthrough validation and is not counted as model accuracy. A short CPU run proves execution, not real-time deployment or robust accuracy under domain shift.

Use `--require-temporal` only with genuine poses and timestamps. It fails if that metadata is absent; no frame-rate assumptions or synthetic poses are inserted. See `dataset-validation.md` for source evidence. Missing timestamps block a real motion-validation claim even when the tracker passes controlled regression tests.

## Explicit acceptance checkpoints

The current checkout has no SemanticKITTI asset, so temporal acceptance is not
claimed from RELLIS/SemanticPOSS. Once an authorized local SemanticKITTI root is
available, run:

```bash
.venv/bin/python -m scripts.validate_perception \
  --dataset semantickitti --root /path/to/semantic-kitti \
  --sequence 00 --count 100 --config configs/perception.yaml \
  --require-temporal --output benchmark-results/semantickitti-temporal-100.json
```

Expected evidence is `temporal_proven: true`, dataset-backed pose and timestamp
provenance for every frame, non-zero temporal samples where the sequence has
motion, and the reported stale-track/ego-motion regression results. Do not
download or redistribute the dataset through ordinary PR CI without confirming
its license and storage budget.

ASan/UBSan is a host-toolchain checkpoint: the installed GCC links against
`/usr/lib64/libasan.so.8.0.0`, which is absent on this host. The exact retry is:

```bash
cmake -S . -B /tmp/veyra-asan -DCMAKE_BUILD_TYPE=Debug \
  -DBUILD_TESTING=ON -DVEYRA_BUILD_APPS=ON \
  -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
  -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'
cmake --build /tmp/veyra-asan --parallel
ctest --test-dir /tmp/veyra-asan --output-on-failure
```

## Boundaries for other contributors

Perception integration tests may exercise the existing C++ consumer without changing its storage. Retaining versus discarding observation fields, separating dynamic/static elevation statistics, map-quality comparisons, split/merge and resource governance remain the corresponding contributors' responsibilities. Ground/terrain masks alone cannot make an unsafe downstream fusion rule safe.
