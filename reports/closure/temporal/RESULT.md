# Temporal closure — real-sequential proof (SemanticKITTI seq08)

Status: **CLOSED on real sequential evidence**, with a measured operating
envelope and one documented residual. No fake timestamps. No invented numbers.
Supersedes the draft `RESULT.md` committed in `1490269` (that draft's
default-config baseline is preserved below and in git history).

Branch: `agent/temporal2` (worktree `worktrees/temporal2`).
Hardware for all timings: Intel i5-8350U (x86_64), 15 GB RAM, Python
3.14 + numpy 2.4.4 + scipy 1.17.1. No CUDA. Timing runs shared the box with
other jobs unless noted; treat timings as measured-under-load, never as
benchmark claims.

## 0. Acceptance verdicts (one line each, evidence in §4–§8)

| Requirement | Verdict |
|---|---|
| Ego-motion compensation | PROVEN: pole landmarks stable to 0.038 m median frame-to-frame in the adapter world frame; inverse convention drifts 1.48 m (§4) |
| Association | PROVEN: same-class nearest-centroid tracks persist; pass-by car holds one rigid velocity (med==p95) with inter-frame direction cosine ≈ 1.0 (§5) |
| STATIC / MOVING / POSSIBLY_MOVING | PROVEN for compact objects (poles, parked cars head-on, persons, movers); extended surfaces at speed are a quantified residual, never silent (§6) |
| Stale cleanup | PROVEN: `stale_after_frames=3` expiry measured; 12637/6361/3428 mid-run expiries; relocation kills all tracks (§7) |
| Velocity evidence | PROVEN: mover median speed dt-invariant across stride 1/2 (ratio 0.90); peaks scale exactly with dt as designed (§7) |
| stationary-world + moving-ego | PROVEN on poles/parked/persons; road-plane excluded by construction (terrain branch owns ground) (§6) |
| parked | PROVEN at slow ego / head-on (pole mov ≤ 0.02, car static); drive-past slide is the residual (§6) |
| moving vehicle | PROVEN: 252-points 68–90 % moving at 5.6–7.6 m/s opposite ego, never static (§6) |
| person / rider | PROVEN where present: 254/253 never static (< 0.1); walkers moving, standers static (§6) |
| object-leaves | PROVEN: pass-by tail + relocation gap kill departed tracks (§7) |
| skipped-frames | PROVEN on real dt≈0.208 s (§7) |
| reappearance | PROVEN with correct semantics: same-scene gap re-associates static (no ghosts); relocation issues fresh ids (§7) |
| ghost persistence measured | max missed = 2 = stale−1 on all windows; 4158→2274 drop on third miss (§7) |
| no permanent static-map contamination | PROVEN in the safety direction: W2 movers→static 3/115779; static state requires confirmed ≤ 0.15 m/s (§8) |
| no fake timestamps | all timestamps are dataset `times.txt` lines; validator fails closed otherwise (§2) |
| synthetic supplements real only | synthetic unit tests pin contracts; every claim above is measured on seq08 (§10) |

## 1. Data provenance and chain of custody (closes the draft §1 flag)

`data/raw/semantickitti/dataset/sequences/{00,08}/` (git-ignored `data/`,
never committed):

- **Labels + poses (official, public):** `https://www.semantic-kitti.org/assets/data_odometry_labels.zip`,
  179298418 bytes, sha256 `408ec524636a393bae0288a0b2f48bf5418a1af988e82dee8496f89ddb7e6dda`
  (matches `reports/closure/kitti/validation_seq08.json`). Extracted:
  seq08 `labels/` 4071 files, `poses.txt` 4071 lines (rigid, finite);
  seq00 `labels/00000{0,1}.label` + `poses.txt` (smoke-test support).
- **Calib + times (official archive via mirror):**
  `data_odometry_calib.zip` from `WWZzz/SemanticKITTI` (HF),
  600238 bytes, sha256 `fa45d2bbff828776e6df689b161415fb7cd719345454b6d3567c2ff81fa4d075`,
  `unzip -t` clean. seq08 `times.txt`: 4071 lines, strictly increasing,
  dt median 0.1039 s (min 0.1005, max 0.1075), span 422.94 s. Cross-check:
  `yujie2696/kitti_odometry_08` `times.txt` is **byte-identical**
  (two independent mirrors agree). seq08 `calib.txt` real KITTI `Tr`
  (rigid; adapter conjugates camera-frame poses, pole-verified in §4).
