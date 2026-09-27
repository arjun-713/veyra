# P0.2 UI evidence — temporal state on the production path

No isolated tracker script. Every number below comes from the normal
production path: dataset adapter → `PerceptionPipeline.from_config`
(temporal enabled) → `RuntimeSession._serialize` → `Telemetry.report`,
i.e. the exact fields the viewer and desktop app bind to.

## Production path (files)

- `perception/pipeline.py` — `PerceptionPipeline.from_config`,
  `process()` sets `motion_state` / `track_id`, `PipelineStatus.temporal`
- `viewer/runtime.py` — `RuntimeSession._serialize` emits
  `motion_state`, `track_ids`, `pipeline_status.{semantic,ground,terrain,temporal}`
- `runtime/telemetry.py` — `Telemetry.report` emits
  `perception.status.{semantic,ground,terrain,temporal}`,
  `perception.motion_point_counts`, `perception.track_counts`
  (`_track_counts`: `None` → unavailable, `-1` excluded, `{}` = zero tracks)
- `viewer/static/app.js` — `motionRead ← statuses.temporal`
  (`renderReadouts`, line ~403); motion colour mode reads
  `motion_probability` only when `pipeline_status.temporal !== "unavailable"`
  (`evidenceColor`, line ~149); per-frame `/api/frame` via `loadFrame`
- `apps/desktop/src/renderer/TelemetrySummary.svelte` — Tracks row binds
  `perception().track_counts` (`null` → "Unavailable", `{}` → "0 tracks")
  (lines 10, 33); `App.svelte` Motion layer shows STATIC/MOVING/UNKNOWN
  legend plus a fail-closed warning when the motion layer is unavailable
  (lines 101, 104); `MapCanvas.svelte` cell field 5 = motion

## Run A — real data, SemanticPOSS seq 00 frames 0–2, temporal enabled

Config: `{semantic: ground_truth, ground: on, terrain: on, temporal: on}`,
`SemanticPOSSDataset("data/raw/semanticposs/dataset")`,
`_serialize(..., budget=5000)`, then `Telemetry().report(...)`.
(SemanticKITTI is absent locally — only `data/raw/semanticposs` — so no
real-data tracked numbers exist or are claimed.)

```
frame 000000  n_points 66658  provider "Ground Truth"  temporal "unavailable"
  motion_states {"unknown": 4762}  track_ids null  track_counts null
  provenance {world, timestamp_source "absent", pose_source "dataset"}
frame 000001  n_points 66653  ... identical shape ...
frame 000002  n_points 66616  ... identical shape ...
```

(motion_state counts are over the budget-sampled subset shown in the UI.)
Read-off: with `timestamp_source: absent` (SemanticPOSS ships `poses.txt`
but no timestamps file) the pipeline fails closed — `temporal:
"unavailable"`, all `motion_state: "unknown"`, `track_ids: null`,
`track_counts: null`. The UI renders this as MOTION: UNAVAILABLE /
"no track data reported" / the App.svelte motion-layer warning —
static map evidence unaffected. `scripts/validate_temporal.py` on the same
sequence agrees, failing closed:
`temporal validation failed closed: semanticposs/00/000000 lacks a finite
dataset timestamp`. The lightweight `viewer/server.py` preview path (no
`--runtime-config`) likewise hardcodes `"temporal": "unavailable"`.

## Run B — sequential progression, temporal available, same path

Synthetic world-frame frames (`coordinate_frame: world`,
`pose_source/timestamp_source: dataset`), same `from_config` +
`_serialize` + `Telemetry.report`, frames 0 → 1 → 2:

```
frame 0  temporal "available"  motion ["unknown","unknown"]  track_ids [0,0]  track_counts {"0":2}
frame 1  temporal "available"  motion ["static","static"]    track_ids [0,0]  track_counts {"0":2}
frame 2  temporal "available"  motion ["static","static"]    track_ids [0,0]  track_counts {"0":2}
tracker live ids: [0]
```

Read-off: the tracker's own monotonic ID (`0`) persists across sequential
frames on every point (identity a UI can follow frame-to-frame);
`motion_state` goes `unknown` → `static` once two observations exist;
`track_counts {"0": 2}` is genuine per-track point counts, not a fabricated
zero. Multi-track persistence, no-ID-reuse after eviction, and the `-1`
excluded-point sentinel → `{}` (zero tracks, distinct from unavailable) are
asserted in `tests/test_track_identity.py` — **6 passed**.

## Commands run

- `python3 -m pytest tests/test_track_identity.py -q` → 6 passed
- `python3 scripts/validate_temporal.py --dataset semanticposs --root
  data/raw/semanticposs/dataset --sequence 00 --start 0 --count 3
  --output /tmp/opencode/temporal-semanticposs.json` → fail-closed
  (no dataset timestamps), exit 0
- Evidence script (uncommitted scratch): `/tmp/opencode/ui_evidence_run.py`
  (imports `SemanticPOSSDataset`, `PerceptionPipeline.from_config`,
  `RuntimeSession._serialize`, `Telemetry.report`; excerpts above)

## Externally UI-only (not runnable headless here)

Actual pixel rendering — three.js scope (`viewer/static/app.js`), the
Tauri desktop app (`apps/desktop`, Motion layer + legend + Tracks row),
and clicking through frames in a browser — require a display/browser and
were verified by code binding only (field names and gating logic quoted
above). No real-data tracked-object UI numbers are claimed anywhere:
with local data, temporal is unavailable by construction.
