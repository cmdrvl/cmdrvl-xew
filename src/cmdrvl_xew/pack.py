from __future__ import annotations

import argparse
import hashlib
import mimetypes
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .artifacts import ArtifactCollectionError, ArtifactHash, collect_artifacts
from . import __version__
from .taxonomy import NonRedistributableReference, non_redistributable_reference_from_path
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

    # Collect and copy artifacts into the pack.
    primary_src = Path(args.primary).resolve()
    if not primary_src.is_file():
        raise SystemExit(f"Primary artifact not found: {primary_src}")

    root_dir = primary_src.parent
    try:
        collected = collect_artifacts(primary_src, root_dir=root_dir)
    except ArtifactCollectionError as e:
        raise SystemExit(str(e))

    primary_dst_rel = Path("artifacts") / "primary.html"
    pack_artifacts: list[ArtifactHash] = []
    non_redistributable_refs: list[NonRedistributableReference] = []
    seen_paths: set[str] = set()
    source_url_map = _build_source_url_map(
        collected,
        primary_document_url=args.primary_document_url,
        primary_pack_path=primary_dst_rel.as_posix(),
    )

    for artifact in collected:
        src_path = root_dir / artifact.path
        source_url = source_url_map.get(f"artifacts/{artifact.path}")

        # Check if this artifact should be treated as non-redistributable
        if _is_non_redistributable_artifact(str(src_path), source_url):
            # Create non-redistributable reference instead of copying
            non_redistributable_ref = _create_non_redistributable_reference(
                artifact, source_url or "", root_dir
            )
            non_redistributable_refs.append(non_redistributable_ref)
            continue

        # Standard artifact processing (copy to pack)
        if artifact.role == "primary_ixbrl":
            dest_rel = primary_dst_rel
        else:
            dest_rel = Path("artifacts") / artifact.path
        dest_rel_str = dest_rel.as_posix()
        if dest_rel_str in seen_paths:
            raise SystemExit(f"Artifact path collision in pack: {dest_rel_str}")
        seen_paths.add(dest_rel_str)

        dest_abs = out_dir / dest_rel
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_abs)

        pack_artifacts.append(
            ArtifactHash(
                path=dest_rel_str,
                role=artifact.role,
                sha256=artifact.sha256,
                bytes=artifact.bytes,
            )
        )

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
    findings_artifacts: list[dict[str, object]] = []
    for artifact in sorted(pack_artifacts, key=lambda a: a.path):
        content_type, _ = mimetypes.guess_type(artifact.path)
        if content_type is None:
            content_type = "application/octet-stream"
        entry: dict[str, object] = {
            "path": artifact.path,
            "role": artifact.role,
            "retrieved_at": retrieved_at,
            "sha256": artifact.sha256,
            "bytes": artifact.bytes,
            "content_type": content_type,
        }
        source_url = source_url_map.get(artifact.path)
        if source_url:
            entry["source_url"] = source_url
        findings_artifacts.append(entry)

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
        "artifacts": findings_artifacts,
        "findings": [],
        "repro": {
            "command": " ".join(args._invocation_argv),
        },
    }

    # Add non-redistributable references if any exist
    if non_redistributable_refs:
        findings_obj["ext"] = {
            "non_redistributable_references": [ref.to_metadata() for ref in non_redistributable_refs]
        }

    write_json(out_dir / findings_path_rel, findings_obj)

    # Build pack_manifest.json for all non-manifest files.
    files: list[FileHash] = []
    for artifact in pack_artifacts:
        abs_path = out_dir / artifact.path
        sha, nbytes = sha256_file(abs_path)
        files.append(FileHash(path=artifact.path, sha256=sha, bytes=nbytes))
    for rel_path in [toolchain_path_rel, findings_path_rel]:
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
                **(_manifest_source_url_for_path(f.path, source_url_map)),
            }
            for f in sorted(files, key=lambda item: item.path)
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


def _manifest_source_url_for_path(path: str, source_url_map: dict[str, str]) -> dict[str, str]:
    source_url = source_url_map.get(path)
    if source_url:
        return {"source_url": source_url}
    return {}


def _build_source_url_map(
    artifacts: list[ArtifactHash],
    *,
    primary_document_url: str,
    primary_pack_path: str,
) -> dict[str, str]:
    base_url = _derive_base_url(primary_document_url)
    source_url_map: dict[str, str] = {}

    for artifact in artifacts:
        if artifact.role == "primary_ixbrl":
            source_url_map[primary_pack_path] = primary_document_url
            continue
        if base_url:
            rel = artifact.path.lstrip("/")
            source_url_map[f"artifacts/{rel}"] = urljoin(base_url, rel)

    return source_url_map


def _is_non_redistributable_artifact(artifact_path: str, source_url: str = None) -> bool:
    """
    Determine if an artifact should be treated as non-redistributable.

    Args:
        artifact_path: Local path to the artifact
        source_url: Optional source URL for the artifact

    Returns:
        True if the artifact cannot be redistributed in Evidence Packs
    """
    # Check for external taxonomy references that may have licensing restrictions
    if source_url:
        parsed = urlparse(source_url)

        # SEC taxonomy packages are typically redistributable, but other sources may not be
        if parsed.netloc and parsed.netloc not in ['www.sec.gov', 'xbrl.sec.gov', 'xbrl.fasb.org']:
            # External non-government source - may be non-redistributable
            return True

        # Large taxonomy packages might exceed pack size limits
        try:
            path = Path(artifact_path)
            if path.exists() and path.stat().st_size > 10 * 1024 * 1024:  # 10MB limit
                return True
        except (OSError, ValueError):
            pass

    # Check file extension patterns that are commonly non-redistributable
    if artifact_path.endswith(('.zip', '.tar.gz', '.7z')):
        # Large compressed packages are often non-redistributable
        return True

    return False


def _create_non_redistributable_reference(artifact: ArtifactHash, source_url: str,
                                        root_dir: Path) -> NonRedistributableReference:
    """Create a non-redistributable reference for an artifact."""
    artifact_path = root_dir / artifact.path

    # Determine content type
    content_type, _ = mimetypes.guess_type(artifact.path)
    if content_type is None:
        content_type = "application/octet-stream"

    return non_redistributable_reference_from_path(
        source_url=source_url,
        path=artifact_path,
        content_type=content_type,
        notes=f"Artifact {artifact.path} cannot be redistributed due to legal/licensing constraints"
    )


def _derive_base_url(primary_url: str) -> str | None:
    parsed = urlparse(primary_url)
    if not parsed.scheme:
        return None
    if parsed.scheme != "file" and not parsed.netloc:
        return None
    if not parsed.path:
        return None

    base_path = parsed.path
    if not base_path.endswith("/"):
        base_path = f"{base_path.rsplit('/', 1)[0]}/"

    return parsed._replace(path=base_path, query="", fragment="").geturl()
