"""Pack-level E2E and golden tests for XEW-P008."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.pack import run_pack
from cmdrvl_xew.verify import run_verify_pack


GOLDEN_DIR = Path(__file__).parent / "golden"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Invalid JSON in {path}: {exc}") from exc


def _p008_ixbrl() -> str:
    return """<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:link="http://www.w3.org/1999/xlink"
      xmlns:xlink="http://www.w3.org/1999/xlink">
<head><title>Microsoft P008 Fixture</title></head>
<body>
  <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="entity">Microsoft Corporation</ix:nonNumeric>
  <ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="entity">0000789019</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="entity">2026-03-31</ix:nonNumeric>

  <ix:nonNumeric name="dei:Security12bTitle" contextRef="stock">Common stock, $0.00000625 par value per share</ix:nonNumeric>
  <ix:nonNumeric name="dei:TradingSymbol" contextRef="stock">MSFT</ix:nonNumeric>
  <ix:nonNumeric name="dei:SecurityExchangeName" contextRef="stock">Nasdaq</ix:nonNumeric>

  <ix:nonNumeric name="dei:Security12bTitle" contextRef="note-2028">3.125% Notes due 2028</ix:nonNumeric>
  <ix:nonNumeric name="dei:TradingSymbol" contextRef="note-2028">MSFT</ix:nonNumeric>
  <ix:nonNumeric name="dei:SecurityExchangeName" contextRef="note-2028">Nasdaq</ix:nonNumeric>

  <ix:nonNumeric name="dei:Security12bTitle" contextRef="note-2033">2.625% Notes due 2033</ix:nonNumeric>
  <ix:nonNumeric name="dei:TradingSymbol" contextRef="note-2033">MSFT</ix:nonNumeric>
  <ix:nonNumeric name="dei:SecurityExchangeName" contextRef="note-2033">Nasdaq</ix:nonNumeric>

  <ix:references>
    <link:schemaRef xlink:href="http://xbrl.sec.gov/dei/2025/dei-2025.xsd"/>
  </ix:references>
</body>
</html>"""


def _write_registry(path: Path, *, omit_2033: bool = False) -> None:
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
            "name": "MICROSOFT CORP",
        },
        {
            "figi": "BBG005NPW5Z2",
            "ticker": "MSFT",
            "exchange": "Nasdaq",
            "normalized_title": "NOTE 3.125% DUE 2028",
            "market_sector": "Corp",
            "security_type": "Corporate Bond",
            "name": "MICROSOFT CORP",
        },
    ]
    if not omit_2033:
        rows.append(
            {
                "figi": "BBG004HDR2M6",
                "ticker": "MSFT",
                "exchange": "Nasdaq",
                "normalized_title": "NOTE 2.625% DUE 2033",
                "market_sector": "Corp",
                "security_type": "Corporate Bond",
                "name": "MICROSOFT CORP",
            }
        )
    snapshot = {
        "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
        "schema_version": "1.0",
        "snapshot_id": "p008-msft-demo",
        "generated_at": "2026-06-09T00:00:00Z",
        "source": {"provider": "canon", "dataset": "openfigi"},
        "rows": rows,
    }
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestP008PackE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)
        self.primary = self.root / "msft-p008.htm"
        self.primary.write_text(_p008_ixbrl(), encoding="utf-8")
        self.registry = self.root / "p008-registry.json"
        _write_registry(self.registry)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _pack_args(self, out: Path, *, registry: Path | None = None, require_registry: bool = False):
        return argparse.Namespace(
            pack_id="p008-msft-pack",
            out=str(out),
            primary=str(self.primary),
            issuer_name="Microsoft Corporation",
            cik="0000789019",
            accession="0001193125-26-191507",
            form="10-Q",
            filed_date="2026-04-24",
            period_end="2026-03-31",
            primary_document_url="https://www.sec.gov/Archives/edgar/data/789019/000119312526191507/msft-20260331.htm",
            comparator_accession=None,
            comparator_primary_document_url=None,
            comparator_primary_artifact_path=None,
            history_accession=None,
            history_primary_document_url=None,
            history_primary_artifact_path=None,
            retrieved_at="2026-06-09T00:00:00Z",
            arelle_version="test-no-arelle",
            resolution_mode="offline_preferred",
            require_arelle=False,
            no_arelle=True,
            arelle_xdg_config_home=None,
            derive_artifact_urls=False,
            p001_conflict_mode="rounded",
            p008_registry_snapshot=str(registry) if registry else None,
            p008_require_registry=require_registry,
        )

    def test_p008_e001_e002_pack_emits_finding_generated_artifact_and_manifest_entry(self):
        pack_dir = self.root / "pack"

        result = run_pack(self._pack_args(pack_dir, registry=self.registry))

        self.assertEqual(result, 0)
        findings = _load_json(pack_dir / "xew_findings.json")
        p008_findings = [item for item in findings["findings"] if item["pattern_id"] == "XEW-P008"]
        self.assertEqual(len(p008_findings), 1)
        instance = p008_findings[0]["observed"]["instances"][0]
        self.assertEqual(instance["kind"], "instrument_identity_collapse")
        self.assertEqual(instance["data"]["member_count"], 3)
        self.assertEqual(
            [member["registry"]["row"]["figi"] for member in instance["data"]["members"]],
            ["BBG005NPW5Z2", "BBG004HDR2M6", "BBG000BPH459"],
        )

        generated_path = pack_dir / "generated" / "instrument_identity_collapse.v1.json"
        self.assertTrue(generated_path.is_file())
        generated = _load_json(generated_path)
        self.assertEqual(generated["collapse_group_count"], 1)

        manifest = _load_json(pack_dir / "pack_manifest.json")
        manifest_paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("generated/instrument_identity_collapse.v1.json", manifest_paths)
        self.assertIn("artifacts/p008_registry_snapshot.json", manifest_paths)

        verify_args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=True,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False,
        )
        self.assertEqual(run_verify_pack(verify_args), 0)

    def test_p008_e003_missing_registry_row_is_explicit_not_guessed(self):
        partial_registry = self.root / "partial-registry.json"
        _write_registry(partial_registry, omit_2033=True)
        pack_dir = self.root / "pack-missing"

        self.assertEqual(run_pack(self._pack_args(pack_dir, registry=partial_registry)), 0)
        findings = _load_json(pack_dir / "xew_findings.json")
        instance = [item for item in findings["findings"] if item["pattern_id"] == "XEW-P008"][0]["observed"]["instances"][0]
        statuses = [member["registry"]["status"] for member in instance["data"]["members"]]

        self.assertIn("missing", statuses)
        self.assertIn("registry_snapshot_missing", instance["data"]["issue_codes"])
        missing_members = [member for member in instance["data"]["members"] if member["registry"]["status"] == "missing"]
        self.assertNotIn("row", missing_members[0]["registry"])

    def test_p008_e006_generated_artifact_matches_exact_golden(self):
        pack_dir = self.root / "pack-golden"
        self.assertEqual(run_pack(self._pack_args(pack_dir, registry=self.registry)), 0)

        actual = (pack_dir / "generated" / "instrument_identity_collapse.v1.json").read_text(encoding="utf-8")
        expected = (GOLDEN_DIR / "p008_instrument_identity_collapse.v1.json").read_text(encoding="utf-8")
        self.assertEqual(actual, expected)

    def test_p008_e008_strict_missing_snapshot_fails_before_live_lookup(self):
        pack_dir = self.root / "pack-strict-missing"

        with self.assertRaises(SystemExit) as ctx:
            run_pack(self._pack_args(pack_dir, registry=None, require_registry=True))

        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
