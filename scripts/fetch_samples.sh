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
  "20250324/0001140361-25-010025" # 10-K (local alias: 0000020639-25-010025)
  "20251106/0000036104-25-000066" # 8-K (includes DEF linkbase)
)

extract_dei_cik() {
  local primary_file="$1"
  python3 - "$primary_file" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="ignore")
m = re.search(r"dei:EntityCentralIndexKey[^>]*>([^<]+)<", text)
value = (m.group(1).strip() if m else "")
digits = "".join(ch for ch in value if ch.isdigit())
if digits:
    print(digits.zfill(10))
PY
}

find_primary_ixbrl() {
  local dest_dir="$1"
  local primary=""
  local form_dir=""
  for form_dir in "10-Q" "10-K" "8-K" "20-F" "6-K"; do
    if [[ -d "${dest_dir}/${form_dir}" ]]; then
      primary="$(ls -1 "${dest_dir}/${form_dir}"/*.htm "${dest_dir}/${form_dir}"/*.html 2>/dev/null | head -n 1 || true)"
      if [[ -n "${primary}" ]]; then
        echo "${primary}"
        return 0
      fi
    fi
  done
  return 1
}

for entry in "${samples[@]}"; do
  accession="${entry#*/}"
  prefix="s3://${bucket}/extracted/${entry}/"
  dest="${out_dir}/${accession}"
  echo "Fetching ${prefix} -> ${dest}"
  aws s3 cp "${prefix}" "${dest}" --recursive

  primary_ixbrl="$(find_primary_ixbrl "${dest}" || true)"
  if [[ -n "${primary_ixbrl}" ]]; then
    dei_cik="$(extract_dei_cik "${primary_ixbrl}")"
    if [[ -n "${dei_cik}" ]]; then
      folder_cik="${accession:0:10}"
      suffix="${accession:10}"
      if [[ "${dei_cik}" != "${folder_cik}" ]]; then
        alias_accession="${dei_cik}${suffix}"
        alias_dest="${out_dir}/${alias_accession}"
        if [[ -e "${alias_dest}" ]]; then
          echo "Alias already exists: ${alias_dest}"
        else
          echo "Creating alias ${alias_dest} (DEI CIK ${dei_cik}, original ${accession})"
          cp -a "${dest}" "${alias_dest}"
        fi
      fi
    fi
  fi
done
