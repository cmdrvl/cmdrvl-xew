"""Detector-level tests for XEW-P008 Instrument Identity Collapse."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cmdrvl_xew.detectors._base import DetectorContext
from cmdrvl_xew.detectors.p008_identity_collapse import InstrumentIdentityCollapseDetector


class _QName:
    def __init__(self, local_name: str):
        self.namespaceURI = "http://xbrl.sec.gov/dei/2025"
        self.localName = local_name
        self.prefix = "dei"


def _fact(local_name: str, value: str, context_id: str):
    return SimpleNamespace(
        qname=_QName(local_name),
        value=value,
        context=SimpleNamespace(id=context_id),
    )


def _context(primary: Path, facts, *, registry_snapshot: str = "") -> DetectorContext:
    return DetectorContext(
        primary_document_path=str(primary),
        artifacts_dir=str(primary.parent),
        cik="0000789019",
        accession="0001193125-26-191507",
        form="10-Q",
        filed_date="2026-04-24",
        xbrl_model=SimpleNamespace(facts=facts),
        config={"p008_registry_snapshot": registry_snapshot},
    )


def _msft_facts():
    facts = []
    for context, title in (
        ("stock", "Common stock, $0.00000625 par value per share"),
        ("note-2028", "3.125% Notes due 2028"),
        ("note-2033", "2.625% Notes due 2033"),
    ):
        facts.extend(
            [
                _fact("Security12bTitle", title, context),
                _fact("TradingSymbol", "MSFT", context),
                _fact("SecurityExchangeName", "Nasdaq", context),
            ]
        )
    return facts


def _write_registry(path: Path):
    rows = [
        {
            "figi": "BBG000BPH459",
            "ticker": "MSFT",
            "exchange": "Nasdaq",
            "normalized_title": "COMMON STOCK PAR 0.00000625",
            "composite_figi": "BBG000BPH459",
            "share_class_figi": "BBG001S5TD05",
            "market_sector": "Equity",
            "security_type": "Common Stock",
        },
        {
            "figi": "BBG005NPW5Z2",
            "ticker": "MSFT",
            "exchange": "Nasdaq",
            "normalized_title": "NOTE 3.125% DUE 2028",
            "market_sector": "Corp",
            "security_type": "Corporate Bond",
        },
        {
            "figi": "BBG004HDR2M6",
            "ticker": "MSFT",
            "exchange": "Nasdaq",
            "normalized_title": "NOTE 2.625% DUE 2033",
            "market_sector": "Corp",
            "security_type": "Corporate Bond",
        },
    ]
    snapshot = {
        "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
        "schema_version": "1.0",
        "snapshot_id": "p008-msft-demo",
        "generated_at": "2026-06-09T00:00:00Z",
        "source": {"provider": "canon", "dataset": "openfigi"},
        "rows": rows,
    }
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestP008Detector(unittest.TestCase):
    def setUp(self):
        self.detector = InstrumentIdentityCollapseDetector()

    def test_properties(self):
        self.assertEqual(self.detector.pattern_id, "XEW-P008")
        self.assertEqual(self.detector.pattern_name, "Instrument Identity Collapse")
        self.assertTrue(self.detector.alert_eligible)

    def test_detects_msft_weak_key_collapse_without_registry_live_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text("<html></html>", encoding="utf-8")
            context = _context(primary, _msft_facts())

            findings = self.detector.detect(context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.pattern_id, "XEW-P008")
        self.assertEqual(len(finding.instances), 1)
        data = finding.instances[0].data
        self.assertEqual(data["member_count"], 3)
        self.assertIn("weak_identity_collision", data["issue_codes"])
        self.assertIn("registry_snapshot_missing", data["issue_codes"])
        self.assertEqual(data["collapsed_key"]["ticker"], "MSFT")
        self.assertEqual(data["collapsed_key"]["exchange"], "NASDAQ")
        self.assertEqual({member["registry"]["status"] for member in data["members"]}, {"snapshot_absent"})

    def test_registry_snapshot_resolves_all_three_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text("<html></html>", encoding="utf-8")
            registry = Path(tmp) / "registry.json"
            _write_registry(registry)
            context = _context(primary, _msft_facts(), registry_snapshot=str(registry))

            finding = self.detector.detect(context)[0]

        statuses = [member["registry"]["status"] for member in finding.instances[0].data["members"]]
        figis = [member["registry"]["row"]["figi"] for member in finding.instances[0].data["members"]]
        self.assertEqual(statuses, ["resolved", "resolved", "resolved"])
        self.assertEqual(figis, ["BBG005NPW5Z2", "BBG004HDR2M6", "BBG000BPH459"])

    def test_repeated_duplicate_facts_do_not_create_extra_members(self):
        facts = _msft_facts()
        facts.extend(
            [
                _fact("Security12bTitle", "3.125% Notes due 2028", "note-2028"),
                _fact("TradingSymbol", "MSFT", "note-2028"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text("<html></html>", encoding="utf-8")
            context = _context(primary, facts)

            finding = self.detector.detect(context)[0]

        self.assertEqual(finding.instances[0].data["member_count"], 3)

    def test_single_instrument_under_weak_key_emits_no_finding(self):
        facts = [
            _fact("Security12bTitle", "Common stock, $0.00000625 par value per share", "stock"),
            _fact("TradingSymbol", "MSFT", "stock"),
            _fact("SecurityExchangeName", "Nasdaq", "stock"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text("<html></html>", encoding="utf-8")
            context = _context(primary, facts)

            findings = self.detector.detect(context)

        self.assertEqual(findings, [])

    def test_unsupported_title_in_collapse_group_is_diagnostic_not_guess(self):
        facts = _msft_facts()
        facts.extend(
            [
                _fact("Security12bTitle", "Debt Securities", "unsupported"),
                _fact("TradingSymbol", "MSFT", "unsupported"),
                _fact("SecurityExchangeName", "Nasdaq", "unsupported"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text("<html></html>", encoding="utf-8")
            context = _context(primary, facts)

            finding = self.detector.detect(context)[0]

        data = finding.instances[0].data
        self.assertIn("unsupported_security_title", data["issue_codes"])
        self.assertEqual(data["member_count"], 3)
        self.assertEqual(data["unsupported_candidates"][0]["security_title"], "Debt Securities")
        self.assertIn("unsupported security title grammar", data["unsupported_candidates"][0]["diagnostic"])

    def test_noisy_filing_group_cap_is_stable_and_explicit(self):
        facts = []
        for i in range(105):
            ticker = f"T{i:03d}"
            for suffix, title in (
                ("stock", "Common stock, $0.00000625 par value per share"),
                ("note", "3.125% Notes due 2028"),
            ):
                context_id = f"{ticker}-{suffix}"
                facts.extend(
                    [
                        _fact("Security12bTitle", title, context_id),
                        _fact("TradingSymbol", ticker, context_id),
                        _fact("SecurityExchangeName", "Nasdaq", context_id),
                    ]
                )

        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text("<html></html>", encoding="utf-8")
            context = _context(primary, facts)

            finding = self.detector.detect(context)[0]

        primary_instances = [instance for instance in finding.instances if instance.primary]
        diagnostic_instances = [instance for instance in finding.instances if not instance.primary]
        self.assertEqual(len(primary_instances), 100)
        self.assertEqual(len(diagnostic_instances), 1)
        self.assertIn("detector_group_cap_exceeded", diagnostic_instances[0].data["issue_codes"])

    def test_html_fallback_extracts_inline_facts_without_arelle_model(self):
        html = """<!DOCTYPE html>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
  <body>
    <ix:nonNumeric name="dei:Security12bTitle" contextRef="stock">Common stock, $0.00000625 par value per share</ix:nonNumeric>
    <ix:nonNumeric name="dei:TradingSymbol" contextRef="stock">MSFT</ix:nonNumeric>
    <ix:nonNumeric name="dei:SecurityExchangeName" contextRef="stock">Nasdaq</ix:nonNumeric>
    <ix:nonNumeric name="dei:Security12bTitle" contextRef="note-2028">3.125% Notes due 2028</ix:nonNumeric>
    <ix:nonNumeric name="dei:TradingSymbol" contextRef="note-2028">MSFT</ix:nonNumeric>
    <ix:nonNumeric name="dei:SecurityExchangeName" contextRef="note-2028">Nasdaq</ix:nonNumeric>
  </body>
</html>"""
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.htm"
            primary.write_text(html, encoding="utf-8")
            context = _context(primary, facts=[])

            finding = self.detector.detect(context)[0]

        self.assertEqual(finding.instances[0].data["member_count"], 2)
        self.assertEqual(finding.instances[0].data["members"][0]["facts"][0]["source"]["extraction"], "inline_html")

    def test_runtime_boundary_imports_no_live_provider_modules(self):
        forbidden_loaded = {
            name
            for name in sys.modules
            if name.startswith(("requests", "urllib3", "openai", "anthropic"))
            or "openfigi" in name.lower()
            or "twinning" in name.lower()
        }
        self.assertEqual(forbidden_loaded, set())


if __name__ == "__main__":
    unittest.main()
