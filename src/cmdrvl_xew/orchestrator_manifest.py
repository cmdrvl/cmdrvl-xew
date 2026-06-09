"""Normalize orchestrator filing-list responses into P008 corpus manifests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .util import utc_now_iso, write_json


class OrchestratorManifestError(ValueError):
    """Raised when orchestrator output cannot be normalized."""


def run_p008_manifest_from_orchestrator(args: argparse.Namespace) -> int:
    try:
        if args.dry_run:
            plan = {
                "schema_id": "cmdrvl.xew.orchestrator_manifest_plan",
                "schema_version": "1.0",
                "tenant": args.tenant,
                "query": args.query,
                "out": args.out,
                "will_query_orchestrator": False,
            }
            print(json.dumps(plan, indent=2, sort_keys=True))
            return ExitCode.SUCCESS

        result = manifest_from_orchestrator(
            query=args.query,
            tenant=args.tenant,
            out_path=Path(args.out),
            response_json=Path(args.response_json) if args.response_json else None,
            cmdrvl_project=Path(args.cmdrvl_project) if args.cmdrvl_project else None,
        )
    except OrchestratorManifestError as exc:
        exit_processing_error(str(exc))
    except OSError as exc:
        exit_invocation_error(str(exc))

    print(f"Wrote corpus manifest: {result['manifest_path']}")
    print(f"Rows: {result['scan_ready_count']}")
    print(f"Diagnostics: {result['diagnostics_path']}")
    return ExitCode.SUCCESS


def manifest_from_orchestrator(
    *,
    query: str,
    tenant: str,
    out_path: Path,
    response_json: Path | None,
    cmdrvl_project: Path | None,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise OrchestratorManifestError("query is required")
    tenant = tenant.strip() or "salt"

    if response_json:
        raw_text = response_json.read_text(encoding="utf-8")
        raw_payload = json.loads(raw_text)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        response_source = str(response_json.resolve())
    else:
        raw_payload, raw_text = _query_orchestrator(query, tenant=tenant, cmdrvl_project=cmdrvl_project)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        response_source = "cmdrvl-cli orchestrator query"

    content = _extract_content(raw_payload)
    rows = _extract_rows(content)
    scan_ready = []
    invalid = []
    for index, row in enumerate(rows, start=1):
        normalized = _normalize_row(row)
        missing = [key for key in ("cik", "accession", "filed_date", "form") if not normalized.get(key)]
        if missing:
            invalid.append({"row_index": index, "missing": missing, "raw": row})
            continue
        scan_ready.append(normalized)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(
        scan_ready,
        key=lambda item: (-_date_rank(item["filed_date"]), item.get("ticker", ""), item["accession"]),
    )
    if out_path.suffix.lower() == ".csv":
        _write_manifest_csv(out_path, sorted_rows)
    else:
        _write_manifest_jsonl(out_path, sorted_rows)

    diagnostics_path = out_path.with_suffix(out_path.suffix + ".diagnostics.json")
    provenance_path = out_path.with_suffix(out_path.suffix + ".provenance.json")
    diagnostics = {
        "schema_id": "cmdrvl.xew.orchestrator_manifest_diagnostics",
        "schema_version": "1.0",
        "invalid_count": len(invalid),
        "invalid_rows": invalid,
    }
    provenance = {
        "schema_id": "cmdrvl.xew.orchestrator_manifest_provenance",
        "schema_version": "1.0",
        "query": query,
        "tenant": tenant,
        "created_at": utc_now_iso(),
        "response_source": response_source,
        "raw_response_sha256": raw_hash,
        "scan_ready_count": len(scan_ready),
        "invalid_count": len(invalid),
    }
    write_json(diagnostics_path, diagnostics)
    write_json(provenance_path, provenance)
    return {
        "manifest_path": str(out_path),
        "diagnostics_path": str(diagnostics_path),
        "provenance_path": str(provenance_path),
        "scan_ready_count": len(scan_ready),
        "invalid_count": len(invalid),
    }


def _query_orchestrator(query: str, *, tenant: str, cmdrvl_project: Path | None) -> tuple[dict[str, Any], str]:
    project = cmdrvl_project or Path("/Users/zac/Source/cmdrvl/cmdrvl-cli")
    cmd = [
        "uv",
        "run",
        "--project",
        str(project),
        "cmdrvl",
        "--json",
        "orchestrator",
        "query",
        "--tenant",
        tenant,
        query,
    ]
    try:
        proc = subprocess.run(cmd, check=True, text=True, capture_output=True, timeout=120)
    except FileNotFoundError as exc:
        raise OrchestratorManifestError("uv command not found; cannot query orchestrator") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise OrchestratorManifestError(f"orchestrator query failed{detail}") from exc
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:
        raise OrchestratorManifestError(f"orchestrator returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OrchestratorManifestError("orchestrator returned non-object JSON")
    return payload, proc.stdout


def _extract_content(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        content = payload["data"].get("content")
        if isinstance(content, str):
            stripped = content.strip()
            try:
                return json.loads(stripped)
            except Exception:
                return stripped
        if content is not None:
            return content
    return payload


def _extract_rows(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [row for row in content if isinstance(row, dict)]
    if isinstance(content, dict):
        for key in ("filings", "rows", "data", "results"):
            value = content.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [content]
    raise OrchestratorManifestError("orchestrator content does not contain structured filing rows")


def _normalize_row(row: dict[str, Any]) -> dict[str, str]:
    lower = {str(k).lower(): v for k, v in row.items()}
    filed_date = _normalize_date(str(lower.get("filed_date", lower.get("filing_date", lower.get("date", ""))).strip()))
    accession = _normalize_accession(str(lower.get("accession", lower.get("accession_number", ""))).strip())
    return {
        "ticker": str(lower.get("ticker", "")).strip(),
        "issuer_name": str(lower.get("issuer_name", lower.get("issuer", lower.get("company", "")))).strip(),
        "cik": str(lower.get("cik", "")).strip().zfill(10) if str(lower.get("cik", "")).strip().isdigit() else str(lower.get("cik", "")).strip(),
        "accession": accession,
        "filed_date": filed_date,
        "date_partition": filed_date.replace("-", "") if _date_rank(filed_date) else "",
        "form": str(lower.get("form", lower.get("form_type", ""))).strip().upper(),
        "source_layout": str(lower.get("source_layout", "auto") or "auto").strip(),
        "primary_document_url": str(lower.get("primary_document_url", "")).strip(),
    }


def _write_manifest_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def _write_manifest_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "ticker",
        "issuer_name",
        "cik",
        "accession",
        "filed_date",
        "date_partition",
        "form",
        "source_layout",
        "primary_document_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _normalize_accession(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 18:
        return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"
    return value


def _normalize_date(value: str) -> str:
    stripped = value.strip()
    digits = stripped.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return stripped


def _date_rank(value: str) -> int:
    digits = value.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return int(digits)
    return 0
