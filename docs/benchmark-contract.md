# Benchmark data contract

The benchmark workspace, CI summary, and exported files consume the same
schema-v2 artifact produced by `benchmarks/run_benchmark.py`. Consumers use
policy keys rather than table position because experiment runs may include
additional policies.

## Stable top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Currently `2`; strict consumers reject unknown major schemas. |
| `dataset`, `sequence`, `start`, `input_frames` | Selected source data. |
| `provenance` | Input/config digests, git and workflow identity, host facts, frame range, warmup, repetitions, execution order, and timing scopes. |
| `shared_stage_latency_ns` | Work shared before policy runs, currently perception. `null` means the stage was skipped. |
| `policies` | Requested benchmark names mapped to adapter metadata, raw repetitions, and aggregates. |
| `utility_vs_distance_detail` | Convenience comparison for the two public adaptive policies. |
| `utility_ablation` | Self-describing distance/signal/full UtilityLOD experiment. |

Every `policies.<name>` value contains `adapter`, `runs`, and `aggregate`.
`adapter.suite` distinguishes the four `public` policies from
`utility_ablation` variants. `adapter.signals` records enabled promotion
signals. A run includes the C++ schema-v2 response plus `quality` and
`detail_metric`. Aggregate latency percentiles use nanoseconds. Missing
measurements use JSON `null`; zero is a measured zero.
`aggregate.governor` totals per-frame interventions and applied merges across
repetitions and preserves the final governor status returned by the engine.

The stable public keys are `uniform5`, `uniform40`, `distance_lod`, and
`utility_lod`. The benchmark-only ablation matrix is:

1. `ablation_distance`: radial DistanceLOD control.
2. `ablation_geometry`: distance plus geometry complexity.
3. `ablation_semantics`: distance plus semantic importance and uncertainty.
4. `ablation_motion`: distance plus motion and prediction.
5. `utility_lod`: all configured utility signals, including traversability.

`utility_ablation.status` is `complete`, `partial`, or `not_run`, and
`missing_policies` makes partial execution explicit. Each member reports raw
measurements and `delta_vs_distance`. Negative RMSE is better, negative
weighted mean level means finer retained detail, and negative resource
fractions mean lower measured use. `full_vs_distance_assessment` describes
only the selected data and host. It is never a general quality claim.

The quality block evaluates point conservation, independently reconstructs
active-leaf ownership over observed 5 cm bins, checks parent/descendant
exclusivity and seam gaps/overlaps, checks split/merge sufficient-statistic
conservation, and measures elevation reconstruction against the observed fine
reference. `coverage` states what fraction of reference bins had a final active
owner. Semantic-class and non-drivable-hazard retention are measured only when
the map snapshot emits the corresponding leaf fields; otherwise the artifact
records `unavailable` with a reason. Consumers show coverage beside RMSE and
do not treat finer detail alone as quality improvement.

## CSV and compatibility

CSV contains one row per requested policy with common latency, memory,
topology, and quality columns. JSON is authoritative for per-level cells,
individual repetitions, provenance, and ablations.

The report renderer accepts earlier schema-v2 four-policy artifacts that lack
`utility_ablation`; it displays the ablation as unavailable. Baseline
regression compares only policy keys present in both artifacts, so adding an
experiment does not create a false regression. Correctness failures remain a
hard gate. Hosted-runner latency and RSS changes remain warnings because those
runners are not controlled hardware.

## Commands

Run the four public policies:

```bash
benchmarks/run_local.sh --dataset semanticposs --sequence 00
```

Run the complete UtilityLOD ablation on a generic manifest dataset:

```bash
benchmarks/run_local.sh --dataset generic --dataset-root /path/to/dataset \
  --sequence drive-01 --policies \
  ablation_distance,ablation_geometry,ablation_semantics,ablation_motion,utility_lod
```

Scheduled CI includes the complete matrix. Pull requests retain the smaller
four-policy comparison, while product CI exercises the matrix against a tiny
generic-manifest fixture through the real C++ benchmark executable.

## Measured high-resolution 3D baseline (reference leg)

`benchmarks/baseline_3d.py` is the MEASURED counterpart to the
ANALYTICAL-only `reference_baselines.uniform_5cm_3d` dense-grid estimate: a
sparse voxel-hash occupancy set at 5 cm over the same SemanticPOSS seq 00
frames 0-29 input. It reports accounted bytes, peak RSS, per-frame
voxelize+hash-insert latency, and occupied-voxel count. The binary stream
digest must start with `4cd60ac5` and the occupied count must equal
1,280,014; latency and RSS are host-load dependent and are recorded, not
gated. Raw frame-level rows persist under `elements.frames` (one row per
frame: points, new voxels, cumulative voxels, insert latency ns). Full
provenance (git commit, dataset, sequence, frames, CPU/GPU/RAM/OS, build,
config, policy) lives in `provenance`; `collect_provenance` requires no
dataset access and is covered by the metadata-completeness unit test.

Reproduce recipe (pure Python; no cmake/cargo build; dataset root may point
at any checkout holding the data):

```bash
nice -n 19 python3 benchmarks/baseline_3d.py --dataset semanticposs \
  --sequence 00 --start 0 --count 30 \
  --dataset-root /home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset \
  --output reports/closure/baseline-3d/MEASURED.json
python3 -m pytest benchmarks/test_baseline_3d.py -q
```

First-class leg integration (proposed, not yet wired): `run_benchmark.py`
gains an opt-in flag that imports `run_baseline` from `baseline_3d` and
attaches its summary under `policies.measured_3d` with
`adapter.suite = "reference"`, reusing the existing per-policy `runs` /
`aggregate` shape for the map_update-equivalent stage only. Until that hook
lands, the cross-leg comparison table (Uniform5 / Uniform40 / DistanceLOD /
UtilityLOD from the schema-v2 matrix plus measured-3D) is published in
`reports/closure/baseline-3d/RERUN-2ND-PARTY.json`, which also records the
second-party reproduction proof.
