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

Obtain archive URLs from the authenticated official SemanticKITTI download
portal. The script does not embed credentials, guess URLs, or download model
weights. It refuses to merge into an existing dataset root.
EOF
}

root=""
data_url=""
labels_url=""
data_sha256=""
labels_sha256=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --data-url) data_url="$2"; shift 2 ;;
    --labels-url) labels_url="$2"; shift 2 ;;
    --data-sha256) data_sha256="$2"; shift 2 ;;
    --labels-sha256) labels_sha256="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$root" || -z "$data_url" || -z "$labels_url" ]]; then
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

fetch_and_verify "$data_url" "$workdir/data.zip" "$data_sha256"
fetch_and_verify "$labels_url" "$workdir/labels.zip" "$labels_sha256"
mkdir "$workdir/extracted"
unzip -q "$workdir/data.zip" -d "$workdir/extracted"
unzip -q "$workdir/labels.zip" -d "$workdir/extracted"
if [[ ! -d "$workdir/extracted/dataset/sequences" ]]; then
  echo "Official archives did not produce dataset/sequences; refusing install" >&2
  exit 1
fi
mkdir -p "$(dirname "$root")"
mv "$workdir/extracted" "$root"
echo "Installed SemanticKITTI under $root/dataset (local-only; git ignores data/)."
