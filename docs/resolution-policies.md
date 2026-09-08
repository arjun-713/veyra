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

## Advanced (only after DistanceLOD + benchmarks work)

- **Utility-foveated LOD** — spend resolution where loss matters.
- **Predictive refinement** — refine ahead of moving important objects.
- **Resource governor** — merge low-value distant regions first;
  protect near-field / safety-critical cells.
- **Reversible detail cache** — small bounded residual in selected
  coarse cells so refinement does not restart empty. Never cache
  everywhere.
