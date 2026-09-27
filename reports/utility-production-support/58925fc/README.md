# Utility split-support acceptance run

This is a bounded, frozen SemanticPOSS sequence-00 frames 0–9 evaluation of
the bounded detail-sketch change at source commit `58925fc102aedbf5396e47e10ee58e55a68db5a7`.
It uses ground-truth semantics for policy-potential evaluation; it is not
neural-perception or application acceptance evidence. The challenge manifest
and selected regions were unchanged. Full provenance, input digests, binary
hash, configurations, and measurements are in `acceptance.json`; compact
policy and challenge tables are in the CSV files.

## Result: NO-GO for UtilityLOD benefit

Across the two repetitions (20 map-update samples per policy), DistanceLOD
used 28,280,256 logical bytes and had 33.52 ms map-update p50. UtilityLOD
with the sketch used 33,367,808 logical bytes and 92.67 ms p50. The cache-off
Utility comparison used 31,964,352 logical bytes and 90.02 ms p50.

The sketch and cache-off variants produced identical critical-region quality
for all four frozen challenges. Promotion recall was 0.30 for the pedestrian
challenge (0.00028 precision) and zero for pole and vehicle challenges. The
reported wasted-promotion ratio was about 0.498. UtilityLOD also reduced
pedestrian critical completion from 1.00 under DistanceLOD to 0.75.

The support sketch therefore did not demonstrate a task-relevant quality gain
in this selection, and its extra state is not justified by this run. This PR
preserves spatial evidence across eligible splits and accounts for its memory;
it does not close UtilityLOD issue #60 or promote UtilityLOD. Keep the policy
experimental and retain the NO-GO gate.

The 20 map-update samples support the reported p50/p95 as descriptive for this
run only; they do not establish cross-hardware performance. The benchmark
policies were run serially to avoid CPU/memory contention invalidating their
resource and latency comparison. CTest was separately run with four parallel
jobs; all 23 tests passed.
