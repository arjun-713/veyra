#!/usr/bin/env bash
set -euo pipefail

# Reproducible validation entrypoint.  --ci is the affordable deterministic
# gate; --full additionally requires the real local SemanticPOSS archive and
# pinned SalsaNext model and executes the four-policy benchmark.

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_dir="$(cd -- "${script_dir}/.." && pwd -P)"
mode="ci"
build_dir="${VEYRA_SIH_BUILD_DIR:-${TMPDIR:-/tmp}/veyra-sih-validation-build}"
python_bin="${VEYRA_PYTHON:-${repo_dir}/.venv/bin/python}"

usage() {
  cat <<'EOF'
Usage: scripts/validate_sih.sh [--ci|--full]

  --ci    Run strict C++, Python, benchmark-contract, and desktop checks.
          Real dataset execution is explicitly not requested in this mode.
  --full  Run --ci checks plus the official local SemanticPOSS archive through
          Patchwork++, SalsaNext, terrain, and all four map policies.

Environment:
  VEYRA_SIH_BUILD_DIR  CMake build directory
  VEYRA_PYTHON         Python interpreter (default: repository .venv)
  VEYRA_SIH_FRAMES     Full-mode frame count (default: 488)
  VEYRA_SIH_WARMUP_FRAMES
                       Full-mode warmup frames (default: 10; reduced to
                       one fewer than VEYRA_SIH_FRAMES when necessary)
EOF
}

while (($#)); do
  case "$1" in
    --ci) mode="ci"; shift ;;
    --full) mode="full"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$mode" == "full" ]]; then
  frames="${VEYRA_SIH_FRAMES:-488}"
  warmup_frames="${VEYRA_SIH_WARMUP_FRAMES:-10}"
  if ! [[ "$frames" =~ ^[1-9][0-9]*$ ]]; then
    echo "VEYRA_SIH_FRAMES must be a positive integer: $frames" >&2
    exit 2
  fi
  if ! [[ "$warmup_frames" =~ ^[0-9]+$ ]]; then
    echo "VEYRA_SIH_WARMUP_FRAMES must be a non-negative integer: $warmup_frames" >&2
    exit 2
  fi
  if ((warmup_frames >= frames)); then
    warmup_frames=$((frames - 1))
  fi
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python interpreter is unavailable: $python_bin" >&2
  exit 2
fi

cd "$repo_dir"
echo "SIH26053 VALIDATION ($mode)"

cmake -S . -B "$build_dir" -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=ON -DVEYRA_BUILD_APPS=ON \
  -DCMAKE_CXX_FLAGS="-Wall -Wextra -Wpedantic -Werror"
cmake --build "$build_dir" --parallel
ctest --test-dir "$build_dir" --output-on-failure

"$python_bin" -m unittest discover -s benchmarks -p 'test*.py'
"$python_bin" -m unittest discover -s tests -p 'test*.py'
ruff check benchmarks
ruff format --check benchmarks/run_benchmark.py benchmarks/render_report.py \
  benchmarks/test_product_benchmark.py benchmarks/test_render_report.py
"$python_bin" -m compileall -q benchmarks datasets perception scripts tests
bash -n benchmarks/run_local.sh scripts/validate_sih.sh

if [[ -d apps/desktop/node_modules ]]; then
  (
    cd apps/desktop
    npm test
    npm run check
    npm run build
  )
else
  echo "Desktop checks unavailable: apps/desktop/node_modules is absent" >&2
  exit 2
fi

if [[ "$mode" == "ci" ]]; then
  echo "REAL DATA: NOT RUN (use scripts/validate_sih.sh --full)"
  echo "CI VALIDATION: PASS; FULL SIH VALIDATION: NOT RUN"
  exit 0
fi

dataset_root="${repo_dir}/data/raw/semanticposs/dataset"
model_path="${repo_dir}/data/cache/models/salsanext-onnx-float/salsanext.onnx"
if [[ ! -d "$dataset_root/sequences/00" ]]; then
  echo "REAL DATA: UNAVAILABLE — official SemanticPOSS sequence 00 missing: $dataset_root" >&2
  exit 2
fi
if [[ ! -s "$model_path" ]]; then
  echo "REAL MODEL: UNAVAILABLE — pinned SalsaNext model missing: $model_path" >&2
  exit 2
fi

output_dir="${VEYRA_SIH_OUTPUT_DIR:-${TMPDIR:-/tmp}/veyra-sih-full-results}"
benchmarks/run_local.sh \
  --python "$python_bin" \
  --dataset semanticposs --sequence 00 --count "$frames" --warmup-frames "$warmup_frames" \
  --repetitions "${VEYRA_SIH_REPETITIONS:-1}" \
  --policies uniform5,uniform40,distance_lod,utility_lod \
  --perception-config configs/perception-salsanext.yaml \
  --build-dir "$build_dir" --output-dir "$output_dir" --skip-build

echo "REAL DATA: PASS — SemanticPOSS sequence 00, $frames frames"
echo "FULL SIH VALIDATION: PASS"
