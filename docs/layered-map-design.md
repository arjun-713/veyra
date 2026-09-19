# Layered 2.5D Map — Design Proposal

Status: **§ 2 (layers) is implemented and tested; §§ 3-4 are proposals.**
This answers the three open questions: what the map layers are, how
dynamic updates work, and what comparison would constitute a defensible
win.

Prior-art survey and the gaps it closed: [prior-art.md](prior-art.md).

Implemented: `include/veyra/map/height_layer.hpp`,
`include/veyra/map/occupancy.hpp`, `include/veyra/map/sensor_model.hpp`,
`include/veyra/map/terrain_query.hpp`, `src/map/terrain_query.cpp`, the
layer fields and routing in `CellStats`, and
`tests/test_layered_terrain.cpp` and
`tests/test_occupancy_uncertainty.cpp` (13 + 9 cases, all passing). The
measured memory cost is in § 2.5 and is worse than this document first
estimated.

It is an architecture change under `AGENTS.md` § Boundaries, so the
eight-question checklist is answered at the end. Nothing here should be
built before that section is agreed.

## 0. Where this lands

The repository contains two map storage paths:

| Path | Cell type | Wired into |
| --- | --- | --- |
| `veyra::map::Map` | `CellStats` (`include/veyra/map/map.hpp`) | engine, runtime, benchmarks |
| `veyra::map::TileGrid` | `Cell`, 32 B (`include/veyra/map/cell.hpp`) | unit tests only |

`src/runtime/engine.cpp:263` stores a `variant` over the four `Map`
wrappers; `TileGrid` appears in no engine translation unit. **The layer
work lands in `CellStats` and `src/map/map.cpp`.** `Cell`'s 32-byte
layout and its cache-line reasoning stay untouched, and the two paths
diverge further. That divergence is a real cost and should be an
explicit decision, not a side effect — see Q8.

## 1. The defect the layers fix

`CellStats::add` (`src/map/map.cpp:473`) keeps one Welford accumulator
over every return that falls in the cell:

```
mean_z += delta / count;   // src/map/map.cpp:529
```

Road returns at 0.0 m and a van roof at 2.4 m in the same cell produce
`mean_z ≈ 1.2 m` — a height the sensor never observed, describing a
surface that does not exist. `ground_evidence` and `drivable_evidence`
are count-weighted scalars beside that mean, so they record *how much*
of the cell looked like ground without recording *where the ground was*.
Confidence attached to a pooled mean is confidence in a fiction.

Overhead structure makes it worse in the other direction: a branch at
4 m over clear road raises `max_z` and the mean, and no field
distinguishes "obstacle standing on the road" from "road you can drive
under".

## 2. Map layers

### 2.1 One accumulator type, three instances

Introduce a single reusable accumulator and instantiate it three times
per cell rather than inventing three bespoke summaries:

```cpp
// 28 bytes. Field order mirrors Cell's reasoning: double first for
// 8-alignment, m2 stays float (no self-feedback), count is 32-bit
// because merging 64 leaves sums counts.
struct HeightLayer {
  double mean_z  = 0.0;   // 8  Welford running mean
  float  m2_z    = 0.0F;  // 4  Welford second moment
  float  min_z   = 0.0F;  // 4
  float  max_z   = 0.0F;  // 4
  uint32_t count = 0;     // 4
  uint32_t last_seen = 0; // 4  frame index of newest evidence in THIS layer
};
```

| Layer | Holds | The number that matters |
| --- | --- | --- |
| `ground` | returns perception accepted as ground | `mean_z` = surface height; `m2_z` = roughness |
| `obstacle` | non-ground returns inside the vehicle envelope | `min_z` = obstacle **base** (curb lip, step edge) |
| `overhead` | returns above the envelope | `min_z` = **clearance** |

`min_z` of the obstacle layer is the safety-critical quantity and is
exactly what a pooled mean destroys: a 12 cm curb inside a 40 cm cell
moves the pooled mean by centimetres but sets `obstacle.min_z`
unambiguously.

### 2.2 Layer assignment happens in perception, not in the map

Assigning a return to a layer needs a ground reference, and deriving the
ground reference from the cell's own ground layer is circular on the
first return. Break the loop at the source: **add
`float height_above_ground` to `Observation`**
(`include/veyra/map/observation.hpp`), populated by the Patchwork++
stage, which already fits a ground model
(`perception/ground/patchworkpp.py`). The map then makes a purely local,
loop-free decision:

