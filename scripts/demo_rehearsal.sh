#!/usr/bin/env bash
#
# demo_rehearsal.sh — single scripted Veyra demo rehearsal for an evaluator.
#
# Runs, step by step with per-step evidence logging to a timestamped dir:
#   (1) preflight (binaries, data root, checkpoint presence detection)
#   (2) headless backend session: configure -> step N frames -> policy switch
#       (uniform5/uniform40/distance_lod/utility_lod) -> layer switch ->
#       telemetry snapshot -> clean stop
#   (3) packaged-desktop launch check, or honest SKIP with the build command
#   (4) evidence summary (telemetry JSON, policy timings, checklist pass/fail)
#
# Semantics default: ground_truth (explicit). The neural CENet path is
# CPU-slow (~8.5 s/frame measured) and ONLY runs with --neural, with a
# printed time estimate. Neural output is never relabelled: the probe
# asserts provider mode == "model" and never feeds the map session.
#
# Read-only dry run of step 1 only:
#   scripts/demo_rehearsal.sh --preflight-only
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEFAULT_REPO="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

REPO="${DEFAULT_REPO}"
SEQUENCE="00"
FRAMES=5
DATA_ROOT=""
PYTHON_BIN=""
MAPPER_BIN=""
NEURAL=0
NEURAL_FRAMES=2
NEURAL_CHECKPOINT=""
NEURAL_PYTHON=""
SKIP_DESKTOP=0
PREFLIGHT_ONLY=0
EVIDENCE_DIR=""

POLICIES="uniform5 uniform40 distance_lod utility_lod"
LAYERS="semantic elevation traversability motion lod utility"

# Measured CENet CPU cost (reports/closure/semantic-finetune/RESULT.md):
# provider infer p50 8554 ms / p95 17616 ms on Intel i5-8350U, torch 2.14 CPU,
# intra-op threads=4, 16 closure frames. Rounded up for the estimate.
CENET_MS_PER_FRAME_EST=9000
CENET_LOAD_S_EST=60

usage() {
  cat <<'EOF'
Usage: scripts/demo_rehearsal.sh [options]

  --repo PATH            Repository checkout to rehearse (default: script's repo)
  --sequence ID          SemanticPOSS sequence (default: 00)
  --frames N             Headless frames to step on the default policy (1-488, default: 5)
  --data-root PATH       Dataset root (default: <repo>/data/raw/semanticposs/dataset)
  --python BIN           Python interpreter (default: <repo>/.venv/bin/python)
  --mapper BIN           C++ mapper binary (default: <repo>/build/apps/runtime/veyra_runtime)
  --neural               Opt in to the CENet neural probe (default: OFF, ground_truth only)
  --neural-frames M      Neural probe frames, 1-16 (default: 2). Time est printed first.
  --neural-checkpoint P  CENet weights (default: <repo>/data/cache/cenet-work/model/SENet_valid_best)
  --neural-python BIN    Python with torch for the neural probe (default: auto-detect)
  --skip-desktop         Skip the packaged-desktop check (records SKIP)
  --preflight-only       Run ONLY step 1 preflight (safe, read-only) + summary
  --evidence-dir DIR     Evidence dir (default: <repo>/reports/demo-rehearsal/<UTC timestamp>)
  -h, --help             This help

Semantics: ground_truth unless --neural is given. --neural runs a separate
CENet latency probe (mode "model", asserted); the map session always stays
on ground_truth so neural output is never silently faked.

Examples:
  scripts/demo_rehearsal.sh --preflight-only
  scripts/demo_rehearsal.sh --frames 5
  scripts/demo_rehearsal.sh --frames 5 --neural --neural-frames 2
EOF
}

log() {
  local stamp
  stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '[%s] %s\n' "${stamp}" "$*" | tee -a "${MAIN_LOG}"
}

# record_check <name> <PASS|FAIL|SKIP> <detail>
record_check() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "${CHECKLIST_TSV}"
  log "CHECK ${1}: ${2} — ${3}"
}

is_int_in_range() {
  local value="$1" lo="$2" hi="$3"
  [[ "${value}" =~ ^[0-9]+$ ]] && [ "${value}" -ge "${lo}" ] && [ "${value}" -le "${hi}" ]
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --sequence) SEQUENCE="$2"; shift 2 ;;
    --frames) FRAMES="$2"; shift 2 ;;
    --data-root) DATA_ROOT="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --mapper) MAPPER_BIN="$2"; shift 2 ;;
    --neural) NEURAL=1; shift ;;
    --neural-frames) NEURAL_FRAMES="$2"; shift 2 ;;
    --neural-checkpoint) NEURAL_CHECKPOINT="$2"; shift 2 ;;
    --neural-python) NEURAL_PYTHON="$2"; shift 2 ;;
    --skip-desktop) SKIP_DESKTOP=1; shift ;;
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --evidence-dir) EVIDENCE_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! is_int_in_range "${FRAMES}" 1 488; then
  printf 'error: --frames must be 1-488 (got %s)\n' "${FRAMES}" >&2; exit 2
fi
if ! is_int_in_range "${NEURAL_FRAMES}" 1 16; then
  printf 'error: --neural-frames must be 1-16 (got %s)\n' "${NEURAL_FRAMES}" >&2; exit 2
