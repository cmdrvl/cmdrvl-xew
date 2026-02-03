#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Fetch representative EDGAR filings into a local sample folder (local-only).

Usage:
  scripts/fetch_samples.sh --user-agent UA [--out DIR] [--min-interval SECONDS] [--force] [--cmd PATH]

Notes:
  - This script downloads from SEC EDGAR using `cmdrvl-xew fetch`.
  - A SEC-compliant User-Agent is required (include contact email).

Environment:
  XEW_USER_AGENT  Default User-Agent (if --user-agent not provided)
EOF
}

out_dir="sample"
user_agent="${XEW_USER_AGENT:-}"
min_interval="0.2"
force="false"
cmd="cmdrvl-xew"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user-agent)
      user_agent="$2"
      shift 2
      ;;
    --out)
      out_dir="$2"
      shift 2
      ;;
    --min-interval)
      min_interval="$2"
      shift 2
      ;;
    --force)
      force="true"
      shift
      ;;
    --cmd)
      cmd="$2"
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

if [[ -z "${user_agent}" ]]; then
  echo "Error: --user-agent is required (or set XEW_USER_AGENT)." >&2
  usage >&2
  exit 1
fi

if ! command -v "${cmd}" >/dev/null 2>&1; then
  echo "Error: cmdrvl-xew not found (${cmd}). Install the package or pass --cmd." >&2
  exit 1
fi

mkdir -p "$out_dir"

samples=(
  "0000034903 0000034903-25-000063" # 10-Q
  "0001140361 0001140361-25-010025" # 10-K
  "0000036104 0000036104-25-000066" # 8-K
)

force_flag=()
if [[ "${force}" == "true" ]]; then
  force_flag+=(--force)
fi

for entry in "${samples[@]}"; do
  read -r cik accession <<<"${entry}"
  dest="${out_dir}/${accession}"
  echo "Fetching CIK=${cik} accession=${accession} -> ${dest}"
  "${cmd}" fetch \
    --cik "${cik}" \
    --accession "${accession}" \
    --out "${dest}" \
    --user-agent "${user_agent}" \
    --min-interval "${min_interval}" \
    "${force_flag[@]}"
done
