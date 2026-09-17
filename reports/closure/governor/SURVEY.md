# Governor Survey — Slice 1 (behavior, stress evidence, utility-rerun operating point)

Worktree: `worktrees/governor`, branch `agent/governor`, base `demo-readiness` (`1ad1388`).
No code changes — survey + recipe only. No existing behavior was modified.

## 1. Where the governor lives

| Piece | File |
| --- | --- |
| Config + state machine + candidate ordering | `src/policy/policy.cpp` (`ResourceGovernor::decide`, `ResourceGovernorConfig::validate`, `load_resource_governor_config`), contract in `include/veyra/policy/policy.hpp:111-175` |
| Engine wiring (utility-only attach, ingest clamp, post-frame merge pass) | `src/runtime/engine.cpp` (`MapPolicyAdapter`: ctor `:131-136`, ingest clamp `:173-177`, `apply_governor` `:194-248`, status/reporting `:250-260`, per-frame call `:746-759`) |
| Resolution-pass safety floor + hysteresis + op cap | `src/map/resolution_pass.cpp`, constants in `include/veyra/map/resolution_pass.hpp` (`kNearFieldRadiusM = 10.0`, `kMaxOpsPerPass = 256`, `kHysteresisM = 1.0`) |
| Budgets on disk | `configs/resource_governor.yaml` (default, used by engine), `-balanced`, `-performance`, `-quality` variants |
| Tests | `tests/test_policy.cpp` (governor unit/stress), `tests/test_near_field_protection.cpp`, `tests/test_policy_adapter.cpp` |
| Invariant doc | `docs/map-correctness.md` (safety floor §5, rolling-window §6) |

Key scoping fact: the governor is attached **only to UtilityLOD**
(`engine.cpp:131-136` — `governor_` is `nullopt` for uniform5/uniform40/distance_lod).
Distance/uniform legs run ungoverned by construction, so budget changes affect
only utility legs — the rerun below is clean.

## 2. Budgets (RAM / latency / cell)

Default (`configs/resource_governor.yaml`, the config the utility closure ran under):

| Budget | Default | Balanced | Performance | Quality |
| --- | --- | --- | --- | --- |
| `max_active_cells` | 250 000 | 250 000 | 100 000 | 500 000 |
| `max_logical_bytes` | 128 MB | 128 MB | 64 MB | 256 MB |
| `max_rss_bytes` (0 = disabled) | 0 (off) | 2 GB | 1 GB | 4 GB |
| `target_frame_time_ms` | 100.0 | 100.0 | 50.0 | 100.0 |
| `near_field_radius_m` | 10.0 | 10.0 | 10.0 | 10.0 |
| `max_actions_per_frame` | 64 | 64 | 64 | 64 |
| `pressure_ratio` / `recovery_ratio` | 0.90 / 0.75 | same | same | same |
| `overload_consecutive_frames` / `recovery_consecutive_frames` | 3 / 5 | same | same | same |

Load (`policy.cpp:380-387`) is the max of four ratios, all against
**caller-supplied runtime telemetry, never static readings**:
`active_cells/max_active_cells`, `logical_bytes/max_logical_bytes`,
`frame_time_ms/target`, and (only if configured) `rss/max_rss_bytes`.
Engine telemetry note: `frame_time_ms` = parse + window-follow + update only
(`engine.cpp:746-749`, excludes snapshot/governor work), RSS read live per frame.

State machine (`policy.cpp:394-424`): `Normal` → `ApproachingBudget`
(load ≥ 0.90; splits blocked, no merge actions) → `Overloaded`
(load > 1.0 for 3 consecutive frames, or `Conserve` override; splits blocked
**plus** merge-only coarsen actions) → `Recovering` → `Normal`
(load ≤ 0.75 for 5 consecutive frames re-enables splits). `interventions`
counts transitions into limited; `actions_requested/applied` count merges.
`Disabled` override (`--governor-config` path / `set_governor_override`)
forces splits allowed and returns no actions.

