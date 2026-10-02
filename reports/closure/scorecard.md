# Closure DAG — Veyra (orchestrator-owned)

`scorecard.json` is authoritative. This file is the human DAG view.

```text
test-gate ───────────────────────────── (no deps, START FIRST, unblocks CI signal)
datasets (SemanticPOSS/generic) ─────── (no deps, START FIRST)
rellis ──────────────────────────────── (no deps, START FIRST)
kitti ───────────────────────────────── (no deps, START FIRST)
map ─────────────────────────────────── (no deps, START FIRST, do not redesign)
control-api (owner) ─────────────────── (no deps, sole writer of control protocol)
    ├── cli ── adapts to owner
    ├── mcp ── adapts to owner
    └── tauri ── consumes owner
            ├── ui-telemetry (inventory + renderer + supervisor)
            ├── security (audit after API stable)
            └── platform x4 (ubuntu/fedora/windows/macos, native CI)
                    └── ci-release (framework early, green at end)

datasets ──→ semantic ──→ semantic-quality ──→ utility
kitti ──→ temporal ──→ utility
terrain (indep, needs datasets) ──→ semantic-quality
map ──→ utility / governor / baseline-3d ──→ benchmark ──→ docs-demo
```

**Ownership rule:** shared protocol files (`src-tauri/src/control/controller.rs`,
`src-tauri/src/control/daemon.rs`, `mcp/server.py` tool schemas,
`perception/semantic/semantic_provider.py`) have ONE owning agent.
Others adapt, never redesign.

**Worktree rule:** each agent works in `worktrees/<name>` on
`agent/<name>` branch branched from `6e3cece` (or current HEAD).
Never `git reset --hard` / `git clean -fd`. Merge via orchestrator waves.

**Evidence rule:** every agent writes `reports/closure/<id>/RESULT.md`
+ raw artifacts, returns status/root-cause/files/tests/real-data/bench/gaps/commit.
No success on compile-only.
