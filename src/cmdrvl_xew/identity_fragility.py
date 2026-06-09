"""Operator-facing P008 identity-fragility proof workflow."""

from __future__ import annotations

import argparse
import io
import json
import logging
from pathlib import Path
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from types import SimpleNamespace

from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .pack import run_pack
from .s3_source import run_fetch_s3
from .toolchain import detect_arelle_version
from .verify import run_verify_pack


MSFT_CASE = {
    "ticker": "MSFT",
    "issuer_name": "Microsoft Corporation",
    "cik": "0000789019",
    "accession": "0001193125-26-191507",
    "filed_date": "2026-04-29",
    "date_partition": "20260429",
    "form": "10-Q",
    "period_end": "2026-03-31",
    "primary_filename": "msft-20260331.htm",
    "primary_document_url": "https://www.sec.gov/Archives/edgar/data/789019/000119312526191507/msft-20260331.htm",
    "expected_titles": [
        "Common stock, $0.00000625 par value per share",
        "3.125% Notes due 2028",
        "2.625% Notes due 2033",
    ],
}


def run_p008_identity_fragility(args: argparse.Namespace) -> int:
    work_dir = Path(args.work_dir).resolve()
    flat_dir = work_dir / "flat"
    pack_dir = work_dir / "pack"
    taxonomy_home = Path(args.taxonomy_home).expanduser().resolve() if args.taxonomy_home else None

    plan = _build_plan(args, work_dir=work_dir, flat_dir=flat_dir, pack_dir=pack_dir, taxonomy_home=taxonomy_home)
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return ExitCode.SUCCESS

    if not taxonomy_home:
        exit_invocation_error("--taxonomy-home is required without --dry-run")

    work_dir.mkdir(parents=True, exist_ok=True)
    quiet_steps = not bool(getattr(args, "verbose", False))
    with _operator_step_output(quiet_steps):
        fetch_rc = run_fetch_s3(
            SimpleNamespace(
                s3_uri=None,
                bucket=args.bucket,
                date_partition=MSFT_CASE["date_partition"],
                accession=MSFT_CASE["accession"],
                source_layout=args.source_layout,
                aws_profile=args.aws_profile,
                out=str(flat_dir),
                force=args.force,
            )
        )
    if fetch_rc != ExitCode.SUCCESS:
        exit_processing_error(f"fetch-s3 failed with exit code {fetch_rc}")

    primary = _find_primary(flat_dir)
    pack_args = SimpleNamespace(
        pack_id=args.pack_id,
        out=str(pack_dir),
        primary=str(primary),
        issuer_name=MSFT_CASE["issuer_name"],
        cik=MSFT_CASE["cik"],
        accession=MSFT_CASE["accession"],
        form=MSFT_CASE["form"],
        filed_date=MSFT_CASE["filed_date"],
        period_end=MSFT_CASE["period_end"],
        primary_document_url=MSFT_CASE["primary_document_url"],
        comparator_accession=None,
        comparator_primary_document_url=None,
        comparator_primary_artifact_path=None,
        history_accession=None,
        history_primary_document_url=None,
        history_primary_artifact_path=None,
        retrieved_at=args.retrieved_at,
        arelle_version=None,
        resolution_mode="offline_only",
        require_arelle=True,
        no_arelle=False,
        arelle_xdg_config_home=str(taxonomy_home),
        derive_artifact_urls=False,
        p001_conflict_mode="rounded",
        p008_registry_snapshot=args.p008_registry_snapshot,
        p008_require_registry=args.p008_require_registry,
    )
    with _operator_step_output(quiet_steps):
        pack_rc = run_pack(pack_args)
    if pack_rc != ExitCode.SUCCESS:
        exit_processing_error(f"pack failed with exit code {pack_rc}")

    with _operator_step_output(quiet_steps):
        verify_rc = run_verify_pack(
            SimpleNamespace(
                pack=str(pack_dir),
                validate_schema=True,
                quiet=True,
                verbose=False,
                check_only=False,
                fail_fast=False,
            )
        )
    if verify_rc != ExitCode.SUCCESS:
        exit_processing_error(f"verify-pack failed with exit code {verify_rc}")

    summary = _summarize_p008(pack_dir, flat_dir=flat_dir, taxonomy_home=taxonomy_home)
    _assert_msft_titles(summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return ExitCode.SUCCESS


@contextmanager
def _operator_step_output(quiet: bool):
    if not quiet:
        yield
        return
    previous_disable = logging.root.manager.disable
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        logging.disable(logging.CRITICAL)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield
    finally:
        logging.disable(previous_disable)


def _build_plan(
    args: argparse.Namespace,
    *,
    work_dir: Path,
    flat_dir: Path,
    pack_dir: Path,
    taxonomy_home: Path | None,
) -> dict:
    return {
        "schema_id": "cmdrvl.xew.identity_fragility_plan",
        "schema_version": "1.0",
        "case": MSFT_CASE,
        "work_dir": str(work_dir),
        "flat_dir": str(flat_dir),
        "pack_dir": str(pack_dir),
        "taxonomy_home": str(taxonomy_home) if taxonomy_home else "",
        "no_live_sec": True,
        "no_live_openfigi": True,
        "commands": [
            [
                "cmdrvl-xew",
                "fetch-s3",
                "--bucket",
                args.bucket,
                "--date-partition",
                MSFT_CASE["date_partition"],
                "--accession",
                MSFT_CASE["accession"],
                "--source-layout",
                args.source_layout,
                "--out",
                str(flat_dir),
            ],
            [
                "cmdrvl-xew",
                "pack",
                "--pack-id",
                args.pack_id,
                "--out",
                str(pack_dir),
                "--primary",
                str(flat_dir / MSFT_CASE["primary_filename"]),
                "--require-arelle",
                "--resolution-mode",
                "offline_only",
                "--arelle-xdg-config-home",
                str(taxonomy_home) if taxonomy_home else "<taxonomy-home>",
            ],
            ["cmdrvl-xew", "verify-pack", "--pack", str(pack_dir), "--validate-schema"],
        ],
    }


def _find_primary(flat_dir: Path) -> Path:
    preferred = flat_dir / MSFT_CASE["primary_filename"]
    if preferred.is_file():
        return preferred
    candidates = sorted(path for path in flat_dir.iterdir() if path.suffix.lower() in {".htm", ".html"})
    if not candidates:
        exit_processing_error(f"No primary HTML found in flat directory: {flat_dir}")
    return candidates[0]


def _summarize_p008(pack_dir: Path, *, flat_dir: Path | None = None, taxonomy_home: Path | None = None) -> dict:
    findings_path = pack_dir / "generated" / "instrument_identity_collapse.v1.json"
    if not findings_path.is_file():
        exit_processing_error(f"P008 generated artifact missing: {findings_path}")
    data = json.loads(findings_path.read_text(encoding="utf-8"))
    groups = data.get("collapse_groups", [])
    collapsed_keys = [
        group.get("collapsed_key", {})
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("collapsed_key"), dict)
    ]
    members = []
    registry_statuses = {}
    for group in groups:
        for member in group.get("members", []):
            title = member.get("security_title", "")
            status = ((member.get("registry") or {}).get("status") or "unknown")
            registry_statuses[status] = registry_statuses.get(status, 0) + 1
            members.append(
                {
                    "security_title": title,
                    "ticker": member.get("ticker", ""),
                    "exchange": member.get("exchange", ""),
                    "canonical_signature": member.get("canonical_signature", ""),
                    "registry_status": status,
                    "figi": (((member.get("registry") or {}).get("row") or {}).get("figi") or ""),
                    "source_extraction": _member_source_extraction(member),
                }
            )
    summary = {
        "case": "MSFT 2026-04-29 10-Q",
        "accession": MSFT_CASE["accession"],
        "pack_dir": str(pack_dir),
        "arelle_version": detect_arelle_version(),
        "taxonomy_home": str(taxonomy_home) if taxonomy_home else "",
        "s3_source": _load_s3_source_summary(flat_dir) if flat_dir else {},
        "collapse_group_count": data.get("collapse_group_count", 0),
        "collapsed_keys": collapsed_keys,
        "members": sorted(members, key=lambda item: item["canonical_signature"]),
        "registry_status_counts": dict(sorted(registry_statuses.items())),
        "verify_result": "passed",
        "no_live_sec": True,
        "no_live_openfigi": True,
    }
    return summary


def _load_s3_source_summary(flat_dir: Path | None) -> dict:
    if flat_dir is None:
        return {}
    path = flat_dir / "_xew_s3_provenance.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        "source_uri": data.get("source_uri", ""),
        "selected_source_layout": data.get("selected_source_layout", ""),
        "object_count": len(data.get("objects", [])) if isinstance(data.get("objects"), list) else 0,
    }


def _member_source_extraction(member: dict) -> str:
    for fact in member.get("facts", []):
        source = fact.get("source") if isinstance(fact, dict) else None
        if isinstance(source, dict) and source.get("extraction"):
            return str(source["extraction"])
    return ""


def _assert_msft_titles(summary: dict) -> None:
    titles = {member.get("security_title", "") for member in summary.get("members", [])}
    missing = [title for title in MSFT_CASE["expected_titles"] if title not in titles]
    if missing:
        exit_processing_error(f"P008 output missing expected MSFT instrument title(s): {missing}")
