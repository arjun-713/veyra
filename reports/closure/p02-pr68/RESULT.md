# PR68 independent real-data acceptance: HOLD / NOT CLOSED

Historical acceptance record for the source and paired JSON artifacts below.
PR/issue decisions in this record describe that review, not current GitHub state.

Real SemanticKITTI sequence 08 is locally available: 220 aligned scans/labels
(27,219,030 points), calibration, 4,071 poses and 4,071 increasing dataset
timestamps. The subset contains frames 0–99, 400–459 and 3990–4049.
No timestamps, scans or motion labels were fabricated.

## Paired persistent-map experiment

Frames **000043–000054**, genuine world-frame poses/times, independent dataset
moving labels, GT semantics explicitly for evaluation, real installed
Patchwork++ ground, terrain and temporal processing. Both maps consume the
identical enriched observations in the same order, using DistanceLOD. Clearing
is the only policy difference. The observer includes the production
PersistentEngineSession implementation; it does not reimplement clearing.
Sensor height is explicitly zero because this adapter's pose is the LiDAR
origin. That is distinct from a body-origin pose plus a sensor-height offset.

Hardware: Intel Core i5-8350U, Linux x86_64, CPU-only. Runs shared the laptop
with regression tests; timings are under-load observations, not performance
claims. Twelve samples do not establish reliable p95/p99 tails.

| Seed support | Clearing disabled, final | Clearing enabled, first | Clearing enabled, final |
|---|---:|---:|---:|
| Moving car, raw252 instance4 | 1200/1200 occupied | 1102/1200 | 243/1200 |
| Parked cars, raw10 | 664/664 occupied | 641/664 | 368/664 |

The moving car no longer supplies any of its initial XY support bins in the
final scan. Enabling clearing reduces retained occupied support to **20.25%**,
but does not eliminate it. Parked support falls to **55.42%**. Those are unique
5cm seed XY bins sampled at their centers against resident-leaf occupancy,
**not object IoU or a perfect visibility-ground-truth mask**. Resampling,
mixed/coarse-cell footprints and legitimate disocclusion require investigation
before classifying each parked-bin loss. Initial-scan losses are especially
concerning: occupied support is downgraded while the scene is being observed.
The paired comparison therefore **does not pass safe ghost-cleanup acceptance**.

All frame point-conservation and parent/descendant checks passed. The two maps
retain identical point counts. Both observer processes exited cleanly.
Full selected-frame hashes, actual pipeline status, frame counters and latency
summaries are in `paired-real-kitti08.json`. This is branch-local evidence;
the recorded SHA/dirty state must not be relabelled as current-main proof.

## Integration findings

Two regressions were reproduced before their narrow fixes:

1. Shared config rejected `map.clear_free_space`.
2. Shared ProductRuntime did not forward that flag to PersistentMapEngine.

The added configuration tests exercise normalization and real session creation.
The flag remains boolean-only and opt-in. No temporal or map defaults changed.
The installed 3.13 environment has Patchwork++; the separate system 3.14
environment has Torch. Do not pretend those are one validated deployment.

## Reproduce

```sh
cmake -S . -B build-samay-integration -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build-samay-integration --parallel 2
c++ -std=c++20 -O2 -Wall -Wextra -Wpedantic -Werror -I include \
  -DVEYRA_SOURCE_DIR="\"$PWD\"" \
  reports/closure/p02-pr68/probe.cpp \
  build-samay-integration/src/map/libveyra_map.a \
  build-samay-integration/src/policy/libveyra_policy.a \
  build-samay-integration/src/metrics/libveyra_metrics.a \
  -o /tmp/veyra_persistent_probe
.venv/bin/python reports/closure/p02-pr68/replay.py
.venv/bin/python scripts/validate_temporal.py --dataset semantickitti \
  --root data/raw/semantickitti/dataset --sequence 08 --start 100 --count 20 \
  --exclude-classes 9,10,11,12,17 --output /tmp/kitti08-quiet-window.json
```

`--start 100` is subset index 100, which selects real frame 000400; using 400
as the subset index is invalid. `VEYRA_GHOST_PROBE` and `VEYRA_CLEARING_REPORT`
override the observer/output paths. The replay never writes datasets or models.

## Verification scope

