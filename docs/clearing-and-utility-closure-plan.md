# Scoped clearing and UtilityLOD closure

1. On `fix/p02-persistent-clearing`, reproduce direct-observation self-clearing
   and raster-elevation aliasing using the production map/depth image. Preserve
   current-frame obstacle support; do not replace missing evidence with free
   space. Repeat the frozen KITTI 08 frames 43–54 ON/OFF replay, report seed
   retention separately from directly observed support, and retain old evidence.
2. Verify Release/CTest and affected Python runtime/config tests. Commit only
   temporal fixes/tests/evidence and update PR #68. Do not merge automatically.
3. On `feat/utility-signal-diagnostics`, test taxonomy-aware priorities,
   measured range-aware support, and a reachable quality-gated critical semantic
   promotion path. Preserve DistanceLOD, weights, dwell/cooldown, safety floor,
   defaults, permanent cell layout and experimental V2 isolation.
4. Repeat bounded real-data diagnostics with provenance. Test actual spatial
   refinement, sparse rejection and baseline behavior. Verify all affected gates,
   commit scoped changes, then update PR #64. Do not claim neural end-to-end or
   current-main benchmark proof from branch-local GT-policy experiments.

Excluded: UI/packaging, new datasets/models, V2, frozen challenge selection,
production-default changes, broad refactors, unrelated untracked files.
