# Historical temporal validation — SemanticKITTI seq08

This records the `agent/temporal2` experiments and subsequent object-evaluator
addition at `demo-readiness` tip `8967fb3` (including metadata fix `aafa045`).
Earlier default-config results came from `1490269`. The source revisions,
configs and input selections below must accompany any reused numbers; these
are not current-main acceptance or real-time claims.

Host: Intel i5-8350U, 15 GB RAM, Python 3.14, NumPy 2.4.4, SciPy 1.17.1,
CPU only. Runs shared the machine with other jobs.

## Data provenance

Local, ignored data contained 220 seq08 scans: IDs 0–99, 400–459 and 3990–4049,
plus two seq00 smoke scans. Gaps are real and never interpreted as adjacent time.

| Asset | Recorded origin / verification |
| --- | --- |
| Official labels + SuMa poses | `https://www.semantic-kitti.org/assets/data_odometry_labels.zip`, 179298418 bytes, SHA-256 `408ec524636a393bae0288a0b2f48bf5418a1af988e82dee8496f89ddb7e6dda`; seq08 has 4071 labels/rigid finite pose rows. |
| Calibration + times | `data_odometry_calib.zip` via `WWZzz/SemanticKITTI` mirror, 600238 bytes, SHA-256 `fa45d2bbff828776e6df689b161415fb7cd719345454b6d3567c2ff81fa4d075`; archive test passed. |
| Time cross-check | seq08 `times.txt` byte-identical to independent `yujie2696/kitti_odometry_08` mirror; 4071 increasing rows, dt median 0.1039 s (0.1005–0.1075), span 422.94 s. |
| Velodyne | Ranged extraction of `velodyne_part.00/.01` (concatenated official ZIP64 archive, 43574 entries); all extracted entries CRC32-verified against central directory. |
| Alignment | 220/220 scan/label counts agree; frame0 has 123389 finite points/labels. Scans span 1913488–2022128 bytes. |

Dataset license: CC BY-NC-SA 4.0; cite Behley et al. ICCV19 and Geiger et al.
CVPR12. The other 3851 seq08 scans were not fetched. The
[earlier labels-only record](../kitti/RESULT.md) describes a separate stage.

## Method and configuration

Canonical `SemanticKITTIDataset` frames use real `times.txt`, rigid dataset
poses and `Tr^-1 @ pose @ Tr`; no assumed scan rate. The validator requires
finite increasing time, world coordinates, dataset pose/time provenance and
matching pose/frame timestamps. Missing metadata returns unavailable.

Two tracker configs consumed identical observations:

- Baseline: `TemporalTracker()` defaults.
- Evidence: excludes classes 9/10/11/12/17 (terrain belongs to the ground
  branch), with direction consistency cosine 0.5 and speed ratio 4.0.

From the third observation, inconsistent speed/direction collapses to
`possibly_moving`; confirmed speeds at most 0.15 m/s may be static. Track
snapshots are read-only and include confirmation/centroid state. Excluded
classes retain aligned unknown entries without forming tracks. Repeated W1/W2
evidence runs reproduced identical state counts.

## Ego compensation and motion

Pole landmarks (raw80/81, under 40 m), frames0→1: adapter world-frame residual
median/p95 0.038/0.110 m; inverse convention median 1.478 m. Road-plane median
is 0.114 m, but its centroid can slide with visible support.

Traffic frames43–47 retain one associated moving-car velocity, increasing
5.6→6.07→6.86→7.58 m/s opposite ego with inter-frame direction cosine above
0.9. Stride2/stride1 mover median speed ratio is 0.902 using measured dt
about 0.208 s; gate-limited peaks halve from 19.1 to 9.6 m/s.

| Window | Median ego step | Baseline moving share | Evidence moving share | Scene |
| --- | ---: | ---: | ---: | --- |
| W0, 0–99 | 0.45 m | 0.811 | 0.090 | Traffic; seq-wide moving labels present. |
| W1, 400–459 | 0.83 m | 0.897 | 0.277 | Zero labelled movers; false-motion control. |
| W2, 3990–4049 | 0.10 m | 0.322 | 0.056 | Pass-by peak 7085 moving points at 4020. |

Poles have median speed 0.11–0.23 m/s and moving share 0–0.02. Head-on/slow-ego
parked cars are mostly static or possibly moving; W2 counts are
104376 static / 394047 possibly-moving / 29424 moving. W0 person counts are
1939 / 23233 / 41774. Labelled moving cars are 68–90% moving in the pass-by
frames; moving person/rider static share stays below 0.1 in the tested cases.