- Release build passed; all 23 non-Python CTest entries passed.
- Tauri/Rust library tests: 67 passed, including the real packaged-control flow.
- Frontend: 78 tests passed; Svelte check and production build passed.
- Fresh-binary product-service/map-bridge slice: 14 tests passed.
- Configuration and clearing forwarding regressions: 2 tests passed.
- Full CTest is **not reported green**: its Python entry selected an older
  benchmark executable and failed three bridge assertions. The generated CTest
  entry lacks `VEYRA_BENCHMARK_BINARY` because tests are configured before the
  apps target exists. A focused rerun with the explicit freshly built benchmark
  passed all 14 product/bridge tests. Full-suite reruns must set all three of
  `VEYRA_BENCHMARK_BINARY`, `VEYRA_RUNTIME_BINARY` and `VEYRA_MAPPER` explicitly.

## Required follow-up before merge

- Trace currently observed/static occupied cells that the raster contradicts.
- Check world-space cell footprint versus single-bearing clearing attribution.
- Quantify stationary/occluded retention with independently justified visibility.
- Resolve parked-support loss before enabling the demo's clearing path.
- Validate live temporal visualization separately; a CLI replay is not UI proof.

PR68 is deliberately **not merged** and issue54 is not closed by this result.

## Intermediate clearing correction

`paired-real-kitti08-fixed.json` repeats the same seq08 frames 43–54, real
poses/times and GT + Patchwork++/terrain/temporal pipeline. It corrected
same-frame self-clearing, beam-centre elevation approximation and rays that
never crossed the cell's XY footprint. Current-frame obstacle hits are
protected; measured angles and square-entry/exit tests constrain clearing,
with occlusion winning conflicting through-beams. Cells retain no point history;
two fixed-raster angle arrays supply the extra scan evidence.

| Seed bins | Original ON first/final | Corrected ON first/final | OFF final |
| --- | ---: | ---: | ---: |
| Moving car, raw252 instance4 | 1102 / 243 | 1200 / 25 | 1200 |
| Parked cars, raw10 | 641 / 368 | 664 / 584 | 664 |

Residual moving support was 2.08%; parked retention 87.95%, versus 20.25% and
55.42% originally. These are first-frame XY bins, not object IoU or visibility
GT. At frame54, 967/13151 currently observed obstacle cells remained below
Occupied after earlier negative evidence (zero with clearing off). The result
remained partial; the 80 parked-bin losses were not all proven false clearing.
Point conservation/topology passed and both processes exited. This revision's
CTest passed 24/24 in 231.95 s; Python discovery ran 427 tests with 417 passes
and 10 optional skips. Twelve frame samples do not establish tail latency.

## Follow-up: two-strike PR head, fresh paired replay

The final PR head adds a two-consecutive-contradiction arm before decrementing
occupied log odds. I rebuilt the observer and runtime libraries from this
checkout, then repeated the same SemanticKITTI 08 frames 000043–000054 against
the same real poses, timestamps and dataset labels. Both clearing modes
received identical pipeline observations. The per-frame artifact is
`paired-real-kitti08-two-strike.json`; it records raw input hashes, map
invariants, point conservation, seed-bin occupancy, seed-bin Free state,
currently observed obstacle cells, and child-process exit state.

At frame 54, among the original 1,200 moving-car 5 cm seed bins, clearing ON
reported 145 occupied, 866 Free and 189 Unknown; clearing OFF retained all
1,200 as occupied and declared none Free. Thus the update removed much of the
departed vehicle's persistent occupied support, but did not remove it all.
For the 664 parked-car seed bins, clearing ON retained 646 occupied, declared
4 Free and left 14 Unknown; clearing OFF retained all 664 as occupied. At
frame 50, only 3 parked seed bins were Free. These are map-state seed-bin
measurements, not object IoU or independently labelled visibility truth.

Across the 13,151 cells with current-frame obstacle observations at frame 54,
56 were not Occupied and 2 were Free. This is a small nonzero contradiction
count, so the result supports bounded clearing with high parked-seed
retention, not perfect preservation. Both child processes exited; frame
point-conservation and topology checks passed for both modes. No latency
claim is made from this paired concurrent replay.

The full Release CTest gate on this exact branch passed 25/25 with the freshly
built benchmark and runtime binaries explicitly supplied to the Python test
target. The actual temporal layer still needs a desktop pixel/render proof;
code-binding inspection did not capture live GUI evidence. This experiment
therefore does not establish desktop rendering acceptance.