```
observation.ground == 1                       -> ground
hag <  0                                      -> ground   (depression; also sets a depression flag)
0 <= hag <  clearance_envelope_m              -> obstacle
hag >= clearance_envelope_m                   -> overhead
```

`clearance_envelope_m` is a **vehicle** parameter and belongs in
`MapConfig`, not in perception. Perception supplies physics; the map
applies the platform's limits. A return whose `hag` is non-finite or
whose ground model was not available is assigned to `obstacle` — the
fail-safe direction — and counted, never silently dropped.

### 2.3 Invariant 4 is preserved, not weakened

Pooled statistics are no longer stored; they are **reconstructed** by
Chan-merging the three layers, which is the same operation `mergeCells`
already performs (`include/veyra/map/cell.hpp`). Therefore:

- `count` = sum of layer counts — exact, so point conservation is
  unchanged.
- pooled `mean_z`, `m2_z`, `min_z`, `max_z` are recoverable to the
  existing tolerances in `docs/map-correctness.md` § 4.
- `merge_children` merges **layer-wise**; invariant 4 is then checked
  per layer *and* on the reconstruction, which is strictly stronger than
  today's test.

This is why all three layers are full Welford accumulators rather than
the cheaper `(count, min_z)` that the overhead layer would otherwise
need. The cheaper form breaks pooled reconstruction and would force
invariant 4 to be restated. Compressing the overhead layer is a
legitimate follow-up, but only after measurement, and it costs an
invariant.

### 2.4 Observability — `unknown` is a first-class state

Derived per cell, not stored:

| State | Condition | Meaning |
| --- | --- | --- |
| `GROUND_OBSERVED` | `ground.count >= min_ground_returns` | ground height is measured |
| `GROUND_OCCLUDED` | `ground.count == 0` and (`obstacle.count > 0` or `overhead.count > 0`) | something was seen here, the floor was not |
| `UNOBSERVED` | cell does not exist | never seen |

`GROUND_OCCLUDED` must never be reported drivable. This is the rule the
dossier's pages 4 and 12 are really asking for, and it is the one a
pooled map cannot express at all: today a cell containing only van-roof
returns reports a confident `mean_z` of 2.4 m and no indication that the
road underneath was never observed.

Traversability then becomes a function of the layers against the
platform, rather than a stored scalar:

```
drivable      <- GROUND_OBSERVED
               & ground roughness (sqrt(m2/count)) <= roughness_limit
               & step vs. neighbours <= step_limit           (uses ground.mean_z, not pooled)
               & obstacle layer absent or obstacle.min_z - ground.mean_z >= 0 is refuted
               & overhead.min_z - ground.mean_z >= vehicle_height_m
unknown       <- GROUND_OCCLUDED or stale (see §3)
non-drivable  <- otherwise
```

### 2.5 Memory: the honest number

`HeightLayer` is 32 B (the double forces 8-byte alignment, so the five
narrower fields round up either way — the wider `uint64_t last_seen` that
matches `CellStats::last_seen` is therefore free).

The +60 B figure in the first draft of this document was a hand count and
it was wrong. **Measured, on the implemented code:**

| Struct | Before | After | Delta |
| --- | --- | --- | --- |
| `HeightLayer` | — | 32 B | new |
| `CellStats` | 88 B | 192 B | **+104 B** |
| `Leaf` | 104 B | 208 B | **+104 B** |
| `Observation` | 80 B | 80 B | 0 — `height_above_ground` fit in tail padding |

`sizeof(Leaf)` is what `MapMemoryAccounting::logical_payload_bytes`
multiplies by (`src/map/map.cpp:687`), so **the map's logical payload
exactly doubles.** `tests/test_layered_terrain.cpp` pins these numbers so
they cannot drift silently.

The pooled accumulator is retained rather than deleted, which is where
40 B of that goes. Deleting it is the obvious reduction — the layers
reconstruct it — but it would move invariant 4's exact-equality rule for
`min_z` / `max_z` onto float layer fields and would touch every consumer
of `CellStats`. That is a deliberate follow-up with a stated cost, not a
cleanup to slip in.

