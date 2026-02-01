"""Unit tests for XEW-P004 type/unit/numeric detector."""

import unittest
from unittest.mock import Mock

from cmdrvl_xew.detectors.p004_type_unit import TypeUnitNumericDetector
from cmdrvl_xew.detectors._base import DetectorContext


class TestP004TypeUnitDetector(unittest.TestCase):
    """Test cases for P004 detector behavior."""

    def setUp(self):
        self.detector = TypeUnitNumericDetector()

    def test_no_violations_returns_empty(self):
        """Numeric fact with valid unit and attributes should yield no findings."""
        context = self._make_context([
            self._create_fact(
                concept_type="monetaryItemType",
                value="100",
                is_numeric=True,
                unit=self._create_unit("USD"),
                decimals="0",
                precision=None,
            )
        ])

        findings = self.detector.detect(context)
        self.assertEqual(findings, [])

    def test_missing_unit_violation(self):
        """Numeric fact without unit should flag missing_unit."""
        context = self._make_context([
            self._create_fact(
                concept_type="decimalItemType",
                value="123",
                is_numeric=True,
                unit=None,
                decimals=None,
                precision=None,
            )
        ])

        findings = self.detector.detect(context)
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("missing_unit", issue_codes)

    def test_invalid_decimals_and_precision_conflict(self):
        """Invalid decimals plus decimals/precision conflict should both be recorded."""
        context = self._make_context([
            self._create_fact(
                concept_type="decimalItemType",
                value="123",
                is_numeric=True,
                unit=self._create_unit("USD"),
                decimals="abc",
                precision="2",
            )
        ])

        findings = self.detector.detect(context)
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("invalid_decimals", issue_codes)
        self.assertIn("decimals_precision_conflict", issue_codes)

    def test_unit_incompatible_for_monetary(self):
        """Monetary concepts with non-currency units should be flagged."""
        context = self._make_context([
            self._create_fact(
                concept_type="monetaryItemType",
                value="100",
                is_numeric=True,
                unit=self._create_unit("SHARES", namespace="http://www.example.com/unit"),
                decimals="0",
                precision=None,
            )
        ])

        findings = self.detector.detect(context)
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("unit_incompatible", issue_codes)

    def test_non_numeric_with_unit(self):
        """Non-numeric facts should not include unit attributes."""
        context = self._make_context([
            self._create_fact(
                concept_type="stringItemType",
                value="text",
                is_numeric=False,
                unit=self._create_unit("USD"),
                decimals=None,
                precision=None,
            )
        ])

        findings = self.detector.detect(context)
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("non_numeric_with_unit", issue_codes)

    def _extract_issue_codes(self, finding):
        return {instance.data.get("issue_code") for instance in finding.instances}

    def _make_context(self, facts):
        xbrl_model = Mock()
        xbrl_model.facts = facts

        return DetectorContext(
            primary_document_path="/tmp/primary.htm",
            artifacts_dir="/tmp",
            cik="0001234567",
            accession="0001234567-25-000001",
            form="10-Q",
            filed_date="2025-01-31",
            xbrl_model=xbrl_model,
            config={},
        )

    def _create_fact(self, *, concept_type, value, is_numeric, unit, decimals, precision):
        fact = Mock()
        fact.qname = self._create_qname("http://example.com/gaap", "Revenue")
        concept = Mock()
        concept.type = concept_type
        fact.concept = concept
        fact.value = value
        fact.context = self._create_context("ctx-1")
        fact.unit = unit
        fact.isNumeric = is_numeric
        fact.decimals = decimals
        fact.precision = precision
        return fact

    def _create_context(self, context_id):
        context = Mock()
        context.id = context_id
        return context

    def _create_unit(self, local_name, *, namespace="http://www.xbrl.org/2003/iso4217"):
        unit = Mock()
        unit.id = f"unit_{local_name}"
        measure_qname = self._create_qname(namespace, local_name)
        measure = Mock()
        measure.qname = measure_qname
        unit.measures = [measure]
        return unit

    def _create_qname(self, namespace, local_name):
        qname = Mock()
        qname.namespaceURI = namespace
        qname.localName = local_name
        qname.prefix = None
        return qname


if __name__ == '__main__':
    unittest.main()
