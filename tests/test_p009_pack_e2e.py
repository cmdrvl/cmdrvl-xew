"""Pack-level E2E tests for XEW-P009."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.pack import run_pack
from cmdrvl_xew.verify import run_verify_pack


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Invalid JSON in {path}: {exc}") from exc


def _minimal_ixbrl() -> str:
    return """<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:link="http://www.w3.org/1999/xlink"
      xmlns:xlink="http://www.w3.org/1999/xlink">
<head><title>P009 Fixture</title></head>
<body>
  <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="entity">Example Trust</ix:nonNumeric>
  <ix:references>
    <link:schemaRef xlink:href="http://xbrl.sec.gov/dei/2025/dei-2025.xsd"/>
  </ix:references>
</body>
</html>"""


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


def _observation_rows() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "p009_observations.v1",
            "source_family": "local_export",
            "source_adapter": "pack_fixture",
            "scope_key": "trust:alpha",
            "accession": "0000000001-26-000001",
            "filed_date": "2026-02-02",
            "report_period": "2026-01-31",
            "observation_ordinal": 0,
            "source_path": "trust-alpha-jan.jsonl#row=1",
            "cusip": "123456AB7",
            "issuer_name": "Bridge Issuer",
            "title_or_description": "Bridge Security",
            "value": "100000000",
        },
        {
            "schema_version": "p009_observations.v1",
            "source_family": "local_export",
            "source_adapter": "pack_fixture",
            "scope_key": "trust:alpha",
            "accession": "0000000001-26-000002",
            "filed_date": "2026-03-02",
            "report_period": "2026-02-28",
            "observation_ordinal": 0,
            "source_path": "trust-alpha-feb.jsonl#row=1",
            "figi": "BBG000000001",
            "issuer_name": "Bridge Issuer",
            "title_or_description": "Bridge Security",
            "value": "100000000",
        },
    ]


def _write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
                "schema_version": "1.0",
                "snapshot_id": "p009-pack-test",
                "generated_at": "2026-06-09T00:00:00Z",
                "source": {"producer": "canon", "dataset": "openfigi"},
                "rows": [{"figi": "BBG000000001", "cusip": "123456AB7", "name": "Bridge Security"}],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class TestP009PackE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)
        self.primary = self.root / "p009-primary.htm"
        self.primary.write_text(_minimal_ixbrl(), encoding="utf-8")
        self.observations = self.root / "p009-observations.jsonl"
        self.observations.write_text(_jsonl(_observation_rows()), encoding="utf-8")
        self.registry = self.root / "p009-registry.json"
        _write_registry(self.registry)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _pack_args(self, out: Path, *, pack_id: str = "p009-pack", registry: bool = True):
        return argparse.Namespace(
            pack_id=pack_id,
            out=str(out),
            primary=str(self.primary),
            issuer_name="Example Trust",
            cik="0000000001",
            accession="0000000001-26-000002",
            form="10-Q",
            filed_date="2026-03-02",
            period_end="2026-02-28",
            primary_document_url="https://www.sec.gov/Archives/edgar/data/1/000000000126000002/p009-primary.htm",
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
            p008_registry_snapshot=str(self.registry) if registry else None,
            p008_require_registry=False,
            p009_observations=[str(self.observations)],
        )

    def test_pack_emits_p009_finding_generated_artifact_and_manifest_entry(self):
        pack_dir = self.root / "pack"

        self.assertEqual(run_pack(self._pack_args(pack_dir)), 0)

        findings = _load_json(pack_dir / "xew_findings.json")
        p009_findings = [item for item in findings["findings"] if item["pattern_id"] == "XEW-P009"]
        self.assertEqual(len(p009_findings), 1)
        instance = p009_findings[0]["observed"]["instances"][0]
        self.assertEqual(instance["kind"], "instrument_identity_drift")
        self.assertEqual(instance["data"]["continuity_class"], "registry_bridged")
        self.assertEqual(
            set(instance["data"]["issue_codes"]),
            {"identifier_basis_transition", "registry_bridge_available"},
        )

        generated_path = pack_dir / "generated" / "instrument_identity_drift.v1.json"
        self.assertTrue(generated_path.is_file())
        generated = _load_json(generated_path)
        self.assertEqual(generated["event_count"], 1)
        self.assertEqual(
            generated["observation_inputs"][0]["path"],
            "artifacts/p009_observations/001_p009-observations.jsonl",
        )

        manifest = _load_json(pack_dir / "pack_manifest.json")
        manifest_paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("generated/instrument_identity_drift.v1.json", manifest_paths)
        self.assertIn("artifacts/p009_observations/001_p009-observations.jsonl", manifest_paths)
        self.assertIn("artifacts/p008_registry_snapshot.json", manifest_paths)

        artifact_paths = {entry["path"] for entry in findings["artifacts"]}
        self.assertIn("generated/instrument_identity_drift.v1.json", artifact_paths)

        verify_args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=True,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False,
        )
        self.assertEqual(run_verify_pack(verify_args), 0)

    def test_pack_without_registry_snapshot_succeeds_with_snapshot_absent_evidence(self):
        pack_dir = self.root / "pack-no-registry"

        self.assertEqual(run_pack(self._pack_args(pack_dir, registry=False)), 0)

        findings = _load_json(pack_dir / "xew_findings.json")
        p009_findings = [item for item in findings["findings"] if item["pattern_id"] == "XEW-P009"]
        self.assertEqual(len(p009_findings), 1)
        instance = p009_findings[0]["observed"]["instances"][0]
        self.assertEqual(instance["data"]["continuity_class"], "weak_collision")
        self.assertEqual(instance["data"]["issue_codes"], ["weak_key_temporal_collision"])
        self.assertEqual(instance["data"]["registry_snapshot"]["status"], "absent")

        generated_path = pack_dir / "generated" / "instrument_identity_drift.v1.json"
        self.assertTrue(generated_path.is_file())
        generated = _load_json(generated_path)
        self.assertEqual(generated["registry_snapshot"]["status"], "absent")
        self.assertEqual(generated["unresolved_candidates"][0]["continuity_class"], "weak_collision")

        manifest = _load_json(pack_dir / "pack_manifest.json")
        manifest_paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("generated/instrument_identity_drift.v1.json", manifest_paths)
        self.assertIn("artifacts/p009_observations/001_p009-observations.jsonl", manifest_paths)
        self.assertNotIn("artifacts/p008_registry_snapshot.json", manifest_paths)

        verify_args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=True,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False,
        )
        self.assertEqual(run_verify_pack(verify_args), 0)

    def test_generated_artifact_is_stable_across_pack_directories(self):
        left = self.root / "pack-left"
        right = self.root / "pack-right"

        self.assertEqual(run_pack(self._pack_args(left, pack_id="p009-left")), 0)
        self.assertEqual(run_pack(self._pack_args(right, pack_id="p009-right")), 0)

        self.assertEqual(
            (left / "generated" / "instrument_identity_drift.v1.json").read_text(encoding="utf-8"),
            (right / "generated" / "instrument_identity_drift.v1.json").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