Three consequences that must be stated plainly and not buried:

1. This change makes the map **twice as big**, not smaller. The adaptive
   resolution controller is what earns it back, by coarsening flat
   regions that now provably have nothing to lose. The layers are what
   make that provable — which is the argument for the implementation
   order in § 5. At a doubling rather than a 60 % increase, that
   repayment is no longer comfortable: the controller must now free more
   than half the cells at equal quality to break even, and until it is
   measured doing so, **this change is a net memory regression.** It
   should not be presented otherwise.
2. The dossier's **94.3 % reduction is an analytical example** assuming
   full coverage and a uniform 32-byte payload. It was never a Veyra
   measurement and it is now definitively not one, since our payload is
   no longer 32 bytes. Per `AGENTS.md`, report measured RSS on named
   hardware and cite the analytical figure only as the source's
   illustration.

### 2.6 Integration: closed, via protocol V3

The gap this section previously described — layers fully functional
in-process and completely dormant on the live path, because the 19-field
V2 stream had nowhere to carry `height_above_ground` — **is closed.**

- `PROTOCOL_VERSION = 3`; the record gains one trailing field. V2 streams
  are still accepted and their points are counted as unmodelled rather
  than assumed to be at ground level.
- `perception.ground.height_above_ground` computes the value from the
  Patchwork++ ground mask: a coarse XY lattice, the **median** elevation
  of ground returns per cell, one-ring fallback, NaN where there is no
  nearby ground evidence. Median rather than mean because returns leaking
  through the ground segmentation from a kerb would drag a mean upward
  and make real obstacles look shorter — an error in the unsafe
  direction.
- `MapSnapshot::layers` exposes the totals, so the representation is
  observable from outside the process. `unmodelled_returns` is the field
  that makes a degraded producer loud.
- `tests/test_layered_end_to_end.py` drives real frames through the real
  protocol into the real engine binary, on both the batch and persistent
  paths.

One caution learned in the process: bumping the version while the
persistent engine's `VEYRA_ENGINE` handshake still announced V2 caused
20-field records to be parsed against a 19-field layout, surfacing as
`nonfinite required point value` — an error several fields from the real
fault. Both the stream header and the handshake now derive from
`PROTOCOL_VERSION`, and a test asserts it.

## 3. Dynamic updates

### 3.1 Persistence is per layer, not per cell

- **Ground is persistent.** It is never decayed by absence. It changes
  only on *contradiction*: new ground returns at a different height.
  Terrain does not expire because the vehicle looked away.
- **Obstacle is transient.** It decays on evidence of absence.
- **Overhead is persistent** for the same reason as ground — a bridge
  does not leave.

This separation is the mechanism that makes "a person's old positions
clear without erasing the curb behind them" true by construction rather
than by tuning.

### 3.2 Evidence of absence, in 2.5D

> **Superseded — see [prior-art.md § 4](prior-art.md).** The per-point ray
> traversal specified below is the wrong shape of solution. HKU MaRS's
> D-Map determines occupancy by rasterising the scan into a depth image
> at the sensor pose and projecting cells into it, which is O(1) per cell
> instead of O(cells along ray) per point, and needs none of the
> decimation or work-capping in § 3.5. The occupancy primitives
> (`observe_free` / `observe_occupied`) are implemented and are the
> interface such a pass would drive. Rewrite this section around the
> depth-image approach before implementing the traversal.
>
> The elevation reasoning below still holds and carries over unchanged:
> a beam only contradicts a cell if it passed *through* the claimed
> vertical extent.


A return at range `R` along bearing `θ` proves the beam traversed empty
space from the sensor to `R`. Projecting that to 2D and clearing every
cell along the bearing is the bug named on page 12: a beam that passed
*over* a curb to hit a wall behind it clears the curb.

Carry the beam's elevation through the traversal. For each cell the beam
crosses, compute the beam's `z` where it crosses:

```
clear the obstacle layer  iff  obstacle.min_z <= beam_z <= obstacle.max_z
```

- Beam above `obstacle.max_z` — it flew over. Says nothing. Do not clear.
- Beam below `obstacle.min_z` — passed underneath. Says nothing.
- Beam inside the claimed vertical extent — a genuine contradiction.

The same traversal never touches the ground or overhead layers.

