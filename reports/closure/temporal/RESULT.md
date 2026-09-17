# Temporal closure — KITTI-220 real-data result (draft)

Branch: `agent/temporal2` (worktree `worktrees/temporal2`).
Validator: `scripts/validate_temporal.py` (`validate_frames` API) + `TemporalTracker.active_tracks()` snapshots.
Hardware for all timings: Intel i5-8350U (x86_64), 15 GB RAM, Python 3.14.7. No CUDA.

## 1. Data provenance (verified 2026-09-17, worktree-local)

`data/raw/semantickitti/dataset/sequences/08/` (git-ignored `data/`, never committed):

- `velodyne/*.bin`: **220 files**, three contiguous blocks `000000–000099` (100),
  `000400–000459` (60), `003990–004049` (60). Sizes 1,913,488–2,022,128 B
  (mean 1,979,565.8). mtimes all 2026-09-17 15:21:19 +0530.
- `labels/`: 4071 files (full official set). `poses.txt`: 4071 lines, rigid
  (RTR−I ≤ 7.2e-07, det = 1). `times.txt`: 4071 lines, strictly increasing,
  dt median ≈ 0.104 s (~10 Hz). `calib.txt`: real KITTI `Tr`; adapter conjugates
  camera-frame poses to LiDAR (`Tr⁻¹·P·Tr`, verified line-400 match to 1e-9).
  mtimes 15:09 same day.
- Bin/label alignment: byte counts satisfy `bin_bytes/16 == label_bytes/4` on all
  sampled frames (e.g. frame 0: 123,389 pts).
- Spot sha256 (first 64 KiB): `000000:9eeae106…`, `000050:58f223dd…`,
  `000099:76a8dd3d…`, `000400:d0c042f2…`, `000430:6ee492ac…`, `000459:d075735b…`,
  `003990:c9502192…`, `004020:eae9f215…`, `004049:722326b5…`.

**Chain-of-custody flag (unresolved):** committed
`reports/closure/kitti/validation_seq08.json` records velodyne scans as
"NOT obtained (KITTI login-gated)", yet these 220 bins exist on disk (written
15:21, after labels/poses/times at 15:09). Fetcher/source and full-file checksums
against an official manifest are unknown. These results prove the *pipeline* on
real-format data; they must not be cited as official-benchmark closure evidence
until the fetch source is confirmed and `validation_seq08.json` is amended.

## 2. Label census over the 220 covered frames (no GT invented)