What the governor does when overloaded (`policy.cpp:426-456`, `engine.cpp:229-247`):
merge-only actions, capped at 64/frame, over **complete sibling quads only**
(`count == 4`), ordered deterministically by (utility asc, range desc, level
asc, ix, iy) — i.e. **low-value far terrain degrades first, deterministically**.
Candidate utility reuses policy weights (0.20 geometry + 0.30 semantic +
0.15 motion + 0.25 traversability risk). At ingest, `allow_optional_splits=false`
clamps utility promotions back toward the distance baseline for non-safety
points (`engine.cpp:173-177`) — promotions die twice under clamp.

## 3. Protected near-field rule (three layers, all vehicle-relative)

1. **Resolution-pass floor** (`resolution_pass.cpp:62-67`, checked before the op
   cap so protection is never a casualty of a busy frame): a coarsen request
   with cell-center range < 10 m is refused (`near_field_protected++`).
2. **Governor candidate filter** (`policy.cpp:434-437`): candidates with
   `range_m <= near_field_radius_m` (10 m), `safety_critical`, or already at
   level 3 are ineligible for merge. Engine measures range conservatively as
   parent-square-to-vehicle minimum distance (`engine.cpp:211-215`), so any
   square intersecting the safety disk is protected.
3. **Ingest-clamp exemption** (`engine.cpp:173`): `drivable == 2`
   (non-drivable / safety-critical) promotions survive even under clamp.
   `semantic_class` ≠ `motion_state`; dynamics never enter the terrain path.

Hysteresis against boundary chatter: resolution-pass ±1.0 m probe
(`resolution_pass.cpp:56-60`); utility split/merge consecutive-frame + cooldown
counters; governor 3-frame overload latch / 5-frame recovery. Eviction
(rolling window) never renames in-window cells — governor merges, never evicts.

## 4. Stress evidence (this slice, named hardware where applicable)

Ran in this worktree after a clean Release configure+build:

- `ctest -R 'govern|near_field'` → `near_field_protection` PASS (hostile
  Uniform40 policy cannot coarsen the near field; protection follows the
  vehicle, `test_near_field_protection.cpp:40-98`).
- `ctest -R policy` → `policy` + `policy_adapter` PASS. The `policy` binary
  contains the smallest governor stresses, which directly prove the required
  property:
  - `governor_degrades_low_value_before_more_distant_hazards` (`test_policy.cpp:211-228`):
    under sustained overload with 1 action/frame, a near low-value cell
    (40 m, utility 0.1) is merged **before** a farther high-value cell
    (90 m, utility 0.9) — low-value-first, not far-first.
  - `resource_governor_uses_measured_pressure_and_preserves_near_field_and_hazards`
    (`:173-209`): near-field (5 m) and safety-critical (80 m, utility 0.9)
    candidates are never selected; the two far non-safety cells are.
  - `governor_waits_for_sustained_overload_and_recovers_with_hysteresis`
    (`:328-363`): pressure blocks splits without overload; RSS-over-budget
    trips overload after exactly 3 sustained frames; recovery needs load ≤ 0.75
    for 2 frames (test config); Conserve/Disabled overrides behave; reset clears.

Re-analysis of the utility-closure clamp (numbers from
`worktrees/utility-lod2/reports/closure/utility/{RESULT.md,ablation_matrix.json}`,
i5-8350U, 15.4 GB RAM):

| Ratio | Measured / budget | Verdict |
| --- | --- | --- |
| cells 247k / 250k | **0.99 > 0.90 pressure** | splits blocked from ~frame 1 |
| frame time p50 144–180 ms / 100 ms | **1.44–1.8 > 1.0 × 3 frames** | latched `Overloaded`, `allow_optional_splits=false` |
| logical 26.6 MB / 128 MB | 0.21 | not binding (5× headroom) |
| RSS 175 MB / 0 | disabled | not binding |
| 1792 coarsens/run ÷ 28 frames = **exactly 64/frame** | saturates `max_actions_per_frame` | smoking gun of saturation |

