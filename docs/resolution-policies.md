# Resolution Policies — Veyra

Source: `AGENTS.md` §§8,15,22 and `README.md` Core Idea /
Resolution Modes / Planned Advanced Features.

## Modes

- **Uniform5** — 5 cm everywhere. High-quality 2.5D baseline.
- **Uniform40** — 40 cm everywhere. Shows aggressive-compression loss.
- **DistanceLOD** — range-only baseline (`0–10 m → 5 cm, 10–30 m →
  10 cm, 30–60 m → 20 cm, 60–100 m → 40 cm`). The basic SIH solution;
  the policy UtilityLOD must beat.
- **UtilityLOD** — distance baseline + promotion on geometry
  complexity, semantic importance, motion, traversability risk, and
  gated uncertainty. Observation quality / density must gate semantic
  uncertainty — never refine noisy distant returns just because
  uncertainty is high.

## Baselines

Always compare `Uniform5 / Uniform40 / DistanceLOD / UtilityLOD`
(+ PS-requested high-res 3D where required). The critical comparison
is **DistanceLOD vs UtilityLOD**. Do not compare only against a
strawman dense 3D map.

The benchmark runner also accepts `ablation_distance`,
`ablation_geometry`, `ablation_semantics`, `ablation_motion`, and
`ablation_traversability`.
These isolate each promotion signal with the same frame selection,
thresholds, hysteresis, and resource governor; `utility_lod` is the
full weighted policy. A detail delta proves only that promotion
occurred. Quality and resource measurements decide whether the full
policy improves the trade-off.

## Advanced (only after DistanceLOD + benchmarks work)

- **Utility-foveated LOD** — spend resolution where loss matters.
- **Predictive refinement** — refine ahead of moving important objects.
- **Resource governor** — merge low-value distant regions first;
  protect near-field / safety-critical cells.
- **Reversible detail cache** — small bounded residual in selected
  coarse cells so refinement does not restart empty. Never cache
  everywhere.

## Runtime adaptation contract

`LodPolicy::begin_frame(id)` advances a monotonic runtime frame ordinal;
reset the policy before replaying from an earlier frame. The runtime adapter
keys adaptation by the world-aligned 40 cm ancestor, so splitting an active
leaf does not erase its hysteresis. Callers that omit `begin_frame` retain
legacy one-decision-per-step behavior.

Within an explicit frame, maximum evidence is accumulated and temporal state
is recomputed from the frame-start state. Repeated points cannot consume
multiple promotion or cooldown frames. Demotion waits until the complete
frame's evidence is available; a late hazard can cancel an early low-value
observation. Gaps in observations reset consecutive-evidence counters.

All optional utility signals require configured observation quality and
point density. Safety evidence may promote without that gate. Predictive
refinement additionally requires motion probability at least 0.5 and
semantic importance or traversability risk. `max_promotion_depth` limits
refinement relative to the current radial baseline (0 disables optional
promotion), while `max_level_changes_per_decision` limits incremental
utility changes. The radial baseline is restored immediately when the
vehicle approaches; the step limit cannot delay near-field resolution.

`max_state_cells` bounds adaptation records and `state_ttl_frames` expires
unseen regions. At capacity, new regions use the radial baseline, with
safety refinement still allowed. This is bounded policy metadata, separate
from map cells; no raw observations are retained. Expiry scans the bounded
state table once per frame and must be included in runtime measurement.

## Governor controls

The governor compares active cells, logical map bytes, optional measured
mapper-process RSS, and frame time with configured budgets. Missing RSS is
unavailable evidence, not a zero measurement. `max_rss_bytes: 0` disables
that budget. A telemetry frame-time target overrides the configured target
only when positive.

Approaching the pressure ratio stops new optional utility splits. Actual
merge requests require sustained overload for
`overload_consecutive_frames`; restoration requires consecutive samples
below `recovery_ratio`. Manual `Disabled` and `Conserve` modes support
debugging. Neither mode permits a protected candidate to be merged.

Merge candidates are complete, disjoint sibling groups. Any hazardous
sibling protects the entire group, and distance is the minimum distance to
the parent square, protecting groups that intersect the 10 m safety disk.
Candidates are ranked by maximum sibling utility first, then distance,
then cell ID for deterministic ties. Near-field radius below 10 m is invalid.

Frame time and RSS are wall-clock/process measurements, so feeding them back
makes two runs of one stream produce different maps. `veyra_benchmark
--deterministic-governor` withholds both (frame time contributes no load; RSS
is unavailable), leaving the cell and logical-byte budgets in force. The
benchmark harness passes it by default and records `governor_feedback` in
provenance; `run_benchmark.py --wall-clock-governor` restores live behavior.
The live runtime keeps wall-clock feedback.

Status exposes the state, optional-split permission, overload/recovery
counts, intervention count, and requested/applied merge totals. These
counters distinguish requested work from successful topology operations;
the runtime should record their per-frame deltas in benchmark artifacts.

`resource_governor-performance.yaml`, `resource_governor-balanced.yaml`, and
`resource_governor-quality.yaml` are configurable starting budgets, not
measured capacity claims. They cover mapper resources; perception and the
desktop renderer require separate process measurements. If the protected
map alone exceeds the budget, the governor reports pressure and preserves
safety rather than promising an unattainable frame rate or memory ceiling.

## UtilityLOD verdict — REFUTED on SemanticPOSS seq00 f0–29 (2026-09-18)

Four controlled matrices on one pinned stream (digest `4cd60ac5`, 3 reps,
`--retain-frames`): default budget, 750k-cell/500 ms recipe, 750k/1200 ms,
and governor-disabled diagnostic (100M cells/1000000 ms). Evidence:
`reports/closure/utility/{RESULT,RERUN,RUN3_A,RUN3_B}.md` + matrices.

Result: full UtilityLOD is byte-identical to DistanceLOD (ΔRMSE 0.00000 m,
±0 bins, ±0 leaves, ×3 reps) with the governor provably absent — the
composition's combined gate rejects 100% of promotable evidence. The
isolated semantics signal is real (ped +1170 bins, RMSE −0.103 m) but costs
~Uniform5 resources for mixed overall quality; geometry promoted nothing
with a clean live shot. Motion/traversability/hazard legs were structurally
untestable on this selection (no timestamps, terrain unavailable, 0
non-drivable bins).

Standing: DistanceLOD remains the shipping baseline. UtilityLOD ships
OFF/disabled-by-default pending a re-gated composition proven on a
hazard/motion-bearing selection with this same committed recipe. Revival is
a new claim, not a rerun.