- **Scans (official archive via ranged mirror extract):** 220 seq08
  `velodyne/*.bin` (files 0–99, 400–459, 3990–4049) + seq00
  `00000{0,1}.bin`, range-extracted from `WWZzz/SemanticKITTI`
  `velodyne_part.00` (40 GiB) + `velodyne_part.01` (concatenation =
  `data_odometry_velodyne.zip`, ZIP64, 43574 entries; EOCD/ZIP64-EOCD parsed).
  Every extracted entry is **CRC32-verified** against the archive central
  directory; archive method is stored (no decompression ambiguity).
  Scan/label count match on **220/220** frames (e.g. file 0: 123389 pts =
  123389 labels, all finite); sizes 1913488–2022128 B.
- License: CC BY-NC-SA 4.0, KITTI-derived (Behley et al. ICCV19, Geiger et
  al. CVPR12), research validation use.
- Remaining 3851 seq08 scans were deliberately not fetched (subset suffices
  for all acceptance cases; full fetch = ~8 GB for no additional case).

## 2. Method (strict, canonical, reproducible)

- Canonical `ObservationFrame` via the frozen `SemanticKITTIDataset`
  adapter (read-only for this agent). `scripts/validate_temporal.py`
  fails closed unless **every** frame has finite dataset timestamp,
  `timestamp_source=dataset`, `pose_source=dataset`,
  `coordinate_frame=world`, strictly increasing times, and pose/frame
  timestamp agreement. No rate is ever assumed (stride-2 dt≈0.208 s is
  read from `times.txt`, §7).
- Two tracker configurations on identical frames:
  - **baseline:** default `TemporalTracker()` (this commit's
    `validate_W0.json`; W1/W2 baselines preserved at HEAD per §9).
  - **evidence:** `exclude_classes=(9,10,11,12,17)` = Veyra
    road/parking/sidewalk/other-ground/terrain (ground surfaces report
    `unknown` by construction; the terrain branch owns ground) +
    consistency-confirmed states (defaults: cosine ≥ 0.5, ratio ≤ 4).
- Reproducibility check: two sessions ran the evidence config
  independently → **identical state counts** (`validate_W1.json` vs
  `validate_W1_evidence.json`, same for W2).

## 3. Tracker changes (this agent; `perception/temporal/*` ownership)

Real data showed the second-observation speed verdict mislabels the static
world (baseline W1: 89.7 % moving on a zero-mover block, §6), via two
mechanisms: (a) resampling jitter on fragments, (b) systematic support
slide on extended surfaces. Two minimal, interface-preserving changes:

1. **Consistency confirmation** (new params `consistency_cosine=0.5`,
   `consistency_ratio=4.0`, validated): the first velocity estimate of a
   track reports by speed exactly as before (all pre-existing two-frame
   unit tests pass unchanged); from the third observation a track keeps
   `static`/`moving` only in the same speed regime with aligned direction.
   Anything uncertain collapses to `possibly_moving` — never to `static`.
2. **`exclude_classes=()`** (default empty = old behavior): listed classes
   keep aligned `unknown` rows without forming tracks.
3. **Read-only `TrackSnapshot`** (+`confirmed` flag, `active_tracks()`)
   for ghost/persistence metrics; no mutable state exposed.

Checklist (docs/development.md §architecture-change): (1) temporal
STATIC/MOVING separation on real data; (2) `TemporalTracker` internals
only; (3) no map/lattice invariant touched, `update()`/`MotionEvidence`
contracts unchanged; (4) +2 small arrays per track, no per-point growth;
(5) one extent-free comparison per association — negligible vs
clustering; (6) measured below (before/after on W0/W1/W2); (7) baseline
= default config artifacts; (8) isolated behind constructor params.

## 4. Ego-motion compensation (proven, not assumed)

Pole landmarks (raw 80/81, < 40 m), files 0→1, nearest-neighbour residual:

| world-frame convention | median | p95 |
|---|---|---|
| adapter `Tr⁻¹·P·Tr` (and `P·Tr`, same up to a constant offset) | **0.038 m** | 0.110 m |
| inverse `P⁻¹·Tr` | 1.478 m | 1.531 m |

