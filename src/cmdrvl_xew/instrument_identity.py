"""Pure deterministic instrument identity helpers for XEW-P008."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


class InstrumentIdentityError(ValueError):
    """Raised when an instrument identity cannot be built deterministically."""


_SPACE_RE = re.compile(r"\s+")
_COMMON_STOCK_RE = re.compile(
    r"^common\s+stock\s*,\s*\$?\s*(?P<par>[0-9]+(?:\.[0-9]+)?)\s+par\s+value\s+per\s+share$",
    re.IGNORECASE,
)
_DECIMAL_NOTE_RE = re.compile(
    r"^(?P<coupon>[0-9]+(?:\.[0-9]+)?)\s*%\s+notes?\s+due\s+(?P<maturity>[0-9]{4})$",
    re.IGNORECASE,
)
_FRACTION_NOTE_RE = re.compile(
    r"^(?P<whole>[0-9]+)\s+(?P<num>[0-9]+)\s*/\s*(?P<den>[0-9]+)\s*%\s+notes?\s+due\s+(?P<maturity>[0-9]{4})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedInstrumentTitle:
    """Normalized, deterministic representation of a security title."""

    raw_title: str
    normalized_title: str
    instrument_kind: str
    par_value: str = ""
    coupon_percent: str = ""
    maturity_year: str = ""

    def signature_fields(self) -> tuple[tuple[str, str], ...]:
        return (
            ("kind", self.instrument_kind),
            ("title", self.normalized_title),
            ("par_value", self.par_value),
            ("coupon_percent", self.coupon_percent),
            ("maturity_year", self.maturity_year),
        )


@dataclass(frozen=True)
class InstrumentIdentity:
    """Canonical identity candidate extracted from a filing."""

    context_ref: str
    title: ParsedInstrumentTitle
    ticker: str = ""
    exchange: str = ""
    no_trading_symbol: bool = False
    cusip: str = ""
    isin: str = ""

    @property
    def canonical_signature(self) -> str:
        fields = [
            ("context_ref", normalize_key_token(self.context_ref)),
            *self.title.signature_fields(),
            ("ticker", normalize_ticker(self.ticker)),
            ("exchange", normalize_exchange_key(self.exchange)),
            ("no_trading_symbol", "true" if self.no_trading_symbol else "false"),
            ("cusip", normalize_identifier(self.cusip)),
            ("isin", normalize_identifier(self.isin)),
        ]
        return canonical_signature("instrument", fields)

    @property
    def weak_key(self) -> str:
        if self.no_trading_symbol:
            return ""
        ticker = normalize_ticker(self.ticker)
        exchange = normalize_exchange_key(self.exchange)
        if not ticker or not exchange:
            return ""
        return canonical_signature("weak", (("ticker", ticker), ("exchange", exchange)))

    @property
    def weak_key_data(self) -> dict[str, str]:
        return {
            "ticker": normalize_ticker(self.ticker),
            "exchange": normalize_exchange_key(self.exchange),
            "key": self.weak_key,
        }

    @property
    def issue_identity_key(self) -> str:
        strong = normalize_identifier(self.cusip) or normalize_identifier(self.isin)
        if strong:
            return strong
        return self.canonical_signature

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "context_ref": self.context_ref,
            "security_title": self.title.raw_title,
            "normalized_title": self.title.normalized_title,
            "instrument_kind": self.title.instrument_kind,
            "canonical_signature": self.canonical_signature,
            "ticker": normalize_ticker(self.ticker),
            "exchange": normalize_exchange_key(self.exchange),
            "no_trading_symbol": self.no_trading_symbol,
        }
        if self.title.par_value:
            data["par_value"] = self.title.par_value
        if self.title.coupon_percent:
            data["coupon_percent"] = self.title.coupon_percent
        if self.title.maturity_year:
            data["maturity_year"] = self.title.maturity_year
        if self.cusip:
            data["cusip"] = normalize_identifier(self.cusip)
        if self.isin:
            data["isin"] = normalize_identifier(self.isin)
        return data


def normalize_text(value: object) -> str:
    """Normalize human-facing filing text without inventing semantics."""

    if value is None:
        return ""
    text = html.unescape(str(value))
    text = text.replace("\u00a0", " ")
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def normalize_key_token(value: object) -> str:
    return normalize_text(value).upper()


def normalize_ticker(value: object) -> str:
    return normalize_key_token(value)


def normalize_exchange_key(value: object) -> str:
    text = normalize_key_token(value)
    aliases = {
        "NASDAQ STOCK MARKET LLC": "NASDAQ",
        "THE NASDAQ STOCK MARKET LLC": "NASDAQ",
        "NASDAQ GLOBAL SELECT MARKET": "NASDAQ",
        "NASDAQ": "NASDAQ",
        "NYSE": "NYSE",
        "NEW YORK STOCK EXCHANGE": "NYSE",
    }
    return aliases.get(text, text)


def normalize_identifier(value: object) -> str:
    text = normalize_key_token(value)
    return "".join(ch for ch in text if ch.isalnum())


def normalize_decimal_text(value: object) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InstrumentIdentityError(f"invalid decimal value: {value!r}") from exc
    normalized = format(decimal.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized == "-0":
        normalized = "0"
    return normalized


def parse_instrument_title(raw_title: object) -> ParsedInstrumentTitle:
    """Parse supported SEC registered-security titles deterministically."""

    raw = normalize_text(raw_title)
    if not raw:
        raise InstrumentIdentityError("security title is empty")

    common = _COMMON_STOCK_RE.match(raw)
    if common:
        par = normalize_decimal_text(common.group("par"))
        return ParsedInstrumentTitle(
            raw_title=raw,
            normalized_title=f"COMMON STOCK PAR {par}",
            instrument_kind="common_stock",
            par_value=par,
        )

    decimal_note = _DECIMAL_NOTE_RE.match(raw)
    if decimal_note:
        coupon = normalize_decimal_text(decimal_note.group("coupon"))
        maturity = decimal_note.group("maturity")
        return ParsedInstrumentTitle(
            raw_title=raw,
            normalized_title=f"NOTE {coupon}% DUE {maturity}",
            instrument_kind="debt_note",
            coupon_percent=coupon,
            maturity_year=maturity,
        )

    fraction_note = _FRACTION_NOTE_RE.match(raw)
    if fraction_note:
        whole = Decimal(fraction_note.group("whole"))
        numerator = Decimal(fraction_note.group("num"))
        denominator = Decimal(fraction_note.group("den"))
        if denominator == 0:
            raise InstrumentIdentityError("note coupon fraction denominator is zero")
        coupon = normalize_decimal_text(whole + (numerator / denominator))
        maturity = fraction_note.group("maturity")
        return ParsedInstrumentTitle(
            raw_title=raw,
            normalized_title=f"NOTE {coupon}% DUE {maturity}",
            instrument_kind="debt_note",
            coupon_percent=coupon,
            maturity_year=maturity,
        )

    raise InstrumentIdentityError(f"unsupported security title grammar: {raw!r}")


def build_instrument_identity(
    *,
    context_ref: object,
    security_title: object,
    ticker: object = "",
    exchange: object = "",
    no_trading_symbol: bool = False,
    cusip: object = "",
    isin: object = "",
) -> InstrumentIdentity:
    context = normalize_text(context_ref)
    if not context:
        raise InstrumentIdentityError("context_ref is required")
    title = parse_instrument_title(security_title)
    return InstrumentIdentity(
        context_ref=context,
        title=title,
        ticker=normalize_ticker(ticker),
        exchange=normalize_exchange_key(exchange),
        no_trading_symbol=bool(no_trading_symbol),
        cusip=normalize_identifier(cusip),
        isin=normalize_identifier(isin),
    )


def canonical_signature(prefix: str, fields: Iterable[tuple[str, str]]) -> str:
    safe_prefix = normalize_key_token(prefix).lower()
    if not safe_prefix or "|" in safe_prefix:
        raise InstrumentIdentityError("canonical signature prefix is invalid")
    parts = [f"P008:{safe_prefix}"]
    for key, value in fields:
        normalized_key = normalize_key_token(key).lower()
        normalized_value = normalize_text(value)
        if "|" in normalized_key or "=" in normalized_key:
            raise InstrumentIdentityError(f"canonical signature key is invalid: {key!r}")
        normalized_value = normalized_value.replace("|", "%7C").replace("=", "%3D")
        parts.append(f"{normalized_key}={normalized_value}")
    return "|".join(parts)


def instrument_instance_id(signature: str) -> str:
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()
