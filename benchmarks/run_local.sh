#!/usr/bin/env bash
set -euo pipefail

# Offline, local-only benchmark entry point.
# It never downloads datasets, model weights, or dependencies.

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_dir="$(cd -- "${script_dir}/.." && pwd -P)"
build_dir="${VEYRA_BUILD_DIR:-${TMPDIR:-/tmp}/veyra-build-local}"
output_dir="${VEYRA_OUTPUT_DIR:-${TMPDIR:-/tmp}/veyra-benchmark-results}"
dataset="semanticposs"
sequence="00"
start="0"
count="10"
warmup_frames="2"
repetitions="3"
policies="uniform5,uniform40,distance_lod,utility_lod"

usage() {
  cat <<'EOF'
Usage: benchmarks/run_local.sh [options]

Runs the configured local dataset through Python perception and the C++ map
benchmark. No network access or dataset download is performed.

Options:
  --dataset NAME       semanticposs or rellis3d (default: semanticposs)
  --sequence ID        dataset sequence (default: 00)
  --start N            first frame index (default: 0)
  --count N            number of input frames (default: 10)
  --warmup-frames N    unreported frames that initialize map state (default: 2)
  --repetitions N      measured process repetitions per policy (default: 3)
  --policies LIST      comma-separated available policies (default: all four)
  --build-dir PATH     local CMake build directory
  --output-dir PATH    JSON/CSV output directory
  -h, --help           show this help

Environment:
  VEYRA_BUILD_DIR      overrides the default build directory
  VEYRA_OUTPUT_DIR     overrides the default result directory
EOF
}

while (($#)); do
  case "$1" in
    --dataset) dataset="${2:?missing value for --dataset}"; shift 2 ;;
    --sequence) sequence="${2:?missing value for --sequence}"; shift 2 ;;
    --start) start="${2:?missing value for --start}"; shift 2 ;;
    --count) count="${2:?missing value for --count}"; shift 2 ;;
    --warmup-frames) warmup_frames="${2:?missing value for --warmup-frames}"; shift 2 ;;
    --repetitions) repetitions="${2:?missing value for --repetitions}"; shift 2 ;;
    --policies) policies="${2:?missing value for --policies}"; shift 2 ;;
    --build-dir) build_dir="${2:?missing value for --build-dir}"; shift 2 ;;
    --output-dir) output_dir="${2:?missing value for --output-dir}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$dataset" in
  semanticposs|rellis3d) ;;
  *) echo "dataset must be semanticposs or rellis3d" >&2; exit 2 ;;
esac

cmake -S "$repo_dir" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=ON \
  -DVEYRA_BUILD_APPS=ON
cmake --build "$build_dir" --target veyra_benchmark -j

mkdir -p "$output_dir"
json_output="${output_dir}/${dataset}-${sequence}-${start}-${count}.json"
csv_output="${output_dir}/${dataset}-${sequence}-${start}-${count}.csv"

python3 "$repo_dir/benchmarks/run_benchmark.py" \
  --repo "$repo_dir" \
  --binary "$build_dir/apps/benchmark/veyra_benchmark" \
  --dataset "$dataset" \
  --sequence "$sequence" \
  --start "$start" \
  --count "$count" \
  --warmup-frames "$warmup_frames" \
  --repetitions "$repetitions" \
  --policies "$policies" \
  --output "$json_output" \
  --csv-output "$csv_output"

echo "JSON: $json_output"
echo "CSV:  $csv_output"