The residual is systematic false motion on extended surfaces as their visible
support slides with ego motion. W1's 0.277 moving share is not correct dynamic
perception. Centroid association alone cannot separate that support change
from rigid motion. Quiet-window tests bound the residual, not eliminate it.

## Persistence and gaps

With `stale_after_frames=3`, missed-track age never exceeds two. Mid-run
expiries are 12637/6361/3428 for W0/W1/W2; a gap probe drops tracks from
4158 to 2274 on the third miss. Tracks at the 4020 traffic peak do not retain
departed speeds above 5 m/s to 4049. Same-scene 4042→4047 (~2 m ego travel)
reassociates surviving structure; the 343 m 99→400 relocation expires all
2710 tracks and allocates new IDs. No gap-derived timestamp was fabricated.

In W2, 3/115779 moving-labelled observations are assigned static (0.003%);
W0 has 3.7% during instantaneously near-zero label-carrier speed. These are
scoped tracker-state measurements, not proof that persistent-map ghosts are
absent; the [paired clearing experiment](../p02-pr68/RESULT.md) measures that
separate map behavior.

## Object-level motion evaluator

`perception/temporal/evaluator.py` adds `evaluate_motion`, `unknown_report`,
KITTI moving/static raw-ID sets and `MotionEvaluationError`. It evaluates
raw252–259 moving masks and raw10/30/31/32 static controls. GT objects are
`(instance_id, raw_id)` groups with at least 200 points, splitting mixed raw
classes rather than treating one instance ID as one pure object.

World-frame centroid displacement divided by dataset dt is a velocity proxy,
not annotated rigid-object velocity. Association is one-to-one to fresh
same-class `TrackSnapshot` centroids within the tracker's 2 m gate; missed
tracks cannot score. Missing predecessors or GT speeds exceeding gate/dt
(~19.2 m/s here) are excluded as unreliable; first-frame matches do not enter
velocity statistics. Small fragments remain reported and unscored. Missing
time, pose, raw labels or instance labels returns UNKNOWN with a reason.

Evidence config, frames43–47; same host, minimum object support 200:

| Scope | Metric | Recorded value |
| --- | --- | --- |
| Car objects | Association recall | 15/15; 10/15 share mixed instances. |
| Car confirmed pairs | Velocity error median/p95/max | ~0 / 0.039 / 0.054 m/s, n=8. |
| Moving car raw252 | Moving / non-static recall | 0.647 / 0.816. |
| Rider raw253 | Moving recall | 0.811, 90 points. |
| Person raw254 | Moving / non-static recall | 0.179 / 0.804, 1818 points. |
| All moving GT | Recall / non-static recall / precision | 0.632 / 0.815 / 0.587. |
| Static car raw10 | False-moving share | 0.011, 5222 points. |
| Static person raw30 | False-moving share | 0, 779 points. |
| Exclusions | Small fragments / unreliable GT | 25 / 0. |

Quiet control frames400–402 contain no labelled movers; car false-moving
share is 0.003 and moving precision 0.0. Only 8/220 frames were object-scored.
Person/rider groups lack 200-point support for object velocity and remain
point-scored only. Temporal smoothing can preserve systematic errors as well
as valid tracks; these measurements do not establish global correctness.

## Artifacts and verification scope

`validate_W0.json` preserves baseline; `validate_W0_evidence.json`,
`validate_W1.json` and `validate_W2.json` retain the committed window runs.
The repeat-run names mentioned in the original notes are not tracked. See
`metrics_temporal_evidence.json`, `gap_99_400.json` and `validate_kitti220.json`
for roll-up and gap probes. JSON source/config provenance governs interpretation.

```bash
python -m pytest tests/test_temporal_tracker.py tests/test_validate_temporal.py
python scripts/validate_temporal.py --help
```

The earlier tracker gate reported 44 passes / 1 skip in 46.6 s; the evaluator
follow-up reported 52 passes / 1 skip in 64.6 s. A historical full-suite run had
265 passes/20 skips/1 failure: an adapter test disagreed with absolute versus
subset-order metadata association. It was routed separately; this report does
not claim a current full-suite pass. CTest was not run in those tracker-only
experiments. Local timing was seconds/frame (W0 p50 1006 ms/p95 11755 ms under
load, W2 p50 647 ms), so no real-time claim follows.
