#!/usr/bin/env bash
# Fetch official, user-authorized SemanticKITTI archives without committing data.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  datasets/download_semantickitti.sh --root data/raw/semantickitti \
    --data-url <official-velodyne-archive-url> \
    --labels-url <official-label-archive-url> \
    [--data-sha256 <sha256>] [--labels-sha256 <sha256>]

  # Labels-only validation subset (no login required):
  datasets/download_semantickitti.sh --root data/raw/semantickitti \
    --labels-only --labels-url https://www.semantic-kitti.org/assets/data_odometry_labels.zip

Obtain archive URLs from the authenticated official SemanticKITTI download
portal. The script does not embed credentials, guess URLs, or download model
weights. It refuses to merge into an existing dataset root.

Provenance notes (verified 2026-09-17):
- `data_odometry_labels.zip` (179298418 bytes) is publicly downloadable from
  semantic-kitti.org and contains `dataset/sequences/00-10` labels plus the
  SuMa `poses.txt` per sequence (sequence 08: 4071 labels + 4071 poses).
- Velodyne scans (`data_odometry_velodyne.zip`, 80 GB), calibration
  (`data_odometry_calib.zip`), and `times.txt` require a KITTI benchmark
  login: `download.php` returns an email-gated form without credentials, so
  full scan/label/timestamp replay stays blocked until the operator provides
  authenticated archive URLs via --data-url.
- `--labels-only` installs the public labels + poses subset for taxonomy and
  pose-sequence validation; adapter scan replay still skips until scans land.
EOF
}

root=""
data_url=""
labels_url=""
data_sha256=""
labels_sha256=""
labels_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --data-url) data_url="$2"; shift 2 ;;
    --labels-url) labels_url="$2"; shift 2 ;;
    --data-sha256) data_sha256="$2"; shift 2 ;;
    --labels-sha256) labels_sha256="$2"; shift 2 ;;
    --labels-only) labels_only=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$root" || -z "$labels_url" ]]; then
  usage >&2
  exit 2
fi
if [[ "$labels_only" -eq 0 && -z "$data_url" ]]; then
  usage >&2
  exit 2
fi
if [[ -e "$root" ]]; then
  echo "Refusing to overwrite existing path: $root" >&2
  exit 1
fi

workdir="$(mktemp -d)"
cleanup() { rm -rf "$workdir"; }
trap cleanup EXIT

fetch_and_verify() {
  local url="$1" archive="$2" expected_sha="$3"
  curl --fail --location --retry 3 --output "$archive" "$url"
  unzip -tq "$archive" >/dev/null
  if [[ -n "$expected_sha" ]]; then
    printf '%s  %s\n' "$expected_sha" "$archive" | sha256sum --check --status
  fi
}

fetch_and_verify "$labels_url" "$workdir/labels.zip" "$labels_sha256"
mkdir "$workdir/extracted"
if [[ "$labels_only" -eq 0 ]]; then
  fetch_and_verify "$data_url" "$workdir/data.zip" "$data_sha256"
  unzip -q "$workdir/data.zip" -d "$workdir/extracted"
fi
unzip -q "$workdir/labels.zip" -d "$workdir/extracted"
if [[ ! -d "$workdir/extracted/dataset/sequences" ]]; then
  echo "Official archives did not produce dataset/sequences; refusing install" >&2
  exit 1
fi
mkdir -p "$(dirname "$root")"
mv "$workdir/extracted" "$root"
echo "Installed SemanticKITTI under $root/dataset (local-only; git ignores data/)."
