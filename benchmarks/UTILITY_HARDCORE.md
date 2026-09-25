# Frozen UtilityLOD challenge benchmark

This benchmark asks whether UtilityLOD preserves **task-relevant** evidence
better than DistanceLOD at a comparable cost. It does not retune either policy.

The committed `utility_challenge_manifest.json` was selected from raw XYZ,
dataset labels, range and available pose/time metadata before running any
policy. Its content SHA-256 is validated before each run. The fixed windows
contain ten consecutive original scan IDs; no window crosses a missing-ID gap.
Each selected scan and label file is also SHA-256 checked. The executed stream
digest covers every frame and must match across compared policies.

Run from the repository root after a Release build:

```bash
PYTHONPATH=. .venv/bin/python benchmarks/utility_hardcore_run.py \
  --repo . --repetitions 3 --matrix-repetitions 1 \
  --output-dir reports/utility-hardcore
```

The first four policies are Uniform5, Uniform40, DistanceLOD and production
UtilityLOD. A0 is DistanceLOD; A1–A4 retain the production weight magnitudes
for enabled signals but set other weights to zero; A5 is production UtilityLOD.
The safety override, quality gate, hysteresis and thresholds are **not**
changed. The +0/5/10/20/30% budget sweep copies the existing governor and
isolates its logical-byte budget by setting other limits high. It cannot
enforce an exact same-frame cap, so the report records whether each target was
actually met. Ablations and budget variants share one staged perception stream.

The challenge reference is the **observed Uniform5 map**, not surveyed ground
truth. Critical regions come from frozen GT semantic support or deterministic
height-IQR regions; labels select/evaluate scenes, while the full-policy run
explicitly uses the GroundTruth semantic provider. SemanticPOSS and RELLIS
object patches without instance IDs are not true tracked objects. RELLIS has
no trusted local pose/time metadata; multi-frame terrain quality there is an
exploratory sensor-frame result. SemanticKITTI moving raw labels select a
candidate but do not alone prove tracker motion or refinement following it.

Promotion precision here means the share of observed 5 cm bins finer in final
UtilityLOD than DistanceLOD that intersect the frozen critical region. Recall
uses critical observed bins whose DistanceLOD owner was coarser than L0.
`wasted_promotion_ratio` is the fraction of promoted observed bins **outside**
the critical region with no absolute elevation-error reduction against the
observed Uniform5 reference. These are benchmark definitions, not semantic
classifier precision/recall or proof that every outside-region promotion is
useless. Reason masks are from the triggering observation and are not exact
causal attribution across all observations in a state cell.

Map p95 with fewer than 20 measured frames is marked `tail_latency_credible:
false`. The opt-in diagnostic counters can add overhead to UtilityLOD. Repeat
the four-policy comparison without attribution to assess production timing:

```bash
PYTHONPATH=. .venv/bin/python benchmarks/utility_hardcore_run.py \
  --repo . --repetitions 3 --skip-ablations --skip-budgets \
  --disable-promotion-telemetry --output-dir reports/utility-hardcore-repeat
```

For a bounded GT-vs-real-CENet semantic-signal isolation experiment, use a
Python environment with PyTorch and run `utility_cenet_sensitivity.py` with
`--checkpoint`. Both arms intentionally disable ground, terrain and temporal;
the script rejects a silent model fallback. That result cannot stand in for
the complete GT+Patchwork++ production-path experiment.

All generated results contain run provenance, source/config digests, actual
policy settings, hardware, and sample counts. SVG plots label missing evidence
`UNAVAILABLE`; they never substitute zeros or theoretical values.
