# Judge View — live foveation proof (issue #95)

One click in the Map toolbar — **Judge View** — configures the live Viewer
to explain Veyra's core idea in ~20–30 seconds. Everything renders from
real incoming visualization frames; nothing is precomputed or scripted.

## What one click does

- Map-focused view (raw points hidden so cells read clearly)
- Top-down camera + follow-robot ON
- LOD/resolution layer + cell boundaries + range rings ON

Exiting restores the exact prior display state. The preset never touches
mapping, perception, policy, or telemetry.

## What the judge sees

**Range bands, stated plainly.** The resolution legend reads
`L0 · 5 cm · 0–10 m` through `L3 · 40 cm · 60–100 m` whenever a
range-based policy (DistanceLOD/UtilityLOD) is active. The robot moves,
the policy window moves with it, and the cells stay world-aligned —
actual map cells with actual LOD values, never a screen-space gradient.

**Curated live metrics** beside the viewport: active cells, splits/s,
merges/s, policy, map-update latency, logical map memory. All measured;
anything absent renders as missing, never zero.

## Why this resolution?

Clicking a cell highlights it in 3D and explains the stored level from
measured inputs only: actual policy, robot-relative range from the live
pose, stored size/level, and stored evidence (utility, quality, geometry,
semantic, motion, drivable/ground evidence). Missing inputs produce an
explicit unavailable message.

DistanceLOD bands are half-open (`range < boundary`). Inside 10 m the
explanation notes the governor never coarsens the safety-protected
near-field. A cell finer than its band is reported as unexplained-by-this-frame
— promotion telemetry is required, never assumed. UtilityLOD ships
`OFF/disabled-by-default` (see `docs/resolution-policies.md`), so the UI
never claims a utility win; utility signals render as measured values.

## 2.5D anatomy

The inspector's **2.5D ANATOMY** panel draws the cell's vertical profile
from the physical-layer section: ground line, obstacle block, overhead
outline, each with count/mean/min/max. Empty layers render as
`Unavailable`, never as zero-height geometry. Pooled elevation is labeled
a summary, not a surface. Ground occluded by obstacle/overhead evidence
is flagged unknown — never drivable, never marked free without visibility
evidence, per `docs/map-correctness.md`.

A 2D grid stores occupancy in XY. A Veyra 2.5D cell stores XY plus
vertical/elevation/physical statistics — that is the whole story, visible
per click.

## Deliberately deferred (do not expand this view into them)

- **Same-frame Uniform5 vs DistanceLOD comparison.** Needs
  benchmark-generated artifacts on identical input to stay fair.
- **Temporal ghost-trail before/after.** Needs a real timestamped
  sequence with usable motion evidence; motion is never faked from
  semantic class alone.