### 3.3 Decrement, never delete; stale, never free

> **Implemented, and the tuned constant is gone.** `K` no longer needs
> choosing: log-odds clamping
> ([occupancy.hpp](../include/veyra/map/occupancy.hpp)) bounds the
> evidence in both directions, so the observations needed to flip a cell
> fall out of the arithmetic — measured at 10 from full saturation. See
> [prior-art.md § 1](prior-art.md).


Contradiction decrements an evidence counter; it does not erase. An
obstacle is released only after `K` contradicting traversals, so one
spurious ray cannot delete a wall.

Absence of *any* evidence is handled separately and is the point the
dossier is most insistent about:

| Situation | Transition | Reported as |
| --- | --- | --- |
| obstacle contradicted `K` times | obstacle layer released | **free** |
| obstacle not re-confirmed for `T` frames, no contradiction | `STALE` | **unknown** |
| cell occluded (no returns, no traversals) | ages to `STALE` | **unknown** |

A timeout returns a cell toward **unknown**, never toward free. Occlusion
and absence are indistinguishable from the sensor's point of view, so
they must produce the same conservative answer.

`motion_state` from `perception/temporal/tracker.py` modulates `K`
only — `MOVING` evidence lowers the contradictions needed, `STATIC`
raises it. It never clears a cell on its own: dynamics tune the rate,
they do not contaminate terrain (`AGENTS.md` § Perception).

### 3.4 The walk–stop–walk case, traced

1. Person walks into view: obstacle layer populated, `MOVING`.
2. Person stops: no contradicting rays yet (they occlude their own
   cells), evidence holds. Curb behind them is occluded → `STALE` →
   **unknown**. Correctly not cleared, correctly not asserted drivable.
3. Person walks on: beams now reach the curb at curb elevation.
   - Their old cells receive beams at torso height inside the recorded
     `[min_z, max_z]` → contradicted → released to **free**.
   - The curb receives returns → ground and obstacle layers re-confirmed
     → back to **observed**. It was never cleared, because no beam ever
     passed through its 12 cm vertical extent.

### 3.5 The cost, stated up front

Ray traversal is the single largest latency risk in this proposal —
~120 k points per frame, each walking several cells. It is not free and
should not be presented as though it were. Controls:

- traverse a decimated subset (one beam per bearing bucket per frame);
- traverse only within the range where obstacle clearing matters
  (~30 m), not to `max_range_m`;
- a hard per-frame work cap in the style of `kMaxOpsPerPass`
  (`include/veyra/map/resolution_pass.hpp`), with deferred work
  **counted**, as `PolicyStats::deferred` already does.

If p95 latency regresses past the frame budget, the feature is wrong as
specified and the decimation rate becomes the primary tuning knob. That
must be measured before the feature is claimed, not after.

## 4. The comparison that would constitute a win

### 4.1 Comparison targets

The dossier gives research directions but **no evidence that the named
competing teams have evaluated implementations**, so no claim of
superiority over them is supportable. Superiority is established against
controlled internal baselines, all driven through the existing schema-v2
harness (`docs/benchmark-contract.md`) on identical frames, order, host,
warmup and repetitions.

| Key | What it is | Why it is there |
| --- | --- | --- |
| `uniform5`, `uniform40` | existing | resolution floor and ceiling |
| `distance_lod` | existing | the honest strong baseline |
| `pooled_mean` | today's Veyra | isolates the layer change |
| `timeout_clear` | 2D projected-ray clearing + timeout-to-free | the literature-standard dynamic handling; beating it is the actual result |

`timeout_clear` must be implemented properly, not as a strawman. If it
does not lose on static erosion, our premise is wrong and we need to
know that before a demo, not during one.

### 4.2 Metrics, one family per feature

**A — terrain correctness (layers).** Reference: held-out ground returns
plus SemanticKITTI road/sidewalk labels.

- ground-height RMSE, scored **only over `GROUND_OBSERVED` cells** — a
  map that guesses at occluded ground must not be rewarded for guessing
  close;
- clearance error on cells with overhead structure;
- **false-drivable rate** — fraction of cells reported drivable that
  contain a reference obstacle. This is the safety number and the
  headline;
- **unknown honesty** — fraction of occluded reference cells reported
  `unknown` rather than drivable.

