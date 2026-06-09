"""Source-neutral P009 instrument identity observation contract.

P009 detection consumes normalized observations. Source-specific parsing
belongs behind adapters that produce this model; the detector should not know
whether an observation came from iXBRL facts, XML, HTML, or a local export.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .instrument_identity import normalize_identifier, normalize_key_token, normalize_text, normalize_ticker


class P009ObservationError(ValueError):
    """Raised when P009 observation input cannot be handled deterministically."""


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_FIGI_RE = re.compile(r"^[A-Z0-9]{12}$")
_CUSIP_RE = re.compile(r"^[A-Z0-9]{9}$")
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
_SEDOL_RE = re.compile(r"^[A-Z0-9]{7}$")
_SCHEMA_VERSIONS = {"", "1.0", "p009_observations.v1", "p009_observations.v1.jsonl"}
_ROW_ADAPTER_SOURCE_FAMILIES = {
    "",
    "csv",
    "ixbrl",
    "jsonl",
    "local_export",
    "sec_filing",
    "test_fixture",
    "xml",
}


@dataclass(frozen=True)
class P009SourceScope:
    """Source-defined reporting scope for temporal comparison."""

    scope_key: str
    source_family: str = ""
    source_adapter: str = ""
    cik: str = ""
    series_id: str = ""
    series_name: str = ""

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        source_family: str,
        source_adapter: str,
    ) -> "P009SourceScope | None":
        raw_scope = row.get("source_scope", "")
        scope_data = raw_scope if isinstance(raw_scope, dict) else {}
        scope_key = _first_text(
            scope_data.get("scope_key"),
            row.get("scope_key"),
            row.get("source_scope_key"),
            raw_scope if not isinstance(raw_scope, dict) else "",
        )
        if not scope_key:
            return None
        return cls(
            scope_key=scope_key,
            source_family=source_family,
            source_adapter=source_adapter,
            cik=_first_text(scope_data.get("cik"), row.get("cik")),
            series_id=_first_text(scope_data.get("series_id"), row.get("series_id")),
            series_name=_first_text(scope_data.get("series_name"), row.get("series_name")),
        )

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.source_family, self.source_adapter, self.scope_key)

    def to_json(self) -> dict[str, str]:
        data = {
            "scope_key": self.scope_key,
            "source_family": self.source_family,
            "source_adapter": self.source_adapter,
        }
        optional = {
            "cik": self.cik,
            "series_id": self.series_id,
            "series_name": self.series_name,
        }
        for key in sorted(optional):
            if optional[key]:
                data[key] = optional[key]
        return data


@dataclass(frozen=True)
class P009SourceRef:
    """Stable pointer back to the source observation evidence."""

    path: str
    pointer: str = ""
    row_number: int | None = None
    line_number: int | None = None
    column: str = ""
    field: str = ""
    sha256: str = ""

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        default_path: str,
        row_number: int,
    ) -> tuple["P009SourceRef", ...]:
        raw_refs = row.get("source_refs")
        if isinstance(raw_refs, list):
            refs: list[P009SourceRef] = []
            for raw_ref in raw_refs:
                if not isinstance(raw_ref, dict):
                    continue
                ref = cls(
                    path=_first_text(raw_ref.get("path"), raw_ref.get("source_path"), default_path),
                    pointer=_first_text(raw_ref.get("pointer"), raw_ref.get("xpath"), raw_ref.get("json_pointer")),
                    row_number=_as_int(raw_ref.get("row_number")),
                    line_number=_as_int(raw_ref.get("line_number")),
                    column=normalize_text(raw_ref.get("column", "")),
                    field=normalize_text(raw_ref.get("field", "")),
                    sha256=normalize_identifier(raw_ref.get("sha256", "")),
                )
                refs.append(ref)
            if refs:
                return tuple(sorted(refs, key=lambda ref: ref.sort_key))

        source_path = _first_text(row.get("source_path"), row.get("path"), default_path)
        pointer = _first_text(row.get("source_pointer"), row.get("pointer"), row.get("xpath"))
        return (
            cls(
                path=source_path,
                pointer=pointer,
                row_number=_as_int(row.get("row_number")) or row_number,
                line_number=_as_int(row.get("line_number")),
                column=normalize_text(row.get("column", "")),
                field=normalize_text(row.get("field", "")),
                sha256=normalize_identifier(row.get("source_sha256", "")),
            ),
        )

    @property
    def sort_key(self) -> tuple[str, str, int, int, str, str]:
        return (
            self.path,
            self.pointer,
            self.row_number or 0,
            self.line_number or 0,
            self.column,
            self.field,
        )

    @property
    def signature_path(self) -> str:
        parts = [self.path]
        if self.pointer:
            parts.append(f"pointer={self.pointer}")
        if self.row_number is not None:
            parts.append(f"row={self.row_number}")
        if self.line_number is not None:
            parts.append(f"line={self.line_number}")
        if self.column:
            parts.append(f"column={self.column}")
        if self.field:
            parts.append(f"field={self.field}")
        return "#".join(parts)

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {"path": self.path}
        if self.pointer:
            data["pointer"] = self.pointer
        if self.row_number is not None:
            data["row_number"] = self.row_number
        if self.line_number is not None:
            data["line_number"] = self.line_number
        if self.column:
            data["column"] = self.column
        if self.field:
            data["field"] = self.field
        if self.sha256:
            data["sha256"] = self.sha256
        return data


@dataclass(frozen=True)
class P009ReportedIdentifiers:
    """Identifiers reported by the source for one instrument observation."""

    figi: str = ""
    cusip: str = ""
    isin: str = ""
    sedol: str = ""
    ticker: str = ""
    other_identifiers: tuple[tuple[str, str], ...] = ()

    @property
    def has_strong_identifier(self) -> bool:
        return bool(self.figi or self.cusip or self.isin or self.sedol or self.other_identifiers)

    @property
    def has_any_identifier(self) -> bool:
        return bool(self.has_strong_identifier or self.ticker)

    @property
    def strongest_basis(self) -> tuple[str, str]:
        for key, value in (
            ("figi", self.figi),
            ("cusip", self.cusip),
            ("isin", self.isin),
            ("sedol", self.sedol),
        ):
            if value:
                return (key, value)
        if self.other_identifiers:
            id_type, value = self.other_identifiers[0]
            return ("other_typed_identifier", f"{id_type}:{value}")
        if self.ticker:
            return ("ticker", self.ticker)
        return ("absent", "")

    @property
    def signature_fields(self) -> tuple[tuple[str, str], ...]:
        fields = [
            ("figi", self.figi),
            ("cusip", self.cusip),
            ("isin", self.isin),
            ("sedol", self.sedol),
            ("ticker", self.ticker),
        ]
        for id_type, value in self.other_identifiers:
            fields.append((f"other:{id_type}", value))
        return tuple((key, value) for key, value in fields if value)

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {}
        for key, value in self.signature_fields:
            if key.startswith("other:"):
                continue
            data[key] = value
        if self.other_identifiers:
            data["other_identifiers"] = [
                {"id_type": id_type, "value": value} for id_type, value in self.other_identifiers
            ]
        return data


@dataclass(frozen=True)
class P009WeakEvidence:
    """Weak descriptive/economic evidence that cannot resolve identity alone."""

    issuer_name: str = ""
    title_or_description: str = ""
    value: str = ""
    pct_value: str = ""
    currency: str = ""
    asset_type: str = ""
    issuer_type: str = ""
    balance: str = ""
    units: str = ""
    maturity_date: str = ""
    coupon: str = ""

    @property
    def has_weak_evidence(self) -> bool:
        return any(value for _key, value in self.signature_fields)

    @property
    def signature_fields(self) -> tuple[tuple[str, str], ...]:
        fields = (
            ("issuer_name", self.issuer_name),
            ("title_or_description", self.title_or_description),
            ("value", self.value),
            ("pct_value", self.pct_value),
            ("currency", self.currency),
            ("asset_type", self.asset_type),
            ("issuer_type", self.issuer_type),
            ("balance", self.balance),
            ("units", self.units),
            ("maturity_date", self.maturity_date),
            ("coupon", self.coupon),
        )
        return tuple((key, value) for key, value in fields if value)

    def to_json(self) -> dict[str, str]:
        return {key: value for key, value in self.signature_fields}


@dataclass(frozen=True)
class P009ObservationDiagnostic:
    """Deterministic diagnostic emitted by P009 observation adapters."""

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
    def sort_key(self) -> tuple[str, str, int, str, str]:
        return (self.code, self.source_path, self.row_number or 0, self.field, self.message)

    def to_json(self, *, include_id: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "code": self.code,
            "message": self.message,
        }
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
class P009InstrumentObservation:
    """One source-reported instrument identity observation."""

    source_scope: P009SourceScope
    source_family: str
    source_adapter: str
    accession: str
    observation_ordinal: int
    source_refs: tuple[P009SourceRef, ...]
    identifiers: P009ReportedIdentifiers
    weak_evidence: P009WeakEvidence
    filed_date: str = ""
    report_period: str = ""
    source_record_id: str = ""

    @property
    def source_id(self) -> str:
        return self.accession or self.source_record_id

    @property
    def sort_key(self) -> tuple[str, str, str, str, str, int, str]:
        first_ref = self.source_refs[0].signature_path if self.source_refs else ""
        return (
            self.source_family,
            self.source_adapter,
            self.report_period,
            self.source_id,
            self.source_scope.scope_key,
            self.observation_ordinal,
            first_ref,
        )

    @property
    def canonical_signature(self) -> str:
        source_path = self.source_refs[0].signature_path if self.source_refs else ""
        strong_fields = _canonical_fields(self.identifiers.signature_fields)
        weak_fields = _canonical_fields(self.weak_evidence.signature_fields)
        parts = (
            "P009:observation",
            self.source_family,
            self.source_adapter,
            self.source_id,
            self.report_period,
            self.source_scope.scope_key,
            str(self.observation_ordinal),
            source_path,
            strong_fields,
            weak_fields,
        )
        return "|".join(_safe_signature_token(part) for part in parts)

    @property
    def observation_id(self) -> str:
        return stable_observation_id(self)

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "observation_id": self.observation_id,
            "source_family": self.source_family,
            "source_adapter": self.source_adapter,
            "source_scope": self.source_scope.to_json(),
            "observation_ordinal": self.observation_ordinal,
            "source_refs": [ref.to_json() for ref in self.source_refs],
            "reported_identifiers": self.identifiers.to_json(),
            "weak_evidence": self.weak_evidence.to_json(),
            "canonical_signature": self.canonical_signature,
        }
        if self.accession:
            data["accession"] = self.accession
        if self.source_record_id:
            data["source_record_id"] = self.source_record_id
        if self.filed_date:
            data["filed_date"] = self.filed_date
        if self.report_period:
            data["report_period"] = self.report_period
        return data


@dataclass(frozen=True)
class P009ObservationParseResult:
    """Observations plus deterministic adapter diagnostics."""

    observations: tuple[P009InstrumentObservation, ...] = ()
    diagnostics: tuple[P009ObservationDiagnostic, ...] = ()
    input_sha256: str = ""
    row_count: int = 0
    malformed_row_count: int = 0

    def to_json(self) -> dict[str, object]:
        return {
            "input_sha256": self.input_sha256,
            "row_count": self.row_count,
            "observation_count": len(self.observations),
            "malformed_row_count": self.malformed_row_count,
            "observations": [observation.to_json() for observation in self.observations],
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
        }


class P009ObservationAdapter(Protocol):
    """Adapter protocol for source-specific observation producers."""

    source_family: str
    source_adapter: str

    def parse(
        self,
        data: bytes | str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> P009ObservationParseResult:
        """Parse source input into normalized P009 observations."""


@dataclass(frozen=True)
class P009RowsAdapter:
    """Adapter for source-neutral JSONL/CSV observation rows."""

    source_family: str = "local_export"
    source_adapter: str = "p009_rows_v1"

    def parse(
        self,
        data: bytes | str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> P009ObservationParseResult:
        text, source_path, input_sha = _read_adapter_input(data, metadata=metadata)
        metadata = metadata or {}
        if not text.strip():
            return P009ObservationParseResult(
                diagnostics=(
                    P009ObservationDiagnostic(
                        code="P009-OBS-E001",
                        message="observation input is empty",
                        source_path=source_path,
                    ),
                ),
                input_sha256=input_sha,
            )

        rows, diagnostics = _read_rows(text, source_path=source_path)
        observations: list[P009InstrumentObservation] = []
        more_diagnostics: list[P009ObservationDiagnostic] = []
        for row_number, row in rows:
            observation, row_diagnostics = _observation_from_row(
                row,
                row_number=row_number,
                default_source_path=source_path,
                metadata=metadata,
            )
            more_diagnostics.extend(row_diagnostics)
            if observation is not None:
                observations.append(observation)

        all_diagnostics = diagnostics + more_diagnostics
        return P009ObservationParseResult(
            observations=tuple(sorted(observations, key=lambda observation: observation.sort_key)),
            diagnostics=tuple(sorted(all_diagnostics, key=lambda diagnostic: diagnostic.sort_key)),
            input_sha256=input_sha,
            row_count=len(rows),
            malformed_row_count=sum(1 for diagnostic in all_diagnostics if diagnostic.code == "P009-OBS-E001"),
        )


@dataclass(frozen=True)
class UnsupportedP009ObservationAdapter:
    """Fail-closed adapter for source families not yet supported."""

    source_family: str
    source_adapter: str = "unsupported"

    def parse(
        self,
        data: bytes | str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> P009ObservationParseResult:
        _text, source_path, input_sha = _read_adapter_input(data, metadata=metadata)
        family = normalize_key_token(self.source_family).lower()
        return P009ObservationParseResult(
            diagnostics=(
                P009ObservationDiagnostic(
                    code="P009-OBS-E009",
                    message=f"no P009 observation adapter is available for source family: {family}",
                    source_path=source_path,
                ),
            ),
            input_sha256=input_sha,
        )


def adapter_for_source_family(source_family: object) -> P009ObservationAdapter:
    """Return the deterministic adapter for a source family.

    Unknown families return a fail-closed adapter that emits diagnostics instead
    of raising in normal parse paths.
    """

    family = normalize_key_token(source_family).lower()
    if family in _ROW_ADAPTER_SOURCE_FAMILIES:
        return P009RowsAdapter(source_family=family or "local_export")
    return UnsupportedP009ObservationAdapter(source_family=family)


def load_p009_observations(
    path: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> P009ObservationParseResult:
    """Load normalized P009 observations from a JSONL/CSV file."""

    return P009RowsAdapter().parse(Path(path), metadata=metadata)


def parse_p009_observation_rows(
    data: bytes | str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> P009ObservationParseResult:
    """Parse source-neutral P009 observation rows from bytes, text, or a path."""

    return P009RowsAdapter().parse(data, metadata=metadata)


def normalize_p009_identifier(id_type: object, value: object) -> str:
    """Normalize a reported identifier according to its identifier type."""

    kind = _canonical_id_type(id_type)
    raw = normalize_text(value)
    if not raw:
        return ""
    if kind == "ticker":
        return normalize_ticker(raw)
    if kind == "other_typed_identifier":
        return normalize_key_token(raw)
    return normalize_identifier(raw)


def observation_identity_evidence(observation: P009InstrumentObservation) -> dict[str, object]:
    """Return the identity evidence relevant to ledger/detector stages."""

    basis_type, basis_value = observation.identifiers.strongest_basis
    return {
        "observation_id": observation.observation_id,
        "scope_key": observation.source_scope.scope_key,
        "source_id": observation.source_id,
        "report_period": observation.report_period,
        "basis_type": basis_type,
        "basis_value": basis_value,
        "reported_identifiers": observation.identifiers.to_json(),
        "weak_evidence": observation.weak_evidence.to_json(),
        "source_refs": [ref.to_json() for ref in observation.source_refs],
    }


def stable_observation_id(observation: P009InstrumentObservation) -> str:
    """Build a deterministic sha256 id for a P009 observation."""

    signature = f"v1|{observation.canonical_signature}"
    encoded = signature.encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _observation_from_row(
    row: dict[str, Any],
    *,
    row_number: int,
    default_source_path: str,
    metadata: dict[str, Any],
) -> tuple[P009InstrumentObservation | None, list[P009ObservationDiagnostic]]:
    diagnostics: list[P009ObservationDiagnostic] = []
    source_family = _first_text(row.get("source_family"), metadata.get("source_family"), "local_export").lower()
    source_adapter = _first_text(row.get("source_adapter"), metadata.get("source_adapter"), "p009_rows_v1")
    source_family = normalize_key_token(source_family).lower()
    source_adapter = normalize_key_token(source_adapter).lower()

    schema_version = normalize_text(row.get("schema_version", metadata.get("schema_version", "")))
    if schema_version not in _SCHEMA_VERSIONS:
        diagnostics.append(
            _diag(
                "P009-OBS-E007",
                "unsupported P009 observation row schema_version",
                row_number=row_number,
                field="schema_version",
                value=schema_version,
                source_path=default_source_path,
            )
        )
        return None, diagnostics

    if source_family not in _ROW_ADAPTER_SOURCE_FAMILIES - {""}:
        diagnostics.append(
            _diag(
                "P009-OBS-E002",
                "unsupported source_family for source-neutral observation rows",
                row_number=row_number,
                field="source_family",
                value=source_family,
                source_path=default_source_path,
            )
        )
        return None, diagnostics

    source_scope = P009SourceScope.from_row(
        row,
        source_family=source_family,
        source_adapter=source_adapter,
    )
    if source_scope is None:
        diagnostics.append(
            _diag(
                "P009-OBS-E003",
                "missing source scope; row must include scope_key or source_scope.scope_key",
                row_number=row_number,
                field="scope_key",
                source_path=default_source_path,
            )
        )
        return None, diagnostics

    accession = normalize_text(row.get("accession", ""))
    source_record_id = _first_text(row.get("source_record_id"), row.get("record_id"))
    if accession and not _ACCESSION_RE.match(accession):
        diagnostics.append(
            _diag(
                "P009-OBS-E007",
                "accession format is invalid; expected SEC accession form ##########-##-######",
                row_number=row_number,
                field="accession",
                value=accession,
                source_path=default_source_path,
            )
        )
        accession = ""
    if not accession and not source_record_id:
        diagnostics.append(
            _diag(
                "P009-OBS-E007",
                "row must include accession or source_record_id",
                row_number=row_number,
                field="accession",
                source_path=default_source_path,
            )
        )
        return None, diagnostics

    filed_date = normalize_text(row.get("filed_date", ""))
    report_period = _first_text(row.get("report_period"), row.get("period_end"), row.get("report_date"))
    for field, value in (("filed_date", filed_date), ("report_period", report_period)):
        if value and not _DATE_RE.match(value):
            diagnostics.append(
                _diag(
                    "P009-OBS-E007",
                    f"{field} must use YYYY-MM-DD",
                    row_number=row_number,
                    field=field,
                    value=value,
                    source_path=default_source_path,
                )
            )
    if not report_period:
        diagnostics.append(
            _diag(
                "P009-OBS-E008",
                "report_period is missing; temporal ordering may require external context",
                row_number=row_number,
                field="report_period",
                source_path=default_source_path,
            )
        )

    identifiers, identifier_diagnostics = _identifiers_from_row(
        row,
        row_number=row_number,
        source_path=default_source_path,
    )
    diagnostics.extend(identifier_diagnostics)
    weak_evidence = _weak_evidence_from_row(row)
    if not identifiers.has_any_identifier and not weak_evidence.has_weak_evidence:
        diagnostics.append(
            _diag(
                "P009-OBS-E004",
                "row has no reported identifier or weak descriptive identity evidence",
                row_number=row_number,
                field="identity",
                source_path=default_source_path,
            )
        )
        return None, diagnostics

    source_refs = P009SourceRef.from_row(row, default_path=default_source_path, row_number=row_number)
    observation_ordinal = _as_int(row.get("observation_ordinal"))
    if observation_ordinal is None:
        observation_ordinal = _as_int(row.get("holding_ordinal")) or row_number - 1

    return (
        P009InstrumentObservation(
            source_scope=source_scope,
            source_family=source_family,
            source_adapter=source_adapter,
            accession=accession,
            source_record_id=source_record_id,
            filed_date=filed_date,
            report_period=report_period,
            observation_ordinal=observation_ordinal,
            source_refs=source_refs,
            identifiers=identifiers,
            weak_evidence=weak_evidence,
        ),
        diagnostics,
    )


def _identifiers_from_row(
    row: dict[str, Any],
    *,
    row_number: int,
    source_path: str,
) -> tuple[P009ReportedIdentifiers, list[P009ObservationDiagnostic]]:
    diagnostics: list[P009ObservationDiagnostic] = []
    values: dict[str, str] = {}
    for id_type in ("figi", "cusip", "isin", "sedol", "ticker"):
        normalized = normalize_p009_identifier(id_type, row.get(id_type, ""))
        if normalized and not _valid_identifier_shape(id_type, normalized):
            diagnostics.append(
                _diag(
                    "P009-OBS-E006",
                    f"invalid {id_type} identifier shape",
                    row_number=row_number,
                    field=id_type,
                    value=normalized,
                    source_path=source_path,
                )
            )
            normalized = ""
        values[id_type] = normalized

    other_identifiers = _other_identifiers_from_row(
        row,
        row_number=row_number,
        source_path=source_path,
        diagnostics=diagnostics,
    )
    return (
        P009ReportedIdentifiers(
            figi=values["figi"],
            cusip=values["cusip"],
            isin=values["isin"],
            sedol=values["sedol"],
            ticker=values["ticker"],
            other_identifiers=other_identifiers,
        ),
        diagnostics,
    )


def _other_identifiers_from_row(
    row: dict[str, Any],
    *,
    row_number: int,
    source_path: str,
    diagnostics: list[P009ObservationDiagnostic],
) -> tuple[tuple[str, str], ...]:
    raw_pairs: list[tuple[Any, Any]] = []
    raw_other = row.get("other_identifiers")
    if isinstance(raw_other, list):
        for item in raw_other:
            if isinstance(item, dict):
                raw_pairs.append((_first_text(item.get("id_type"), item.get("type")), item.get("value")))
            else:
                diagnostics.append(
                    _diag(
                        "P009-OBS-E007",
                        "other_identifiers entries must be objects",
                        row_number=row_number,
                        field="other_identifiers",
                        source_path=source_path,
                    )
                )
    raw_pair_type = _first_text(row.get("other_id_type"), row.get("other_identifier_type"))
    raw_pair_value = _first_text(row.get("other_id_value"), row.get("other_identifier_value"))
    if raw_pair_type or raw_pair_value:
        raw_pairs.append((raw_pair_type, raw_pair_value))

    normalized: list[tuple[str, str]] = []
    for id_type_raw, value_raw in raw_pairs:
        id_type = normalize_key_token(id_type_raw)
        value = normalize_p009_identifier("other_typed_identifier", value_raw)
        if not id_type or not value:
            diagnostics.append(
                _diag(
                    "P009-OBS-E006",
                    "other identifier requires both type and value",
                    row_number=row_number,
                    field="other_identifiers",
                    source_path=source_path,
                )
            )
            continue
        normalized.append((id_type, value))
    return tuple(sorted(set(normalized)))


def _weak_evidence_from_row(row: dict[str, Any]) -> P009WeakEvidence:
    return P009WeakEvidence(
        issuer_name=_first_text(row.get("issuer_name"), row.get("issuer"), row.get("name")),
        title_or_description=_first_text(
            row.get("title_or_description"),
            row.get("title"),
            row.get("description"),
            row.get("investment_description"),
            row.get("security_title"),
        ),
        value=_first_text(row.get("value"), row.get("fair_value"), row.get("market_value")),
        pct_value=_first_text(row.get("pct_value"), row.get("percent_value")),
        currency=normalize_key_token(row.get("currency", "")),
        asset_type=_first_text(row.get("asset_type"), row.get("asset_category")),
        issuer_type=_first_text(row.get("issuer_type")),
        balance=_first_text(row.get("balance")),
        units=_first_text(row.get("units"), row.get("unit")),
        maturity_date=_first_text(row.get("maturity_date")),
        coupon=_first_text(row.get("coupon"), row.get("coupon_percent")),
    )


def _read_adapter_input(
    data: bytes | str | Path,
    *,
    metadata: dict[str, Any] | None,
) -> tuple[str, str, str]:
    source_path = normalize_text((metadata or {}).get("source_path", ""))
    if isinstance(data, Path):
        raw = data.read_bytes()
        source_path = source_path or str(data)
    elif isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        text_candidate = data.strip()
        maybe_path = Path(data)
        if (
            "\n" not in data
            and len(data) < 1024
            and not text_candidate.startswith(("{", "["))
            and maybe_path.is_file()
        ):
            raw = maybe_path.read_bytes()
            source_path = source_path or str(maybe_path)
        else:
            raw = data.encode("utf-8")
    else:
        raise P009ObservationError(f"unsupported P009 observation input type: {type(data)!r}")
    text = raw.decode("utf-8", errors="replace")
    input_sha = hashlib.sha256(raw).hexdigest()
    return text, source_path or "<memory>", input_sha


def _read_rows(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009ObservationDiagnostic]]:
    first = next((line for line in text.splitlines() if line.strip()), "")
    if first.lstrip().startswith("["):
        return _read_json_array(text, source_path=source_path)
    if first.lstrip().startswith("{"):
        return _read_jsonl(text, source_path=source_path)
    return _read_csv(text, source_path=source_path)


def _read_json_array(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009ObservationDiagnostic]]:
    try:
        raw = json.JSONDecoder().decode(text)
    except json.JSONDecodeError as exc:
        return [], [
            _diag(
                "P009-OBS-E001",
                f"malformed JSON observation array: {exc.msg}",
                row_number=exc.lineno,
                source_path=source_path,
            )
        ]
    if not isinstance(raw, list):
        return [], [
            _diag(
                "P009-OBS-E007",
                "JSON observation root must be an array or JSONL objects",
                source_path=source_path,
            )
        ]
    rows: list[tuple[int, dict[str, Any]]] = []
    diagnostics: list[P009ObservationDiagnostic] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            rows.append((index, item))
        else:
            diagnostics.append(
                _diag(
                    "P009-OBS-E001",
                    "JSON array observation item must be an object",
                    row_number=index,
                    source_path=source_path,
                )
            )
    return rows, diagnostics


def _read_jsonl(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009ObservationDiagnostic]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    diagnostics: list[P009ObservationDiagnostic] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.JSONDecoder().decode(line)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                _diag(
                    "P009-OBS-E001",
                    f"malformed JSONL observation row: {exc.msg}",
                    row_number=line_number,
                    source_path=source_path,
                )
            )
            continue
        if not isinstance(raw, dict):
            diagnostics.append(
                _diag(
                    "P009-OBS-E001",
                    "JSONL observation row must be an object",
                    row_number=line_number,
                    source_path=source_path,
                )
            )
            continue
        rows.append((line_number, raw))
    return rows, diagnostics


def _read_csv(
    text: str,
    *,
    source_path: str,
) -> tuple[list[tuple[int, dict[str, Any]]], list[P009ObservationDiagnostic]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return [], [
                _diag(
                    "P009-OBS-E001",
                    "CSV observation input has no header row",
                    source_path=source_path,
                )
            ]
        rows = [(index, dict(row)) for index, row in enumerate(reader, start=2)]
        return rows, []
    except csv.Error as exc:
        return [], [
            _diag(
                "P009-OBS-E001",
                f"malformed CSV observation input: {exc}",
                source_path=source_path,
            )
        ]


def _valid_identifier_shape(id_type: str, value: str) -> bool:
    if not value:
        return True
    if id_type == "figi":
        return bool(_FIGI_RE.match(value))
    if id_type == "cusip":
        return bool(_CUSIP_RE.match(value))
    if id_type == "isin":
        return bool(_ISIN_RE.match(value))
    if id_type == "sedol":
        return bool(_SEDOL_RE.match(value))
    return True


def _canonical_id_type(id_type: object) -> str:
    raw = normalize_key_token(id_type)
    aliases = {
        "BB_GLOBAL": "figi",
        "COMPOSITE_FIGI": "figi",
        "FIGI": "figi",
        "ID_BB_GLOBAL": "figi",
        "ID_CUSIP": "cusip",
        "CUSIP": "cusip",
        "CUSIP_NUMBER": "cusip",
        "ID_ISIN": "isin",
        "ISIN": "isin",
        "ID_SEDOL": "sedol",
        "SEDOL": "sedol",
        "ID_TICKER": "ticker",
        "TICKER": "ticker",
    }
    return aliases.get(raw, "other_typed_identifier")


def _canonical_fields(fields: tuple[tuple[str, str], ...]) -> str:
    if not fields:
        return ""
    return ";".join(
        f"{_safe_signature_token(key)}={_safe_signature_token(value)}"
        for key, value in sorted(fields, key=lambda item: (item[0], item[1]))
    )


def _safe_signature_token(value: object) -> str:
    encoded = json.dumps(normalize_text(value), ensure_ascii=True, separators=(",", ":"))
    return encoded[1:-1].replace("|", "%7C").replace("=", "%3D")


def _first_text(*values: object) -> str:
    for value in values:
        text = normalize_text(value)
        if text:
            return text
    return ""


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _diag(
    code: str,
    message: str,
    *,
    row_number: int | None = None,
    field: str = "",
    source_path: str = "",
    value: str = "",
) -> P009ObservationDiagnostic:
    return P009ObservationDiagnostic(
        code=code,
        message=message,
        row_number=row_number,
        field=field,
        source_path=source_path,
        value=value,
    )
