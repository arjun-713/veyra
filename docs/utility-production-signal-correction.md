# Production UtilityLOD signal correction (#57)

This changes the existing promotion-only policy, not experimental V2. The
DistanceLOD baseline, default policy, weighted sum, thresholds, depth limit,
dwell, EMA, cooldown and governor budgets are unchanged.

## Class importance

`semantic_importance = configured_priority[canonical_class] * confidence`.
All 20 canonical class priorities are listed in `configs/utility_lod.yaml`.
Unknown and unrecognized classes have zero importance. Pedestrian/rider,
vehicle and thin-obstacle priorities are high; road/parking/flat terrain are
low. These are explicit engineering priorities, not measured model quality.
Confidence remains necessary; a low-confidence person cannot qualify merely
from its class name. Non-ground observation quality was corrected separately
in this PR and is not gated by an unavailable ground-plane fit.

## Measured support

Count accepted observations per world-aligned 40cm policy region **in this
scan**, never accumulated map history. Normalize:

`expected = max(3, 16 * (10 / max(range_m, 10))^2)`

`density = min(1, observed_count / expected)`

The three quantities are config-driven. This inverse-square prior compensates
for range sparsity while retaining an evidence floor: one far return gives
1/3, failing the unchanged 0.5 density gate; two give 2/3. Sixteen returns at
10m saturate support. This is a nominal support prior, not a calibrated sensor
noise/visibility model. No raw points are added to permanent cells.

Production text and binary frame paths pre-count a bounded complete frame
before allocation. Buffering is capped at two million points, matching the
existing binary limit; metadata mismatches fail rather than allocate forever.
The temporary counter map is capped by `max_state_cells`; excess regions fail
closed with zero support. Direct streaming adapter calls without a prepared
frame use causal current-frame counts; real production paths pre-count.

## Reachable critical semantic admission

The old semantic maximum 0.30 cannot reach the 0.55 fused split threshold.
Rather than retuning those values, strong critical semantics is an independent
admission condition: configured class priority >= 0.80, semantic confidence >=
0.80, valid canonical class, positive semantic weight, AND existing
quality/density gates. Both minima are separately configurable: a vehicle with
priority 0.80 need not have impossible confidence greater than 1. It follows the
same consecutive-frame dwell, depth/change limits, cooldown and governor veto
as ordinary optional promotions. It is not a safety override. Zero semantic
weight disables this path for ablations. Admission/retention is explicitly
counted as `critical_semantic_promotion`, not falsely labelled fused-score gain.

The governor ranks using the same configured class priorities/weights instead
of reverting to confidence in every known class. Its resource algorithm and
near-field/hazard protection are unchanged.

## Evidence gate

Unit tests must prove actual person/pole/car footprints refine at the same
range as a flat road that stays coarse; sparse and low-confidence controls
must stay coarse. Real diagnostics and any quality experiment must remain
GT-policy evaluation explicitly labelled, unless real neural inference ran.
Admission requests are not fidelity or task advantage. Issue60 requires
critical-region quality/resource proof, and issue62 requires approved current
main provenance. This correction alone cannot establish either claim.
