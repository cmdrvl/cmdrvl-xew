from __future__ import annotations

import argparse
import hashlib
import mimetypes
import re
import shutil
from pathlib import Path

from . import __version__
from .util import FileHash, sha256_file, utc_now_iso, write_json

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def _compute_pack_sha256(files: list[FileHash]) -> str:
    # v1 contract: pack_sha256 is computed from manifest entries (path + sha256),
    # excluding pack_manifest.json.
    entries = [f"{f.path}\t{f.sha256}\n" for f in files]
    entries.sort(key=lambda s: s.split("\t", 1)[0])
    data = "".join(entries).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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


def run_pack(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    if out_dir.exists():
        if not out_dir.is_dir():
            raise SystemExit(f"Output path exists and is not a directory: {out_dir}")
        if any(out_dir.iterdir()):
            raise SystemExit(f"Refusing to write into non-empty directory: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (out_dir / "toolchain").mkdir(parents=True, exist_ok=True)

    retrieved_at = args.retrieved_at or utc_now_iso()
    generated_at = utc_now_iso()

    cik = _normalize_cik(args.cik)
    accession = _normalize_accession(args.accession)

    # Copy primary artifact into the pack.
    primary_src = Path(args.primary)
    if not primary_src.is_file():
        raise SystemExit(f"Primary artifact not found: {primary_src}")

    primary_dst_rel = Path("artifacts") / "primary.html"
    primary_dst = out_dir / primary_dst_rel
    shutil.copyfile(primary_src, primary_dst)

    primary_sha, primary_bytes = sha256_file(primary_dst)
    content_type, _ = mimetypes.guess_type(str(primary_dst))
    if content_type is None:
        content_type = "application/octet-stream"

    toolchain_path_rel = Path("toolchain") / "toolchain.json"
    toolchain_obj = {
        "cmdrvl_xew_version": __version__,
        "arelle_version": args.arelle_version or "unknown",
        "config": {
            "resolution_mode": args.resolution_mode,
        },
    }
    write_json(out_dir / toolchain_path_rel, toolchain_obj)

    input_obj = {
        "cik": cik,
        "accession": accession,
        "form": args.form,
        "filed_date": args.filed_date,
        "primary_document_url": args.primary_document_url,
        "primary_artifact_path": str(primary_dst_rel).replace("\\", "/"),
    }
    if args.issuer_name:
        input_obj["issuer_name"] = args.issuer_name
    if args.period_end:
        input_obj["period_end"] = args.period_end

    if args.comparator_accession:
        if not args.comparator_primary_document_url or not args.comparator_primary_artifact_path:
            raise SystemExit("Comparator requires --comparator-primary-document-url and --comparator-primary-artifact-path")
        input_obj["comparator"] = {
            "accession": _normalize_accession(args.comparator_accession),
            "primary_document_url": args.comparator_primary_document_url,
            "primary_artifact_path": args.comparator_primary_artifact_path,
        }

    findings_path_rel = Path("xew_findings.json")
    findings_obj = {
        "schema_id": "cmdrvl.xew_findings",
        "schema_version": "1.0",
        "generated_at": generated_at,
        "toolchain": {
            "cmdrvl_xew_version": __version__,
            "arelle_version": args.arelle_version or "unknown",
            "config": {
                "resolution_mode": args.resolution_mode,
            },
        },
        "input": input_obj,
        "artifacts": [
            {
                "path": str(primary_dst_rel).replace("\\", "/"),
                "role": "primary_ixbrl",
                "source_url": args.primary_document_url,
                "retrieved_at": retrieved_at,
                "sha256": primary_sha,
                "bytes": primary_bytes,
                "content_type": content_type,
            }
        ],
        "findings": [],
        "repro": {
            "command": " ".join(args._invocation_argv),
        },
    }

    write_json(out_dir / findings_path_rel, findings_obj)

    # Build pack_manifest.json for all non-manifest files.
    files: list[FileHash] = []
    for rel_path in [primary_dst_rel, toolchain_path_rel, findings_path_rel]:
        abs_path = out_dir / rel_path
        sha, nbytes = sha256_file(abs_path)
        files.append(FileHash(path=str(rel_path).replace("\\", "/"), sha256=sha, bytes=nbytes))

    pack_sha256 = _compute_pack_sha256(files)

    manifest_obj = {
        "pack_id": args.pack_id,
        "retrieved_at": retrieved_at,
        "pack_sha256": pack_sha256,
        "files": [
            {
                "path": f.path,
                "sha256": f.sha256,
                "bytes": f.bytes,
                "role": _manifest_role_for_path(f.path),
                **(_manifest_source_url_for_path(f.path, args.primary_document_url)),
            }
            for f in files
        ],
    }

    write_json(out_dir / "pack_manifest.json", manifest_obj)

    return 0


def _manifest_role_for_path(path: str) -> str:
    if path == "xew_findings.json":
        return "xew_output"
    if path == "toolchain/toolchain.json":
        return "toolchain"
    if path.startswith("artifacts/"):
        return "edgar_artifact"
    return "other"


def _manifest_source_url_for_path(path: str, primary_url: str) -> dict[str, str]:
    if path == "artifacts/primary.html":
        return {"source_url": primary_url}
    return {}