Hence all five utility legs byte-identical (sha `08145ff8`): promotions were
clamped at ingest and merged post-frame before signal differences could
materialize. Machinery sound (determinism perfect); operating point wrong.

## 5. Utility-rerun operating point (proposal for the utility agent, i5-8350U)

Goal: cell and latency ratios sit **below 0.90/1.0 with margin at the
*unclamped* working set**, so `allow_optional_splits` stays true and legs can
diverge. Unclamped size is unknown but bounded above by Uniform5 on the same
selection (631k leaves, 308 MB RSS); per-cell logical ≈ 107 B (26.6 MB/247k),
so even a Uniform5-dense map is ≈ 68 MB logical. RAM (15.4 GB) is not a constraint.

Custom governor config for the rerun (write as e.g.
`configs/resource_governor-utility-rerun.yaml`; do not overwrite the default):

```yaml
max_active_cells: 750000        # 3x default; 631k worst case -> 0.84; expected ~300k -> ~0.4
max_logical_bytes: 134217728   # unchanged: 26.6 MB measured -> 0.21; 68 MB worst case -> 0.53
near_field_radius_m: 10.0      # safety floor: NON-NEGOTIABLE, unchanged
max_actions_per_frame: 64      # unchanged; expect ~0 applied — nonzero means still clamped
max_rss_bytes: 0               # unchanged (disabled); RSS 175 MB vs 15.4 GB is not the question
target_frame_time_ms: 500.0    # above worst measured p99 (392 ms, +geometry leg); latency path
                               # becomes a regression tripwire, not a constant clamp
pressure_ratio: 0.90           # unchanged
recovery_ratio: 0.75           # unchanged
overload_consecutive_frames: 3 # unchanged
recovery_consecutive_frames: 5 # unchanged
```

Why 500 ms and not 300 ms: worst-leg p99 is 392 ms and unclamped splits add
work; 300 ms would still latch on three consecutive p99-class frames. The
ablation asks a *policy* question — hold the *latency* governor out of the way
and re-arm it (100 ms target) only for deployment tuning.

Rerun recipe (utility agent owns the matrix; ~15 min, do NOT combine selections):

1. Rerun the 9-leg matrix on the identical staged stream (digest
   `4cd60ac5a5746bbc`, `--retain-frames`, same reps/warmup) with
   `--governor-config` pointing at the rerun file above.
2. **Divergence gate before reading any delta**: the five utility-leg snapshot
   shas must NOT be byte-identical, and every utility leg must end with
   `allow_optional_splits=true`, state `normal` (approaching at most), and
   `actions_applied ≈ 0`. If any leg ends `overloaded`, the operating point is
   still invalid — raise `max_active_cells` toward 1 M and repeat; do not
   interpret deltas from a clamped run.
3. Cross-check legs (cheap, diagnostic): one `utility_lod` leg with
   `--governor-config` default file to reproduce the clamp (harness sanity),
   and one with governor `Disabled` override for pure-policy deltas.
4. Keep `tests/test_policy.cpp` green; do not touch the benchmark statistics
   framework (benchmark agent owns `sample_adequacy`).
5. Still open after this rerun (out of scope here): traversability/motion legs
   need a selection with real non-drivable terrain + timestamps (seq00
   frames 0–29 have 0 non-drivable bins, motion evidence uniformly zero).

`resource_governor-quality.yaml` (500k cells, 100 ms target) is **not**
sufficient as-is: 631k worst case exceeds the cell cap and 144–180 ms p50
exceeds the frame target — it would re-clamp via both paths.

## 6. Gaps / follow-ups

- Unclamped utility working set on seq00 is estimated (bounded by Uniform5),
  not measured — the rerun itself measures it; size the final deployment budget
  from that, on the named box, analytical vs measured reported separately.
- `frame_time_ms` telemetry excludes snapshot/governor work; a deployment
  budget should validate against end-to-end `frame_pipeline`, not just the
  governor input.
- Slice 2 (not started): eviction/window pressure behavior and RSS-cap tuning
  (`max_rss_bytes`) remain uncharacterized; default config leaves RSS unbudgeted.