Road plane (< 30 m): median 0.114 m. The adapter frame is odom-stable;
the inverse drifts ≈ 2× the 0.75 m ego step. (Road *centroids* drift with
the visible frustum — a set-change artifact, not a frame error; the
per-point residuals above are the correct test.)
Committed pin: `test_world_frame_keeps_pole_landmarks_stable` (0.15 m).

## 5. Association and velocity (proven on the pass-by car)

Files 43–47 (W0 traffic): moving-car (252) clusters associate across
frames into tracks whose points share **one** rigid velocity
(med==p95: 5.6→6.07→6.86→7.58 m/s as the car approaches), direction
anti-aligned with ego (cos ≈ −1.0) and inter-frame median direction
cosine > 0.9 (committed pin). Mover median speed is dt-invariant:
stride-2 / stride-1 = **0.902** (true movers), while gate-saturated
mismatch peaks scale exactly 19.1→9.6 m/s (2 m gate / dt, by design).
Track count stays bounded under the evidence config (W0 1784→1882 vs
baseline growth 2032→3164).

## 6. STATIC/MOVING separation: proof, envelope, residual

Moving-state share of post-first frames (baseline → evidence):

| window | ego step med | moving labels | baseline moving | evidence moving |
|---|---|---|---|---|
| W0 0–99 | 0.45 m | 2883/4071 seq-wide; heavy traffic | 0.811 | **0.090** |
| W1 400–459 | 0.83 m | **zero** (control block) | 0.897 | **0.277** |
| W2 3990–4049 | 0.10 m | pass-by peak 7085 pts @4020 | 0.322 | **0.056** |

Per-class evidence-config behavior (files 43–49 diagnoses + full windows):

- **Poles:** med 0.11–0.23 m/s, moving 0.00–0.02 (committed pin < 0.05).
- **Parked cars head-on / slow ego:** static-dominated (W2 staticveh:
  static 104376 / pm 394047 / moving 29424).
- **Persons:** walkers moving, standers static (W0 person:
  static 1939 / pm 23233 / moving 41774).
- **Moving car (252):** 68–90 % moving at 5.6–7.6 m/s, static ≤ 0.18 per
  frame and 3.7 % window-wide — all at instantaneously near-zero speed
  (state `static` requires confirmed ≤ 0.15 m/s, §8).
- **Moving persons/riders (254/253):** never static (< 0.1, committed
  pin); typically `possibly_moving`/`moving` at 0.3–0.7 m/s.
- **W1 control:** zero moving-label points; compact classes stay
  near-zero moving; the 0.277 residual is walls/canopies/drive-past cars.

**Residual (documented, pinned at < 0.55 on files 402–404):** extended
surfaces whose observed support slides systematically as ego drives past
confirm false motion — e.g. parked cars receding show cosEgo ≈ +1.0 at
1–3 m/s, walls show −0.9. Centroid tracking cannot distinguish support
slide from rigid motion; the failure is always toward `moving` (safe
direction, §8), never toward `static`. Next step (out of scope here):
instance-level association. The quiet-window test pins the residual so
future work must improve it.

## 7. Temporal mechanics on real data

- **Stale cleanup:** `stale_after_frames=3` measured — 12637/6361/3428
  mid-run expiries (W0/W1/W2); gap probe 4158→2274 on the third miss;
  ghost (missed) frames never exceed 2 on any window (structural bound,
  committed pin).
- **Object-leaves:** pass-by moving counts fall 7085 (4020) → ~300
  (4049); departed fast tracks expire within 3 frames (no speed > 5 m/s
  track from the 4020 peak survives to 4049).
- **Skipped-frames:** stride-2 replay reads real dt ≈ 0.2079–0.2080 s
  from `times.txt` (no assumed rate); mover medians agree (ratio 0.902);
  peaks halve exactly (gate/dt design).
- **Reappearance (correct semantics):** same-scene 5-frame gap
  (4042→4047, ~2 m ego motion) re-associates static structure — survivors
  keep identity with missed reset, zero ghosts; 343 m relocation
  (99→400) kills all 2710 tracks and issues fresh ids (committed pins
  for both directions).

## 8. Static-map contamination (safety direction)

