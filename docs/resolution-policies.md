# Resolution policies

Veyra provides four map policies. The production desktop starts with
DistanceLOD; UtilityLOD is selectable, but its intended behavior is not
evidence that it improves map quality. Benchmark comparisons must use the same
input stream and report quality beside resource cost. See
[`benchmark-contract.md`](benchmark-contract.md).

## Policies

| Policy | Behavior | Evaluation role |
| --- | --- | --- |
| uniform5 | Represent observations at 5 cm resolution. | Fine 2.5D reference. |
| uniform40 | Represent observations at 40 cm resolution. | Coarse, low-detail reference. |
| distance_lod | Select a level by range using the configured distance boundaries. | Stable adaptive baseline and desktop default. |
| utility_lod | Start from the distance level; eligible evidence may request local promotion to finer cells. | Experimental in quality terms; no superiority claim without current-source results. |

The default distance boundaries are 10, 30, and 60 m, with a 100 m maximum
range:

| Range | Level | Resolution |
| --- | --- | --- |
| 0–10 m | L0 | 5 cm |
| 10–30 m | L1 | 10 cm |
| 30–60 m | L2 | 20 cm |
| 60–100 m | L3 | 40 cm |

The policy computes a level; the map engine owns point fusion and topology.
Grid coordinates are world-aligned. A policy decision does not itself prove
that a split improves retained map evidence.

## UtilityLOD signals and temporal state

configs/utility_lod.yaml supplies the configured class priorities, signal
weights, observation-quality and point-density gates, split/merge thresholds,
dwell, cooldown, maximum level change, promotion depth, and state limits.
The C++ loader validates the configuration in src/policy/policy.cpp.

The implementation combines geometry complexity, semantic importance,
motion, traversability risk, and quality-gated uncertainty with distance as the
baseline. Semantic class priorities are multiplied by semantic confidence;
critical semantic evidence also has configured threshold and confidence
requirements. Measured local point support is range-normalized. Missing or
low-quality evidence must not be interpreted as a reason to refine.

Utility policy state is keyed to world-aligned regions. With explicit frame
IDs, evidence is accumulated per frame before hysteresis is updated; repeated
points within one frame do not count as separate dwell frames. Split and merge
thresholds differ, and cooldown limits oscillation. Policy metadata has a
configured maximum size and TTL; it is separate from map storage and does not
retain raw observations.

These are implementation mechanisms, not proof that the resulting allocation
is task-selective. The frozen UtilityLOD benchmark and its limitations are
documented in the [frozen challenge methodology](../benchmarks/README.md#frozen-utilitylod-challenges);
benchmark results must retain their own code/data provenance.

## Resource governor

The optional governor observes active-cell count, logical map bytes, frame
time, and mapper RSS when available. Missing RSS is unavailable evidence, not
zero. Configured pressure and recovery ratios use consecutive-frame
requirements. Under sustained pressure, the governor can request merges of
eligible optional regions; safety-protected near-field and hazardous sibling
groups are protected. Requested and applied topology changes are reported
separately.

The deterministic benchmark mode withholds wall-clock frame time and RSS from
the governor; live runtime feedback remains wall-clock based. Resource profiles
are configurable starting budgets, not device-capacity guarantees. If
protected state exceeds the configured budget, preserving that state takes
precedence over claiming the budget was met.

## Quality and evidence

Uniform5 is an observed high-resolution representation reference, not surveyed
ground truth. See [`benchmark-contract.md`](benchmark-contract.md) for the
exact accuracy, completion,
Chamfer, common-support, latency, memory, and provenance definitions. Historical
artifacts remain tied to their recorded commit and must not be presented as
measurements of the current source unless the provenance matches.
