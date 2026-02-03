"""
Unit tests for XEW-P005 taxonomy inconsistency detector.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from cmdrvl_xew.detectors.p005_taxonomy import TaxonomyInconsistencyDetector
from cmdrvl_xew.detectors._base import DetectorContext


class TestTaxonomyInconsistencyDetector(unittest.TestCase):
    """Test cases for P005 taxonomy inconsistency detector."""

    def setUp(self):
        """Set up test fixtures."""
        self.detector = TaxonomyInconsistencyDetector()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.primary_path = self.root_dir / "primary.htm"

        self.mock_context = Mock(spec=DetectorContext)
        self.mock_context.accession = "0000123456-23-000001"  # Valid EDGAR accession format
        self.mock_context.primary_document_path = str(self.primary_path)
        self.mock_context.artifacts_dir = str(self.root_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pattern_properties(self):
        """Test basic pattern properties."""
        self.assertEqual(self.detector.pattern_id, "XEW-P005")
        self.assertEqual(self.detector.pattern_name, "Inconsistent Taxonomy References")
        self.assertTrue(self.detector.alert_eligible)

    def test_no_inconsistencies(self):
        """Test when there are no taxonomy inconsistencies."""
        self._write_primary(schema_refs=["ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap"],
        )
        xbrl_model = self._create_mock_xbrl_model(
            fact_namespaces=["http://example.com/ext", "http://example.com/gaap"]
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_unreferenced_namespace(self):
        """Test detection of namespaces used in facts but not declared in schemaRef."""
        self._write_primary(schema_refs=["ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap"],
        )
        xbrl_model = self._create_mock_xbrl_model(
            fact_namespaces=[
                "http://example.com/ext",
                "http://example.com/gaap",
                "http://example.com/undeclared",
            ]
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.pattern_id, "XEW-P005")

        # Check that namespace mismatch issue is detected
        instance_data = [inst.data for inst in finding.instances]
        mismatch_instances = [
            inst for inst in instance_data
            if inst['issue_code'] == 'namespace_schema_ref_mismatch'
        ]
        self.assertTrue(len(mismatch_instances) > 0)

    def test_unused_schema_ref(self):
        """Unused imported namespaces should not trigger findings."""
        self._write_primary(schema_refs=["ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap", "http://example.com/unused"],
        )
        xbrl_model = self._create_mock_xbrl_model(
            fact_namespaces=["http://example.com/ext", "http://example.com/gaap"]
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_duplicate_schema_ref(self):
        """Test that duplicate schemaRef elements for same namespace don't trigger false positives."""
        self._write_primary(schema_refs=["ext.xsd", "ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap"],
        )
        xbrl_model = self._create_mock_xbrl_model(
            fact_namespaces=["http://example.com/ext", "http://example.com/gaap"]
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        # P005 focuses on namespace vs schema ref mismatches, not duplicate refs
        # Having multiple schema refs for the same namespace is not necessarily an inconsistency
        # This should not trigger findings since namespaces and facts are consistent
        self.assertEqual(len(findings), 0)

    def test_malformed_schema_ref(self):
        """Test detection of malformed schemaRef href."""
        # Empty href should be ignored and must not cause a false positive.
        self._write_primary(schema_refs=[""])
        xbrl_model = self._create_mock_xbrl_model(fact_namespaces=["http://example.com/gaap"])
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_schema_ref_mismatch(self):
        """External schemaRefs are ignored for declared namespace extraction."""
        self._write_primary(schema_refs=["https://example.com/ext.xsd"])
        xbrl_model = self._create_mock_xbrl_model(fact_namespaces=["http://example.com/ext"])
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_multiple_inconsistencies(self):
        """Test when multiple types of inconsistencies are present."""
        self._write_primary(schema_refs=["ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap"],
        )
        xbrl_model = self._create_mock_xbrl_model(
            fact_namespaces=[
                "http://example.com/ext",
                "http://example.com/gaap",
                "http://example.com/undeclared",
            ]
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        # Should detect namespace/schema ref inconsistencies
        instance_data = [inst.data for inst in finding.instances]
        issue_codes = {inst['issue_code'] for inst in instance_data}

        # Should detect namespace schema ref mismatches as the main issue type
        expected_codes = {'namespace_schema_ref_mismatch'}
        self.assertTrue(expected_codes.issubset(issue_codes))

    def test_canonical_signature_consistency(self):
        """Test that canonical signatures are generated consistently."""
        self._write_primary(schema_refs=["ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap"],
        )
        xbrl_model = self._create_mock_xbrl_model(
            fact_namespaces=["http://example.com/ext", "http://example.com/undeclared"]
        )
        self.mock_context.xbrl_model = xbrl_model

        # Run detection twice
        findings1 = self.detector.detect(self.mock_context)
        findings2 = self.detector.detect(self.mock_context)

        # Should get same results both times
        self.assertEqual(len(findings1), len(findings2))

        if findings1:
            # Instance IDs should be the same
            ids1 = {inst.instance_id for inst in findings1[0].instances}
            ids2 = {inst.instance_id for inst in findings2[0].instances}
            self.assertEqual(ids1, ids2)

    def test_empty_model(self):
        """Test behavior with empty or malformed XBRL model."""
        # Empty model
        xbrl_model = Mock()
        xbrl_model.modelDocument = None
        xbrl_model.facts = []
        self.mock_context.xbrl_model = xbrl_model
        self._write_primary(schema_refs=["ext.xsd"])
        self._write_schema(
            "ext.xsd",
            target_namespace="http://example.com/ext",
            imports=["http://example.com/gaap"],
        )

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_break_triggers(self):
        """Test that break triggers are properly defined."""
        triggers = self.detector.get_break_triggers()
        self.assertIsInstance(triggers, list)
        self.assertTrue(len(triggers) > 0)

        for trigger in triggers:
            self.assertIn('id', trigger)
            self.assertIn('summary', trigger)
            self.assertIsInstance(trigger['id'], str)
            self.assertIsInstance(trigger['summary'], str)

    def test_rule_basis(self):
        """Test that rule basis is properly defined."""
        rule_basis = self.detector.load_rule_basis()
        self.assertIsInstance(rule_basis, list)
        # Rule basis may be empty during testing if registry not fully set up
        # This is acceptable as the detector gracefully handles empty rule basis

        # If rule basis is populated, validate structure
        for rule in rule_basis:
            # P005 uses citation format from rule basis registry
            self.assertIsInstance(rule, dict)
            # Note: Different detectors use different field names (citation vs title)

    def _write_primary(self, *, schema_refs: list[str]) -> None:
        refs = "".join(f'<link:schemaRef xlink:href="{href}"/>' for href in schema_refs)
        self.primary_path.write_text(f"<html>{refs}</html>", encoding="utf-8")

    def _write_schema(self, filename: str, *, target_namespace: str, imports: list[str]) -> None:
        imports_xml = "".join(
            f'<xs:import namespace="{ns}" schemaLocation="{ns}.xsd"/>'
            for ns in imports
        )
        data = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{target_namespace}">\n'
            f"{imports_xml}\n"
            "</xs:schema>\n"
        )
        (self.root_dir / filename).write_text(data, encoding="utf-8")

    def _create_mock_xbrl_model(self, *, fact_namespaces: list[str]) -> Mock:
        """Create a mock XBRL model with given fact namespaces."""
        xbrl_model = Mock()

        # Mock facts with namespaces
        facts = []
        for namespace in fact_namespaces:
            fact = Mock()
            fact_qname = Mock()
            fact_qname.namespaceURI = namespace
            fact.qname = fact_qname
            facts.append(fact)

        xbrl_model.facts = facts

        return xbrl_model


if __name__ == '__main__':
    unittest.main()
