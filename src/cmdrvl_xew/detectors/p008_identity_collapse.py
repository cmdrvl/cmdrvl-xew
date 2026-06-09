"""XEW-P008: Instrument Identity Collapse.

Detects cases where distinct registered instruments collapse under weak
ticker/exchange identity facts. The detector is deterministic and consumes only
local filing artifacts plus an optional local registry snapshot.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..instrument_identity import (
    InstrumentIdentity,
    InstrumentIdentityError,
    build_instrument_identity,
    instrument_instance_id,
    normalize_exchange_key,
    normalize_text,
    normalize_ticker,
)
from ..instrument_registry import (
    InstrumentRegistrySnapshot,
    RegistryLookup,
    RegistrySnapshotError,
    absent_registry_lookup,
    invalid_registry_lookup,
)
from ..util import qname_object, qname_to_parts


_IX_FACT_RE = re.compile(
    r"<ix:(?P<tag>nonNumeric|nonFraction)\b(?P<attrs>[^>]*)>(?P<body>.*?)</ix:(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(r"([A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(['\"])(.*?)\2", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

_DEI_NAMESPACE = "http://xbrl.sec.gov/dei/2025"
_SECURITY_TITLE_NAMES = {"Security12bTitle", "SecurityTitle"}
_TRADING_SYMBOL_NAMES = {"TradingSymbol"}
_EXCHANGE_NAMES = {"SecurityExchangeName"}
_NO_SYMBOL_NAMES = {"NoTradingSymbolFlag"}
_CUSIP_NAMES = {"SecurityCUSIP", "SecurityCusip", "CUSIP", "Cusip"}
_ISIN_NAMES = {"SecurityISIN", "SecurityIsin", "ISIN", "Isin"}

_P008_MAX_CONTEXTS = 500
_P008_MAX_GROUPS = 100
_P008_MAX_MEMBERS_PER_GROUP = 25


class InstrumentIdentityCollapseDetector(BaseDetector):
    """Detector for XEW-P008 instrument identity collapse."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P008"

    @property
    def pattern_name(self) -> str:
        return "Instrument Identity Collapse"

    @property
    def alert_eligible(self) -> bool:
        return True

    def should_run(self, context: DetectorContext) -> bool:
        return bool(context.primary_document_path)

    def detect(self, context: DetectorContext) -> list[DetectorFinding]:
        fact_groups = self._extract_security_fact_groups(context)
        if not fact_groups:
            return []

        snapshot, registry_error = self._load_registry_snapshot(context)
        candidates, unsupported = self._build_candidates(fact_groups)
        if not candidates:
            return []

        by_weak_key: dict[str, list[tuple[InstrumentIdentity, list[dict[str, object]]]]] = defaultdict(list)
        for instrument, facts in candidates:
            weak_key = instrument.weak_key
            if weak_key:
                by_weak_key[weak_key].append((instrument, facts))

        instances: list[DetectorInstance] = []
        diagnostics: list[dict[str, object]] = []
        if registry_error is not None:
            diagnostics.append(
                {
                    "issue_code": "registry_snapshot_invalid",
                    "message": str(registry_error),
                }
            )

        for weak_key in sorted(by_weak_key):
            members = by_weak_key[weak_key]
            distinct = self._distinct_members(members)
            if len(distinct) < 2:
                continue
            if len(instances) >= _P008_MAX_GROUPS:
                diagnostics.append(
                    {
                        "issue_code": "detector_group_cap_exceeded",
                        "message": f"P008 group cap {_P008_MAX_GROUPS} exceeded; remaining groups suppressed.",
                    }
                )
                break
            instance = self._create_instance(
                weak_key=weak_key,
                members=distinct[:_P008_MAX_MEMBERS_PER_GROUP],
                unsupported=unsupported.get(weak_key, []),
                snapshot=snapshot,
                registry_error=registry_error,
            )
            instances.append(instance)

        if not instances:
            return []

        finding = DetectorFinding(
            finding_id=self.generate_finding_id(context),
            pattern_id=self.pattern_id,
            pattern_name=self.pattern_name,
            alert_eligible=self.alert_eligible,
            status="detected",
            human_review_required=True,
            break_triggers=self.get_break_triggers(),
            instances=instances,
            mechanism=(
                "P008 groups registered-security facts by weak ticker/exchange identity and reports groups "
                "where multiple distinct deterministic instrument signatures collapse under the same weak key."
            ),
            why_not_fatal_yet=(
                "Ticker and exchange facts can be valid filing facts while still being too weak to identify "
                "the individual registered instrument without security-title and registry-backed identity."
            ),
        )
        if diagnostics:
            finding.instances.append(
                DetectorInstance(
                    instance_id=hashlib.sha256(
                        f"P008|diagnostics|{context.accession}|{len(diagnostics)}".encode("utf-8")
                    ).hexdigest(),
                    kind="instrument_identity_collapse",
                    primary=False,
                    data={
                        "issue_codes": sorted({str(item["issue_code"]) for item in diagnostics}),
                        "collapsed_key": {"key": "diagnostics"},
                        "member_count": 0,
                        "members": [],
                        "diagnostics": diagnostics,
                    },
                )
            )
        return [finding]

    def compute_canonical_signature(self, **kwargs) -> str:
        weak_key = normalize_text(kwargs.get("weak_key", ""))
        members = sorted(normalize_text(value) for value in kwargs.get("member_signatures", []))
        return "P008|collapse|" + weak_key + "|" + "|".join(members)

    def get_break_triggers(self) -> list[dict[str, str]]:
        return [
            {
                "id": "XEW-BT008",
                "summary": "Multiple distinct registered instruments share the same weak ticker/exchange identity.",
            }
        ]

    def _load_registry_snapshot(
        self,
        context: DetectorContext,
    ) -> tuple[InstrumentRegistrySnapshot | None, Exception | None]:
        snapshot_path = normalize_text(context.config.get("p008_registry_snapshot", ""))
        if not snapshot_path:
            return None, None
        try:
            return InstrumentRegistrySnapshot.load(snapshot_path), None
        except RegistrySnapshotError as exc:
            return None, exc

    def _extract_security_fact_groups(self, context: DetectorContext) -> dict[str, dict[str, list[dict[str, object]]]]:
        groups: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))

        for fact in getattr(context.xbrl_model, "facts", []) or []:
            extracted = self._extract_arelle_fact(fact)
            if extracted is None:
                continue
            context_ref, field, evidence = extracted
            groups[context_ref][field].append(evidence)

        if groups:
            return self._cap_contexts(groups)

        return self._cap_contexts(self._extract_html_facts(Path(context.primary_document_path)))

    def _extract_arelle_fact(self, fact: Any) -> tuple[str, str, dict[str, object]] | None:
        qname = getattr(fact, "qname", None)
        if qname is None:
            return None
        try:
            _namespace, local_name, prefixed = qname_to_parts(qname)
        except Exception:
            local_name = str(qname).split("}")[-1].split(":")[-1]
            prefixed = str(qname)
        field = self._field_for_local_name(local_name)
        if not field:
            return None
        context_obj = getattr(fact, "context", None)
        context_ref = normalize_text(getattr(context_obj, "id", "") or getattr(fact, "contextID", ""))
        if not context_ref:
            return None
        value = normalize_text(getattr(fact, "value", ""))
        evidence = {
            "concept": self._concept_obj(qname, local_name, prefixed),
            "context_ref": context_ref,
            "value": value,
            "source": {"extraction": "arelle"},
        }
        return context_ref, field, evidence

    def _extract_html_facts(self, primary_path: Path) -> dict[str, dict[str, list[dict[str, object]]]]:
        groups: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
        try:
            text = primary_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}

        for match in _IX_FACT_RE.finditer(text):
            attrs = self._parse_attrs(match.group("attrs"))
            name = attrs.get("name", "")
            local_name = name.split("}")[-1].split(":")[-1]
            field = self._field_for_local_name(local_name)
            if not field:
                continue
            context_ref = normalize_text(attrs.get("contextRef") or attrs.get("contextref") or "")
            if not context_ref:
                continue
            body = _TAG_RE.sub("", match.group("body"))
            value = normalize_text(body)
            evidence = {
                "concept": self._concept_obj(name, local_name, name),
                "context_ref": context_ref,
                "value": value,
                "source": {"extraction": "inline_html"},
            }
            groups[context_ref][field].append(evidence)
        return groups

    def _parse_attrs(self, raw_attrs: str) -> dict[str, str]:
        attrs = {}
        for key, _quote, value in _ATTR_RE.findall(raw_attrs):
            attrs[key] = value
        return attrs

    def _field_for_local_name(self, local_name: str) -> str:
        if local_name in _SECURITY_TITLE_NAMES:
            return "security_title"
        if local_name in _TRADING_SYMBOL_NAMES:
            return "trading_symbol"
        if local_name in _EXCHANGE_NAMES:
            return "exchange"
        if local_name in _NO_SYMBOL_NAMES:
            return "no_trading_symbol"
        if local_name in _CUSIP_NAMES:
            return "cusip"
        if local_name in _ISIN_NAMES:
            return "isin"
        return ""

    def _concept_obj(self, qname: Any, local_name: str, prefixed: str | None) -> dict[str, str]:
        try:
            return qname_object(qname)
        except Exception:
            obj = {
                "clark": f"{{{_DEI_NAMESPACE}}}{local_name}",
                "namespace": _DEI_NAMESPACE,
                "local_name": local_name,
            }
            if prefixed:
                obj["prefixed"] = prefixed
            return obj

    def _cap_contexts(
        self,
        groups: dict[str, dict[str, list[dict[str, object]]]],
    ) -> dict[str, dict[str, list[dict[str, object]]]]:
        capped: dict[str, dict[str, list[dict[str, object]]]] = {}
        for context_ref in sorted(groups)[:_P008_MAX_CONTEXTS]:
            capped[context_ref] = {
                field: sorted(values, key=lambda item: (str(item.get("value", "")), str(item.get("context_ref", ""))))
                for field, values in sorted(groups[context_ref].items())
            }
        return capped

    def _build_candidates(
        self,
        fact_groups: dict[str, dict[str, list[dict[str, object]]]],
    ) -> tuple[
        list[tuple[InstrumentIdentity, list[dict[str, object]]]],
        dict[str, list[dict[str, object]]],
    ]:
        candidates: list[tuple[InstrumentIdentity, list[dict[str, object]]]] = []
        unsupported: dict[str, list[dict[str, object]]] = defaultdict(list)
        for context_ref in sorted(fact_groups):
            group = fact_groups[context_ref]
            titles = self._unique_values(group.get("security_title", []))
            if not titles:
                continue
            ticker = self._first_value(group.get("trading_symbol", []))
            exchange = self._first_value(group.get("exchange", []))
            no_symbol = self._bool_value(self._first_value(group.get("no_trading_symbol", [])))
            cusip = self._first_value(group.get("cusip", []))
            isin = self._first_value(group.get("isin", []))

            for title in titles:
                facts = self._facts_for_candidate(group, title)
                try:
                    instrument = build_instrument_identity(
                        context_ref=context_ref,
                        security_title=title,
                        ticker=ticker,
                        exchange=exchange,
                        no_trading_symbol=no_symbol,
                        cusip=cusip,
                        isin=isin,
                    )
                except InstrumentIdentityError as exc:
                    weak_key = self._weak_key_from_raw(ticker=ticker, exchange=exchange, no_symbol=no_symbol)
                    if weak_key:
                        unsupported[weak_key].append(
                            {
                                "context_ref": context_ref,
                                "security_title": normalize_text(title),
                                "ticker": normalize_ticker(ticker),
                                "exchange": normalize_exchange_key(exchange),
                                "diagnostic": str(exc),
                                "facts": facts,
                            }
                        )
                    continue
                candidates.append((instrument, facts))
        return candidates, unsupported

    def _unique_values(self, facts: list[dict[str, object]]) -> list[str]:
        values = sorted({normalize_text(fact.get("value", "")) for fact in facts if normalize_text(fact.get("value", ""))})
        return values

    def _first_value(self, facts: list[dict[str, object]]) -> str:
        values = self._unique_values(facts)
        return values[0] if values else ""

    def _bool_value(self, value: str) -> bool:
        return normalize_text(value).lower() in {"true", "1", "yes", "y"}

    def _facts_for_candidate(
        self,
        group: dict[str, list[dict[str, object]]],
        title: str,
    ) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        for field in ("security_title", "trading_symbol", "exchange", "no_trading_symbol", "cusip", "isin"):
            for fact in group.get(field, []):
                if field == "security_title" and normalize_text(fact.get("value", "")) != normalize_text(title):
                    continue
                selected.append(dict(fact))
        selected.sort(key=lambda item: (
            str(item.get("context_ref", "")),
            str(item.get("concept", {}).get("clark", "")) if isinstance(item.get("concept"), dict) else "",
            str(item.get("value", "")),
        ))
        return selected

    def _weak_key_from_raw(self, *, ticker: str, exchange: str, no_symbol: bool) -> str:
        if no_symbol:
            return ""
        ticker_key = normalize_ticker(ticker)
        exchange_key = normalize_exchange_key(exchange)
        if not ticker_key or not exchange_key:
            return ""
        return f"P008:weak|ticker={ticker_key}|exchange={exchange_key}"

    def _distinct_members(
        self,
        members: list[tuple[InstrumentIdentity, list[dict[str, object]]]],
    ) -> list[tuple[InstrumentIdentity, list[dict[str, object]]]]:
        deduped: dict[str, tuple[InstrumentIdentity, list[dict[str, object]]]] = {}
        for instrument, facts in members:
            deduped.setdefault(instrument.issue_identity_key, (instrument, facts))
        return [
            deduped[key]
            for key in sorted(deduped, key=lambda item: deduped[item][0].canonical_signature)
        ]

    def _create_instance(
        self,
        *,
        weak_key: str,
        members: list[tuple[InstrumentIdentity, list[dict[str, object]]]],
        unsupported: list[dict[str, object]],
        snapshot: InstrumentRegistrySnapshot | None,
        registry_error: Exception | None,
    ) -> DetectorInstance:
        member_json = []
        issue_codes = {"weak_identity_collision"}
        ambiguous_registry = False
        missing_registry = False

        for instrument, facts in members:
            lookup = self._lookup_registry(instrument, snapshot, registry_error)
            if lookup.status in {"missing", "snapshot_absent"}:
                missing_registry = True
            if lookup.status in {"ambiguous", "snapshot_invalid"}:
                ambiguous_registry = True

            item = instrument.to_json()
            item["registry"] = lookup.to_json()
            item["facts"] = facts
            member_json.append(item)

        if missing_registry:
            issue_codes.add("registry_snapshot_missing")
        if ambiguous_registry:
            issue_codes.add("registry_snapshot_ambiguous")
        if unsupported:
            issue_codes.add("unsupported_security_title")

        member_json.sort(key=lambda item: str(item.get("canonical_signature", "")))
        unsupported = sorted(
            unsupported,
            key=lambda item: (
                str(item.get("context_ref", "")),
                str(item.get("security_title", "")),
            ),
        )
        first_member = members[0][0]
        signature = self.compute_canonical_signature(
            weak_key=weak_key,
            member_signatures=[instrument.canonical_signature for instrument, _facts in members],
        )

        data: dict[str, object] = {
            "issue_codes": sorted(issue_codes),
            "collapsed_key": first_member.weak_key_data,
            "member_count": len(member_json),
            "members": member_json,
            "deterministic_repair": [
                {
                    "target": "dei:Security12bTitle",
                    "action": "Retain each registered security title as the instrument-level identity discriminator.",
                },
                {
                    "target": "registry_snapshot.figi",
                    "action": "Attach the registry FIGI from the local canon/OpenFIGI snapshot when the match is resolved.",
                },
            ],
        }
        if unsupported:
            data["unsupported_candidates"] = unsupported
        if snapshot is not None:
            data["registry_snapshot"] = snapshot.metadata
        elif registry_error is not None:
            data["registry_snapshot"] = {"status": "invalid", "diagnostic": str(registry_error)}
        else:
            data["registry_snapshot"] = {"status": "absent"}

        return DetectorInstance(
            instance_id=instrument_instance_id(signature),
            kind="instrument_identity_collapse",
            primary=True,
            data=data,
        )

    def _lookup_registry(
        self,
        instrument: InstrumentIdentity,
        snapshot: InstrumentRegistrySnapshot | None,
        registry_error: Exception | None,
    ) -> RegistryLookup:
        if registry_error is not None:
            return invalid_registry_lookup(registry_error)
        if snapshot is None:
            return absent_registry_lookup()
        return snapshot.lookup(instrument)
