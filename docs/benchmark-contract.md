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

### Quality/resource and planner evaluation

`quality_resource.schema_version = 1` is embedded in the schema-v2 benchmark
JSON when all four public policies are requested. It is `measured` only when
all four have finite required quality/resource values and matching non-empty
native input-stream digests; otherwise it is `partial`. Its compact table
reports logical and allocated map bytes, benchmark-process peak RSS, active
cells, map-update p50/p95/p99, median C++ `frame_pipeline` runtime per frame,
throughput,
height accuracy at 5/10/20 cm, completion, symmetric Chamfer, elevation RMSE,
and available semantic/object retention. Unavailable values remain null.
`quality_resource_table.csv` has one row per policy; the standalone JSON also
contains dataset/sequence/frame selection, digest, definitions, and Pareto
frontiers. The parent benchmark JSON remains authoritative for full host,
config, build, git, and dataset provenance. It also records whether the Git
worktree was dirty and a SHA-256 of the tracked diff plus untracked source-like
files (`source_state_sha256`); generated reports are excluded from that source
fingerprint. This lets an artifact identify the exact local code state even
before it has been committed.

The reference is observed Uniform5 map support produced from the identical
selection/stream. It is **not surveyed ground truth**. `height_accuracy_10cm`
is the fraction of uniquely matched reference bins whose vertical error is at
most 0.10 m; its denominator is matched bins only. `completion_fraction` is
matched unique bins divided by all valid reference bins. `chamfer_distance_m`
is half the sum of the two directed means of unsquared 3D nearest-neighbour
distances over reconstructed matched common support. Range-binned Chamfer
rebuilds nearest-neighbour sets inside each half-open range band, preventing
cross-band matches. Range-binned accuracy/RMSE are conditional on matched bins;
completion carries missing support separately.

Nine SVGs are generated without extra plotting dependencies: three
logical-map-memory versus quality plots, three measured peak-RSS versus quality
plots, and three map-update-latency versus quality plots. The latency plot and
frontier use p95 only when every policy has at least 20 map-update samples;
otherwise they use p50. p95/p99 remain in the table with sample counts and
reliability flags. Pareto outlines use
separate two-objective frontiers; the joint frontier minimizes logical bytes,
the selected reliable map-update percentile (p95 when adequate, otherwise
p50), and Chamfer while maximizing height accuracy and completion.
No weighted aggregate score is computed. RSS includes process overhead and is
not a map-only allocation measurement.

`benchmarks.costmap_eval` is an offline/evaluation-only conversion from a
physical leaf snapshot to a bounded, world-aligned 5 cm raster; it is not part
of mapper policy or runtime. Unknown cells block by default. A deterministic
8-connected A* is run for occupancy, semantic, slope, geometry,
semantics+slope, and full-evidence ablations. Per-profile common endpoints are
selected from the largest 4-connected Uniform5 geometry-supported ground
component, not from semantic drivable labels. This allows semantic-unknown
datasets to produce geometry-only measurements; semantics-only and full
costmaps still keep unknown cells blocked and can return explicit no-path
results. Endpoint selection is evaluation support, not a drivable claim. One deterministic centered,
aspect-preserving ROI is derived from Uniform5 active bounds to fit the dense
temporary-grid cell cap, then reused unchanged by all policies, profiles, and
ablations. The exact 5 cm lattice bounds are recorded in the artifact. Each
profile reuses its selected endpoint pair across all map policies and
ablations. Wheeled-UGV and quadruped thresholds are explicitly
illustrative assumptions, not tuned or certified vehicle properties. Reported
hazard/unknown crossings compare the selected path with the corresponding
Uniform5-derived reference and are not absolute safety accuracy. Large maps
grids are bounded by the recorded ROI cell cap and searches by an expansion
cap; invalid or partial runs remain explicit in `planner_ablation.json/.csv`.
### Reconstruction quality (`quality.reconstruction`)

The standard reconstruction metrics, computed by
`benchmarks/reconstruction.py` (protocol `veyra-reconstruction-v1`) when
source frames are retained (`--retain-frames`); otherwise `unavailable`.

| Field | Meaning |
| --- | --- |
| `accuracy` | Map → reference nearest distance (`mean_m`, `median_m`, `p90_m`): is what the map claims really there? |
| `completion` | Reference → map nearest distance: is what was observed still represented? |
| `chamfer_l1_m` | Mean of accuracy and completion means. |
| `thresholds` | Precision, recall and F-score at 5, 10 and 20 cm. |
| `by_range` | The same, banded by distance from the final vehicle position (0–10, 10–30, 30–60, 60–100 m). |

The reference is the accepted world-frame input inside the final map window,
voxel-averaged at 5 cm. The reconstruction is the voxel centres each active
leaf claims at its own resolution: the ground layer at its mean height,
obstacle and overhead layers across `[min_z, max_z]`. Both sets are identical
across policies, so the comparison isolates resolution policy. Reference
points are the map's own input, not independent survey ground truth.

`benchmarks/tradeoff_plot.py` plots one point per policy with a
reconstruction metric on the y axis against measured map update p50 and
logical map bytes on the x axes:

```bash
python -m benchmarks.tradeoff_plot results/*.json --output tradeoff.svg
```

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
