# Temporal closure — sequential-evidence survey

Branch: `agent/temporal2` (worktree `worktrees/temporal2`).
Date: 2026-09-17. Method: targeted reads + one single-file pytest; no builds.

## What the closure gate requires

Scorecard `temporal` node acceptance: **real sequential proof** of
ego-compensation, `STATIC / POSSIBLY_MOVING / MOVING`, stale cleanup,
velocity, ghost persistence, plus parked/moving vehicle, person/rider,
and leave / reappear / skip cases. Blockers on record: "no real temporal
proof", "synthetic-only insufficient". Closure policy bans
synthetic-as-real-temporal. `scripts/validate_temporal.py` is the strict
gate: it fails closed unless **every** frame has dataset timestamp
(`timestamp_source == "dataset"`), dataset pose, world coordinates, and
strictly increasing timestamps. It reports *observed* tracker states only —
there is no object-level motion ground-truth evaluator.

## What real sequences exist (verified today)

### 1. SemanticKITTI seq 08 — worktree-local, git-ignored `data/`

`worktrees/temporal2/data/raw/semantickitti/dataset/sequences/08/`:

| artifact | count | note |
|---|---|---|
| labels (`*.label`) | 4071 | full official set; matches `validation_seq08.json` (4071 label files, moving ids 252/253/254/259 seen) |
| `poses.txt` | 4071 lines | finite, rigid; median step 0.85 m per committed report |
| `times.txt` | 4071 lines | ~10.4 Hz spacing, dataset timestamps available |
| `calib.txt` | present | real KITTI `Tr`; adapter conjugates camera-frame poses to LiDAR (`convert_camera_pose_with_calibration = True`) |
| `velodyne/*.bin` | **220 only** | three blocks: `000000–000099` (100), `000400–000459` (60), `003990–004049` (60) |

- All 220 bins are scan/label byte-aligned (bin_bytes/16 == label_bytes/4; frame 0: 123389 pts) and content-plausible as real HDL-64 returns (range p50 ≈ 11.4 m, p99 ≈ 65.7 m; angles within sensor FOV).
- Sampled covered frames contain moving raw ids 252 (moving-car), 253, 254; 259 not seen in sampling.
- **Provenance flag:** committed `reports/closure/kitti/validation_seq08.json`
  says velodyne scans were "NOT obtained (KITTI login-gated)", yet 220 bins
  exist on disk (bins written 15:21 today, labels/poses/times 15:09).
  Chain-of-custody is unverified — confirm fetch source / checksums and
  amend `validation_seq08.json` before any closure claim cites these scans.

### 2. SemanticPOSS — main-repo `data/raw/semanticposs/dataset/`

Sequences `00–05`: 488 + 5×500 frames, each with `velodyne/` + `labels/` +
`poses.txt` + `calib.txt` (identity `Tr`) + `instances.txt`. **No timestamp
file exists anywhere under `data/raw/semanticposs/`** (checked all
sequences; adapter looks for `timestamps.txt` / `timestamps/<seq>.txt`).
Adapter honesty confirmed (`datasets/semanticposs/adapter.py:232-258`):
returns `(None, "absent")`, never invents time. Consequences:

- `test_original_semanticposs_frame_stays_within_temporal_update_budget`
  (`tests/test_temporal_tracker.py:320`) **skips** — it requires dataset
  timestamps and dataset pose provenance.
- `validate_frames` fails closed on POSS (no finite dataset timestamp).
- POSS can only ever supply cluster-only profiling
  (`scripts/profile_temporal.py`, explicitly not temporal validation).
  There is no honest upstream timestamp source to unblock this.

### 3. RELLIS-3D — main-repo `data/raw/rellis3d/`

5 sequences, bins + labels only (e.g. `00000`: 2842 bins). No poses,
timestamps, or calibration files found. Adapter falls back to
`identity_absent` pose → `validate_frames` fails closed. Temporal fully
blocked with reason.

## Code state surveyed

- `perception/temporal/tracker.py`: ego-compensation at observation
  boundary (world-frame input + validated SE(3) pose in contract),
  exact radius-connected clustering per class, deterministic nearest-centroid
  one-to-one association, dt-from-timestamps velocity, `static ≤ 0.15 <
  possibly < 0.5 ≤ moving` m/s, stale expiry, `unknown` until second
  observation. No synthetic timestamps anywhere on the path.
- Uncommitted work in this worktree (not mine, left untouched):
  `TrackSnapshot` + `active_tracks()` in `tracker.py` / `__init__.py` and
  `test_active_tracks_snapshot_is_deterministic_and_read_only`. This is the
  read-only metrics surface ghost-persistence / stale-decay validation needs.
- `tests/test_validate_temporal.py`: 4 passed today (single-file pytest,
  0.82 s) — validator gates behave as documented.

## Provable vs blocked

Provable now (KITTI 220 covered frames, pending provenance check):

- End-to-end `validate_frames` runs: ego-compensated association on real
  data, observed STATIC / POSSIBLY_MOVING / MOVING distributions, velocity
  magnitudes, per-frame latency (p50/p95/p99), active-track counts.
- Stale cleanup + ghost persistence via `active_tracks()` snapshots.
- Leave / reappear / skip dynamics across the real gaps 99→400 and
  459→3990 (expiry vs re-acquisition with honest dt).
- Moving-vehicle cases via raw ids 252–254; parked-vs-moving contrasts
  where static same-class instances coexist.

Blocked:

- Object-level motion correctness (e.g. "parked car stays STATIC",
  "person track persists"): no GT motion evaluator exists; validator reports
  observed evidence only. Needs instance-mined case checks, not just replay.
- Person/rider coverage inside the 220 frames is unverified (sampling only).
- Full-4071-frame closure: remaining 3851 scans still login-gated.
- SemanticPOSS temporal proof: no honest timestamp source exists upstream;
  record as blocked-with-reason, keep cluster-only profiling.
- RELLIS temporal proof: no poses upstream; record as blocked-with-reason.

## Concrete next steps

1. Verify the 220 KITTI bins (source/checksums); amend
   `validation_seq08.json` so the record matches disk.
2. Run `scripts/validate_temporal.py --dataset semantickitti` on the three
   covered blocks (`start/count`: 0/100, 400/60, 3990/60) and persist JSON to
   `reports/closure/temporal/` (records must carry checksums — `data/` is
   git-ignored and must never be committed).
3. Mine instances carrying ids 252–254 (moving) plus static counterparts for
   parked/moving, leave/reappear/skip case evidence; check person/rider
   presence in covered ranges.
4. Commit the `TrackSnapshot` + snapshot-test work; it is the surface step
   2–3 measurements depend on.
5. Decide GT motion evaluation: hand-checked instance cases vs accepting
   observed-evidence-only reports for closure.