fi
if [ -z "${DATA_ROOT}" ]; then DATA_ROOT="${REPO}/data/raw/semanticposs/dataset"; fi
if [ -z "${PYTHON_BIN}" ]; then PYTHON_BIN="${REPO}/.venv/bin/python"; fi
if [ -z "${MAPPER_BIN}" ]; then MAPPER_BIN="${REPO}/build/apps/runtime/veyra_runtime"; fi
if [ -z "${NEURAL_CHECKPOINT}" ]; then
  NEURAL_CHECKPOINT="${REPO}/data/cache/cenet-work/model/SENet_valid_best"
fi
if [ -z "${EVIDENCE_DIR}" ]; then
  EVIDENCE_DIR="${REPO}/reports/demo-rehearsal/$(date -u +%Y%m%dT%H%M%SZ)"
fi

mkdir -p "${EVIDENCE_DIR}"
MAIN_LOG="${EVIDENCE_DIR}/rehearsal.log"
CHECKLIST_TSV="${EVIDENCE_DIR}/checklist.tsv"
: > "${MAIN_LOG}"
: > "${CHECKLIST_TSV}"

# Resolved in preflight; consumed by later steps.
PREFLIGHT_OK=0
HAVE_TORCH_PYTHON=""

# ---------------------------------------------------------------- step 1 ---
step_preflight() {
  local step_log="${EVIDENCE_DIR}/step-01-preflight.log"
  {
    log "=== STEP 1/5: preflight (read-only) ==="
    log "repo=${REPO} sequence=${SEQUENCE} frames=${FRAMES}"
    if [ "${NEURAL}" = "1" ]; then
      log "semantics=ground_truth (map session) + CENet neural probe (${NEURAL_FRAMES} frames)"
    else
      log "semantics=ground_truth (neural probe OFF; pass --neural to opt in)"
    fi

    local ok=1

    # Repo + HEAD provenance.
    if [ -d "${REPO}/runtime" ] && [ -d "${REPO}/perception" ]; then
      local head="unknown"
      if head="$(git -C "${REPO}" rev-parse HEAD 2>/dev/null)"; then
        log "repo HEAD=${head}"
        printf '%s\n' "${head}" > "${EVIDENCE_DIR}/repo_HEAD.txt"
        record_check "preflight.repo" "PASS" "HEAD ${head}"
      else
        record_check "preflight.repo" "PASS" "layout ok, HEAD unavailable (not a git checkout?)"
      fi
    else
      record_check "preflight.repo" "FAIL" "missing runtime/ or perception/ under ${REPO}"
      ok=0
    fi

    # Python interpreter + product-runtime imports (read-only import probe).
    if [ -x "${PYTHON_BIN}" ]; then
      local pyver
      pyver="$("${PYTHON_BIN}" --version 2>&1 | head -n 1)"
      log "python: ${PYTHON_BIN} (${pyver})"
      if "${PYTHON_BIN}" -c "import runtime.service, viewer.runtime" 2>"${EVIDENCE_DIR}/python_import.err"; then
        record_check "preflight.python" "PASS" "${pyver}"
      else
        record_check "preflight.python" "FAIL" "cannot import product runtime: $(head -c 300 "${EVIDENCE_DIR}/python_import.err")"
        ok=0
      fi
    else
      record_check "preflight.python" "FAIL" "not executable: ${PYTHON_BIN} (try --python)"
      ok=0
    fi

    # C++ mapper binary.
    if [ -x "${MAPPER_BIN}" ]; then
      record_check "preflight.mapper" "PASS" "${MAPPER_BIN}"
    else
      record_check "preflight.mapper" "FAIL" "missing: ${MAPPER_BIN} (build it; no build is run by this script)"
      ok=0
    fi

    # Real data: SemanticPOSS seqkt, 488 frames + labels + poses.
    if [ -d "${DATA_ROOT}/sequences/${SEQUENCE}/velodyne" ]; then
      local scans=0 labels=0
      shopt -s nullglob
      for _ in "${DATA_ROOT}/sequences/${SEQUENCE}/velodyne/"*.bin; do scans=$((scans + 1)); done
      for _ in "${DATA_ROOT}/sequences/${SEQUENCE}/labels/"*.label; do labels=$((labels + 1)); done
      shopt -u nullglob
      log "dataset seq ${SEQUENCE}: scans=${scans} labels=${labels}"
      printf 'sequence=%s scans=%d labels=%d\n' "${SEQUENCE}" "${scans}" "${labels}" > "${EVIDENCE_DIR}/dataset_counts.txt"
      if [ "${scans}" -ge "${FRAMES}" ] && [ "${labels}" -ge "${FRAMES}" ] && [ -f "${DATA_ROOT}/sequences/${SEQUENCE}/poses.txt" ]; then
        record_check "preflight.dataset" "PASS" "seq ${SEQUENCE}: ${scans} scans, ${labels} labels, poses.txt present"
      else
        record_check "preflight.dataset" "FAIL" "seq ${SEQUENCE}: scans=${scans} labels=${labels}; need >= ${FRAMES} each + poses.txt"
        ok=0
      fi
    else
      record_check "preflight.dataset" "FAIL" "missing: ${DATA_ROOT}/sequences/${SEQUENCE}/velodyne (try --data-root)"
      ok=0
    fi

    # CENet checkpoint presence detection (informational unless --neural).
    local archive="${REPO}/data/cache/models/cenet-poss/cenet-poss-291MB.bin"
    local ckpt_detail="archive:absent weights:absent torch(${PYTHON_BIN}):unknown"
    local have_archive=0 have_weights=0 have_torch=0
    if [ -f "${archive}" ]; then have_archive=1; fi
    if [ -f "${NEURAL_CHECKPOINT}" ]; then have_weights=1; fi
    if [ -x "${PYTHON_BIN}" ] && "${PYTHON_BIN}" -c "import torch" 2>/dev/null; then
      have_torch=1
      HAVE_TORCH_PYTHON="${PYTHON_BIN}"
    elif command -v python3 >/dev/null 2>&1 && python3 -c "import torch; import sys; sys.path.insert(0, '${REPO}')" 2>/dev/null; then
      # System python3 may carry torch while the venv does not; imports of the
      # repo tree are still resolved by inserting REPO on sys.path.
      if PYTHONPATH="${REPO}" python3 -c "import torch, runtime.service" 2>/dev/null; then
        HAVE_TORCH_PYTHON="python3"
      fi
    fi
    ckpt_detail="archive:$([ "${have_archive}" = "1" ] && echo present || echo absent)"
    ckpt_detail="${ckpt_detail} weights:$([ "${have_weights}" = "1" ] && echo present || echo "absent(${NEURAL_CHECKPOINT})")"
    ckpt_detail="${ckpt_detail} torch:${HAVE_TORCH_PYTHON:-none}"
    log "cenet presence: ${ckpt_detail}"
    printf '%s\n' "${ckpt_detail}" > "${EVIDENCE_DIR}/cenet_presence.txt"
    if [ "${NEURAL}" = "1" ]; then
      local est_s
      est_s=$(( CENET_LOAD_S_EST + (NEURAL_FRAMES * CENET_MS_PER_FRAME_EST + 500) / 1000 ))
      log "NEURAL probe time estimate: ~${est_s}s for ${NEURAL_FRAMES} frame(s) (p50 8.6 s/frame + ~60 s load; measured i5-8350U torch-CPU, see reports/closure/semantic-finetune/RESULT.md)"
      if [ "${have_weights}" = "1" ] && [ -n "${HAVE_TORCH_PYTHON}" ]; then
        record_check "preflight.neural" "PASS" "weights+torch present; est ~${est_s}s for ${NEURAL_FRAMES} frames"
      else
        record_check "preflight.neural" "FAIL" "${ckpt_detail}; neural probe cannot run honestly"
        ok=0
      fi
    else
      record_check "preflight.neural" "SKIP" "probe OFF (default ground_truth); ${ckpt_detail}"
    fi

    # Packaged bundle presence (informational here; step 3 decides).
    local deb rpm relbin
    deb="$(printf '%s' "${REPO}"/src-tauri/target/release/bundle/deb/*.deb 2>/dev/null | head -n 1)"
    rpm="$(printf '%s' "${REPO}"/src-tauri/target/release/bundle/rpm/*.rpm 2>/dev/null | head -n 1)"
    relbin="${REPO}/src-tauri/target/release/veyra"
    log "bundle detect: deb=[${deb}] rpm=[${rpm}] release_bin=[${relbin}]"
    printf 'deb=%s\nrpm=%s\nrelease_bin=%s\n' "${deb}" "${rpm}" "${relbin}" > "${EVIDENCE_DIR}/bundle_detect.txt"

    if [ "${ok}" = "1" ]; then
      PREFLIGHT_OK=1
      log "preflight: ALL REQUIRED CHECKS PASS"
    else
      PREFLIGHT_OK=0
      log "preflight: FAILURES PRESENT — downstream steps will SKIP, see summary"
    fi
    # The closing pipeline runs this brace group in a subshell, so persist
    # parent-consumed state to files; the parent re-reads them below.
    printf '%s\n' "${PREFLIGHT_OK}" > "${EVIDENCE_DIR}/.preflight_ok"
    printf '%s\n' "${HAVE_TORCH_PYTHON}" > "${EVIDENCE_DIR}/.have_torch_python"
  } 2>&1 | tee "${step_log}" | tee -a "${MAIN_LOG}"
  PREFLIGHT_OK="$(cat "${EVIDENCE_DIR}/.preflight_ok" 2>/dev/null || printf '0')"
  HAVE_TORCH_PYTHON="$(cat "${EVIDENCE_DIR}/.have_torch_python" 2>/dev/null || printf '')"
}

