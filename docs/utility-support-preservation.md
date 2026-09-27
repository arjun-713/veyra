# Bounded UtilityLOD split support

## Architecture review (approved separate PR)

1. **Requirement:** production UtilityLOD refinement must retain real spatial
   support, rather than empty children plus an unlocated parent prior.
2. **Existing component:** Map's split/merge seam and full-frame policy adapter.
3. **Invariants:** sketches duplicate sufficient statistics for reconstruction,
   not map ownership. On a complete split, transfer evidence exactly once.
   Incomplete history falls back to existing non-spatial priors.
4. **Memory:** no changes to Observation, CellStats or Leaf. At most 128 selected
   40 cm regions by default, each with 64 five-centimetre CellStats bins. Count
   the entire region payload and lookup index in logical/allocated map bytes.
5. **Frame allocations:** reserve the configured bound once. Frame selection is
   bounded; updates use an ordered region index, no raw-point allocations.
6. **Benchmark:** unchanged SemanticPOSS sequence 00 frame 0:10 frozen masks,
   identical enriched observation stream, four public policies. Include sketch
   state in the resource comparison and preserve negative before-cache results.
7. **Baseline:** DistanceLOD is unchanged. A useful result requires spatial
   completion and task-region quality, not merely more fine cells.
8. **Isolation:** opt-in Map API, enabled only by production UtilityLOD adapter;
   configurable zero bound disables it. No default-policy or V2 change.

## Admission and lifetime

Before fusion, rank observed regions using existing configured critical semantic
importance and confidence, with existing observation-quality/density gates.
Select up to the bound, deterministic world-ID tie breaks. Selection is not based
on benchmark annotations. A region is complete only if admitted before any
historical evidence exists there. Every subsequent accepted return in a selected
region updates its spatial bin; no coordinates/raw point history are stored.

On split, reconstruct children only when complete bins account for the parent's
entire count. Otherwise retain the parent's non-spatial prior. Cache eviction
never deletes active map evidence. Clearing or removal invalidates affected
sketches: old occupied/expired evidence must never be replayed. Late admission,
eviction/re-admission and invalidation cannot reconstruct discarded history.

The sketch preserves cell sufficient statistics, not exact surface samples or
object instances. It is not a neural, motion, hard-budget or general fidelity
claim. Its bounded memory cost is subject to the existing governor.

`detail_rehydrated_splits` counts reconstruction events. `detail_rehydrated_points`
counts evidence transferred across those events (the same return may participate
in successive nested splits), not additional or unique accepted observations.
`point_count` remains the active leaf/prior accounting total and excludes sketches.
