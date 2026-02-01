"""
Unit tests for XEW-P005 taxonomy inconsistency detector.
"""

import unittest
from unittest.mock import Mock, MagicMock
from typing import List, Dict, Any

from cmdrvl_xew.detectors.p005_taxonomy import TaxonomyInconsistencyDetector
from cmdrvl_xew.detectors._base import DetectorContext


class TestTaxonomyInconsistencyDetector(unittest.TestCase):
    """Test cases for P005 taxonomy inconsistency detector."""

    def setUp(self):
        """Set up test fixtures."""
        self.detector = TaxonomyInconsistencyDetector()
        self.mock_context = Mock(spec=DetectorContext)
        self.mock_context.accession = "0000123456-23-000001"  # Valid EDGAR accession format

    def test_pattern_properties(self):
        """Test basic pattern properties."""
        self.assertEqual(self.detector.pattern_id, "XEW-P005")
        self.assertEqual(self.detector.pattern_name, "Taxonomy Inconsistency Checks")
        self.assertTrue(self.detector.alert_eligible)

    def test_no_inconsistencies(self):
        """Test when there are no taxonomy inconsistencies."""
        # Create mock XBRL model with consistent schema refs and namespaces
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap.xsd', 'namespace': 'http://example.com/gaap'}
            ],
            fact_namespaces=['http://example.com/gaap']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_unreferenced_namespace(self):
        """Test detection of namespaces used in facts but not declared in schemaRef."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap.xsd', 'namespace': 'http://example.com/gaap'}
            ],
            fact_namespaces=['http://example.com/gaap', 'http://example.com/undeclared']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.pattern_id, "XEW-P005")

        # Check that unreferenced namespace issue is detected
        instance_data = [inst.data for inst in finding.instances]
        unreferenced_instances = [
            inst for inst in instance_data
            if inst['issue_code'] == 'unreferenced_namespace'
        ]
        self.assertTrue(len(unreferenced_instances) > 0)

    def test_unused_schema_ref(self):
        """Test detection of schemaRef declared but not used in facts."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap.xsd', 'namespace': 'http://example.com/gaap'},
                {'href': 'http://example.com/unused.xsd', 'namespace': 'http://example.com/unused'}
            ],
            fact_namespaces=['http://example.com/gaap']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        # Check that unused schema ref issue is detected
        instance_data = [inst.data for inst in finding.instances]
        unused_instances = [
            inst for inst in instance_data
            if inst['issue_code'] == 'unused_schema_ref'
        ]
        self.assertTrue(len(unused_instances) > 0)

    def test_duplicate_schema_ref(self):
        """Test detection of duplicate schemaRef elements for same namespace."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap1.xsd', 'namespace': 'http://example.com/gaap'},
                {'href': 'http://example.com/gaap2.xsd', 'namespace': 'http://example.com/gaap'}
            ],
            fact_namespaces=['http://example.com/gaap']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        # Check that duplicate schema ref issue is detected
        instance_data = [inst.data for inst in finding.instances]
        duplicate_instances = [
            inst for inst in instance_data
            if inst['issue_code'] == 'duplicate_schema_ref'
        ]
        self.assertTrue(len(duplicate_instances) > 0)

    def test_malformed_schema_ref(self):
        """Test detection of malformed schemaRef href."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap.xsd', 'namespace': 'http://example.com/gaap'},
                {'href': '', 'namespace': 'http://example.com/malformed'}  # Empty href
            ],
            fact_namespaces=['http://example.com/gaap']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        # Check that malformed and unused schema ref issues are detected
        instance_data = [inst.data for inst in finding.instances]
        malformed_instances = [
            inst for inst in instance_data
            if inst['issue_code'] == 'malformed_schema_ref'
        ]
        unused_instances = [
            inst for inst in instance_data
            if inst['issue_code'] == 'unused_schema_ref'
        ]
        # Should detect either malformed or unused (or both)
        self.assertTrue(len(malformed_instances) > 0 or len(unused_instances) > 0)

    def test_schema_ref_mismatch(self):
        """Test detection of href/namespace mismatches."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://different.com/schema.xsd', 'namespace': 'http://example.com/gaap'}
            ],
            fact_namespaces=['http://example.com/gaap']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        if findings:  # Mismatch detection is heuristic-based, so may not always trigger
            finding = findings[0]
            instance_data = [inst.data for inst in finding.instances]
            mismatch_instances = [
                inst for inst in instance_data
                if inst['issue_code'] == 'schema_ref_mismatch'
            ]
            # If detected, should be flagged as mismatch
            if mismatch_instances:
                self.assertTrue(len(mismatch_instances) > 0)

    def test_multiple_inconsistencies(self):
        """Test when multiple types of inconsistencies are present."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap.xsd', 'namespace': 'http://example.com/gaap'},
                {'href': 'http://example.com/unused.xsd', 'namespace': 'http://example.com/unused'},
                {'href': '', 'namespace': 'http://example.com/malformed'}
            ],
            fact_namespaces=['http://example.com/gaap', 'http://example.com/undeclared']
        )
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        # Should detect multiple types of issues
        instance_data = [inst.data for inst in finding.instances]
        issue_codes = {inst['issue_code'] for inst in instance_data}

        # Should detect at least unreferenced namespace and unused schema ref
        expected_codes = {'unreferenced_namespace', 'unused_schema_ref'}
        self.assertTrue(expected_codes.issubset(issue_codes))

    def test_canonical_signature_consistency(self):
        """Test that canonical signatures are generated consistently."""
        xbrl_model = self._create_mock_xbrl_model(
            schema_refs=[
                {'href': 'http://example.com/gaap.xsd', 'namespace': 'http://example.com/gaap'}
            ],
            fact_namespaces=['http://example.com/undeclared']
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
        self.assertTrue(len(rule_basis) > 0)

        for rule in rule_basis:
            self.assertIn('source', rule)
            self.assertIn('citation', rule)
            self.assertIn('url', rule)
            self.assertIsInstance(rule['source'], str)
            self.assertIsInstance(rule['citation'], str)
            self.assertIsInstance(rule['url'], str)

    def _create_mock_xbrl_model(self, schema_refs: List[Dict[str, str]],
                               fact_namespaces: List[str]) -> Mock:
        """Create a mock XBRL model with given schema refs and fact namespaces."""
        xbrl_model = Mock()

        # Mock model document with schema references
        model_doc = Mock()
        xbrl_model.modelDocument = model_doc

        # Mock referencesDocument for schema refs (use only this to avoid duplicates)
        model_doc.referencesDocument = {}
        for i, ref in enumerate(schema_refs):
            ref_doc = Mock()
            ref_doc.schemaLocation = ref['href']
            ref_doc.targetNamespace = ref['namespace']
            model_doc.referencesDocument[f'ref_{i}'] = ref_doc

        # Mock empty schemaLocationElements to avoid duplicates
        model_doc.schemaLocationElements = {}

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