Raw SemanticKITTI ids (`& 0xFFFF`), mapped via `SEMANTICKITTI_LABELS`
(252→car, 253→bicyclist, 254→person, 259→other-vehicle; moving ids share the
static counterpart's class, so parked/moving contrast is representable):

| block | moving raw ids (252/253/254/…) | person (30/254) | rider (31/32/253/255) |
|---|---|---|---|
| W0 `000000–000099` | 100/100 frames (252:100, 254:100, 253:61) | present throughout | 62-frame subset starts here |
| W1 `000400–000459` | **0/60 — no moving raw ids** (static/parked contrast block) | present | absent (checked) |
| W2 `003990–004049` | 60/60 (252:60, 254:60, 253:1) | present | — |

Person coverage overall: 160/220 frames. Rider: 62/220.
Ego motion per block (dataset poses): W0 step median 0.44 m, W1 0.82 m,
W2 0.09 m (near-stationary ego). Gaps: 99→400: dt 31.25 s / 343.5 m;
459→3990: dt 366.95 s / 445.8 m (relocation — reappearance untestable here).

## 3. Adapter bug found and fixed (this session)

`datasets/semanticposs/adapter.py::_frame_index` returned the position inside
`list_frames` (available scans) and used it to index `poses.txt`/`times.txt`,
which are line-indexed by **absolute** frame number. With the full 4071-scan set
the two coincide; with our 220-scan subset, frame `000400` silently received
`times.txt[100]` (10.39 s instead of 41.54 s) and the line-100 pose — while
provenance still read `dataset/dataset/world`. The validator's fail-closed gates
did **not** catch this (timestamps still increased, poses still rigid).
Fix: numeric frame ids resolve their own metadata line (matches
`_frame_sort_key`); non-numeric ids keep refs-position behavior; out-of-range
lines fail closed downstream. Regression test:
`test_partial_checkout_resolves_absolute_pose_and_timestamp_lines`.
Verified post-fix: frames 000000/99/400/459/3990/4049 all match their absolute
`times.txt` lines, and the line-400 pose matches `Tr⁻¹·P₄₀₀·Tr` to 1e-9.

Consequences for replay indexing (refs-space, not absolute):
W0 = `start=0,count=100` → frames 000000–000099;
W1 = `start=100,count=60` → frames 000400–000459;
W2 = `start=160,count=60` → frames 003990–004049.
W0 (`validate_W0.json`, pre-fix artifact) is unaffected: refs 0–99 coincide with
absolute lines 0–99, so its metadata was already correct (ids verified contiguous
`000000–000099`, timestamps 0→10.29 s match `times.txt[0:100]`).

## 4. Validation runs (observed evidence only — no object GT)

### W0 — frames 000000–000099 (`validate_W0.json`, 100 frames)

- Provenance: every frame `pose_source=dataset`, `timestamp_source=dataset`,
  `coordinate_frame=world`; timestamps strictly increasing (span 10.29086 s).
- Motion evidence on 99/99 post-first frames; `moving` state present 99/99.
- State totals (frames 1–99): moving 81.1 %, possibly_moving 11.9 %,
  static 3.5 %, rest unknown (first frame all unknown by design).
- `max_speed_mps` median 19.19, max 19.31 m/s; 0 frames > 20 m/s.
  **Interpretation (observed, not GT):** 2.0 m / 0.104 s = 19.2 m/s — the per-frame
  max speed sits exactly at the association-gate/dt saturation limit, i.e. the
  max is dominated by nearest-centroid mismatches at the 2 m gate (and/or large
  same-class cluster centroid swings), not by verified object velocities. The
  81 % moving fraction is likewise tracker-observed output, consistent with
  large-cluster centroid jitter — it must not be read as "81 % of the scene
  moves".
- Active tracks grow 2032 → 3164 monotonically (min at first frame, max at last):
  track creation outpaces `stale_after_frames=3` expiry inside this block —
  accumulation/fragmentation is visible; no bound demonstrated at this horizon.
- Latency (i5-8350U, measured, not a claim): p50 1789 ms, p95 6399 ms,
  p99 6841 ms, mean 2527 ms, max 6948 ms — far from real-time on this hardware.

### W1 — frames 000400–000459 (`validate_W1.json`, 60 frames)

- Provenance: every frame `pose_source=dataset`, `timestamp_source=dataset`,
  `coordinate_frame=world`; timestamps strictly increasing, 41.54063 → 47.67063 s
  (absolute `times.txt` lines — confirms the §3 fix in a validator run).
- Motion evidence on 59/59 post-first frames; `moving` state present 59/59.
- State totals (frames 1–59): moving **89.7 %**, possibly_moving 5.8 %,
  static 1.2 %. **This block contains zero moving raw ids (§2)** yet reports the
  highest moving fraction of the three blocks — the strongest observed evidence
  that tracker-reported MOVING is not object motion. Pattern across blocks (W1
  fastest ego 0.82 m/step → 90 % moving; W0 0.44 m/step → 81 %; near-stationary
  W2 → 32 %) is consistent with cluster-centroid/association-gate artifacts
  scaling with ego displacement, but that mechanism is a hypothesis, not a
  measured claim.
- `max_speed_mps` median 19.18, max 19.33 m/s — again gate-saturated (2 m gate).
- Active tracks 1579 → max 2821 mid-block → 1167 at end (rise then fall, unlike
  W0's monotonic growth — scene-dependent, observed only).
- Latency: p50 4030 ms, p95 8957 ms, p99 16406 ms, mean 4429 ms, max 16858 ms.

### W2 — frames 003990–004049 (`validate_W2.json`, 60 frames)

- Provenance: all dataset/dataset/world; timestamps strictly increasing,
  414.6204 → 420.7588 s.
- Motion evidence 59/59; `moving` present 59/59.
- State totals: moving 32.2 %, **possibly_moving 60.6 %**, static 5.5 % —
  near-stationary ego (0.09 m/step) shifts mass from moving to possibly_moving.
- `max_speed_mps` median 19.11, max 19.26 m/s — gate-saturated in all blocks.
- Active tracks 1105 → 1707 (growth within block).
- Latency: p50 2163 ms, p95 4193 ms, p99 4993 ms, mean 2378 ms, max 5012 ms.

## 5. Cross-gap stale/ghost probe (`gap_99_400.json`)

One shared tracker fed 000098, 000099 → 000400, 000401, 000402 with real
poses/timestamps (dt 31.25 s, 343.5 m relocation across the gap).
`still-alive` = track ids not yet pruned (includes ghosts); `missed={k:n}` from
`active_tracks()` snapshots:

| frame | active | still-alive ids | new ids | missed histogram | persist_max |
|---|---|---|---|---|---|
| 000098 | 2192 | — (fresh tracker) | 2192 | {0:2192} | 1 |
| 000099 | 2710 | 2192 | 518 | {0:2166, 1:544} | 2 |
| 000400 | 4289 | 2710 | 1579 | {1:2166, 2:544, 0:1579} | 2 |
| 000401 | 4158 | 3745 | 413 | {2:2166, 0:1605, 1:387} | 2 |
| 000402 | 2274 | 1992 | 282 | {0:1587, 1:459, 2:228} | 3 |

- **Leave:** across the gap, all 2710 old tracks miss (missed ≥ 1) and 1579 new
  tracks spawn — zero re-association after 343 m relocation, as expected.
- **Ghost persistence:** old tracks survive with missed=1 (000400) and missed=2
  (000401), still counted in active tracks.
- **Stale cleanup:** on the third consecutive miss the 2166 ghosts expire and
  active count drops 4158 → 2274 — exactly the `stale_after_frames=3` design,
  measured on real data.
- True same-scene **reappearance** is untestable (both gaps relocate ego
  hundreds of metres). Skipped-frame dt honesty is covered at unit level
  (`test_skipped_frames_use_timestamp_delta_for_velocity`).

## 6. Targeted pytest (this session)

- `tests/test_validate_temporal.py`: 4 passed (0.68 s).
- `tests/test_temporal_tracker.py`: 25 passed, 1 skipped (POSS budget test —
  no local POSS data in this worktree; matches SURVEY).
- `tests/test_semantickitti_adapter.py`: 12 passed incl. the new regression test;
  1 pre-existing environmental failure
  (`test_real_data_smoke_…` assumes local sequence `00`; worktree holds only
  `08` — fails identically on the clean tree).

## 7. Gaps / what is still blocked

1. No object-level motion GT evaluator exists — parked-vs-moving correctness,
   person/rider persistence, and moving-vehicle precision/recall are
   unmeasurable; all motion numbers above are observed tracker output.
2. Bin chain-of-custody unresolved (see §1); remaining 3851 scans still missing.
3. Reappearance/leave cases with the *same* scene are not constructible from
   these three blocks (gaps relocate ego 343 m / 446 m).
4. Latency on the measured laptop CPU is seconds/frame; no real-time claim.
5. POSS/RELLIS temporal proof stays blocked-with-reason (no timestamps / no
   poses upstream).

## 8. Code-version caveat (added post-commit, read first on rerun)

All measurements above (W0/W1/W2/gap) ran against the TrackSnapshot-era
`TemporalTracker` (nearest-centroid association, `static ≤ 0.15 < possibly <
0.5 ≤ moving` m/s from second observation, `stale_after_frames=3`) plus the §3
adapter fix. A concurrent session developing in this shared worktree landed
`consistency-confirmed` motion states (`confirmed` flag, `consistency_cosine /
consistency_ratio`, `exclude_classes`) in `perception/temporal/tracker.py`
*after* the validation runs finished (file mtime 15:38:31 vs W2 done 15:37:37,
gap-probe import ~15:38:03). That work is included in commit `f6bb49c` by
shared-worktree timing, not by authorship, and `scripts/validate_temporal.py`
`exclude_classes` plumbing is still uncommitted. Rerunning validation on newer
code will shift state distributions (more `possibly_moving` from the third
observation on); rerun W0–W2 + gap probe after that work lands and compare
against `validate_kitti220.json`.
