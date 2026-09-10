# Perception Acceptance Implementation Plan

**Goal:** Deliver Mallik's real pretrained semantics, correct perception evidence, and reproducible perception acceptance for issues #4, #5 and the perception portion of #20.

**Architecture:** Keep the public ObservationFrame and C++ map boundary. Run sensor-trained backends in LiDAR coordinates, terrain and temporal processing in their documented coordinates, and measure the actual persistent mapper. Three stacked PRs make dependent changes reviewable without merging them automatically.

**Tech stack:** C++20/CMake; NumPy, CPU ONNX Runtime, official Patchwork++ bindings; existing Python test infrastructure.

**Spec:** `docs/perception-terrain-temporal.md`, `docs/map-correctness.md`, `docs/datasets-benchmarks.md`; issue #4 replay/poses and #5 perception; user acceptance tasks 1–7. The externally published PS description must be distinguished from repository-specific scope and unverified mirrors.

## Constraints

- Fixed world lattice; one observation per leaf; sufficient statistics without raw point history.
- Unknown is not free; category is not motion; timestamps and poses must have source provenance.
- No datasets, models or generated benchmark dumps committed. Fetch pinned assets into ignored paths.
- CPU proof first; bounded representative runs and explicit checkpoints for large/GPU workloads.

## PR 1 — Real semantic backends and coordinate-correct perception

Own `perception/semantic/`, `perception/pipeline.py`, ground/terrain code, taxonomy, relevant tests, model configuration and setup/acceptance scripts.

- [ ] Tests: nearest-return projection, normalization, original point order, invalid inputs/model outputs, taxonomy by meaning, world-pose backend invariance, obstacle-not-drivable, enabled-stage failure.
- [ ] Implement SalsaNext range-image ONNX provider using upstream checkpoint/preprocessing specifications. Keep per-point confidence and explicit unknown support.
- [ ] Fetch a pinned pretrained asset with checksum; run actual CPU inference and Patchwork++ on local full scans; record backend stage timings and counts.
- [ ] Correct RELLIS taxonomy and unsafe terrain broadcasting; verify ground/terrain behavior with real scans and synthetic regression cases.
- [ ] One strict acceptance command must reject missing required stages and feed enriched frames to the real C++ mapper.

## PR 2 — Temporal and replay correctness

Own temporal tracker/profiler, dataset adapters/tests and perception output validation. C++ map storage/fusion, LOD, governor and renderer belong to the other contributors and are excluded. Existing map consumers may be exercised read-only; findings requiring their code are handoffs.

- [ ] Profile full-frame temporal clustering before/after. Test parked/moving, timestamp equality, first observation uncertainty, TTL, reset, ego-motion contract and bounded dense workloads.
- [ ] Cache sequence discovery/metadata; validate original timestamp/pose/calibration conventions and preserve deterministic frame selection.
- [ ] Prove aligned enriched ObservationFrame fields and serialization. Record downstream gaps without changing map fusion or snapshot APIs.
- [ ] Run representative real-data paths; state unavailable metadata rather than generating it.

## PR 3 — Regression measurements and acceptance

Own benchmark runner/support scripts/tests, CI, acceptance documentation.

- [ ] Deterministic real-data slice manifest with pinned hashes and provenance, fetched outside Git; CI executes production perception and uploads measurements.
- [ ] Measure perception-stage p50/p95/p99, throughput, RSS, alignment, semantic accuracy by range when labels exist. Hosted-runner timing is diagnostic, not a hardware-independent FPS guarantee.
- [ ] Full perception Python tests, malformed/reset regressions and existing CI checks; preserve C++ build verification without adding mapping features or redesigning its benchmarks.
- [ ] Independent integration/review pass, publish each scoped PR and inspect actual GitHub checks. Do not mark blocked assets or pending checks complete.

## Acceptance commands

Existing baseline: `.venv/bin/python -m pytest tests benchmarks -q`; `cmake -S . -B /tmp/veyra-acceptance -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS='-Wall -Wextra -Wpedantic -Werror'`; `cmake --build /tmp/veyra-acceptance -j2`; `ctest --test-dir /tmp/veyra-acceptance --output-on-failure`.

New real-model/strict execution and regression commands will be documented alongside the tested executable scripts when their exact asset contracts are verified.
