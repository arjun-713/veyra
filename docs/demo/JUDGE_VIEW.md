# Judge View — live and replay foveation proof (issue #95)

One click in the Map toolbar — **Judge View** — configures the Viewer to
explain Veyra's core idea in ~20–30 seconds. It works on **live
processing frames and truthful Smooth Replay caches** alike: every claim
renders from real incoming visualization frames or real cached snapshots,
labeled accordingly. Nothing is precomputed silently, scripted, or faked.

## LIVE vs REPLAY

- **LIVE**: the current pipeline (dataset → perception → mapper). Metrics
  are current measurements.
- **REPLAY**: precomputed real Veyra snapshots from a `*.veyra-replay`
  cache, always badged `REPLAY · CACHED`. Cache measurements render only
  with a `RECORDED` label; anything the cache does not store renders
  `N/A DURING REPLAY` — stale live values are never reused. Replay FPS is
  a presentation rate, never processing throughput.

## What one click does

- Semantic display and range rings ON
- Camera, follow, point/cell visibility, and cell-boundary settings stay as selected

Exiting restores the exact prior display state. The preset never touches
mapping, perception, policy, or telemetry.

## What the judge sees

**Range bands, stated plainly — from the mapper, not the UI.** The engine
reports its active configuration per frame (`policy_descriptor`: policy
name, level ladder, distance boundaries, window and near-field radii).
The legend (`L0 · 5 cm · 0–10 m` …) and every range claim derive from
that descriptor. Frames that predate it (older caches) explain as
"Policy configuration unavailable" — bands are never assumed. The robot
moves, the policy window moves with it, and the cells stay world-aligned:
actual map cells with actual LOD values, never a screen-space gradient.

**Curated live metrics** beside the viewport: active cells, splits/s,
merges/s, policy, map-update latency, logical map memory. All measured;
anything absent renders as missing, never zero.

## Why this resolution?

Clicking a cell highlights its flat footprint in 3D and explains the
stored level from measured inputs only, with per-policy semantics:

- **Uniform5 / Uniform40**: every active region shares one level;
  distance is never mentioned. A divergent cell reports map/config
  disagreement, not a band story.
- **DistanceLOD**: range vs the descriptor's configured bands, expected
  vs actual level, honest mismatch otherwise.
- **UtilityLOD**: distance reference plus refinement direction; the
  per-cell decision (base/requested/reason flags) is not on the
  visualization wire, so refinement always carries the explicit note
  "Utility decision attribution unavailable for this frame" alongside
  the measured utility signals. UtilityLOD ships `OFF/disabled-by-default`
  (see `docs/resolution-policies.md`); no win is ever claimed.

Semantic classes render by taxonomy name (`Road · ID 9`), never a bare
ID. The selection re-resolves by world key on every new frame — updated
evidence, LOD-ownership changes, or a clear "Selected cell is no longer
active." Stale evidence never lingers during playback.

## 2.5D anatomy

The inspector's **2.5D ANATOMY** panel draws the cell's vertical profile
from the physical-layer section: ground line, obstacle block, overhead
outline, each with count/mean/min/max, plus top/bottom Z markers so the
drawing reads as measured data. Empty layers render as `Unavailable`,
never as zero-height geometry. Pooled elevation is labeled a summary,
not a surface. **Ground absent beside obstacle/overhead evidence is
"ground unobserved" — the word "occluded" is reserved for backend
visibility evidence, which frames do not carry per cell.** Unknown is
never drivable and never marked free. Progressive disclosure adds
SURFACE (slope is not stored per cell), PERCEPTION (semantic, confidence,
motion) and STATE (traversability, observations, quality; visibility
unknown) sections from real stored evidence.

A 2D grid stores occupancy in XY. A Veyra 2.5D cell stores XY plus
vertical/elevation/physical statistics — that is the whole story, visible
per click.

## Sampling honesty

The engine sends the nearest-budget cell disc around the vehicle
(spatially coherent, never random first-N); the renderer additionally
clamps to GPU capacity. The coordinate bar reports both stages —
"X cells drawn (nearest Y of Z to vehicle)" plus a viewport-clamp note —
so a large map never silently masquerades as a small one.

## Deliberately deferred (do not expand this view into them)

- **Same-frame Uniform5 vs DistanceLOD comparison.** Needs
  benchmark-generated artifacts on identical input to stay fair.
- **Temporal ghost-trail before/after.** Needs a real timestamped
  sequence with usable motion evidence; motion is never faked from
  semantic class alone.
