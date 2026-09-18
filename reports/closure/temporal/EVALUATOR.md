# Object-motion evaluator — honest GT scoring for the temporal tracker

Status: **IMPLEMENTED + MEASURED on KITTI seq08 slices** (`perception/temporal/evaluator.py`).
Branch: `agent/temporal2` (fast-forwarded to `demo-readiness` tip `8967fb3` before
work — clean FF, no divergence, no new branch needed; includes the `_frame_index`
fix `aafa045`). Adapters, `src/map/*`, `src-tauri/*` untouched (read-only).
Hardware: Intel i5-8350U, 15 GB RAM, Python 3.14, no CUDA.

## 1. Why this exists (P0 gap it closes)

`scripts/validate_temporal.py` + `RESULT.md` prove the tracker *runs* on real
data (association persists, stale cleanup fires, ego-compensation holds poles
to 0.038 m) but every number there is *observed* evidence — correctness was
unmeasurable with no object-level motion GT. This evaluator supplies the
missing GT link where the dataset allows it, and says UNKNOWN where it does not.

## 2. Design

- **GT moving masks (KITTI):** official motion labels, raw IDs 252–259
  (moving car/bicycle/person/rider/…). Static controls: raw 10/30/31/32
  (car/person/bicyclist/motorcyclist).
- **GT objects:** `(instance_id, raw_id)` groups of moving-label points with
  ≥ `min_object_points` (200, matching the committed pins' floor). Split by
  raw id because seq08 instances are **mixed** (10/15 scored car objects share
  an instance with person/rider labels — measured, §4); the `mixed` flag
  records this. Smaller groups are reported as unscored fragments, never scored.
- **GT velocity:** world-frame centroid displacement between consecutive frames
  ÷ dataset `times.txt` delta. Ego-compensation is inherited (adapter world
  frame from official poses, pole-verified 0.038 m in `RESULT.md` §4).
- **Association:** nearest tracker `TrackSnapshot` centroid within the
  tracker's own gate (2.0 m), same mapped class, one-to-one, fresh tracks
  (`missed_frames == 0`) only — ghosts never score. Required one additive
  read-only field, `TrackSnapshot.centroid_xy` (defaulted; no behavior change,
  no existing construction touched).
- **Velocity gate honesty:** max measurable speed = gate/dt ≈ **19.2 m/s** at
  the 0.104 s KITTI rate. GT pairs faster than gate/dt, or with a missing
  predecessor, are `gt_unreliable_excluded` — fragmentation is not scored as
  motion. First-frame matches are matched but excluded from velocity stats.
- **Metrics per mapped class:** object association recall; point-level
  `moving`-recall + non-static-recall (moving|possibly_moving — slow movers are
  correctly uncertain, never static) + `moving`-precision; velocity error
  (median/p95/max/n) on confirmed pairs only.
- **UNKNOWN, never invented:** no finite dataset timestamp → UNKNOWN (POSS);
  non-world frame (no dataset pose) → UNKNOWN (RELLIS); no raw/instance labels
  → UNKNOWN. Proven against a real `SemanticPOSSDataset` fixture: timestamp
  `None`, `timestamp_source=absent` → UNKNOWN with reason (§5).

## 3. Interface (additive only)

- New: `perception/temporal/evaluator.py` (`evaluate_motion`,
  `unknown_report`, `KITTI_MOVING_RAW_IDS`,
  `KITTI_STATIC_CONTROL_RAW_IDS`, `MotionEvaluationError`).
- Extended: `TrackSnapshot.centroid_xy` (+ population in `active_tracks()`).
- Tracker behavior, `update()`/`MotionEvidence` contracts: unchanged.

## 4. Measured numbers (evidence config, `exclude=(9,10,11,12,17)`, floor 200)

Traffic window seq08 files **43–47** (pass-by car, GT speeds 5.6–7.6 m/s):

| scope | metric | measured |
|---|---|---|
| car (Veyra 1), object level | association recall | **15/15 = 1.0** (10/15 from mixed instances) |
| car, velocity error (n=8 confirmed pairs) | median / p95 / max | **~0.0 / 0.039 / 0.054 m/s** |
| raw 252, point level | moving-recall / non-static-recall | 0.647 / 0.816 |
| raw 253 (rider, 90 pts) | moving-recall | 0.811 |
| raw 254 (person, 1818 pts) | moving-recall / non-static-recall | 0.179 / **0.804** |
| all GT moving, point level | recall / non-static-recall / precision | 0.632 / 0.815 / 0.587 |
| static car-10 (5222 pts) | false-moving share | **0.011** |
| static person-30 (779 pts) | false-moving share | **0.0** |
| exclusions | fragments < 200 pts / unreliable GT | 25 / 0 |

Quiet control files **400–402**: 0 GT moving points (matches the W1 census);
car-10 false-moving 0.003. Precision there is 0.0 — every moving-state point
is false motion, i.e. the known extended-surface residual, now quantified
per-class instead of window-averaged.

Reading: the tracker holds identity on every scored mover and its velocity is
exact to cm/s on the rigid car; persons are kept out of `static` (non-static
recall 0.80) while slow speed keeps them `possibly_moving` (moving-recall
0.18) — the safe direction. Precision 0.59 carries the documented residual.

## 5. UNKNOWN demonstrations

- **POSS:** real-adapter fixture (2 car frames, poses present, no
  `timestamps.txt`) → `{"status": "UNKNOWN", reason: "frame 000000 has no
  finite dataset timestamp; deriving velocity would invent time"}`.
  POSS publishes no timestamps upstream and no local checkout exists here.
- **RELLIS:** no dataset poses/timestamps upstream (adapter yields
  `identity_absent`, points stay in LiDAR frame) and no local checkout →
  evaluator returns UNKNOWN (`not 'world'`). Covered by the lidar-frame unit
  test; no scores emitted.

## 6. Tests

`pytest tests/test_temporal_tracker.py tests/test_validate_temporal.py` →
**52 passed, 1 skipped in 64.6 s** (POSS budget test still skips
with-reason; no local POSS data). New: 6 synthetic `MotionEvaluatorTests`
(known-mover exactness, static silence, gate-saturation exclusion, UNKNOWN
paths, centroid exposure) + 2 tiny-real-slice
`KittiSeq08MotionEvaluatorTests` (traffic 43–47 pins above; quiet 400–402
control). Full suite / ctest untouched per mission bounds.

## 7. Gaps (not hidden)

1. Measured on 8/220 KITTI220 frames (two slices); full-220 evaluator rerun
   not done in this time box — slices chosen for mover presence + quiet
   control, stated as slices, never as full-sequence claims.
2. Person/rider object-level velocity unscored (their `(instance, raw)` groups
   stay < 200 pts in this window); covered at point level instead.
3. No ground-truth object velocity for occluded/fragmented instances — the
   exclusion rules (§2) are the honest boundary, not a fix.
4. `moving_state_precision` 0.59 residual = extended-surface support slide
   (`RESULT.md` §6); instance-level association remains future work.
