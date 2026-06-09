"""SEC complete-submission SGML extraction for cached `.nc` objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .flatten import _strip_xbrl_wrapper
from .util import sha256_file, write_json


class SgmlExtractionError(ValueError):
    """Raised when a complete-submission SGML object cannot be extracted safely."""


_FORM_TYPES = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "20-F", "20-F/A", "6-K", "6-K/A"}
_XBRL_DOC_TYPES = {"EX-101.SCH", "EX-101.CAL", "EX-101.DEF", "EX-101.LAB", "EX-101.PRE", "EX-101.INS"}


@dataclass(frozen=True)
class ExtractedSgmlDocument:
    sequence: str
    document_type: str
    filename: str
    description: str
    output_path: str
    text_sha256: str
    text_bytes: int
    xbrl_wrapper_stripped: bool
    primary_candidate: bool


@dataclass(frozen=True)
class SgmlExtractionResult:
    accession: str
    filing_date: str
    form_type: str
    public_document_count: str
    primary_document: str
    documents: tuple[ExtractedSgmlDocument, ...]
    metadata_path: Path


def extract_complete_submission_sgml(
    nc_path: str | Path,
    out_dir: str | Path,
    *,
    accession: str | None = None,
    unwrap_xbrl: bool = True,
) -> SgmlExtractionResult:
    """Extract an EDGAR complete-submission SGML file into typed artifact dirs."""
    source_path = Path(nc_path)
    if not source_path.is_file():
        raise SgmlExtractionError(f"SGML source not found: {source_path}")

    output_root = Path(out_dir)
    if output_root.exists() and not output_root.is_dir():
        raise SgmlExtractionError(f"Output path exists and is not a directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    data = source_path.read_bytes()
    header, raw_documents = _parse_submission(data)
    if not raw_documents:
        raise SgmlExtractionError("SGML submission contains no DOCUMENT records")

    submission_accession = _header_value(header, "ACCESSION-NUMBER")
    if accession and submission_accession and accession != submission_accession:
        raise SgmlExtractionError(
            f"SGML accession mismatch: expected {accession}, found {submission_accession}"
        )

    seen_outputs: set[str] = set()
    extracted: list[ExtractedSgmlDocument] = []
    primary_document = ""

    for index, raw in enumerate(raw_documents, start=1):
        headers = raw["headers"]
        text = raw["text"]
        filename = _safe_filename(_header_value(headers, "FILENAME"), index)
        document_type = _normalize_document_type(_header_value(headers, "TYPE"))
        sequence = _header_value(headers, "SEQUENCE") or str(index)
        description = _header_value(headers, "DESCRIPTION")
        primary_candidate = _is_primary_candidate(document_type, filename)

        materialized = text
        stripped = False
        if unwrap_xbrl:
            materialized, stripped = _strip_xbrl_wrapper(text)

        target_dir = _target_directory(document_type, filename)
        rel_path = (target_dir / filename).as_posix()
        if rel_path in seen_outputs:
            raise SgmlExtractionError(f"Duplicate extracted output path: {rel_path}")
        seen_outputs.add(rel_path)

        dest = output_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(materialized)
        digest, byte_count = sha256_file(dest)

        if primary_candidate and not primary_document:
            if not materialized.strip():
                raise SgmlExtractionError(f"Primary document candidate is empty: {filename}")
            primary_document = rel_path

        extracted.append(
            ExtractedSgmlDocument(
                sequence=sequence,
                document_type=document_type,
                filename=filename,
                description=description,
                output_path=rel_path,
                text_sha256=digest,
                text_bytes=byte_count,
                xbrl_wrapper_stripped=stripped,
                primary_candidate=primary_candidate,
            )
        )

    if not primary_document:
        for doc in extracted:
            if Path(doc.filename).suffix.lower() in {".htm", ".html"}:
                primary_document = doc.output_path
                break
    if not primary_document:
        raise SgmlExtractionError("No primary iXBRL HTML document found in SGML submission")

    metadata_path = output_root / "_xew_sgml_extraction.json"
    metadata = {
        "schema_id": "cmdrvl.xew.sgml_extraction",
        "schema_version": "1.0",
        "source_path": str(source_path.resolve()),
        "accession": submission_accession,
        "filing_date": _header_value(header, "FILING-DATE"),
        "form_type": _header_value(header, "TYPE"),
        "public_document_count": _header_value(header, "PUBLIC-DOCUMENT-COUNT"),
        "primary_document": primary_document,
        "documents": [
            {
                "sequence": doc.sequence,
                "document_type": doc.document_type,
                "filename": doc.filename,
                "description": doc.description,
                "output_path": doc.output_path,
                "text_sha256": doc.text_sha256,
                "text_bytes": doc.text_bytes,
                "xbrl_wrapper_stripped": doc.xbrl_wrapper_stripped,
                "primary_candidate": doc.primary_candidate,
            }
            for doc in sorted(extracted, key=lambda item: (item.sequence, item.output_path))
        ],
    }
    write_json(metadata_path, metadata)

    return SgmlExtractionResult(
        accession=submission_accession,
        filing_date=_header_value(header, "FILING-DATE"),
        form_type=_header_value(header, "TYPE"),
        public_document_count=_header_value(header, "PUBLIC-DOCUMENT-COUNT"),
        primary_document=primary_document,
        documents=tuple(sorted(extracted, key=lambda item: (item.sequence, item.output_path))),
        metadata_path=metadata_path,
    )


def _parse_submission(data: bytes) -> tuple[dict[str, str], list[dict[str, object]]]:
    header: dict[str, str] = {}
    documents: list[dict[str, object]] = []
    current_headers: dict[str, str] | None = None
    current_text: list[bytes] = []
    state = "submission"

    for line in data.splitlines(keepends=True):
        line_marker = line.strip().upper()

        if state == "submission":
            if line_marker == b"<DOCUMENT>":
                current_headers = {}
                current_text = []
                state = "document_header"
                continue
            parsed = _parse_tag_line(line)
            if parsed:
                header[parsed[0]] = parsed[1]
            continue

        if state == "document_header":
            if line_marker == b"<TEXT>":
                state = "document_text"
                continue
            if line_marker == b"</DOCUMENT>":
                documents.append({"headers": current_headers or {}, "text": b""})
                current_headers = None
                state = "submission"
                continue
            parsed = _parse_tag_line(line)
            if parsed and current_headers is not None:
                current_headers[parsed[0]] = parsed[1]
            continue

        if state == "document_text":
            if line_marker == b"</TEXT>":
                state = "document_after_text"
                continue
            current_text.append(line)
            continue

        if state == "document_after_text":
            if line_marker == b"</DOCUMENT>":
                documents.append({"headers": current_headers or {}, "text": b"".join(current_text)})
                current_headers = None
                current_text = []
                state = "submission"
            continue

    if state in {"document_header", "document_text", "document_after_text"}:
        raise SgmlExtractionError("Malformed SGML submission: unterminated DOCUMENT record")

    return header, documents


def _parse_tag_line(line: bytes) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped.startswith(b"<"):
        return None
    close = stripped.find(b">")
    if close <= 1:
        return None
    tag = stripped[1:close].decode("ascii", errors="ignore").strip().upper()
    if not tag or tag.startswith("/") or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for ch in tag):
        return None
    value = stripped[close + 1 :].decode("utf-8", errors="replace").strip()
    return tag, value


def _header_value(headers: dict[str, str] | object, name: str) -> str:
    if not isinstance(headers, dict):
        return ""
    return str(headers.get(name, "")).strip()


def _safe_filename(raw: str, index: int) -> str:
    name = raw.strip()
    if not name:
        raise SgmlExtractionError(f"DOCUMENT #{index} missing FILENAME")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.name != name:
        raise SgmlExtractionError(f"Unsafe DOCUMENT filename: {raw}")
    if any(ord(ch) < 32 for ch in name):
        raise SgmlExtractionError(f"Unsafe control character in DOCUMENT filename: {raw}")
    return name


def _normalize_document_type(raw: str) -> str:
    return " ".join(raw.upper().split()) or "OTHER"


def _target_directory(document_type: str, filename: str) -> Path:
    if document_type in _FORM_TYPES:
        return Path(document_type)
    if document_type in _XBRL_DOC_TYPES:
        return Path(document_type)
    suffix = Path(filename).suffix.lower()
    if suffix == ".xsd":
        return Path("EX-101.SCH")
    if filename.lower().endswith("_cal.xml"):
        return Path("EX-101.CAL")
    if filename.lower().endswith("_def.xml"):
        return Path("EX-101.DEF")
    if filename.lower().endswith("_lab.xml"):
        return Path("EX-101.LAB")
    if filename.lower().endswith("_pre.xml"):
        return Path("EX-101.PRE")
    return Path("OTHER")


def _is_primary_candidate(document_type: str, filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return document_type in _FORM_TYPES and suffix in {".htm", ".html"} and not filename.lower().startswith("ex")
