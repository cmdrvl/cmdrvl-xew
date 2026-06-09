"""S3-backed EDGAR artifact source for cached filing artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .flatten import run_flatten
from .sgml import SgmlExtractionError, extract_complete_submission_sgml
from .util import sha256_file, write_json


class S3SourceError(ValueError):
    """Raised when an S3 cached filing source cannot be resolved."""


@dataclass(frozen=True)
class S3Uri:
    bucket: str
    key: str

    @classmethod
    def parse(cls, raw: str) -> "S3Uri":
        parsed = urlparse(raw.strip())
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
            raise S3SourceError(f"Invalid S3 URI: {raw}")
        return cls(bucket=parsed.netloc, key=parsed.path.lstrip("/"))

    def as_uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class ResolvedS3Source:
    layout: str
    uri: S3Uri


def run_fetch_s3(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    if out_dir.exists():
        if not out_dir.is_dir():
            exit_invocation_error(f"Output path exists and is not a directory: {out_dir}")
        if any(out_dir.iterdir()) and not args.force:
            exit_invocation_error(f"Output directory not empty (use --force to overwrite): {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    try:
        source = resolve_s3_source(args)
    except S3SourceError as exc:
        exit_invocation_error(str(exc))

    try:
        if source.layout in {"extracted", "auto"}:
            result = _fetch_extracted_source(source, out_dir=out_dir, args=args)
        elif source.layout == "xbrl":
            result = _fetch_xbrl_source(source, out_dir=out_dir, args=args)
        else:
            exit_invocation_error(f"Unsupported S3 source layout: {source.layout}")
    except S3SourceError as exc:
        exit_processing_error(str(exc))

    print(f"S3 source layout: {result['selected_source_layout']}")
    print(f"S3 source URI: {result['source_uri']}")
    print(f"S3 provenance: {out_dir / '_xew_s3_provenance.json'}")
    return ExitCode.SUCCESS


def resolve_s3_source(args: argparse.Namespace) -> ResolvedS3Source:
    layout = (getattr(args, "source_layout", None) or "auto").strip().lower()
    if layout not in {"auto", "extracted", "xbrl"}:
        raise S3SourceError("--source-layout must be one of: extracted, xbrl, auto")

    raw_uri = (getattr(args, "s3_uri", None) or "").strip()
    if raw_uri:
        parsed = S3Uri.parse(raw_uri)
        detected = _detect_layout_from_key(parsed.key)
        if layout == "auto":
            if detected == "unknown":
                raise S3SourceError(f"Cannot infer source layout from S3 key: {parsed.key}")
            layout = detected
        elif detected != "unknown" and detected != layout:
            raise S3SourceError(f"--source-layout {layout} does not match S3 key layout {detected}")
        return ResolvedS3Source(layout=layout, uri=_normalize_uri_for_layout(parsed, layout))

    bucket = (getattr(args, "bucket", None) or "edgar-data-full").strip()
    date_partition = (getattr(args, "date_partition", None) or "").strip()
    accession = (getattr(args, "accession", None) or "").strip()
    if not date_partition or not accession:
        raise S3SourceError("Provide --s3-uri, or provide --date-partition and --accession")
    if len(date_partition) != 8 or not date_partition.isdigit():
        raise S3SourceError("--date-partition must be YYYYMMDD")

    if layout == "xbrl":
        return ResolvedS3Source(layout="xbrl", uri=S3Uri(bucket, f"xbrl/{date_partition}/{accession}.nc"))
    if layout == "extracted":
        return ResolvedS3Source(layout="extracted", uri=S3Uri(bucket, f"extracted/{date_partition}/{accession}/"))
    return ResolvedS3Source(layout="auto", uri=S3Uri(bucket, f"extracted/{date_partition}/{accession}/"))


def _detect_layout_from_key(key: str) -> str:
    normalized = key.strip("/")
    if normalized.startswith("extracted/"):
        return "extracted"
    if normalized.startswith("xbrl/") and normalized.endswith(".nc"):
        return "xbrl"
    return "unknown"


def _normalize_uri_for_layout(uri: S3Uri, layout: str) -> S3Uri:
    key = uri.key
    if layout == "extracted" and not key.endswith("/"):
        key += "/"
    return S3Uri(uri.bucket, key)


def _fetch_extracted_source(source: ResolvedS3Source, *, out_dir: Path, args: argparse.Namespace) -> dict:
    source_uri = _normalize_uri_for_layout(source.uri, "extracted")
    objects = _list_objects(source_uri.bucket, source_uri.key, aws_profile=args.aws_profile)
    if not objects:
        if source.layout == "auto":
            xbrl_uri = _xbrl_uri_from_extracted_uri(source_uri)
            _head_object_or_raise(xbrl_uri.bucket, xbrl_uri.key, aws_profile=args.aws_profile)
            return _fetch_xbrl_source(ResolvedS3Source(layout="xbrl", uri=xbrl_uri), out_dir=out_dir, args=args)
        raise S3SourceError(f"No objects found under {source_uri.as_uri()}")

    with tempfile.TemporaryDirectory(prefix="cmdrvl-xew-s3-extracted-") as tmp:
        staged = Path(tmp) / "extracted"
        _aws_cp_recursive(source_uri.as_uri(), staged, aws_profile=args.aws_profile)
        rc = run_flatten(SimpleNamespace(edgar_dir=str(staged), out=str(out_dir), force=args.force))
        if rc != ExitCode.SUCCESS:
            raise S3SourceError(f"flatten failed for {source_uri.as_uri()} with exit code {rc}")

    provenance = _write_s3_provenance(
        out_dir=out_dir,
        source_layout="extracted",
        source_uri=source_uri,
        objects=objects,
    )
    return provenance


def _fetch_xbrl_source(source: ResolvedS3Source, *, out_dir: Path, args: argparse.Namespace) -> dict:
    source_uri = source.uri
    head = _head_object_or_raise(source_uri.bucket, source_uri.key, aws_profile=args.aws_profile)

    with tempfile.TemporaryDirectory(prefix="cmdrvl-xew-s3-xbrl-") as tmp:
        tmp_path = Path(tmp)
        nc_path = tmp_path / Path(source_uri.key).name
        _aws_cp(source_uri.as_uri(), nc_path, aws_profile=args.aws_profile)
        extracted_dir = tmp_path / "sgml"
        try:
            extraction = extract_complete_submission_sgml(
                nc_path,
                extracted_dir,
                accession=getattr(args, "accession", None) or None,
            )
        except SgmlExtractionError as exc:
            raise S3SourceError(str(exc)) from exc
        rc = run_flatten(SimpleNamespace(edgar_dir=str(extracted_dir), out=str(out_dir), force=args.force))
        if rc != ExitCode.SUCCESS:
            raise S3SourceError(f"flatten failed for extracted SGML {source_uri.as_uri()} with exit code {rc}")
        extraction_metadata = _load_json_if_exists(extraction.metadata_path)

    provenance = _write_s3_provenance(
        out_dir=out_dir,
        source_layout="xbrl",
        source_uri=source_uri,
        objects=[_head_to_object(source_uri.key, head)],
        extra={"sgml_extraction": extraction_metadata},
    )
    return provenance


def _xbrl_uri_from_extracted_uri(uri: S3Uri) -> S3Uri:
    parts = uri.key.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "extracted":
        raise S3SourceError(f"Cannot derive xbrl object from extracted URI: {uri.as_uri()}")
    return S3Uri(uri.bucket, f"xbrl/{parts[1]}/{parts[2]}.nc")


def _write_s3_provenance(
    *,
    out_dir: Path,
    source_layout: str,
    source_uri: S3Uri,
    objects: list[dict],
    extra: dict | None = None,
) -> dict:
    normalized_objects = sorted(
        (
            {
                "bucket": source_uri.bucket,
                "key": str(obj.get("Key") or obj.get("key") or ""),
                "etag": _strip_etag(str(obj.get("ETag") or obj.get("etag") or "")),
                "last_modified": str(obj.get("LastModified") or obj.get("last_modified") or ""),
                "content_length": int(obj.get("Size") or obj.get("ContentLength") or obj.get("content_length") or 0),
            }
            for obj in objects
        ),
        key=lambda item: item["key"],
    )
    document = {
        "schema_id": "cmdrvl.xew.s3_artifact_source",
        "schema_version": "1.0",
        "selected_source_layout": source_layout,
        "source_uri": source_uri.as_uri(),
        "objects": normalized_objects,
    }
    if extra:
        document.update(extra)
    path = out_dir / "_xew_s3_provenance.json"
    write_json(path, document)
    sha, size = sha256_file(path)
    document["provenance_sha256"] = sha
    document["provenance_bytes"] = size
    return document


def _strip_etag(value: str) -> str:
    return value.strip().strip('"')


def _head_to_object(key: str, head: dict) -> dict:
    return {
        "Key": key,
        "ETag": head.get("ETag", ""),
        "LastModified": head.get("LastModified", ""),
        "ContentLength": head.get("ContentLength", 0),
    }


def _load_json_if_exists(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _list_objects(bucket: str, prefix: str, *, aws_profile: str | None) -> list[dict]:
    data = _aws_json(
        ["s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix],
        aws_profile=aws_profile,
    )
    contents = data.get("Contents")
    if not isinstance(contents, list):
        return []
    return [obj for obj in contents if isinstance(obj, dict) and obj.get("Key") and not str(obj.get("Key")).endswith("/")]


def _head_object_or_raise(bucket: str, key: str, *, aws_profile: str | None) -> dict:
    try:
        return _aws_json(["s3api", "head-object", "--bucket", bucket, "--key", key], aws_profile=aws_profile)
    except S3SourceError as exc:
        raise S3SourceError(f"S3 object not found or inaccessible: s3://{bucket}/{key} ({exc})") from exc


def _aws_cp(source_uri: str, dest: Path, *, aws_profile: str | None) -> None:
    _aws_run(["s3", "cp", "--only-show-errors", source_uri, str(dest)], aws_profile=aws_profile)


def _aws_cp_recursive(source_uri: str, dest: Path, *, aws_profile: str | None) -> None:
    _aws_run(["s3", "cp", "--only-show-errors", "--recursive", source_uri, str(dest)], aws_profile=aws_profile)


def _aws_json(args: list[str], *, aws_profile: str | None) -> dict:
    proc = _aws_run(args, aws_profile=aws_profile, capture=True)
    try:
        data = json.loads(proc.stdout)
    except Exception as exc:
        raise S3SourceError(f"AWS CLI returned invalid JSON for {' '.join(args)}: {exc}") from exc
    if not isinstance(data, dict):
        raise S3SourceError(f"AWS CLI returned non-object JSON for {' '.join(args)}")
    return data


def _aws_run(args: list[str], *, aws_profile: str | None, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["aws"]
    if aws_profile:
        cmd.extend(["--profile", aws_profile])
    cmd.extend(args)
    try:
        return subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=capture,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise S3SourceError("AWS CLI not found; install `aws` or use local artifact inputs") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise S3SourceError(f"AWS CLI failed ({' '.join(cmd)}){detail}") from exc
