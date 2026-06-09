"""Provider-neutral P009 corpus input contract.

This module validates local corpus manifests and normalized observation files
without knowing any upstream warehouse, orchestrator, SEC, canon, or provider
data model. It is intentionally limited to local files and opaque provenance.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .instrument_identity import normalize_identifier, normalize_key_token, normalize_text
from .p009_observations import (
    P009InstrumentObservation,
    P009ObservationDiagnostic,
    load_p009_observations as load_p009_observation_rows,
)
from .util import sha256_file


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_RECORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#=+\-@]{0,255}$")
_SCHEMA_VERSIONS = {"", "1.0", "p009_corpus_manifest.v1", "p009_corpus_manifest.v1.jsonl"}
_SUPPORTED_SOURCE_FAMILIES = {
    "csv",
    "external",
    "external_observation",
    "ixbrl",
    "jsonl",
    "local_export",
    "sec_filing",
    "test_fixture",
    "xml",
}


@dataclass(frozen=True)
class P009CorpusDiagnostic:
    """Deterministic diagnostic for P009 corpus inputs."""

    code: str
    message: str
    row_number: int | None = None
    field: str = ""
    source_path: str = ""
    value: str = ""

    @property
    def diagnostic_id(self) -> str:
        payload = json.dumps(self.to_json(include_id=False), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @property
    def sort_key(self) -> tuple[str, str, int, str, str, str]:
        return (
            self.code,
            self.source_path,
            self.row_number or 0,
            self.field,
            self.value,
            self.message,
        )

    def to_json(self, *, include_id: bool = True) -> dict[str, object]:
        data: dict[str, object] = {"code": self.code, "message": self.message}
        if include_id:
            data["diagnostic_id"] = self.diagnostic_id
        if self.row_number is not None:
            data["row_number"] = self.row_number
        if self.field:
            data["field"] = self.field
        if self.source_path:
            data["source_path"] = self.source_path
        if self.value:
            data["value"] = self.value
        return data


@dataclass(frozen=True)
class P009CorpusSource:
    """One provider-neutral source artifact row from a P009 corpus manifest."""

    row_number: int
    source_family: str
    scope_key: str
    source_adapter: str = ""
    accession: str = ""
    source_record_id: str = ""
    filed_date: str = ""
    form: str = ""
    report_period: str = ""
    primary_document_url: str = ""
    local_path: str = ""
    s3_uri: str = ""
    bucket: str = ""
    key: str = ""
    date_partition: str = ""
    source_layout: str = ""
    source_name: str = ""
    source_export_id: str = ""
    declared_artifact_sha256: str = ""
    artifact_sha256: str = ""
    artifact_bytes: int = 0
    manifest_path: str = ""

    @property
    def source_id(self) -> str:
        return self.accession or self.source_record_id

    @property
    def artifact_ref(self) -> str:
        if self.local_path:
            return self.local_path
        if self.s3_uri:
            return self.s3_uri
        if self.bucket and self.key:
            return f"s3://{self.bucket}/{self.key}"
        return ""

    @property
    def sort_key(self) -> tuple[str, str, str, str, str, int]:
        return (
            self.source_family,
            self.scope_key,
            self.report_period,
            self.source_id,
            self.artifact_ref,
            self.row_number,
        )

    @property
    def source_key(self) -> tuple[str, str]:
        return (self.scope_key, self.source_id)

    @property
    def stable_id(self) -> str:
        return stable_p009_row_id(self.to_json(include_id=False))

    def to_json(self, *, include_id: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "source_family": self.source_family,
            "scope_key": self.scope_key,
            "source_id": self.source_id,
            "artifact_ref": self.artifact_ref,
            "row_number": self.row_number,
        }
        if include_id:
            data["source_stable_id"] = self.stable_id
        optional = {
            "accession": self.accession,
            "artifact_sha256": self.artifact_sha256,
            "bucket": self.bucket,
            "date_partition": self.date_partition,
            "declared_artifact_sha256": self.declared_artifact_sha256,
            "filed_date": self.filed_date,
            "form": self.form,
            "key": self.key,
            "local_path": self.local_path,
            "manifest_path": self.manifest_path,
            "primary_document_url": self.primary_document_url,
            "report_period": self.report_period,
            "s3_uri": self.s3_uri,
            "source_adapter": self.source_adapter,
            "source_export_id": self.source_export_id,
            "source_layout": self.source_layout,
            "source_name": self.source_name,
            "source_record_id": self.source_record_id,
        }
        for key in sorted(optional):
            if optional[key]:
                data[key] = optional[key]
        if self.artifact_bytes:
            data["artifact_bytes"] = self.artifact_bytes
        return data


@dataclass(frozen=True)
class P009CorpusLoadResult:
    """Loaded P009 corpus sources, observations, and diagnostics."""

    sources: tuple[P009CorpusSource, ...] = ()
    observations: tuple[P009InstrumentObservation, ...] = ()
    diagnostics: tuple[P009CorpusDiagnostic, ...] = ()
    manifest_input_sha256: str = ""
    observations_input_sha256: str = ""
    manifest_row_count: int = 0
    observation_row_count: int = 0
    malformed_row_count: int = 0
    manifest_path: str = ""
    observations_path: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "manifest_input_sha256": self.manifest_input_sha256,
            "observations_input_sha256": self.observations_input_sha256,
            "manifest_row_count": self.manifest_row_count,
            "observation_row_count": self.observation_row_count,
            "source_count": len(self.sources),
            "observation_count": len(self.observations),
            "malformed_row_count": self.malformed_row_count,
            "manifest_path": self.manifest_path,
            "observations_path": self.observations_path,
            "sources": [source.to_json() for source in self.sources],
            "observations": [observation.to_json() for observation in self.observations],
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
        }


def load_p009_corpus(
    manifest_path: str | Path,
    *,
    observations_path: str | Path | None = None,
) -> P009CorpusLoadResult:
    """Load a provider-neutral P009 corpus manifest and optional observations."""

    manifest_result = load_p009_manifest(manifest_path)
    if observations_path is None:
        return manifest_result

    observation_result = load_p009_observations(observations_path)
    combined = P009CorpusLoadResult(
        sources=manifest_result.sources,
        observations=observation_result.observations,
        diagnostics=tuple(
            sorted(
                manifest_result.diagnostics
                + observation_result.diagnostics
                + validate_p009_corpus(
                    P009CorpusLoadResult(
                        sources=manifest_result.sources,
                        observations=observation_result.observations,
                    )
                ),
                key=lambda diagnostic: diagnostic.sort_key,
            )
        ),
        manifest_input_sha256=manifest_result.manifest_input_sha256,
        observations_input_sha256=observation_result.observations_input_sha256,
        manifest_row_count=manifest_result.manifest_row_count,
        observation_row_count=observation_result.observation_row_count,
        malformed_row_count=manifest_result.malformed_row_count + observation_result.malformed_row_count,
        manifest_path=manifest_result.manifest_path,
        observations_path=observation_result.observations_path,
    )
    return combined


def load_p009_manifest(path: str | Path) -> P009CorpusLoadResult:
    """Load and validate a P009 corpus manifest JSONL/CSV file."""

    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    input_sha = hashlib.sha256(raw).hexdigest()
    rows, diagnostics = _read_manifest_rows(text, source_path=str(path))
    sources: list[P009CorpusSource] = []
    more_diagnostics: list[P009CorpusDiagnostic] = []
    for row_number, row in rows:
        source, row_diagnostics = _source_from_row(
            row,
            row_number=row_number,
            manifest_path=path,
        )
        more_diagnostics.extend(row_diagnostics)
        if source is not None:
            sources.append(source)

    all_diagnostics = diagnostics + more_diagnostics
    return P009CorpusLoadResult(
        sources=tuple(sorted(sources, key=lambda source: source.sort_key)),
        diagnostics=tuple(sorted(all_diagnostics, key=lambda diagnostic: diagnostic.sort_key)),
        manifest_input_sha256=input_sha,
        manifest_row_count=len(rows),
        malformed_row_count=sum(1 for diagnostic in all_diagnostics if diagnostic.code == "P009-CORPUS-E001"),
        manifest_path=str(path),
    )


def load_p009_observations(path: str | Path) -> P009CorpusLoadResult:
    """Load normalized observation rows as a corpus contract fragment."""

    path = Path(path)
    result = load_p009_observation_rows(path)
    diagnostics = tuple(
        sorted(
            (_corpus_diag_from_observation_diag(diagnostic) for diagnostic in result.diagnostics),
            key=lambda diagnostic: diagnostic.sort_key,
        )
    )
    return P009CorpusLoadResult(
        observations=result.observations,
        diagnostics=diagnostics,
        observations_input_sha256=result.input_sha256,
        observation_row_count=result.row_count,
        malformed_row_count=result.malformed_row_count,
        observations_path=str(path),
    )


def validate_p009_corpus(result: P009CorpusLoadResult) -> tuple[P009CorpusDiagnostic, ...]:
    """Validate cross-file corpus rules without provider-specific assumptions."""

    diagnostics: list[P009CorpusDiagnostic] = []
    if not result.sources:
        return ()
    source_keys = {source.source_key for source in result.sources}
    for observation in result.observations:
        if (observation.source_scope.scope_key, observation.source_id) not in source_keys:
            diagnostics.append(
                P009CorpusDiagnostic(
                    code="P009-CORPUS-E007",
                    message="observation does not match a manifest source by scope_key and source id",
                    field="source_scope",
                    source_path=_first_source_path(observation),
                    value=f"{observation.source_scope.scope_key}|{observation.source_id}",
                )
            )
    return tuple(sorted(diagnostics, key=lambda diagnostic: diagnostic.sort_key))


def stable_p009_row_id(row: Mapping[str, object]) -> str:
    """Return a deterministic row id over normalized provider-neutral fields."""

    fields = []
    for key, value in sorted(row.items(), key=lambda item: str(item[0])):
        if key in {"row_number", "source_stable_id"}:
            continue
        text = normalize_text(value)
        if text:
            fields.append((normalize_key_token(key).lower(), text))
    signature = json.dumps(fields, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(f"v1|P009:corpus-row|{signature}".encode("ascii")).hexdigest()


def _source_from_row(
    row: dict[str, Any],
    *,
    row_number: int,
    manifest_path: Path,
) -> tuple[P009CorpusSource | None, list[P009CorpusDiagnostic]]:
    diagnostics: list[P009CorpusDiagnostic] = []
    source_path = str(manifest_path)
    schema_version = normalize_text(row.get("schema_version", ""))
    if schema_version not in _SCHEMA_VERSIONS:
        diagnostics.append(
            _diag(
                "P009-CORPUS-E001",
                "unsupported P009 corpus manifest schema_version",
                row_number=row_number,
                field="schema_version",
                value=schema_version,
                source_path=source_path,
            )
        )
        return None, diagnostics

    source_family = normalize_key_token(row.get("source_family", "")).lower()
    if not source_family:
        diagnostics.append(_missing_field("source_family", row_number, source_path))
        return None, diagnostics
    if source_family not in _SUPPORTED_SOURCE_FAMILIES:
        diagnostics.append(
            _diag(
                "P009-CORPUS-E005",
                "unsupported source_family for P009 corpus manifest",
                row_number=row_number,
                field="source_family",
                value=source_family,
                source_path=source_path,
            )
        )
        return None, diagnostics

    scope_key = _first_text(row.get("scope_key"), row.get("source_scope_key"))
    if not scope_key and isinstance(row.get("source_scope"), dict):
        scope_key = _first_text(row["source_scope"].get("scope_key"))
    if not scope_key:
        diagnostics.append(_missing_field("scope_key", row_number, source_path))
        return None, diagnostics

    accession = normalize_text(row.get("accession", ""))
    source_record_id = _first_text(row.get("source_record_id"), row.get("record_id"))
    accession, source_record_id = _validate_source_ids(
        accession,
        source_record_id,
        row_number=row_number,
        source_path=source_path,
        diagnostics=diagnostics,
    )
    source_id_invalid = not accession and not source_record_id

    filed_date = _date_field(row, "filed_date", row_number, source_path, diagnostics)
    report_period = _date_field(row, "report_period", row_number, source_path, diagnostics)
    local_path = _first_text(row.get("local_path"), row.get("path"), row.get("cached_path"))
    s3_uri = _first_text(row.get("s3_uri"), row.get("uri"))
    bucket = _first_text(row.get("bucket"))
    key = _first_text(row.get("key"), row.get("s3_key"))
    source_layout = _first_text(row.get("source_layout"))

    if not local_path and not s3_uri and not (bucket and key):
        diagnostics.append(
            _diag(
                "P009-CORPUS-E006",
                "manifest row must include local_path, s3_uri, or bucket/key cached artifact reference",
                row_number=row_number,
                field="artifact",
                source_path=source_path,
            )
        )
        return None, diagnostics

    declared_sha = normalize_identifier(
        _first_text(row.get("source_artifact_sha256"), row.get("artifact_sha256"), row.get("sha256"))
    ).lower()
    if declared_sha and not _SHA256_RE.match(declared_sha):
        diagnostics.append(
            _diag(
                "P009-CORPUS-E006",
                "source artifact sha256 must be 64 hex characters",
                row_number=row_number,
                field="source_artifact_sha256",
                value=declared_sha,
                source_path=source_path,
            )
        )
        declared_sha = ""

    artifact_sha, artifact_bytes = _local_artifact_hash(
        local_path,
        manifest_path=manifest_path,
        row_number=row_number,
        source_path=source_path,
        declared_sha=declared_sha,
        diagnostics=diagnostics,
    )

    if source_id_invalid:
        return None, diagnostics

    return (
        P009CorpusSource(
            row_number=row_number,
            source_family=source_family,
            source_adapter=normalize_key_token(row.get("source_adapter", "")).lower(),
            scope_key=scope_key,
            accession=accession,
            source_record_id=source_record_id,
            filed_date=filed_date,
            form=normalize_key_token(row.get("form", "")).upper(),
            report_period=report_period,
            primary_document_url=_first_text(row.get("primary_document_url")),
            local_path=local_path,
            s3_uri=s3_uri,
            bucket=bucket,
            key=key,
            date_partition=_first_text(row.get("date_partition")),
            source_layout=source_layout,
            source_name=_first_text(row.get("source_name")),
            source_export_id=_first_text(row.get("source_export_id")),
            declared_artifact_sha256=declared_sha,
            artifact_sha256=artifact_sha or declared_sha,
            artifact_bytes=artifact_bytes,
            manifest_path=source_path,
        ),
        diagnostics,
    )


def _read_manifest_rows(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009CorpusDiagnostic]]:
    first = next((line for line in text.splitlines() if line.strip()), "")
    if not first:
        return [], [
            _diag(
                "P009-CORPUS-E001",
                "P009 corpus manifest is empty",
                source_path=source_path,
            )
        ]
    if first.lstrip().startswith("["):
        return _read_json_array(text, source_path=source_path)
    if first.lstrip().startswith("{"):
        return _read_jsonl(text, source_path=source_path)
    return _read_csv(text, source_path=source_path)


def _read_json_array(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009CorpusDiagnostic]]:
    try:
        raw = json.JSONDecoder().decode(text)
    except json.JSONDecodeError as exc:
        return [], [
            _diag(
                "P009-CORPUS-E001",
                f"malformed JSON corpus manifest array: {exc.msg}",
                row_number=exc.lineno,
                source_path=source_path,
            )
        ]
    if not isinstance(raw, list):
        return [], [
            _diag(
                "P009-CORPUS-E001",
                "JSON corpus manifest root must be an array or JSONL objects",
                source_path=source_path,
            )
        ]
    rows: list[tuple[int, dict[str, Any]]] = []
    diagnostics: list[P009CorpusDiagnostic] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            rows.append((index, item))
        else:
            diagnostics.append(
                _diag(
                    "P009-CORPUS-E001",
                    "JSON corpus manifest item must be an object",
                    row_number=index,
                    source_path=source_path,
                )
            )
    return rows, diagnostics


def _read_jsonl(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009CorpusDiagnostic]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    diagnostics: list[P009CorpusDiagnostic] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.JSONDecoder().decode(line)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                _diag(
                    "P009-CORPUS-E001",
                    f"malformed JSONL corpus manifest row: {exc.msg}",
                    row_number=line_number,
                    source_path=source_path,
                )
            )
            continue
        if isinstance(raw, dict):
            rows.append((line_number, raw))
        else:
            diagnostics.append(
                _diag(
                    "P009-CORPUS-E001",
                    "JSONL corpus manifest row must be an object",
                    row_number=line_number,
                    source_path=source_path,
                )
            )
    return rows, diagnostics


def _read_csv(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009CorpusDiagnostic]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return [], [
                _diag(
                    "P009-CORPUS-E001",
                    "CSV corpus manifest has no header row",
                    source_path=source_path,
                )
            ]
        return [(index, dict(row)) for index, row in enumerate(reader, start=2)], []
    except csv.Error as exc:
        return [], [
            _diag(
                "P009-CORPUS-E001",
                f"malformed CSV corpus manifest: {exc}",
                source_path=source_path,
            )
        ]


def _validate_source_ids(
    accession: str,
    source_record_id: str,
    *,
    row_number: int,
    source_path: str,
    diagnostics: list[P009CorpusDiagnostic],
) -> tuple[str, str]:
    if accession and not _ACCESSION_RE.match(accession):
        diagnostics.append(
            _diag(
                "P009-CORPUS-E004",
                "accession format is invalid; expected SEC accession form ##########-##-######",
                row_number=row_number,
                field="accession",
                value=accession,
                source_path=source_path,
            )
        )
        accession = ""
    if source_record_id and not _SOURCE_RECORD_RE.match(source_record_id):
        diagnostics.append(
            _diag(
                "P009-CORPUS-E004",
                "source_record_id contains unsupported characters",
                row_number=row_number,
                field="source_record_id",
                value=source_record_id,
                source_path=source_path,
            )
        )
        source_record_id = ""
    if not accession and not source_record_id:
        diagnostics.append(_missing_field("accession_or_source_record_id", row_number, source_path))
    return accession, source_record_id


def _date_field(
    row: dict[str, Any],
    field: str,
    row_number: int,
    source_path: str,
    diagnostics: list[P009CorpusDiagnostic],
) -> str:
    value = _first_text(row.get(field))
    if value and not _DATE_RE.match(value):
        diagnostics.append(
            _diag(
                "P009-CORPUS-E003",
                f"{field} must use YYYY-MM-DD",
                row_number=row_number,
                field=field,
                value=value,
                source_path=source_path,
            )
        )
        return ""
    return value


def _local_artifact_hash(
    local_path: str,
    *,
    manifest_path: Path,
    row_number: int,
    source_path: str,
    declared_sha: str,
    diagnostics: list[P009CorpusDiagnostic],
) -> tuple[str, int]:
    if not local_path:
        return "", 0
    path = Path(local_path)
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file():
        diagnostics.append(
            _diag(
                "P009-CORPUS-E006",
                "local cached artifact is missing",
                row_number=row_number,
                field="local_path",
                value=local_path,
                source_path=source_path,
            )
        )
        return "", 0
    digest, size = sha256_file(path)
    if declared_sha and not hmac.compare_digest(digest, declared_sha):
        diagnostics.append(
            _diag(
                "P009-CORPUS-E006",
                "local cached artifact sha256 does not match declared sha256",
                row_number=row_number,
                field="source_artifact_sha256",
                value=declared_sha,
                source_path=source_path,
            )
        )
    return digest, size


def _corpus_diag_from_observation_diag(diagnostic: P009ObservationDiagnostic) -> P009CorpusDiagnostic:
    code = "P009-CORPUS-E001"
    if diagnostic.code == "P009-OBS-E002":
        code = "P009-CORPUS-E005"
    elif diagnostic.code == "P009-OBS-E003":
        code = "P009-CORPUS-E002"
    elif diagnostic.code == "P009-OBS-E004":
        code = "P009-CORPUS-E008"
    elif diagnostic.code == "P009-OBS-E006":
        code = "P009-CORPUS-E008"
    elif diagnostic.code == "P009-OBS-E007":
        if diagnostic.field in {"filed_date", "report_period"}:
            code = "P009-CORPUS-E003"
        elif diagnostic.field in {"accession", "source_record_id"}:
            code = "P009-CORPUS-E004"
        else:
            code = "P009-CORPUS-E002"
    return P009CorpusDiagnostic(
        code=code,
        message=f"observation row diagnostic: {diagnostic.message}",
        row_number=diagnostic.row_number,
        field=diagnostic.field,
        source_path=diagnostic.source_path,
        value=str(diagnostic.value),
    )


def _first_source_path(observation: P009InstrumentObservation) -> str:
    if observation.source_refs:
        return observation.source_refs[0].path
    return ""


def _missing_field(field: str, row_number: int, source_path: str) -> P009CorpusDiagnostic:
    return _diag(
        "P009-CORPUS-E002",
        f"missing required field: {field}",
        row_number=row_number,
        field=field,
        source_path=source_path,
    )


def _diag(
    code: str,
    message: str,
    *,
    row_number: int | None = None,
    field: str = "",
    source_path: str = "",
    value: str = "",
) -> P009CorpusDiagnostic:
    return P009CorpusDiagnostic(
        code=code,
        message=message,
        row_number=row_number,
        field=field,
        source_path=source_path,
        value=value,
    )


def _first_text(*values: object) -> str:
    for value in values:
        text = normalize_text(value)
        if text:
            return text
    return ""
