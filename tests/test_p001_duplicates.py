"""
Unit tests for XEW-P001 duplicate facts detector.
"""

import unittest
from unittest.mock import Mock, MagicMock
from typing import List, Dict, Any

from cmdrvl_xew.detectors.p001_duplicates import DuplicateFactsDetector
from cmdrvl_xew.detectors._base import DetectorContext


class TestDuplicateFactsDetector(unittest.TestCase):
    """Test cases for P001 duplicate facts detector."""

    def setUp(self):
        """Set up test fixtures."""
        self.detector = DuplicateFactsDetector()
        self.mock_context = Mock(spec=DetectorContext)
        self.mock_context.accession = "0000123456-23-000001"  # Valid EDGAR accession format

    def test_pattern_properties(self):
        """Test basic pattern properties."""
        self.assertEqual(self.detector.pattern_id, "XEW-P001")
        self.assertEqual(self.detector.pattern_name, "Duplicate Facts With Equivalent Context/Unit")
        self.assertTrue(self.detector.alert_eligible)

    def test_no_duplicates(self):
        """Test when there are no duplicate facts."""
        # Create facts with different signatures
        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=self._create_mock_context(
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0000123456",
                    period_type="instant",
                    instant_date="2023-12-31"
                ),
                value="1000000",
                is_numeric=True,
                unit=self._create_mock_unit("USD")
            ),
            self._create_mock_fact(
                concept="gaap:Assets",  # Different concept
                context=self._create_mock_context(
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0000123456",
                    period_type="instant",
                    instant_date="2023-12-31"
                ),
                value="5000000",
                is_numeric=True,
                unit=self._create_mock_unit("USD")
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_duplicate_facts_same_value(self):
        """Test detection of duplicate facts with same value."""
        # Create two facts with identical signature and value
        context = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2023-12-31"
        )
        unit = self._create_mock_unit("USD")

        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,
                value="1000000",
                is_numeric=True,
                unit=unit
            ),
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,  # Same context
                value="1000000",  # Same value
                is_numeric=True,
                unit=unit  # Same unit
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.pattern_id, "XEW-P001")

        # Should have one instance for the duplicate group
        self.assertEqual(len(finding.instances), 1)
        instance = finding.instances[0]

        # Check instance data
        self.assertEqual(instance.data['fact_count'], 2)
        self.assertEqual(instance.data['concept']['clark'], '{http://fasb.org/us-gaap/2023-01-31}Revenue')
        self.assertFalse(instance.data['value_conflict'])  # Same values, no conflict
        self.assertIn("duplicate_fact", instance.data['issue_codes'])

    def test_duplicate_facts_different_values(self):
        """Test detection of duplicate facts with conflicting values."""
        context = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2023-12-31"
        )
        unit = self._create_mock_unit("USD")

        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,
                value="1000000",
                is_numeric=True,
                unit=unit
            ),
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,  # Same context
                value="1500000",  # Different value - conflict!
                is_numeric=True,
                unit=unit
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        instance = finding.instances[0]
        self.assertEqual(instance.data['fact_count'], 2)
        self.assertTrue(instance.data['value_conflict'])  # Different values = conflict
        self.assertIn("value_conflict", instance.data['issue_codes'])

    def test_duplicate_facts_different_periods(self):
        """Test that facts with different periods are not considered duplicates."""
        unit = self._create_mock_unit("USD")

        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=self._create_mock_context(
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0000123456",
                    period_type="instant",
                    instant_date="2023-12-31"  # Different period
                ),
                value="1000000",
                is_numeric=True,
                unit=unit
            ),
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=self._create_mock_context(
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0000123456",
                    period_type="instant",
                    instant_date="2022-12-31"  # Different period
                ),
                value="1000000",
                is_numeric=True,
                unit=unit
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)  # Different periods = no duplicates

    def test_duplicate_facts_different_entities(self):
        """Test that facts with different entities are not considered duplicates."""
        unit = self._create_mock_unit("USD")

        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=self._create_mock_context(
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0000123456",  # Entity 1
                    period_type="instant",
                    instant_date="2023-12-31"
                ),
                value="1000000",
                is_numeric=True,
                unit=unit
            ),
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=self._create_mock_context(
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0000789012",  # Entity 2
                    period_type="instant",
                    instant_date="2023-12-31"
                ),
                value="1000000",
                is_numeric=True,
                unit=unit
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)  # Different entities = no duplicates

    def test_duplicate_facts_different_units(self):
        """Test that facts with different units are not considered duplicates."""
        context = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2023-12-31"
        )

        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,
                value="1000000",
                is_numeric=True,
                unit=self._create_mock_unit("USD")  # USD unit
            ),
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,
                value="1000000",
                is_numeric=True,
                unit=self._create_mock_unit("EUR")  # EUR unit
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)  # Different units = no duplicates

    def test_duration_period_duplicates(self):
        """Test duplicate detection for duration periods."""
        context = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="duration",
            start_date="2023-01-01",
            end_date="2023-12-31"
        )
        unit = self._create_mock_unit("USD")

        facts = [
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,
                value="1000000",
                is_numeric=True,
                unit=unit
            ),
            self._create_mock_fact(
                concept="gaap:Revenue",
                context=context,
                value="1000000",
                is_numeric=True,
                unit=unit
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        instance = finding.instances[0]
        self.assertEqual(instance.data['fact_count'], 2)

    def test_multiple_duplicate_groups(self):
        """Test detection when there are multiple groups of duplicates."""
        context1 = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2023-12-31"
        )
        context2 = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2022-12-31"  # Different period
        )
        unit = self._create_mock_unit("USD")

        facts = [
            # Group 1: Revenue 2023 duplicates
            self._create_mock_fact("gaap:Revenue", context1, "1000000", True, unit),
            self._create_mock_fact("gaap:Revenue", context1, "1000000", True, unit),

            # Group 2: Revenue 2022 duplicates
            self._create_mock_fact("gaap:Revenue", context2, "900000", True, unit),
            self._create_mock_fact("gaap:Revenue", context2, "900000", True, unit),
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]

        # Should have 2 instances (one for each duplicate group)
        self.assertEqual(len(finding.instances), 2)

        fact_counts = [inst.data['fact_count'] for inst in finding.instances]
        self.assertEqual(sorted(fact_counts), [2, 2])

    def test_non_numeric_facts(self):
        """Test duplicate detection for non-numeric facts."""
        context = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2023-12-31"
        )

        facts = [
            self._create_mock_fact(
                concept="dei:EntityCommonStockSharesOutstanding",
                context=context,
                value="Small Business Issuer",
                is_numeric=False,
                unit=None
            ),
            self._create_mock_fact(
                concept="dei:EntityCommonStockSharesOutstanding",
                context=context,
                value="Small Business Issuer",
                is_numeric=False,
                unit=None
            )
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
        self.mock_context.xbrl_model = xbrl_model

        findings = self.detector.detect(self.mock_context)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        instance = finding.instances[0]
        self.assertEqual(instance.data['fact_count'], 2)

    def test_canonical_signature_consistency(self):
        """Test that canonical signatures are generated consistently."""
        context = self._create_mock_context(
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000123456",
            period_type="instant",
            instant_date="2023-12-31"
        )
        unit = self._create_mock_unit("USD")

        facts = [
            self._create_mock_fact("gaap:Revenue", context, "1000000", True, unit),
            self._create_mock_fact("gaap:Revenue", context, "1500000", True, unit)
        ]

        xbrl_model = self._create_mock_xbrl_model(facts)
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
        """Test behavior with empty XBRL model."""
        xbrl_model = Mock()
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

    def test_rule_basis(self):
        """Test that rule basis is properly defined."""
        rule_basis = self.detector.load_rule_basis()
        self.assertIsInstance(rule_basis, list)
        self.assertTrue(len(rule_basis) > 0)

        for rule in rule_basis:
            self.assertIn('source', rule)
            self.assertIn('citation', rule)
            self.assertIn('url', rule)

    def _create_mock_fact(self, concept: str, context: Mock, value: str,
                         is_numeric: bool, unit: Mock = None) -> Mock:
        """Create a mock fact with given properties."""
        fact = Mock()

        # Create QName mock
        qname = Mock()
        # Extract namespace from concept (e.g., "gaap:Revenue" -> gaap namespace)
        if ':' in concept:
            prefix, local = concept.split(':', 1)
            if prefix == 'gaap':
                qname.namespaceURI = 'http://fasb.org/us-gaap/2023-01-31'
            elif prefix == 'dei':
                qname.namespaceURI = 'http://xbrl.sec.gov/dei/2023-01-31'
            else:
                qname.namespaceURI = f'http://example.com/{prefix}'
            qname.localName = local
        else:
            qname.namespaceURI = 'http://example.com/test'
            qname.localName = concept

        fact.qname = qname
        fact.concept = Mock()  # Concept details not needed for basic tests
        fact.value = value
        fact.context = context
        fact.unit = unit
        fact.isNumeric = is_numeric

        return fact

    def _create_mock_context(self, entity_scheme: str, entity_identifier: str,
                           period_type: str, instant_date: str = None,
                           start_date: str = None, end_date: str = None,
                           dimensions: List = None) -> Mock:
        """Create a mock context with given properties."""
        context = Mock()

        # Entity identifier
        entity_id = Mock()
        entity_id.scheme = entity_scheme
        entity_id.value = entity_identifier
        context.entityIdentifier = entity_id

        # Period information
        if period_type == "instant":
            context.isInstantPeriod = True
            context.isStartEndPeriod = False
            context.instantDate = instant_date or "2023-12-31"
        elif period_type == "duration":
            context.isInstantPeriod = False
            context.isStartEndPeriod = True
            context.startDate = start_date or "2023-01-01"
            context.endDate = end_date or "2023-12-31"

        # Dimensions (simplified for basic tests)
        context.qnameDims = dimensions or {}

        return context

    def _create_mock_unit(self, currency_code: str) -> Mock:
        """Create a mock unit for the given currency."""
        unit = Mock()
        unit.id = f"unit_{currency_code}"

        # Mock unit measures (simplified)
        measure_qname = Mock()
        measure_qname.namespaceURI = 'http://www.xbrl.org/2003/iso4217'
        measure_qname.localName = currency_code
        measure_qname.prefix = None
        measure = Mock()
        measure.qname = measure_qname
        unit.measures = [measure]

        return unit

    def _create_mock_xbrl_model(self, facts: List[Mock]) -> Mock:
        """Create a mock XBRL model with given facts."""
        xbrl_model = Mock()
        xbrl_model.facts = facts
        return xbrl_model


if __name__ == '__main__':
    unittest.main()
