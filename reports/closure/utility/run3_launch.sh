#!/usr/bin/env bash
# Utility-run3 launch: unclamped-latency matrix + Disabled-override diagnostic.
#
# Context: default-budget and 750k/500ms-recipe matrices both stayed clamped --
# the latency path latches on the semantics leg (frame spikes ~900 ms).
# The experiment summarized in RESULT.md sizes this diagnostic from the
# unclamped spikes (1200 ms target here) and/or a Disabled-override diagnostic
# for pure-policy deltas.
#
# Harness note: benchmarks/run_benchmark.py accepts ONE --governor-config per
# invocation (no per-leg override), and build_matrix.py requires all 9
# policies. The Disabled diagnostic is therefore a second FULL 9-leg matrix
# invocation with configs/resource_governor-unclamped.yaml (100M cells /
# 1000000 ms target: effectively disabled, splits always allowed, ~0 actions).
# The two matrices run SEQUENTIALLY in this script -- never parallelize them;
# contention on this box would distort the latency measurements under test.
#
# Stream (identical to both prior matrices): staged SemanticPOSS seq00
# frames 0-29, --retain-frames, 3 reps, 2 warmup. Expect stream digest
# prefix 4cd60ac5. No benchmarks/* framework changes.
#
# Usage: ./reports/closure/utility/run3_launch.sh
#   DATASET_ROOT overrides the SemanticPOSS dataset root (default: the main
#   checkout's data dir; worktrees do not carry the 4 GB raw dataset).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO"
DATASET_ROOT="${DATASET_ROOT:-/home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset}"
POLICIES="uniform5,uniform40,distance_lod,ablation_distance,ablation_geometry,ablation_semantics,ablation_motion,ablation_traversability,utility_lod"
OUT="reports/closure/utility"

run_matrix() {
  local gov="$1" json="$2" csv="$3"
  echo "=== [$(date -u +%FT%TZ)] governor=${gov} -> ${json}"
  python3 benchmarks/run_benchmark.py \
    --binary build/apps/benchmark/veyra_benchmark \
    --dataset semanticposs --sequence 00 --start 0 --count 30 \
    --warmup-frames 2 --repetitions 3 \
    --policies "$POLICIES" \
    --retain-frames \
    --dataset-root "$DATASET_ROOT" \
    --governor-config "$gov" \
    --output "$json" --csv-output "$csv"
  echo "=== [$(date -u +%FT%TZ)] done ${json}"
}

# Matrix A: 1200 ms / 750k-cell operating point (unclamped-latency attempt).
run_matrix configs/resource_governor-utility-run3.yaml \
  "$OUT/benchmark_run3_semanticposs00.json" \
  "$OUT/benchmark_run3_semanticposs00.csv"

# Matrix B: Disabled-override diagnostic (pure-policy deltas).
run_matrix configs/resource_governor-unclamped.yaml \
  "$OUT/benchmark_run3_unclamped_semanticposs00.json" \
  "$OUT/benchmark_run3_unclamped_semanticposs00.csv"

echo "=== [$(date -u +%FT%TZ)] run3 complete; analysis is a separate mission"