**B — dynamic correctness.**

- clearing delay after departure, median and p95;
- **static erosion** — persistent structure cells wrongly cleared per
  100 frames;
- ghost persistence — cells still occupied `N` frames after departure.

**C — resolution controller.**

- **iso-memory hazard recall** — fix the memory budget, measure the
  fraction of reference hazards (curbs, steps, thin poles) retained at a
  resolution able to represent them. Fixing the budget is what makes
  this ungameable: finer detail is not a quality improvement if it costs
  more, and `docs/benchmark-contract.md` already refuses that
  conflation;
- height error at retained detail, p95 latency, RSS.

### 4.3 Discipline

- **Pre-register thresholds.** Write down what counts as a win before
  running, so no metric is selected after seeing results.
- Extend the existing ablation matrix, which is already the right shape:
  add `ablation_layers` and `ablation_visibility` alongside the current
  `ablation_geometry` / `_semantics` / `_motion`.
- Report analytical and measured separately, on named hardware
  (`AGENTS.md`). Retire 94.3 % as a Veyra claim.
- Coverage beside every RMSE, as the contract already requires.

### 4.4 Three demonstrations

1. **Road beneath a branch.** Pooled map renders a phantom ramp; layered
   map renders flat road plus a clearance figure.
2. **Walk–stop–walk.** `timeout_clear` erases the wall; visibility-aware
   map keeps it and still clears the person.
3. **Iso-memory curb.** At equal bytes, `distance_lod` has coarsened the
   curb at 35 m out of existence; hazard-preserving LOD still resolves
   it.

Each is one sequence, two maps, side by side, with the metric on screen.

## 5. Order, and why

1. **Ground / obstacle / overhead layers.**
2. **Visibility-aware dynamic updates.**
3. **Hazard-preserving resolution controller.**

The controller's central question — *what would this merge lose?* — is
unanswerable today, because merge loss would be measured against a
pooled mean that is already wrong. Layers first give the controller
truthful evidence about what deserves detail. Dynamic updates second,
because a controller that preserves detail around phantom obstacles
spends its budget on ghosts.

## 6. Architecture-change checklist (`docs/development.md` § 47)

1. **Which requirement?** Ground/obstacle/clearance separation with
   calibrated uncertainty; correct dynamic-object handling. Both follow
   from the pooled-mean defect in § 1.
2. **Existing component?** No. `ground_evidence` records how much of a
   cell was ground, never its height. No component represents overhead
   clearance or distinguishes occluded from free.
3. **Invariant impact?** Invariants 1, 2, 3, 5, 6 unaffected. Invariant 4
   is preserved via layer-wise merge plus pooled reconstruction, and its
   test becomes stronger. `docs/map-correctness.md` needs the layer-wise
   restatement.
4. **Memory/cell delta?** **+104 B per active cell, measured** — `Leaf`
   104 B → 208 B, an exact doubling of logical payload. The +60 B in the
   first draft was a hand count and was wrong; § 2.5 carries the measured
   table and a test pins it. Must be earned back by step 3, and that
   repayment is a measurement, not an assumption. This is the answer most
   likely to sink the proposal, and it should be argued on the measured
   number.
5. **Frame-time allocs?** Layers: none — fixed-size fields in an existing
   cell. Ray traversal: none if the traversal buffer is preallocated and
   capped; this is a hard requirement, not an aspiration.
6. **Benchmark?** Yes — § 4, through the existing schema-v2 harness, with
   `pooled_mean` and `timeout_clear` added as baselines.
7. **Which baseline shows gain?** `pooled_mean` for ground-height RMSE
   and false-drivable rate; `timeout_clear` for static erosion;
   `distance_lod` at iso-memory for hazard recall.
8. **Isolatable behind interface?** Partly, and this is the weakest
   answer. `CellStats` is a public struct in `include/veyra/map/map.hpp`
   and its layout is visible to the engine, the snapshot path and the
   benchmark quality checks. The change is additive at the API level
   (pooled values remain queryable as derived accessors), but it is not
   hidden. **Open decision: whether `TileGrid`/`Cell` mirrors the layers
   or is retired.** Carrying two divergent cell layouts indefinitely is
   a cost we should choose deliberately rather than inherit.

Q8 and Q4 are the two answers worth arguing about before any code is
written.
