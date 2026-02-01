from __future__ import annotations

import argparse
import re
from pathlib import Path

from .edgar_fetch import accession_base_url, collect_accession_artifacts, download_artifacts, fetch_accession_items
from .exit_codes import exit_invocation_error, exit_system_error, ExitCode

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def run_fetch(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    if out_dir.exists():
        if not out_dir.is_dir():
            exit_invocation_error(f"Output path exists and is not a directory: {out_dir}")
        if any(out_dir.iterdir()) and not args.force:
            exit_invocation_error(f"Output directory not empty (use --force to overwrite): {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    cik = _normalize_cik(args.cik)
    accession = _normalize_accession(args.accession)

    user_agent = args.user_agent.strip()
    if not user_agent:
        exit_invocation_error("--user-agent is required for EDGAR access")

    items = fetch_accession_items(cik, accession, user_agent=user_agent)
    primary, extensions = collect_accession_artifacts(items)
    base_url = accession_base_url(cik, accession)

    downloaded = download_artifacts(
        base_url,
        [primary, *extensions],
        out_dir,
        user_agent=user_agent,
        min_interval_seconds=args.min_interval,
    )

    print(f"Primary iXBRL: {primary.name}")
    print(f"Downloaded {len(downloaded)} files to {out_dir}:")
    for path in sorted(downloaded, key=lambda p: p.name):
        print(f"  {path.name}")

    return ExitCode.SUCCESS


def _normalize_cik(cik: str) -> str:
    s = cik.strip()
    if not s.isdigit():
        raise ValueError("CIK must be digits")
    if len(s) > 10:
        raise ValueError("CIK must be <= 10 digits")
    return s.zfill(10)


def _normalize_accession(accession: str) -> str:
    s = accession.strip()
    if not _ACCESSION_RE.match(s):
        raise ValueError("accession must match ^\\d{10}-\\d{2}-\\d{6}$")
    return s
