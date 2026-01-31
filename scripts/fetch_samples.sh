#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Fetch representative EDGAR extracted filings into a local sample folder.

Usage:
  scripts/fetch_samples.sh [--profile NAME] [--bucket NAME] [--out DIR]

Defaults:
  --profile  edgar-readonly (or AWS_PROFILE if set)
  --bucket   edgar-data-full
  --out      sample
EOF
}

profile="${AWS_PROFILE:-edgar-readonly}"
bucket="edgar-data-full"
out_dir="sample"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      profile="$2"
      shift 2
      ;;
    --bucket)
      bucket="$2"
      shift 2
      ;;
    --out)
      out_dir="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found; install AWS CLI first." >&2
  exit 1
fi

export AWS_PROFILE="$profile"

mkdir -p "$out_dir"

samples=(
  "20251031/0000034903-25-000063" # 10-Q
  "20250324/0001140361-25-010025" # 10-K
  "20251106/0000036104-25-000066" # 8-K (includes DEF linkbase)
)

for entry in "${samples[@]}"; do
  accession="${entry#*/}"
  prefix="s3://${bucket}/extracted/${entry}/"
  dest="${out_dir}/${accession}"
  echo "Fetching ${prefix} -> ${dest}"
  aws s3 cp "${prefix}" "${dest}" --recursive
done
