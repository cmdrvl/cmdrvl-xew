"""Local instrument registry snapshot reader for XEW-P008.

This module intentionally does not call OpenFIGI, canon, twinning, HTTP, or any
provider runtime. It only consumes a local snapshot file that was produced
outside cmdrvl-xew.
"""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .instrument_identity import (
    InstrumentIdentity,
    normalize_exchange_key,
    normalize_identifier,
    normalize_key_token,
    normalize_text,
    normalize_ticker,
)
from .util import sha256_file


class RegistrySnapshotError(ValueError):
    """Raised when a local registry snapshot is malformed."""


_FIGI_RE = re.compile(r"^[A-Z0-9]{12}$")


def _public_text_equal(left: str, right: str) -> bool:
    return left == right


@dataclass(frozen=True)
class RegistryRow:
    figi: str
    ticker: str = ""
    exchange: str = ""
    security_title: str = ""
    normalized_title: str = ""
    canonical_signature: str = ""
    cusip: str = ""
    isin: str = ""
    sedol: str = ""
    composite_figi: str = ""
    share_class_figi: str = ""
    market_sector: str = ""
    security_type: str = ""
    name: str = ""
    other_identifiers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_json(cls, raw: dict[str, Any], index: int) -> "RegistryRow":
        if not isinstance(raw, dict):
            raise RegistrySnapshotError(f"registry row {index} must be an object")
        figi = normalize_identifier(raw.get("figi", ""))
        if not figi:
            raise RegistrySnapshotError(f"registry row {index} missing figi")
        if not _FIGI_RE.match(figi):
            raise RegistrySnapshotError(f"registry row {index} has invalid figi: {figi}")
        return cls(
            figi=figi,
            ticker=normalize_ticker(raw.get("ticker", "")),
            exchange=normalize_exchange_key(raw.get("exchange", "")),
            security_title=normalize_text(raw.get("security_title") or raw.get("title", "")),
            normalized_title=normalize_text(raw.get("normalized_title", "")),
            canonical_signature=normalize_text(raw.get("canonical_signature", "")),
            cusip=normalize_identifier(raw.get("cusip", "")),
            isin=normalize_identifier(raw.get("isin", "")),
            sedol=normalize_identifier(raw.get("sedol", "")),
            composite_figi=normalize_identifier(raw.get("composite_figi", "")),
            share_class_figi=normalize_identifier(raw.get("share_class_figi", "")),
            market_sector=normalize_text(raw.get("market_sector", "")),
            security_type=normalize_text(raw.get("security_type", "")),
            name=normalize_text(raw.get("name", "")),
            other_identifiers=_other_identifiers(raw),
        )

    @property
    def dedupe_key(self) -> tuple[str, ...]:
        return (
            self.figi,
            self.ticker,
            self.exchange,
            self.security_title,
            self.normalized_title,
            self.canonical_signature,
            self.cusip,
            self.isin,
            self.sedol,
            self.composite_figi,
            self.share_class_figi,
            self.market_sector,
            self.security_type,
            self.name,
            ";".join(f"{id_type}:{value}" for id_type, value in self.other_identifiers),
        )

    @property
    def stable_id(self) -> str:
        payload = json.dumps(self.to_json(), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    def to_json(self) -> dict[str, str]:
        data = {
            "figi": self.figi,
            "ticker": self.ticker,
            "exchange": self.exchange,
        }
        optional = {
            "security_title": self.security_title,
            "normalized_title": self.normalized_title,
            "canonical_signature": self.canonical_signature,
            "cusip": self.cusip,
            "isin": self.isin,
            "sedol": self.sedol,
            "composite_figi": self.composite_figi,
            "share_class_figi": self.share_class_figi,
            "market_sector": self.market_sector,
            "security_type": self.security_type,
            "name": self.name,
        }
        for key in sorted(optional):
            if optional[key]:
                data[key] = optional[key]
        if self.other_identifiers:
            data["other_identifiers"] = [
                {"id_type": id_type, "value": value} for id_type, value in self.other_identifiers
            ]
        return data


@dataclass(frozen=True)
class RegistryLookup:
    status: str
    row: RegistryRow | None = None
    candidates: tuple[RegistryRow, ...] = ()
    duplicate_count: int = 0
    diagnostic: str = ""

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {"status": self.status}
        if self.row is not None:
            data["row"] = self.row.to_json()
        if self.candidates:
            data["candidates"] = [row.to_json() for row in self.candidates]
        if self.duplicate_count:
            data["duplicate_count"] = self.duplicate_count
        if self.diagnostic:
            data["diagnostic"] = self.diagnostic
        return data


class InstrumentRegistrySnapshot:
    """Validated local snapshot used for deterministic P008 lookups."""

    def __init__(
        self,
        *,
        snapshot_id: str,
        generated_at: str,
        source: dict[str, Any],
        rows: Iterable[RegistryRow],
        path: Path | None = None,
        sha256: str = "",
        bytes_count: int = 0,
    ) -> None:
        self.snapshot_id = normalize_text(snapshot_id)
        self.generated_at = normalize_text(generated_at)
        self.source = {str(k): _normalize_json_value(v) for k, v in sorted(source.items())}
        self.rows = tuple(sorted(rows, key=lambda row: row.dedupe_key))
        self.path = path
        self.sha256 = sha256
        self.bytes_count = bytes_count
        if not self.snapshot_id:
            raise RegistrySnapshotError("registry snapshot missing snapshot_id")
        if not self.generated_at:
            raise RegistrySnapshotError("registry snapshot missing generated_at")

    @classmethod
    def load(cls, path: str | Path) -> "InstrumentRegistrySnapshot":
        snapshot_path = Path(path).resolve()
        if not snapshot_path.is_file():
            raise RegistrySnapshotError(f"registry snapshot not found: {snapshot_path}")
        try:
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RegistrySnapshotError(f"registry snapshot is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise RegistrySnapshotError("registry snapshot root must be an object")
        schema_id = normalize_text(raw.get("schema_id", ""))
        if schema_id and schema_id != "cmdrvl.canon.openfigi_registry_snapshot":
            raise RegistrySnapshotError(f"unsupported registry snapshot schema_id: {schema_id}")
        schema_version = normalize_text(raw.get("schema_version", ""))
        if schema_version and schema_version != "1.0":
            raise RegistrySnapshotError(f"unsupported registry snapshot schema_version: {schema_version}")
        rows_raw = raw.get("rows")
        if not isinstance(rows_raw, list):
            raise RegistrySnapshotError("registry snapshot rows must be an array")
        rows = [RegistryRow.from_json(row, idx) for idx, row in enumerate(rows_raw)]
        sha, size = sha256_file(snapshot_path)
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        return cls(
            snapshot_id=raw.get("snapshot_id", ""),
            generated_at=raw.get("generated_at", ""),
            source=source,
            rows=rows,
            path=snapshot_path,
            sha256=sha,
            bytes_count=size,
        )

    @property
    def metadata(self) -> dict[str, object]:
        data: dict[str, object] = {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "source": self.source,
            "row_count": len(self.rows),
        }
        if self.sha256:
            data["sha256"] = self.sha256
        if self.bytes_count:
            data["bytes"] = self.bytes_count
        return data

    def lookup(self, instrument: InstrumentIdentity) -> RegistryLookup:
        return self._lookup_from_matches(
            self._candidate_rows(instrument),
            missing_diagnostic="No row in the local registry snapshot matched this instrument identity.",
            ambiguous_diagnostic="Multiple distinct FIGI rows matched the same filing identity.",
        )

    def lookup_identifier(self, id_type: str, value: object) -> RegistryLookup:
        """Look up rows by an exact identifier only.

        This is the P009-safe path: no ticker, title, name, or weak descriptive
        fields are used as bridge authority.
        """

        key_type = _canonical_lookup_id_type(id_type)
        key_value = _normalize_lookup_value(key_type, value)
        if not key_type:
            return RegistryLookup(
                status="unsupported_id_type",
                diagnostic=f"Unsupported local registry identifier type: {normalize_text(id_type)}",
            )
        if not key_value:
            return RegistryLookup(
                status="missing",
                diagnostic="No identifier value was supplied for local registry lookup.",
            )
        return self._lookup_from_matches(
            [row for row in self.rows if _row_matches_identifier(row, key_type, key_value)],
            missing_diagnostic=f"No row in the local registry snapshot matched {key_type}.",
            ambiguous_diagnostic=f"Multiple distinct FIGI rows matched {key_type}.",
        )

    def lookup_identifiers(self, identifiers: Iterable[tuple[str, object]]) -> RegistryLookup:
        """Return the first non-missing exact-identifier lookup in input order."""

        saw_unsupported = False
        for id_type, value in identifiers:
            lookup = self.lookup_identifier(id_type, value)
            if lookup.status == "unsupported_id_type":
                saw_unsupported = True
                continue
            if lookup.status != "missing":
                return lookup
        if saw_unsupported:
            return RegistryLookup(
                status="unsupported_id_type",
                diagnostic="Only unsupported identifier types were available for local registry lookup.",
            )
        return RegistryLookup(
            status="missing",
            diagnostic="No row in the local registry snapshot matched any exact identifier.",
        )

    def _lookup_from_matches(
        self,
        matches: list[RegistryRow],
        *,
        missing_diagnostic: str,
        ambiguous_diagnostic: str,
    ) -> RegistryLookup:
        if not matches:
            return RegistryLookup(
                status="missing",
                diagnostic=missing_diagnostic,
            )

        deduped: dict[tuple[str, ...], RegistryRow] = {}
        for row in matches:
            deduped.setdefault(row.dedupe_key, row)
        unique_rows = tuple(sorted(deduped.values(), key=lambda row: row.dedupe_key))

        unique_figis = sorted({row.figi for row in unique_rows})
        if len(unique_figis) > 1:
            return RegistryLookup(
                status="ambiguous",
                candidates=unique_rows,
                diagnostic=ambiguous_diagnostic,
            )

        duplicate_count = len(matches) - len(unique_rows)
        status = "duplicate_identical" if duplicate_count else "resolved"
        return RegistryLookup(
            status=status,
            row=unique_rows[0],
            duplicate_count=duplicate_count,
            diagnostic=(
                "Duplicate-identical rows were deduplicated deterministically."
                if duplicate_count
                else ""
            ),
        )

    def _candidate_rows(self, instrument: InstrumentIdentity) -> list[RegistryRow]:
        cusip = normalize_identifier(instrument.cusip)
        isin = normalize_identifier(instrument.isin)
        ticker = normalize_ticker(instrument.ticker)
        exchange = normalize_exchange_key(instrument.exchange)
        normalized_title = normalize_text(instrument.title.normalized_title)
        canonical_value = normalize_text(instrument.canonical_signature)

        exact_matches: list[RegistryRow] = []
        if cusip or isin:
            for row in self.rows:
                if cusip and row.cusip == cusip:
                    exact_matches.append(row)
                elif isin and row.isin == isin:
                    exact_matches.append(row)
            if exact_matches:
                return exact_matches

        signature_matches = [
            row for row in self.rows
            if row.canonical_signature and _public_text_equal(row.canonical_signature, canonical_value)
        ]
        if signature_matches:
            return signature_matches

        title_matches = []
        for row in self.rows:
            row_title = row.normalized_title or normalize_text(row.security_title).upper()
            if row_title != normalized_title:
                continue
            if row.ticker and row.ticker != ticker:
                continue
            if row.exchange and row.exchange != exchange:
                continue
            title_matches.append(row)
        return title_matches


def absent_registry_lookup() -> RegistryLookup:
    return RegistryLookup(
        status="snapshot_absent",
        diagnostic="No local registry snapshot was provided; no live lookup was attempted.",
    )


def invalid_registry_lookup(error: Exception) -> RegistryLookup:
    return RegistryLookup(
        status="snapshot_invalid",
        diagnostic=str(error),
    )


def _other_identifiers(raw: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    raw_items = raw.get("other_identifiers")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            id_type = normalize_key_token(item.get("id_type") or item.get("type") or "")
            value = normalize_key_token(item.get("value", ""))
            if id_type and value:
                pairs.append((id_type, value))
    raw_type = normalize_key_token(raw.get("other_id_type", ""))
    raw_value = normalize_key_token(raw.get("other_id_value", ""))
    if raw_type and raw_value:
        pairs.append((raw_type, raw_value))
    return tuple(sorted(set(pairs)))


def _canonical_lookup_id_type(id_type: object) -> str:
    raw = normalize_key_token(id_type)
    aliases = {
        "BB_GLOBAL": "figi",
        "COMPOSITE_FIGI": "composite_figi",
        "CUSIP": "cusip",
        "CUSIP_NUMBER": "cusip",
        "FIGI": "figi",
        "ID_BB_GLOBAL": "figi",
        "ID_CUSIP": "cusip",
        "ID_ISIN": "isin",
        "ID_SEDOL": "sedol",
        "ISIN": "isin",
        "SEDOL": "sedol",
        "SHARE_CLASS_FIGI": "share_class_figi",
    }
    if raw in aliases:
        return aliases[raw]
    if raw:
        return f"other:{raw}"
    return ""


def _normalize_lookup_value(key_type: str, value: object) -> str:
    if not key_type:
        return ""
    if key_type.startswith("other:"):
        return normalize_key_token(value)
    return normalize_identifier(value)


def _row_matches_identifier(row: RegistryRow, key_type: str, value: str) -> bool:
    if key_type == "figi":
        return value in {row.figi, row.composite_figi, row.share_class_figi}
    if key_type == "composite_figi":
        return row.composite_figi == value
    if key_type == "share_class_figi":
        return row.share_class_figi == value
    if key_type == "cusip":
        return row.cusip == value
    if key_type == "isin":
        return row.isin == value
    if key_type == "sedol":
        return row.sedol == value
    if key_type.startswith("other:"):
        id_type = key_type.split(":", 1)[1]
        return (id_type, value) in row.other_identifiers
    return False


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_json_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_json_value(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return normalize_text(value)
