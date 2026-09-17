# Temporal validation evidence and checkpoint

Real sequential proof now exists on SemanticKITTI sequence 08
(4071-scan val sequence; 220 scans + full labels/poses/times/calib
assembled under git-ignored `data/raw/semantickitti/dataset`). This note
records the evidence layout and the commands that reproduce it. It does not
turn frame IDs, file order, or filesystem metadata into timestamps.

## Provenance (verified 2026-09-17, chain of custody in `reports/closure/temporal/RESULT.md`)

- Labels + poses: official `data_odometry_labels.zip` (179298418 B,
  sha256 `408ec524…7e6dda`).
- Calib + `times.txt`: official `data_odometry_calib.zip` via mirror
  (600238 B, sha256 `fa45d2bb…075`); seq08 `times.txt` byte-identical
  across two independent mirrors; 4071 lines, strictly increasing,
  dt ≈ 0.104 s.
- Scans: 220 seq08 bins (files 0–99, 400–459, 3990–4049) + 2 seq00 bins,
  range-extracted from a mirrored `data_odometry_velodyne.zip` with
  per-entry CRC32 verification and 220/220 scan/label count match.

## Local evidence audit (other roots)

- `data/raw/semanticposs/dataset`: 2,988 `.bin` scans and 2,988 labels
  across sequences `00`–`05`; per-sequence `poses.txt` + `calib.txt`;
  no timestamp files. Replay has dataset pose/world coordinates but
  absent timestamp provenance, so `validate_temporal.py` fails closed
  there by design (no timestamps are generated).
- `data/raw/rellis3d/Rellis-3D`: scans + labels only; no pose, timestamp,
  or calibration metadata. Replay stays in the LiDAR frame.

## Reproduction commands (evidence config)

Ground-surface classes (Veyra road/parking/sidewalk/other-ground/terrain
= 9,10,11,12,17) report `unknown` motion by construction; motion states
are consistency-confirmed from the third observation on. Ordinal `start`
indexes the scans present on disk (W0 = 0/100 → files 0–99;
W1 = 100/60 → files 400–459; W2 = 160/60 → files 3990–4049):

```bash
python3 scripts/validate_temporal.py \
  --dataset semantickitti \
  --root data/raw/semantickitti/dataset \
  --sequence 08 \
  --start 0 --count 100 --stride 1 --max-range-m 100 \
  --exclude-classes "9,10,11,12,17" \
  --output reports/closure/temporal/validate_W0_evidence.json
```

The checkpoint passes only if all adapter frames have finite, strictly
increasing dataset timestamps, dataset pose provenance, world
coordinates, and pose/frame timestamp agreement. Missing or untrusted
metadata exits nonzero and writes no success report. The report's motion
section is observed tracker evidence, not object-level ground truth.

## What the evidence shows (detail: `reports/closure/temporal/RESULT.md`)

- World frame odom-stable (pole NN residual 0.038 m vs 1.478 m inverse).
- Moving-state share, baseline → evidence: W0 0.811 → 0.090,
  W1 0.897 → 0.277, W2 0.322 → 0.056.
- Compact objects separate cleanly (poles, parked cars head-on,
  persons, pass-by car at 5.6–7.6 m/s, dt-invariant across strides).
- Known residual: extended surfaces during fast ego motion confirm
  false motion via systematic support slide (W1 control block);
  always toward `moving`, never toward `static`.
- Safety direction: pass-by movers→static 3/115779; ghosts ≤ 2 frames;
  stale-3 expiry measured; relocation kills all tracks.

## KITTI220 real-sequential evidence (integrated, `agent/temporal2`)

220 seq08 scans (files 0–99 / 400–459 / 3990–4049; windows W0/W1/W2) under
the evidence config (`--exclude-classes 9,10,11,12,17`,
consistency-confirmed states): pole landmarks stable to 0.038 m median,
pass-by car 68–90% moving at 5.6–7.6 m/s with dt-invariant medians
(stride-2/stride-1 0.902), mover→static 3/115779 on the pass-by block,
ghosts ≤ 2 frames, stale-3 expiry measured, relocation kills all tracks.
Detail: `reports/closure/temporal/RESULT.md` (+
`validate_W0_evidence.json`, `validate_W1.json`, `validate_W2.json`,
`metrics_temporal_evidence.json`).

Honest limits: velocity peaks saturate at the 2 m association gate over dt
(19.1→9.6 m/s across strides, by design — not a speed measurement); there
is no object-level ground truth (the motion section is observed tracker
evidence against semantic/moving labels, not tracked boxes); the W1
zero-mover control keeps a 0.277 moving residual from extended-surface
support slide (always toward `moving`, never `static`); POSS/RELLIS
temporal proof stays blocked-with-reason (no timestamps). Chain of
custody: raw data lives only under git-ignored `data/` (official label zip
sha256-verified, calib cross-checked byte-identical across two mirrors,
scans CRC32-verified, 220/220 count match) — only derived JSON reports are
committed.
