"""Divergence gate + per-leg summary for the UtilityLOD rerun matrix.

Usage: python3 reports/closure/utility/check_divergence.py <benchmark.json>

Gate (governor SURVEY.md recipe, section 5):
  1. The five utility-leg canonical snapshot SHAs must NOT be byte-identical.
  2. Every utility leg must end with allow_optional_splits=true, state
     normal (approaching at most), and actions_applied ~= 0.
If any leg ends overloaded, the operating point is still invalid: raise
max_active_cells and repeat; do not interpret deltas from a clamped run.

Snapshot leaves are compacted out of the report before quality is attached,
so the SHA covers the canonical compact snapshot + detail metric + final
quality (elevation RMSE/coverage, retention bins). Any policy-level map
difference that moves leaves, RMSE, or retention changes the SHA.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

UTILITY_LEGS = [
    "ablation_geometry",
    "ablation_semantics",
    "ablation_motion",
    "ablation_traversability",
    "utility_lod",
]


def canonical_sha(run: dict) -> str:
    payload = {
        "snapshot": run["snapshot"],
        "detail_metric": run["detail_metric"],
        "elevation": run["quality"]["elevation_vs_fine_reference"],
        "retention": {
            "semantic": run["quality"]["field_retention"]["semantic"],
            "terrain_hazard": run["quality"]["field_retention"]["terrain_hazard"],
            "task_classes": run["quality"]["field_retention"].get("task_classes"),
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def ms(ns) -> float:
    return float(ns) / 1_000_000.0


def main() -> int:
    report = json.loads(Path(sys.argv[1]).read_text())
    policies = report["policies"]
    print(f"selection_digest: {report['provenance']['selection_digest']}")
    print(f"git_sha: {report['provenance']['git_sha']}")
    print(f"governor configs hashed: "
          f"{sorted(k for k in report['provenance']['config_sha256'] if 'governor' in k)}")
    print()
    print("== divergence gate ==")
    shas: dict[str, set[str]] = {}
    gate_ok = True
    for leg in UTILITY_LEGS:
        runs = policies[leg]["runs"]
        leg_shas = {canonical_sha(r) for r in runs}
        shas[leg] = leg_shas
        det = len(leg_shas) == 1
        gov = [r.get("governor") or {} for r in runs]
        splits = {g.get("allow_optional_splits") for g in gov}
        states = set()
        for g in gov:
            s = g.get("state") or g.get("final_state") or g
            states.add(s.get("state") if isinstance(s, dict) else s)
        actions = [g.get("actions_applied") for g in gov]
        agg = policies[leg]["aggregate"]["governor"]
        print(f"{leg}: run_shas={sorted(leg_shas)} deterministic={det}")
        print(f"  allow_optional_splits={sorted(splits, key=str)} "
              f"states={sorted(str(s) for s in states)} "
              f"actions_applied/run={actions} agg={agg['actions_applied']}")
        if splits != {True} or actions != [0] * len(actions):
            gate_ok = False
    distinct = {next(iter(v)) for v in shas.values() if len(v) == 1}
    print(f"\ndistinct leg SHAs: {len(distinct)} of {len(UTILITY_LEGS)} "
          f"(byte-identical={len(distinct) == 1})")
    if len(distinct) == 1:
        gate_ok = False
    print(f"DIVERGENCE GATE: {'PASS' if gate_ok else 'FAIL'}")
    print()
    print("== per-leg summary (final run quality, aggregate cost) ==")
    for leg in ["ablation_distance", *UTILITY_LEGS, "distance_lod",
                "uniform5", "uniform40"]:
        if leg not in policies:
            continue
        pol = policies[leg]
        q = pol["runs"][-1]["quality"]
        el = q["elevation_vs_fine_reference"]
        sem = q["field_retention"]["semantic"]
        haz = q["field_retention"]["terrain_hazard"]
        tc = q["field_retention"].get("task_classes", {}).get("members", {})
        mu = pol["aggregate"]["stage_latency_ns"]["map_update"]
        agg = pol["aggregate"]
        leaves = agg["final_leaves_per_level"]
        print(f"{leg}: RMSE={el['rmse_m']:.5f} cover={el['coverage']:.3f} "
              f"wml={pol['runs'][-1]['detail_metric']['weighted_mean_level']:.4f} "
              f"sem={sem.get('retention_fraction')} "
              f"({sem.get('retained_bins')}/{sem.get('reference_bins')}) "
              f"haz={haz.get('retention_fraction')}({haz.get('reference_bins')} ref) "
              f"pole={tc.get('pole', {}).get('retention_fraction')} "
              f"ped={tc.get('pedestrian', {}).get('retention_fraction')} "
              f"veh={tc.get('vehicle', {}).get('retention_fraction')}")
        print(f"  p50={ms(mu['p50']):.1f} p95={ms(mu['p95']):.1f} "
              f"p99={ms(mu['p99']):.1f}ms RSS={agg['peak_rss_bytes'] / 1048576:.1f}MB "
              f"leaves={sum(leaves.values())} {leaves} "
              f"churn_p95={agg['topology_churn_per_frame']['p95']} "
              f"gov={agg['governor']}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