# --------------------------------------------------------------- step 2 ---
# Headless backend session through the real product runtime entrypoint
# (`python -m runtime --repo`), the same boot path the Tauri supervisor uses:
# NDJSON commands on stdin, VYRA-framed messages on stdout.
step_headless() {
  local step_log="${EVIDENCE_DIR}/step-02-headless.log"
  {
    log "=== STEP 2/5: headless backend session (semantics=ground_truth) ==="
    if [ "${PREFLIGHT_OK}" != "1" ]; then
      record_check "headless.session" "SKIP" "preflight failed; refusing to run a session without proven prerequisites"
      return 0
    fi

    cat > "${EVIDENCE_DIR}/drive_headless.py" <<'PYEOF'
"""Drive `python -m runtime --repo` over NDJSON stdin / VYRA stdout.

Mirrors the packaged Tauri flow: configure -> step N -> per-policy
switch+step -> layer switches -> metrics/telemetry snapshot -> shutdown.
Exits nonzero with a clear message on any failed assertion; writes
session.json + telemetry.json to the evidence dir.
"""
import json
import os
import select
import subprocess
import sys
import time

REPO = os.environ["VEYRA_RH_REPO"]
DATA_ROOT = os.environ["VEYRA_RH_DATA_ROOT"]
SEQ = os.environ["VEYRA_RH_SEQUENCE"]
NFRAMES = int(os.environ["VEYRA_RH_FRAMES"])
OUT = os.environ["VEYRA_RH_SESSION_JSON"]
TELEMETRY_OUT = os.environ["VEYRA_RH_TELEMETRY_JSON"]
STDERR_PATH = os.environ["VEYRA_RH_STDERR"]
POLICIES = os.environ["VEYRA_RH_POLICIES"].split()
LAYERS = os.environ["VEYRA_RH_LAYERS"].split()

sys.path.insert(0, REPO)
from runtime.protocol import read_message  # noqa: E402

err_stream = open(STDERR_PATH, "wb")
proc = subprocess.Popen(
    [sys.executable, "-m", "runtime", "--repo", REPO],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=err_stream,
    cwd=REPO,
    bufsize=0,
)

seqn = 0
telemetry_latest = None
visual_max = 0


def rpc(command, args, timeout):
    """Send one command; drain messages until its response arrives."""
    global seqn, telemetry_latest, visual_max
    seqn += 1
    ident = "rh-%d" % seqn
    proc.stdin.write(
        (json.dumps({"id": ident, "command": command, "args": args}) + "\n").encode()
    )
    proc.stdin.flush()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for %s (%s)" % (command, ident))
        ready, _, _ = select.select([proc.stdout], [], [], remaining)
        if not ready:
            raise TimeoutError("no output while waiting for %s (%s)" % (command, ident))
        if proc.poll() is not None:
            raise RuntimeError(
                "runtime exited code=%s during %s" % (proc.returncode, command)
            )
        meta, payload = read_message(proc.stdout)
        mtype = meta.get("type")
        if mtype == "telemetry":
            telemetry_latest = meta
        elif mtype == "visualization":
            visual_max = max(visual_max, len(payload or b""))
        elif mtype == "response" and meta.get("id") == ident:
            if not meta.get("ok"):
                raise RuntimeError(
                    "%s failed: %s" % (command, json.dumps(meta.get("error")))
                )
            return meta
        # Other broadcasts (status) are ignored here.


def active_cells():
    if not telemetry_latest:
        return None
    return (telemetry_latest.get("map") or {}).get("active_cells")


result = {"steps": [], "policies": [], "layers": []}

config = {
    "dataset": "semanticposs",
    "dataset_root": DATA_ROOT,
    "sequence": SEQ,
    "pipeline": {
        "semantic": {"mode": "ground_truth"},
        "ground": {
            "enabled": True,
            "parameter_overrides": {"min_range": 0.0, "max_range": 100.0},
        },
        "terrain": {"enabled": True},
        "temporal": {"enabled": False},
    },
}

started = time.perf_counter()
resp = rpc("configure", {"config": config}, 300)
configure_ms = (time.perf_counter() - started) * 1000.0
frames = resp["status"]["frames"]
result["configured_frames"] = frames
result["configure_ms"] = configure_ms
result["sequence"] = resp["status"]["sequence"]
print("configured frames=%s sequence=%s in %.1fs" % (frames, SEQ, configure_ms / 1000.0))
if frames < NFRAMES:
    raise RuntimeError("need >= %d frames, session has %s" % (NFRAMES, frames))

for i in range(NFRAMES):
    started = time.perf_counter()
    status = rpc("step", {}, 180)["status"]
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result["steps"].append(
        {"frame": status["index"], "step_ms": elapsed_ms, "active_cells": active_cells()}
    )
    print("step frame=%s %.1fs active_cells=%s" % (status["index"], elapsed_ms / 1000.0, active_cells()))

for policy in POLICIES:
    started = time.perf_counter()
    status = rpc("policy", {"policy": policy}, 300)["status"]
    switch_ms = (time.perf_counter() - started) * 1000.0
    if status["policy"] != policy:
        raise RuntimeError("policy switch to %s not reflected: %s" % (policy, status["policy"]))
    started = time.perf_counter()
    status = rpc("step", {}, 180)["status"]
    step_ms = (time.perf_counter() - started) * 1000.0
    result["policies"].append(
        {
            "policy": policy,
            "switch_ms": switch_ms,
            "step_ms": step_ms,
            "active_cells": active_cells(),
        }
    )
    print("policy %s switch=%.1fs step=%.1fs active_cells=%s"
          % (policy, switch_ms / 1000.0, step_ms / 1000.0, active_cells()))

for layer in LAYERS:
    status = rpc("layer", {"layer": layer}, 60)["status"]
    if status["layer"] != layer:
        raise RuntimeError("layer switch to %s not reflected" % layer)
    result["layers"].append(layer)
print("layers ok: %s" % " ".join(result["layers"]))

metrics = rpc("metrics", {}, 60)["result"]
result["metrics_status"] = metrics.get("status", "snapshot")

if telemetry_latest is None:
    raise RuntimeError("no telemetry message observed during the session")
if not active_cells():
    raise RuntimeError("telemetry reports no live map cells (active_cells=%r)" % active_cells())
if visual_max == 0:
    raise RuntimeError("no binary visualization frame reached the renderer channel")
result["telemetry_visual_bytes_max"] = visual_max

rpc("shutdown", {}, 60)
proc.stdin.close()
try:
    returncode = proc.wait(timeout=20)
except subprocess.TimeoutExpired:
    proc.kill()
    returncode = proc.wait(timeout=10)
    raise RuntimeError("runtime process was not reaped after clean stop")
result["stop_returncode"] = returncode
result["reaped"] = True
print("clean stop: returncode=%s" % returncode)

with open(OUT, "w", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
with open(TELEMETRY_OUT, "w", encoding="utf-8") as stream:
    json.dump(telemetry_latest, stream, indent=2)
print("wrote %s and %s" % (OUT, TELEMETRY_OUT))
PYEOF

    export VEYRA_RH_REPO="${REPO}"
    export VEYRA_RH_DATA_ROOT="${DATA_ROOT}"
    export VEYRA_RH_SEQUENCE="${SEQUENCE}"
    export VEYRA_RH_FRAMES="${FRAMES}"
    export VEYRA_RH_SESSION_JSON="${EVIDENCE_DIR}/session.json"
    export VEYRA_RH_TELEMETRY_JSON="${EVIDENCE_DIR}/telemetry.json"
    export VEYRA_RH_STDERR="${EVIDENCE_DIR}/runtime.stderr.log"
    export VEYRA_RH_POLICIES="${POLICIES}"
    export VEYRA_RH_LAYERS="${LAYERS}"

    if "${PYTHON_BIN}" "${EVIDENCE_DIR}/drive_headless.py" > "${EVIDENCE_DIR}/headless_driver.out" 2>&1; then
      log "headless session complete; driver output tailed below"
      tail -n 20 "${EVIDENCE_DIR}/headless_driver.out" >> "${MAIN_LOG}"
      record_check "headless.session" "PASS" "configure+${FRAMES} steps+4 policies+6 layers+telemetry+clean stop (see session.json)"
      # Per-policy timing evidence, extracted with the same proven interpreter.
      "${PYTHON_BIN}" -c "
import json
s = json.load(open('${EVIDENCE_DIR}/session.json'))
for p in s['policies']:
    print('policy %-12s switch=%8.1fms step=%8.1fms active_cells=%s' % (p['policy'], p['switch_ms'], p['step_ms'], p['active_cells']))
" 2>/dev/null | tee -a "${MAIN_LOG}" || log "(policy timing table unavailable)"
    else
      log "headless driver FAILED; tail:"
      tail -n 30 "${EVIDENCE_DIR}/headless_driver.out" >> "${MAIN_LOG}" || true
      record_check "headless.session" "FAIL" "driver error; see headless_driver.out + runtime.stderr.log"
    fi
  } 2>&1 | tee "${step_log}" | tee -a "${MAIN_LOG}"
}

# --------------------------------------------------------------- step 3 ---
# Optional neural probe. Runs ONLY with --neural. Times the real CENet
# provider on real frames and asserts mode == "model". Never touches the
# map session: ground_truth-as-neural substitution is explicitly refused.
step_neural() {
  local step_log="${EVIDENCE_DIR}/step-03-neural.log"
  {
    log "=== STEP 3/5: neural CENet probe (opt-in only) ==="
    if [ "${NEURAL}" != "1" ]; then
      record_check "neural.probe" "SKIP" "default ground_truth; re-run with --neural to measure CENet (~8.5 s/frame CPU)"
      return 0
    fi
    if [ "${PREFLIGHT_OK}" != "1" ]; then
      record_check "neural.probe" "SKIP" "preflight failed; refusing to run the neural probe"
      return 0
    fi

    local est_s
    est_s=$(( CENET_LOAD_S_EST + (NEURAL_FRAMES * CENET_MS_PER_FRAME_EST + 500) / 1000 ))
    log "CENet estimate: ~${est_s}s for ${NEURAL_FRAMES} frame(s) (p50 8.6 s/frame + ~60 s checkpoint load)"

    local npy="${NEURAL_PYTHON}"
    if [ -z "${npy}" ]; then npy="${HAVE_TORCH_PYTHON}"; fi
    if [ -z "${npy}" ]; then
      record_check "neural.probe" "FAIL" "no torch-bearing python found (need torch CPU for perception/semantic/cenet.py)"
      return 0
    fi
    if [ ! -f "${NEURAL_CHECKPOINT}" ]; then
      record_check "neural.probe" "FAIL" "missing weights: ${NEURAL_CHECKPOINT}"
      return 0
    fi
    log "neural python=${npy} checkpoint=${NEURAL_CHECKPOINT}"

    cat > "${EVIDENCE_DIR}/probe_cenet.py" <<'PYEOF'
"""Time the real CENet provider on real SemanticPOSS frames.

Asserts every result carries mode == "model" (never ground_truth relabelled
as neural). Pure provider latency probe: output never enters the map.
"""
import json
import os
import sys
import time

REPO = os.environ["VEYRA_RN_REPO"]
CKPT = os.environ["VEYRA_RN_CHECKPOINT"]
DATA_ROOT = os.environ["VEYRA_RN_DATA_ROOT"]
SEQ = os.environ["VEYRA_RN_SEQUENCE"]
N = int(os.environ["VEYRA_RN_FRAMES"])
OUT = os.environ["VEYRA_RN_OUT"]

sys.path.insert(0, REPO)
import numpy as np  # noqa: E402
from datasets.semanticposs import SemanticPOSSDataset  # noqa: E402
from perception.semantic.cenet import CENetSemanticProvider  # noqa: E402

started = time.perf_counter()
provider = CENetSemanticProvider(CKPT)
load_ms = (time.perf_counter() - started) * 1000.0
print("cenet loaded in %.1fs" % (load_ms / 1000.0))

adapter = SemanticPOSSDataset(DATA_ROOT)
refs = adapter.list_frames(SEQ)
if len(refs) < N:
    raise RuntimeError("need %d frames, sequence %s has %d" % (N, SEQ, len(refs)))

frames = []
for ref in refs[:N]:
    frame = adapter.load_frame(SEQ, ref.frame_id)
    points = np.asarray(frame.points, dtype=np.float32)
    sensor_points = points
    if frame.provenance.coordinate_frame in ("world", "calibrated_lidar"):
        sensor_points = points.copy()
        sensor_points[:, :3] = (
            points[:, :3] - frame.pose.matrix[:3, 3]
        ) @ frame.pose.matrix[:3, :3]
    started = time.perf_counter()
    result = provider.infer(sensor_points, frame.semantic_class)
    infer_ms = (time.perf_counter() - started) * 1000.0
    if result.mode != "model":
        raise RuntimeError(
            "refusing to report mode=%r as neural output" % (result.mode,)
        )
    frames.append(
        {
            "frame": ref.frame_id,
            "points": int(points.shape[0]),
            "infer_ms": infer_ms,
            "mode": result.mode,
        }
    )
    print("frame %s points=%d infer=%.1fs mode=%s"
          % (ref.frame_id, points.shape[0], infer_ms / 1000.0, result.mode))

with open(OUT, "w", encoding="utf-8") as stream:
    json.dump(
        {"checkpoint": CKPT, "load_ms": load_ms, "frames": frames}, stream, indent=2
    )
print("wrote %s" % OUT)
PYEOF

    export VEYRA_RN_REPO="${REPO}"
    export VEYRA_RN_CHECKPOINT="${NEURAL_CHECKPOINT}"
    export VEYRA_RN_DATA_ROOT="${DATA_ROOT}"
    export VEYRA_RN_SEQUENCE="${SEQUENCE}"
    export VEYRA_RN_FRAMES="${NEURAL_FRAMES}"
    export VEYRA_RN_OUT="${EVIDENCE_DIR}/neural.json"

    if "${npy}" "${EVIDENCE_DIR}/probe_cenet.py" > "${EVIDENCE_DIR}/neural_probe.out" 2>&1; then
      tail -n 10 "${EVIDENCE_DIR}/neural_probe.out" >> "${MAIN_LOG}"
      record_check "neural.probe" "PASS" "CENet mode=model on ${NEURAL_FRAMES} real frames (see neural.json; map session stayed ground_truth)"
    else
      tail -n 20 "${EVIDENCE_DIR}/neural_probe.out" >> "${MAIN_LOG}" || true
      record_check "neural.probe" "FAIL" "CENet probe error; see neural_probe.out (no neural result reported)"
    fi
  } 2>&1 | tee "${step_log}" | tee -a "${MAIN_LOG}"
}

# --------------------------------------------------------------- step 4 ---
# Packaged-desktop launch check, or honest SKIP with the build command.
step_desktop() {
  local step_log="${EVIDENCE_DIR}/step-04-desktop.log"
  {
    log "=== STEP 4/5: packaged-desktop launch check ==="
    if [ "${SKIP_DESKTOP}" = "1" ]; then
      record_check "desktop.launch" "SKIP" "--skip-desktop was passed"
      return 0
    fi

    local bundle_dir="${REPO}/src-tauri/target/release/bundle"
    local debs rpms relbin
    debs="$(printf '%s\n' "${bundle_dir}"/deb/*.deb 2>/dev/null || true)"
    rpms="$(printf '%s\n' "${bundle_dir}"/rpm/*.rpm 2>&1 || true)"
    relbin="${REPO}/src-tauri/target/release/veyra"
    {
      printf 'bundle dir: %s\n' "${bundle_dir}"
      printf 'debs:\n%s\n' "${debs}"
      printf 'rpms:\n%s\n' "${rpms}"
      printf 'release binary: %s\n' "${relbin}"
      if command -v dpkg-deb >/dev/null 2>&1; then
        for pkg in "${bundle_dir}"/deb/*.deb; do
          [ -f "${pkg}" ] || continue
          dpkg-deb --info "${pkg}" 2>&1 | head -n 8 || true
        done
      fi
    } > "${EVIDENCE_DIR}/desktop_artifacts.txt" 2>&1 || true

    local have_bundle=0
    shopt -s nullglob
    local pkg
    for pkg in "${bundle_dir}"/deb/*.deb "${bundle_dir}"/rpm/*.rpm; do
      [ -f "${pkg}" ] && have_bundle=1
    done
    shopt -u nullglob

    local build_cmd="cd apps/desktop && npm run tauri:build   # full installer bundles are built by .github/workflows/release-tauri.yml CI"
    if [ "${have_bundle}" != "1" ]; then
      record_check "desktop.launch" "SKIP" "no packaged bundle under ${bundle_dir}; build with: ${build_cmd}"
      log "SKIP: no bundle exists. To produce one: ${build_cmd}"
      return 0
    fi

    log "bundle artifacts present (see desktop_artifacts.txt)"
    if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
      if [ "${VEYRA_REHEARSAL_LAUNCH:-0}" = "1" ]; then
        log "display detected and VEYRA_REHEARSAL_LAUNCH=1: evaluator may launch the installed bundle now; recording artifact PASS"
        record_check "desktop.launch" "PASS" "bundle present + display available; manual launch by evaluator (see desktop_artifacts.txt)"
      else
        record_check "desktop.launch" "SKIP" "bundle present + display available, but auto-launch is opt-in (VEYRA_REHEARSAL_LAUNCH=1); artifacts verified only"
      fi
    else
      # Headless packaged smoke: owns the REBUILD.md §3 exit-101 assertion.
      # Display-isolated GUI binary must reach window creation and fail ONLY
      # on the absent display (tao gtk-init exit 101). Any other exit (missing
      # libs, backend errors, timeout) = FAIL. No window is ever opened here.
      local gui_bin="" gui_src=""
      if [ -x "/usr/bin/veyra" ]; then
        gui_bin="/usr/bin/veyra"
        gui_src="installed:/usr/bin/veyra"
      else
        shopt -s nullglob
        local cand
        for cand in "${bundle_dir}"/deb/*/data/usr/bin/veyra; do
          if [ -x "${cand}" ]; then gui_bin="${cand}"; gui_src="extracted:${cand}"; break; fi
        done
        shopt -u nullglob
        if [ -z "${gui_bin}" ] && [ -x "${relbin}" ]; then
          gui_bin="${relbin}"
          gui_src="release:${relbin}"
        fi
      fi
      if [ -z "${gui_bin}" ]; then
        record_check "desktop.launch" "SKIP" "bundle present but headless and no runnable GUI binary found (checked installed /usr/bin/veyra, extracted deb staging data/usr/bin/veyra, ${relbin}); launch deferred to evaluator desktop"
        log "SKIP: headless smoke has no binary to run (neither extracted nor release binary present)"
        return 0
      fi
      if ! command -v timeout >/dev/null 2>&1; then
        record_check "desktop.launch" "SKIP" "bundle present but headless and 'timeout' unavailable; cannot bound the smoke probe (binary: ${gui_src})"
        return 0
      fi
      local smoke_iso smoke_rc smoke_err
      smoke_iso="$(mktemp -d 2>/dev/null || true)"
      if [ -z "${smoke_iso}" ] || [ ! -d "${smoke_iso}" ]; then
        record_check "desktop.launch" "SKIP" "bundle present but headless and XDG_RUNTIME_DIR isolation setup failed; smoke probe refused (binary: ${gui_src})"
        return 0
      fi
      log "headless smoke: display-isolated probe of ${gui_src} (timeout -s KILL 15, empty XDG_RUNTIME_DIR; expect exit 101 gtk-init display-absent)"
      set +e
      env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
        "XDG_RUNTIME_DIR=${smoke_iso}" GDK_BACKEND=x11 \
        timeout -s KILL 15 "${gui_bin}" \
        >"${EVIDENCE_DIR}/desktop_smoke.stdout.log" 2>"${EVIDENCE_DIR}/desktop_smoke.stderr.log"
      smoke_rc=$?
      set -e
      smoke_err="$(tail -n 5 "${EVIDENCE_DIR}/desktop_smoke.stderr.log" 2>/dev/null || true)"
      {
        printf 'smoke binary: %s\n' "${gui_src}"
        printf 'isolation: env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR=<empty-tempdir> GDK_BACKEND=x11 timeout -s KILL 15\n'
        printf 'exit: %s (expect 101)\n' "${smoke_rc}"
        printf 'stderr tail:\n%s\n' "${smoke_err}"
        if command -v pgrep >/dev/null 2>&1; then
          printf 'orphan check (pgrep -x veyra):\n'
          pgrep -ax veyra 2>/dev/null || printf '(none)\n'
        fi
      } > "${EVIDENCE_DIR}/desktop_smoke.txt" 2>&1 || true
      rm -rf "${smoke_iso}" || true
      log "headless smoke exit=${smoke_rc} (see desktop_smoke.txt); stderr tail: ${smoke_err:-<empty>}"
      if [ "${smoke_rc}" = "101" ]; then
        record_check "desktop.launch" "PASS" "SMOKE headless packaged smoke: exit 101 (gtk-init display-absent, window-creation reached) via ${gui_src}; full windowed launch still deferred to evaluator desktop (see desktop_smoke.txt)"
      else
        if command -v ldd >/dev/null 2>&1; then
          ldd "${gui_bin}" 2>&1 | grep "not found" > "${EVIDENCE_DIR}/desktop_smoke.ldd-missing.txt" 2>/dev/null || : > "${EVIDENCE_DIR}/desktop_smoke.ldd-missing.txt"
        fi
        record_check "desktop.launch" "FAIL" "headless packaged smoke: exit ${smoke_rc} (expected 101 gtk-init display-absent) via ${gui_src}; see desktop_smoke.txt + desktop_smoke.stderr.log (missing libs? backend error?)"
      fi
    fi
  } 2>&1 | tee "${step_log}" | tee -a "${MAIN_LOG}"
}

# --------------------------------------------------------------- step 5 ---
step_summary() {
  local step_log="${EVIDENCE_DIR}/step-05-summary.log"
  {
    log "=== STEP 5/5: evidence summary ==="
    log "evidence dir: ${EVIDENCE_DIR}"
    ls -la "${EVIDENCE_DIR}" >> "${MAIN_LOG}"

    local name status detail
    local fails=0 total=0
    while IFS=$'\t' read -r name status detail; do
      total=$((total + 1))
      if [ "${status}" = "FAIL" ]; then fails=$((fails + 1)); fi
    done < "${CHECKLIST_TSV}" || true
    # A skipped core session outside --preflight-only means nothing was
    # exercised; that must fail loudly, never pass as PASS-or-SKIP.
    local core_skipped=0
    if [ "${PREFLIGHT_ONLY}" != "1" ] && grep -q "^headless\.session"$'\t'"SKIP" "${CHECKLIST_TSV}" 2>/dev/null; then
      core_skipped=1
    fi

    {
      printf '# Demo rehearsal summary\n\n'
      printf 'Evidence: `%s`\n\n' "${EVIDENCE_DIR}"
      printf 'Semantics: ground_truth%s\n\n' "$([ "${NEURAL}" = "1" ] && printf ' + opt-in CENet probe (%s frames)' "${NEURAL_FRAMES}" || printf ' (neural probe OFF)')"

      printf '## Checklist (%d checks, %d FAIL)\n\n' "${total}" "${fails}"
      printf '| check | status | detail |\n|---|---|---|\n'
      while IFS=$'\t' read -r name status detail; do
        printf '| `%s` | %s | %s |\n' "${name}" "${status}" "${detail}"
      done < "${CHECKLIST_TSV}" || true
      printf '\n## Key artifacts\n\n'
      for artifact in session.json telemetry.json neural.json repo_HEAD.txt dataset_counts.txt cenet_presence.txt bundle_detect.txt desktop_artifacts.txt; do
        if [ -f "${EVIDENCE_DIR}/${artifact}" ]; then
          printf -- '- `%s` present\n' "${artifact}"
        else
          printf -- '- `%s` absent\n' "${artifact}"
        fi
      done
      if [ -f "${EVIDENCE_DIR}/session.json" ] && [ -x "${PYTHON_BIN}" ]; then
        printf '\n## Policy timings (ms)\n\n```\n'
        "${PYTHON_BIN}" -c "
import json
s = json.load(open('${EVIDENCE_DIR}/session.json'))
print('configure %.1f  frames=%s' % (s.get('configure_ms', float('nan')), s.get('configured_frames')))
for st in s.get('steps', []):
    print('step frame=%s %.1f cells=%s' % (st['frame'], st['step_ms'], st['active_cells']))
for p in s.get('policies', []):
    print('%-12s switch=%8.1f step=%8.1f cells=%s' % (p['policy'], p['switch_ms'], p['step_ms'], p['active_cells']))
print('stop rc=%s reaped=%s visual_bytes_max=%s' % (s.get('stop_returncode'), s.get('reaped'), s.get('telemetry_visual_bytes_max')))
" 2>/dev/null || printf '(timing table unavailable)\n'
        printf '```\n'
      fi
    } > "${EVIDENCE_DIR}/SUMMARY.md"
    cat "${EVIDENCE_DIR}/SUMMARY.md" >> "${MAIN_LOG}"

    # Machine-readable checklist; best effort (needs any python3).
    local json_py=""
    if [ -x "${PYTHON_BIN}" ]; then json_py="${PYTHON_BIN}"
    elif command -v python3 >/dev/null 2>&1; then json_py="python3"; fi
    if [ -n "${json_py}" ]; then
      EVIDENCE_DIR="${EVIDENCE_DIR}" "${json_py}" -c "
import json, os
rows = []
with open(os.path.join(os.environ['EVIDENCE_DIR'], 'checklist.tsv'), encoding='utf-8') as f:
    for line in f:
        parts = line.rstrip('\n').split('\t')
        if len(parts) == 3:
            rows.append({'check': parts[0], 'status': parts[1], 'detail': parts[2]})
doc = {'passes': sum(1 for r in rows if r['status'] == 'PASS'),
       'fails': sum(1 for r in rows if r['status'] == 'FAIL'),
       'skips': sum(1 for r in rows if r['status'] == 'SKIP'),
       'rows': rows}
with open(os.path.join(os.environ['EVIDENCE_DIR'], 'checklist.json'), 'w', encoding='utf-8') as f:
    json.dump(doc, f, indent=2)
print('checklist.json: %d pass / %d fail / %d skip' % (doc['passes'], doc['fails'], doc['skips']))
" 2>&1 | tee -a "${MAIN_LOG}" || log "(checklist.json unavailable)"
    else
      log "(no python available for checklist.json; checklist.tsv is the record)"
    fi

    if [ "${fails}" -gt 0 ]; then
      log "RESULT: FAIL (${fails}/${total} checks failed)"
      return 1
    fi
    if [ "${core_skipped}" = "1" ]; then
      log "RESULT: FAIL (headless.session SKIPPED outside --preflight-only; nothing was exercised)"
      return 1
    fi
    log "RESULT: PASS-or-SKIP (${total} checks, 0 fail)"
    return 0
  } 2>&1 | tee "${step_log}" | tee -a "${MAIN_LOG}"
}

main() {
  log "Veyra demo rehearsal starting; evidence -> ${EVIDENCE_DIR}"
  step_preflight
  if [ "${PREFLIGHT_ONLY}" = "1" ]; then
    log "--preflight-only: stopping after step 1 (no session, no probe, no desktop check)"
    step_summary || exit "$?"
    exit 0
  fi
  step_headless
  step_neural
  step_desktop
  step_summary || exit "$?"
}

main
