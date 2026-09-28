#!/usr/bin/env bash
set -euo pipefail

# Offline, local-only benchmark entry point.
# It never downloads datasets, model weights, or dependencies.

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_dir="$(cd -- "${script_dir}/.." && pwd -P)"
build_dir="${VEYRA_BUILD_DIR:-${TMPDIR:-/tmp}/veyra-build-local}"
output_dir="${VEYRA_OUTPUT_DIR:-${TMPDIR:-/tmp}/veyra-benchmark-results}"
dataset="semanticposs"
dataset_root=""
sequence="00"
start="0"
count="10"
warmup_frames="2"
repetitions="3"
policies="uniform5,uniform40,distance_lod,utility_lod"
skip_perception="false"
dataset_sha256=""
build_type="Release"
perception_config="configs/perception.yaml"
perception_output=""
skip_build="false"
retain_frames="false"
promotion_telemetry="false"
python_bin="${VEYRA_PYTHON:-python3}"

usage() {
  cat <<'EOF'
Usage: benchmarks/run_local.sh [options]

Runs the configured local dataset through Python perception and the C++ map
benchmark. Use --skip-perception for a map-only run. No network access or
dataset download is performed.

Options:
  --dataset NAME       semanticposs, rellis3d, semantickitti, or generic
  --dataset-root PATH  explicit local dataset root (required for generic)
  --sequence ID        dataset sequence (default: 00)
  --start N            first frame index (default: 0)
  --count N            number of input frames (default: 10)
  --warmup-frames N    unreported frames that initialize map state (default: 2)
  --repetitions N      measured process repetitions per policy (default: 3)
  --policies LIST      comma-separated available policies (default: all four)
  --skip-perception    send dataset frames directly to the map benchmark
  --dataset-sha256 HEX SHA-256 of the source dataset archive for provenance
  --build-type TYPE    CMake build type recorded in the artifact (default: Release)
  --perception-config PATH  perception config used before mapping
  --python PATH         Python interpreter for the benchmark harness
  --build-dir PATH     local CMake build directory
  --output-dir PATH    JSON/CSV output directory
  --perception-output PATH  JSON report from the shared perception pass
  --skip-build          use an already configured and built benchmark binary
  --retain-frames       keep the source selection in memory so semantic,
                        hazard and task-class field retention are measured
  --promotion-telemetry collect bounded UtilityLOD decision aggregates
  -h, --help           show this help

Environment:
  VEYRA_BUILD_DIR      overrides the default build directory
  VEYRA_OUTPUT_DIR     overrides the default result directory
EOF
}

while (($#)); do
  case "$1" in
    --dataset) dataset="${2:?missing value for --dataset}"; shift 2 ;;
    --dataset-root) dataset_root="${2:?missing value for --dataset-root}"; shift 2 ;;
    --sequence) sequence="${2:?missing value for --sequence}"; shift 2 ;;
    --start) start="${2:?missing value for --start}"; shift 2 ;;
    --count) count="${2:?missing value for --count}"; shift 2 ;;
    --warmup-frames) warmup_frames="${2:?missing value for --warmup-frames}"; shift 2 ;;
    --repetitions) repetitions="${2:?missing value for --repetitions}"; shift 2 ;;
    --policies) policies="${2:?missing value for --policies}"; shift 2 ;;
    --skip-perception) skip_perception="true"; shift ;;
    --dataset-sha256) dataset_sha256="${2:?missing value for --dataset-sha256}"; shift 2 ;;
    --build-type) build_type="${2:?missing value for --build-type}"; shift 2 ;;
    --perception-config) perception_config="${2:?missing value for --perception-config}"; shift 2 ;;
    --perception-output) perception_output="${2:?missing value for --perception-output}"; shift 2 ;;
    --skip-build) skip_build="true"; shift ;;
    --retain-frames) retain_frames="true"; shift ;;
    --promotion-telemetry) promotion_telemetry="true"; shift ;;
    --python) python_bin="${2:?missing value for --python}"; shift 2 ;;
    --build-dir) build_dir="${2:?missing value for --build-dir}"; shift 2 ;;
    --output-dir) output_dir="${2:?missing value for --output-dir}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$dataset" in
  semanticposs|rellis3d|semantickitti|generic) ;;
  *) echo "unsupported dataset: $dataset" >&2; exit 2 ;;
esac
if [[ "$dataset" == "generic" && -z "$dataset_root" ]]; then
  echo "--dataset-root is required for generic datasets" >&2
  exit 2
fi

if [[ "$skip_build" != "true" ]]; then
  cmake -S "$repo_dir" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE="$build_type" \
    -DBUILD_TESTING=ON \
    -DVEYRA_BUILD_APPS=ON
  cmake --build "$build_dir" --target veyra_benchmark -j
fi

mkdir -p "$output_dir"
json_output="${output_dir}/${dataset}-${sequence}-${start}-${count}.json"
csv_output="${output_dir}/${dataset}-${sequence}-${start}-${count}.csv"

benchmark_args=(
  "$python_bin" "$repo_dir/benchmarks/run_benchmark.py"
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
  --csv-output "$csv_output" \
  --build-type "$build_type" \
  --perception-config "$perception_config"
)
if [[ -n "$dataset_sha256" ]]; then
  benchmark_args+=(--dataset-sha256 "$dataset_sha256")
fi
if [[ -n "$dataset_root" ]]; then
  benchmark_args+=(--dataset-root "$dataset_root")
fi
if [[ "$skip_perception" == "true" ]]; then
  benchmark_args+=(--skip-perception)
fi
if [[ "$retain_frames" == "true" ]]; then
  benchmark_args+=(--retain-frames)
fi
if [[ "$promotion_telemetry" == "true" ]]; then
  benchmark_args+=(--promotion-telemetry)
fi
if [[ -n "${perception_output:-}" ]]; then
  benchmark_args+=(--perception-output "$perception_output")
fi
"${benchmark_args[@]}"

echo "JSON: $json_output"
echo "CSV:  $csv_output"
