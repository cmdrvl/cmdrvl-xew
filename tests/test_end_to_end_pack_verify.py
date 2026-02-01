"""
End-to-end test for pack generation + verification pipeline.

This test validates the full Evidence Pack generation workflow:
1. Creates minimal but valid iXBRL fixture
2. Generates Evidence Pack using pack command
3. Verifies the pack using verify command
4. Ensures deterministic output across runs

Validates integration of all pipeline components including recent fixes.
"""

import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import shutil
import subprocess
import sys

from cmdrvl_xew.pack import run_pack
from cmdrvl_xew.verify import run_verify_pack


class TestEndToEndPackVerify(unittest.TestCase):
    """End-to-end test for pack generation + verification."""

    def setUp(self):
        """Set up test fixtures and workspace."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        # Create fixtures directory
        self.fixtures_dir = self.temp_path / "fixtures"
        self.fixtures_dir.mkdir()

        # Create output directory for generated packs
        self.output_dir = self.temp_path / "output"
        self.output_dir.mkdir()

        # Create minimal iXBRL fixture
        self._write_minimal_ixbrl_fixture()

    def tearDown(self):
        """Clean up test workspace."""
        shutil.rmtree(self.temp_dir)

    def _write_minimal_ixbrl_fixture(self):
        """Create minimal but valid iXBRL document for testing."""

        ixbrl_content = self._minimal_ixbrl_content()

        self.primary_file = self.fixtures_dir / "test_filing.htm"
        self.primary_file.write_text(ixbrl_content, encoding='utf-8')

    def _minimal_ixbrl_content(self):
        """Create minimal iXBRL content (helper for history test)."""
        return '''<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<head>
    <title>Test Filing - Form 8-K</title>
    <meta charset="utf-8"/>
</head>
<body>
    <h1>Test Company Inc.</h1>
    <h2>Current Report (Form 8-K)</h2>

    <div>
        <p>Entity Name: <ix:nonFraction name="dei:EntityRegistrantName"
           contextRef="context_instant">Test Company Inc.</ix:nonFraction></p>

        <p>CIK: <ix:nonFraction name="dei:EntityCentralIndexKey"
           contextRef="context_instant">0001234567</ix:nonFraction></p>

        <p>Document Period End Date: <ix:nonFraction name="dei:DocumentPeriodEndDate"
           contextRef="context_instant">2025-01-31</ix:nonFraction></p>
    </div>

    <ix:resources>
        <ix:context id="context_instant">
            <ix:entity>
                <ix:identifier scheme="http://www.sec.gov/CIK">0001234567</ix:identifier>
            </ix:entity>
            <ix:period>
                <ix:instant>2025-01-31</ix:instant>
            </ix:period>
        </ix:context>
    </ix:resources>

    <ix:references>
        <link:schemaRef xlink:href="http://xbrl.sec.gov/dei/2025/dei-2025.xsd"
                       xmlns:link="http://www.w3.org/1999/xlink"
                       xmlns:xlink="http://www.w3.org/1999/xlink"/>
    </ix:references>
</body>
</html>'''

    def test_end_to_end_pack_generation_and_verification(self):
        """Test full pack generation and verification workflow."""

        pack_dir = self.output_dir / "test_pack"

        # Step 1: Generate Evidence Pack
        pack_args = argparse.Namespace(
            pack_id="test-e2e-pack",
            out=str(pack_dir),
            primary=str(self.primary_file),
            issuer_name="Test Company Inc.",
            cik="0001234567",
            accession="0001234567-25-000001",
            form="8-K",
            filed_date="2025-01-31",
            period_end="2025-01-31",
            primary_document_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/test_filing.htm",
            comparator_accession=None,
            comparator_primary_document_url=None,
            comparator_primary_artifact_path=None,
            history_accession=None,
            history_primary_document_url=None,
            history_primary_artifact_path=None,
            retrieved_at="2025-01-31T12:00:00Z",
            arelle_version="1.2.3-test",
            resolution_mode="offline_preferred",
            derive_artifact_urls=False
        )

        # Run pack generation
        try:
            result = run_pack(pack_args)
            self.assertEqual(result, 0, "Pack generation should succeed")
        except SystemExit as e:
            self.assertEqual(e.code, 0, f"Pack generation failed with exit code {e.code}")

        # Verify pack was created
        self.assertTrue(pack_dir.exists(), "Pack directory should be created")
        self.assertTrue((pack_dir / "pack_manifest.json").exists(), "Pack manifest should exist")
        self.assertTrue((pack_dir / "xew_findings.json").exists(), "Findings file should exist")
        self.assertTrue((pack_dir / "toolchain" / "toolchain.json").exists(), "Toolchain file should exist")
        self.assertTrue((pack_dir / "artifacts").exists(), "Artifacts directory should exist")

        # Step 2: Verify the generated pack
        verify_args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,  # Skip schema validation for test
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False
        )

        try:
            verify_result = run_verify_pack(verify_args)
            self.assertEqual(verify_result, 0, "Pack verification should succeed")
        except SystemExit as e:
            self.assertEqual(e.code, 0, f"Pack verification failed with exit code {e.code}")

    def test_pack_deterministic_output(self):
        """Test that pack generation produces deterministic output."""

        pack_dir_1 = self.output_dir / "test_pack_1"
        pack_dir_2 = self.output_dir / "test_pack_2"

        # Common pack arguments
        base_args = {
            "pack_id": "test-deterministic-pack",
            "primary": str(self.primary_file),
            "issuer_name": "Test Company Inc.",
            "cik": "0001234567",
            "accession": "0001234567-25-000001",
            "form": "8-K",
            "filed_date": "2025-01-31",
            "period_end": "2025-01-31",
            "primary_document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/test_filing.htm",
            "comparator_accession": None,
            "comparator_primary_document_url": None,
            "comparator_primary_artifact_path": None,
            "history_accession": None,
            "history_primary_document_url": None,
            "history_primary_artifact_path": None,
            "retrieved_at": "2025-01-31T12:00:00Z",  # Fixed timestamp for determinism
            "arelle_version": "1.2.3-test",
            "resolution_mode": "offline_preferred",
            "derive_artifact_urls": False
        }

        # Generate first pack
        pack_args_1 = argparse.Namespace(out=str(pack_dir_1), **base_args)
        try:
            result1 = run_pack(pack_args_1)
            self.assertEqual(result1, 0, "First pack generation should succeed")
        except SystemExit as e:
            self.assertEqual(e.code, 0, f"First pack generation failed with exit code {e.code}")

        # Generate second pack
        pack_args_2 = argparse.Namespace(out=str(pack_dir_2), **base_args)
        try:
            result2 = run_pack(pack_args_2)
            self.assertEqual(result2, 0, "Second pack generation should succeed")
        except SystemExit as e:
            self.assertEqual(e.code, 0, f"Second pack generation failed with exit code {e.code}")

        # Compare pack manifests for deterministic output
        with open(pack_dir_1 / "pack_manifest.json") as f:
            manifest1 = json.load(f)

        with open(pack_dir_2 / "pack_manifest.json") as f:
            manifest2 = json.load(f)

        # Compare essential fields (excluding timestamps that may vary)
        self.assertEqual(manifest1["pack_sha256"], manifest2["pack_sha256"],
                        "Pack SHA256 should be identical across runs")
        self.assertEqual(len(manifest1["files"]), len(manifest2["files"]),
                        "File count should be identical")

        # Compare file hashes
        files1 = {f["path"]: f["sha256"] for f in manifest1["files"]}
        files2 = {f["path"]: f["sha256"] for f in manifest2["files"]}
        self.assertEqual(files1, files2, "File hashes should be identical across runs")

        print(f"✅ Deterministic test passed:")
        print(f"   Pack SHA256: {manifest1['pack_sha256']}")
        print(f"   File count: {len(manifest1['files'])}")

    def test_pack_hash_stability_regression(self):
        """Regression test: ensure pack and findings bytes are stable across runs."""

        pack_dir_1 = self.output_dir / "test_hash_pack_1"
        pack_dir_2 = self.output_dir / "test_hash_pack_2"

        base_args = {
            "pack_id": "test-hash-pack",
            "primary": str(self.primary_file),
            "issuer_name": "Test Company Inc.",
            "cik": "0001234567",
            "accession": "0001234567-25-000001",
            "form": "8-K",
            "filed_date": "2025-01-31",
            "period_end": "2025-01-31",
            "primary_document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/test_filing.htm",
            "comparator_accession": None,
            "comparator_primary_document_url": None,
            "comparator_primary_artifact_path": None,
            "history_accession": None,
            "history_primary_document_url": None,
            "history_primary_artifact_path": None,
            "retrieved_at": "2025-01-31T12:00:00Z",
            "arelle_version": "1.2.3-test",
            "resolution_mode": "offline_preferred",
            "derive_artifact_urls": False
        }

        for pack_dir in (pack_dir_1, pack_dir_2):
            pack_args = argparse.Namespace(out=str(pack_dir), **base_args)
            try:
                result = run_pack(pack_args)
                self.assertEqual(result, 0, "Pack generation should succeed")
            except SystemExit as e:
                self.assertEqual(e.code, 0, f"Pack generation failed with exit code {e.code}")

        def _hash_file(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        manifest_hash_1 = _hash_file(pack_dir_1 / "pack_manifest.json")
        manifest_hash_2 = _hash_file(pack_dir_2 / "pack_manifest.json")
        self.assertEqual(
            manifest_hash_1,
            manifest_hash_2,
            "pack_manifest.json bytes should be identical across runs"
        )

        findings_hash_1 = _hash_file(pack_dir_1 / "xew_findings.json")
        findings_hash_2 = _hash_file(pack_dir_2 / "xew_findings.json")
        self.assertEqual(
            findings_hash_1,
            findings_hash_2,
            "xew_findings.json bytes should be identical across runs"
        )

    def test_pack_with_history_window(self):
        """Test pack generation with history window (tests recent fixes)."""

        # Create a second fixture for history
        history_content = self._minimal_ixbrl_content().replace(
            "0001234567-25-000001", "0001234567-24-000012"
        ).replace(
            "2025-01-31", "2024-12-31"
        )

        history_file = self.fixtures_dir / "history_filing.htm"
        history_file.write_text(history_content, encoding='utf-8')

        pack_dir = self.output_dir / "test_pack_with_history"

        # Pack arguments with history
        pack_args = argparse.Namespace(
            pack_id="test-history-pack",
            out=str(pack_dir),
            primary=str(self.primary_file),
            issuer_name="Test Company Inc.",
            cik="0001234567",
            accession="0001234567-25-000001",
            form="8-K",
            filed_date="2025-01-31",
            period_end="2025-01-31",
            primary_document_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/test_filing.htm",
            comparator_accession=None,
            comparator_primary_document_url=None,
            comparator_primary_artifact_path=None,
            history_accession=["0001234567-24-000012"],
            history_primary_document_url=["https://www.sec.gov/Archives/edgar/data/1234567/000123456724000012/history_filing.htm"],
            history_primary_artifact_path=[str(history_file)],
            retrieved_at="2025-01-31T12:00:00Z",
            arelle_version="1.2.3-test",
            resolution_mode="offline_preferred",
            derive_artifact_urls=False
        )

        # This tests the bd-l3i fix (history window processing)
        try:
            result = run_pack(pack_args)
            self.assertEqual(result, 0, "Pack generation with history should succeed")
        except SystemExit as e:
            self.assertEqual(e.code, 0, f"Pack generation with history failed with exit code {e.code}")

        # Verify history artifacts were included
        self.assertTrue((pack_dir / "artifacts" / "history").exists(),
                       "History artifacts directory should exist")

        # Verify toolchain config includes history metadata
        with open(pack_dir / "toolchain" / "toolchain.json") as f:
            toolchain = json.load(f)

        # Should contain history window information in reproducibility metadata
        self.assertIn("history_window", toolchain, "Toolchain should contain history window data")
        self.assertIn("marker_thresholds", toolchain, "Toolchain should include marker thresholds")
        thresholds = toolchain["marker_thresholds"]
        self.assertIn("XEW-M001", thresholds)
        self.assertIn("XEW-M005", thresholds)

    def test_schema_compliance_integration(self):
        """Test that generated packs comply with schema (tests bd-3ap and bd-2m0 fixes)."""

        pack_dir = self.output_dir / "test_schema_compliance"

        # Generate pack
        pack_args = argparse.Namespace(
            pack_id="test-schema-pack",
            out=str(pack_dir),
            primary=str(self.primary_file),
            issuer_name="Test Company Inc.",
            cik="0001234567",
            accession="0001234567-25-000001",
            form="8-K",
            filed_date="2025-01-31",
            period_end="2025-01-31",
            primary_document_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/test_filing.htm",
            comparator_accession=None,
            comparator_primary_document_url=None,
            comparator_primary_artifact_path=None,
            history_accession=None,
            history_primary_document_url=None,
            history_primary_artifact_path=None,
            retrieved_at="2025-01-31T12:00:00Z",
            arelle_version="1.2.3-test",
            resolution_mode="offline_preferred",
            derive_artifact_urls=False
        )

        try:
            result = run_pack(pack_args)
            self.assertEqual(result, 0, "Pack generation should succeed")
        except SystemExit as e:
            self.assertEqual(e.code, 0, f"Pack generation failed")

        # Load and validate findings structure (tests bd-3ap and bd-2m0 fixes)
        with open(pack_dir / "xew_findings.json") as f:
            findings = json.load(f)

        # Verify toolchain object is schema-compliant (bd-3ap fix)
        toolchain = findings["toolchain"]
        self.assertIn("cmdrvl_xew_version", toolchain)
        self.assertIn("arelle_version", toolchain)
        self.assertIn("config", toolchain)

        # Config should be minimal for findings JSON (bd-3ap fix)
        config = toolchain["config"]
        self.assertIn("resolution_mode", config)
        self.assertIn("recorded_at", config)
        self.assertIn("system_info", config)

        # Should not contain large pack metadata in findings toolchain config
        self.assertNotIn("comparator_policy", config)
        self.assertNotIn("history_window", config)

        # Verify input object is schema-compliant (bd-2m0 related)
        input_obj = findings["input"]
        self.assertIn("cik", input_obj)
        self.assertIn("accession", input_obj)
        self.assertIn("form", input_obj)

        print(f"✅ Schema compliance test passed:")
        print(f"   Toolchain config size: {len(str(config))} chars")
        print(f"   Input object fields: {len(input_obj)}")

if __name__ == '__main__':
    unittest.main()
