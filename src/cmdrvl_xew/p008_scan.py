"""Deterministic P008 corpus scanner and ranking."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .exit_codes import ExitCode, exit_processing_error
from .identity_fragility import _member_source_extraction
from .pack import run_pack
from .s3_source import run_fetch_s3
from .util import write_json


@dataclass(frozen=True)
class CorpusRow:
    index: int
    cik: str
    accession: str
    filed_date: str
    form: str
    ticker: str = ""
    issuer_name: str = ""
    source_layout: str = "auto"
    primary_document_url: str = ""
    pack_path: str = ""


def run_p008_scan_corpus(args: argparse.Namespace) -> int:
    try:
        results = scan_p008_corpus(
            manifest_path=Path(args.manifest),
            out_dir=Path(args.out_dir),
            run_packs=args.run_packs,
            aws_profile=args.aws_profile,
            bucket=args.bucket,
            taxonomy_home=args.taxonomy_home,
            p008_registry_snapshot=args.p008_registry_snapshot,
            max_filings=args.max_filings,
            keep_packs=args.keep_packs,
            continue_on_error=args.continue_on_error,
            fail_fast=args.fail_fast,
        )
    except (OSError, ValueError) as exc:
        exit_processing_error(str(exc))

    print(f"Wrote P008 corpus scan: {results['jsonl_path']}")
    print(f"Rows: {len(results['rows'])}")
    return ExitCode.SUCCESS


def scan_p008_corpus(
    *,
    manifest_path: Path,
    out_dir: Path,
    run_packs: bool,
    aws_profile: str | None,
    bucket: str,
    taxonomy_home: str | None,
    p008_registry_snapshot: str | None,
    max_filings: int | None,
    keep_packs: bool,
    continue_on_error: bool,
    fail_fast: bool,
) -> dict[str, Any]:
    rows = read_corpus_manifest(manifest_path)
    if max_filings:
        rows = rows[:max_filings]
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            if row.pack_path:
                result = summarize_pack(row, Path(row.pack_path))
            elif run_packs:
                if not taxonomy_home:
                    raise ValueError("--taxonomy-home is required with --run-packs")
                pack_path = _run_row_pack(
                    row,
                    out_dir=out_dir,
                    aws_profile=aws_profile,
                    bucket=bucket,
                    taxonomy_home=taxonomy_home,
                    p008_registry_snapshot=p008_registry_snapshot,
                    keep_packs=keep_packs,
                )
                result = summarize_pack(row, pack_path)
            else:
                result = _skip_row(row, "missing pack_path and --run-packs not set")
        except Exception as exc:
            if fail_fast:
                raise
            result = _error_row(row, str(exc))
            if not continue_on_error:
                results.append(result)
                break
        results.append(result)

    ranked = rank_scan_results(results)
    jsonl_path = out_dir / "p008_scan_results.jsonl"
    csv_path = out_dir / "p008_scan_results.csv"
    _write_jsonl(jsonl_path, ranked)
    _write_csv(csv_path, ranked)
    return {"jsonl_path": str(jsonl_path), "csv_path": str(csv_path), "rows": ranked}


def read_corpus_manifest(path: Path) -> list[CorpusRow]:
    raw_rows = _read_rows(path)
    rows: list[CorpusRow] = []
    for index, row in enumerate(raw_rows, start=1):
        accession = str(row.get("accession", "")).strip()
        cik = str(row.get("cik", "")).strip()
        filed_date = str(row.get("filed_date", row.get("filing_date", ""))).strip()
        form = str(row.get("form", "")).strip().upper()
        if not (accession and cik and filed_date and form):
            rows.append(
                CorpusRow(
                    index=index,
                    cik=cik,
                    accession=accession,
                    filed_date=filed_date,
                    form=form,
                    ticker=str(row.get("ticker", "")).strip(),
                    issuer_name=str(row.get("issuer_name", row.get("issuer", ""))).strip(),
                    source_layout=str(row.get("source_layout", "auto") or "auto").strip(),
                    primary_document_url=str(row.get("primary_document_url", "")).strip(),
                    pack_path=str(row.get("pack_path", "")).strip(),
                )
            )
            continue
        rows.append(
            CorpusRow(
                index=index,
                cik=cik,
                accession=accession,
                filed_date=filed_date,
                form=form,
                ticker=str(row.get("ticker", "")).strip(),
                issuer_name=str(row.get("issuer_name", row.get("issuer", ""))).strip(),
                source_layout=str(row.get("source_layout", "auto") or "auto").strip(),
                primary_document_url=str(row.get("primary_document_url", "")).strip(),
                pack_path=str(row.get("pack_path", "")).strip(),
            )
        )
    return rows


def summarize_pack(row: CorpusRow, pack_path: Path) -> dict[str, Any]:
    generated = pack_path / "generated" / "instrument_identity_collapse.v1.json"
    if not generated.is_file():
        return _skip_row(row, f"P008 generated artifact missing: {generated}")
    data = json.loads(generated.read_text(encoding="utf-8"))
    groups = data.get("collapse_groups", [])
    member_titles: list[str] = []
    registry_status_counts: dict[str, int] = {}
    instrument_kinds: set[str] = set()
    max_member_count = 0
    source_extractions: set[str] = set()
    for group in groups:
        members = group.get("members", []) if isinstance(group, dict) else []
        max_member_count = max(max_member_count, len(members))
        for member in members:
            if not isinstance(member, dict):
                continue
            title = str(member.get("security_title", ""))
            if title:
                member_titles.append(title)
            kind = str(member.get("instrument_kind", ""))
            if kind:
                instrument_kinds.add(kind)
            status = str((member.get("registry") or {}).get("status") or "unknown")
            registry_status_counts[status] = registry_status_counts.get(status, 0) + 1
            extraction = _member_source_extraction(member)
            if extraction:
                source_extractions.add(extraction)
    resolved_or_ambiguous = sum(
        count for status, count in registry_status_counts.items()
        if status in {"resolved", "ambiguous"}
    )
    return {
        "status": "scanned",
        "row_index": row.index,
        "ticker": row.ticker,
        "issuer_name": row.issuer_name,
        "cik": row.cik,
        "accession": row.accession,
        "form": row.form,
        "filed_date": row.filed_date,
        "p008_finding_count": len(groups),
        "collapse_group_count": int(data.get("collapse_group_count", len(groups))),
        "max_member_count": max_member_count,
        "resolved_or_ambiguous_member_count": resolved_or_ambiguous,
        "distinct_instrument_kind_count": len(instrument_kinds),
        "member_titles": sorted(set(member_titles)),
        "registry_status_counts": dict(sorted(registry_status_counts.items())),
        "source_extraction": ",".join(sorted(source_extractions)),
        "source_layout": row.source_layout,
        "pack_path": str(pack_path),
        "error": "",
    }


def rank_scan_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda item: (
            0 if item.get("status") == "scanned" else 1,
            -int(item.get("resolved_or_ambiguous_member_count", 0)),
            -int(item.get("max_member_count", 0)),
            -int(item.get("distinct_instrument_kind_count", 0)),
            -_date_rank(str(item.get("filed_date", ""))),
            str(item.get("accession", "")),
        ),
    )


def _date_rank(value: str) -> int:
    digits = value.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return int(digits)
    return 0


def _run_row_pack(
    row: CorpusRow,
    *,
    out_dir: Path,
    aws_profile: str | None,
    bucket: str,
    taxonomy_home: str,
    p008_registry_snapshot: str | None,
    keep_packs: bool,
) -> Path:
    row_dir = out_dir / row.accession
    flat_dir = row_dir / "flat"
    pack_dir = row_dir / "pack"
    date_partition = row.filed_date.replace("-", "")
    fetch_rc = run_fetch_s3(
        SimpleNamespace(
            s3_uri=None,
            bucket=bucket,
            date_partition=date_partition,
            accession=row.accession,
            source_layout=row.source_layout or "auto",
            aws_profile=aws_profile,
            out=str(flat_dir),
            force=False,
        )
    )
    if fetch_rc != ExitCode.SUCCESS:
        raise ValueError(f"fetch-s3 failed with exit code {fetch_rc}")
    primary = _find_primary(flat_dir)
    pack_rc = run_pack(
        SimpleNamespace(
            pack_id=f"XEW-P008-{row.accession}",
            out=str(pack_dir),
            primary=str(primary),
            issuer_name=row.issuer_name,
            cik=row.cik,
            accession=row.accession,
            form=row.form,
            filed_date=row.filed_date,
            period_end=None,
            primary_document_url=row.primary_document_url or "https://www.sec.gov/",
            comparator_accession=None,
            comparator_primary_document_url=None,
            comparator_primary_artifact_path=None,
            history_accession=None,
            history_primary_document_url=None,
            history_primary_artifact_path=None,
            retrieved_at=None,
            arelle_version=None,
            resolution_mode="offline_only",
            require_arelle=True,
            no_arelle=False,
            arelle_xdg_config_home=taxonomy_home,
            derive_artifact_urls=False,
            p001_conflict_mode="rounded",
            p008_registry_snapshot=p008_registry_snapshot,
            p008_require_registry=bool(p008_registry_snapshot),
        )
    )
    if pack_rc != ExitCode.SUCCESS:
        raise ValueError(f"pack failed with exit code {pack_rc}")
    if not keep_packs:
        marker = row_dir / "PACK_RETAINED_BY_OPERATOR_FLAG"
        write_json(marker, {"pack_path": str(pack_dir), "note": "Pack generated; caller may remove work directory if desired."})
    return pack_dir


def _find_primary(flat_dir: Path) -> Path:
    candidates = sorted(path for path in flat_dir.iterdir() if path.suffix.lower() in {".htm", ".html"})
    if not candidates:
        raise ValueError(f"No primary HTML found in {flat_dir}")
    return candidates[0]


def _skip_row(row: CorpusRow, reason: str) -> dict[str, Any]:
    base = _base_row(row)
    base.update({"status": "skipped", "error": reason})
    return base


def _error_row(row: CorpusRow, reason: str) -> dict[str, Any]:
    base = _base_row(row)
    base.update({"status": "error", "error": reason})
    return base


def _base_row(row: CorpusRow) -> dict[str, Any]:
    return {
        "row_index": row.index,
        "ticker": row.ticker,
        "issuer_name": row.issuer_name,
        "cik": row.cik,
        "accession": row.accession,
        "form": row.form,
        "filed_date": row.filed_date,
        "p008_finding_count": 0,
        "collapse_group_count": 0,
        "max_member_count": 0,
        "resolved_or_ambiguous_member_count": 0,
        "distinct_instrument_kind_count": 0,
        "member_titles": [],
        "registry_status_counts": {},
        "source_extraction": "",
        "source_layout": row.source_layout,
        "pack_path": row.pack_path,
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "status",
        "ticker",
        "issuer_name",
        "cik",
        "accession",
        "form",
        "filed_date",
        "p008_finding_count",
        "collapse_group_count",
        "max_member_count",
        "resolved_or_ambiguous_member_count",
        "distinct_instrument_kind_count",
        "source_extraction",
        "source_layout",
        "pack_path",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