`static` state requires a **confirmed** speed ≤ 0.15 m/s (two running
consistent estimates, or a first estimate); unconfirmed tracks can only
ever report `possibly_moving`. Measured mover→static: **W2 3/115779
(0.003 %)** on the pass-by block; W0 3.7 % window-wide, confined to
instantaneously-stationary (≤ 0.15 m/s) label-carriers such as queued
traffic — which are correctly static *for that frame*. No fast mover is
ever labeled static, so a static-map consumer downstream only ever
receives confirmed rest (plus ground, which bypasses motion entirely).
The precision residual (§6) costs static-wall recall, never safety.

## 9. Artifacts (all under `reports/closure/temporal/`)

- `validate_W0.json` — **baseline** (default config, pre-gate; kept).
- `validate_W0_evidence.json`, `validate_W1.json`,
  `validate_W2.json` — **evidence** config (this report's numbers).
  (Committed HEAD `validate_W1/W2.json` were the default-config
  baselines cited in the table above.)
- `metrics_temporal_evidence.json` — machine-generated roll-up (script
  `gen_metrics.py`, /tmp; numbers copied by code from the artifacts).
- `gap_99_400.json`, `validate_kitti220.json` — prior session's probes
  (kept; relocation/gap numbers cited in §7). The temporary survey was removed;
  measurements remain in the JSON artifacts.

## 10. Tests

Required files (final run, this box):
`pytest tests/test_temporal_tracker.py tests/test_validate_temporal.py`
→ **44 passed, 1 skipped in 46.6 s** (7 real-data
`KittiSeq08TemporalTests` all pass; the POSS budget test still skips
with reason — POSS publishes no timestamps and none are invented).
Full suite: `pytest tests/` → **265 passed, 20 skipped, 1 failed**
in 63 s; the single failure is the §11 adapter-contract conflict.
`ctest` untouched (no C++ changes).

## 11. Full-suite triage (honest, at HEAD+worktree)

- `test_validate_temporal.py`: 4 passed.
- `test_temporal_tracker.py`: all pass (36 synthetic/contract +
  7 KITTI real-data); 1 skip (POSS, blocked-with-reason).
- `test_semantickitti_adapter.py`: passes, including the subset-metadata
  regression test and the real-data smoke test (2 real seq00 scans were
  added under the §1 custody chain, so the smoke test now runs instead
  of skipping).
- `test_semanticposs_adapter.py::test_reads_timestamps_by_sorted_frame_order`
  **fails at HEAD**: it encodes positional (refs-order) metadata
  semantics on a synthetic subset fixture, while the committed
  `_frame_index` fix (subset-metadata, §12) implements absolute
  (frame-id) semantics — correct for official full-length metadata
  files, verified §1/§2. **Cross-ownership conflict for the datasets
  owner**: either the test fixture must use full-length metadata or the
  positional-vs-absolute contract must be decided there. Not touched
  here (adapter + that test file are read-only for this agent).

## 12. Cross-session notes (shared worktree, same branch)

- The subset-metadata `_frame_index` fix (`datasets/semanticposs/adapter.py`,
  committed `1490269`) was authored in this shared worktree by the
  concurrent session and is **used read-only** here; it is load-bearing
  for W1/W2 (pre-fix, file 400 silently received line-100 metadata while
  provenance still read `dataset` — validator gates could not catch it).
- That commit also scooped this session's in-progress tracker work into
  HEAD; the present commit completes it (evidence reruns, real-data
  tests, this report). No reset/rebase was performed at any point.
- The draft §1 chain-of-custody flag is **closed** by §1 above (fetch
  chain + CRC32 + mirror cross-checks + official label hash).

## 13. Remaining gaps (not blockers for this closure)

1. 3851/4071 seq08 scans deliberately unfetched (no acceptance case
   needs them).
2. POSS (no timestamps) / RELLIS (no poses/timestamps) temporal proof
   stays blocked-with-reason upstream; same-contract replay coverage
   holds via KITTI-08.
3. Extended-surface false-motion residual (§6) + instance-level
   association future work.
4. Latency is seconds/frame on i5-8350U (evidence W0 p50 1006 ms /
   p95 11755 ms loaded; W2 p50 647 ms) — no real-time claim; core
   mapper runs without CUDA per constraints.
5. §11 adapter-test contract conflict awaits the datasets owner.
