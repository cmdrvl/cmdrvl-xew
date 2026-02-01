"""
Unit tests for canonical signature serialization and hashing invariants.

Tests lock outputs with golden expectations to ensure deterministic behavior
across platforms and prevent regressions in signature generation.
"""

import hashlib
import unittest
from unittest import TestCase

from cmdrvl_xew.util import (
    canonical_signature_bytes,
    canonical_signature_p001,
    canonical_signature_p002,
    canonical_signature_p004,
    canonical_signature_p005,
    canonical_signature_p007,
    instance_id_from_signature,
    generate_instance_id,
    period_signature,
    dimension_signature,
    unit_signature,
    normalize_unit_measures,
    NormalizedUnit,
    CANONICAL_SIGNATURE_VERSION,
    _sorted_csv,
    _sha256_joined_sorted,
    _ensure_ascii,
)


class TestCanonicalSignatureBytes(TestCase):
    """Test base canonical signature byte generation."""

    def test_basic_signature_generation(self):
        """Test basic signature bytes with version tag."""
        sig_body = "test_pattern|concept|entity"
        result = canonical_signature_bytes(sig_body)
        expected = b"v1|test_pattern|concept|entity"
        self.assertEqual(result, expected)

    def test_custom_version(self):
        """Test signature with custom version."""
        sig_body = "test_pattern|concept"
        result = canonical_signature_bytes(sig_body, version="v2")
        expected = b"v2|test_pattern|concept"
        self.assertEqual(result, expected)

    def test_ascii_enforcement(self):
        """Test that non-ASCII characters raise ValueError."""
        with self.assertRaises(ValueError):
            canonical_signature_bytes("test|concept_with_unicode_€")

    def test_pipe_in_version_rejected(self):
        """Test that pipe character in version is rejected."""
        with self.assertRaises(ValueError):
            canonical_signature_bytes("test", version="v1|invalid")

    def test_deterministic_output(self):
        """Test that identical inputs produce identical outputs."""
        sig_body = "P001|concept|entity|period|dims|unit"
        result1 = canonical_signature_bytes(sig_body)
        result2 = canonical_signature_bytes(sig_body)
        self.assertEqual(result1, result2)


class TestP001Signatures(TestCase):
    """Test P001 duplicate detection signature generation."""

    def test_golden_p001_signature(self):
        """Test P001 signature with golden expected output."""
        concept_clark = "{http://example.com/gaap/2023}Revenue"
        entity_scheme = "http://www.sec.gov/CIK"
        entity_identifier = "0000123456"
        period_sig = "instant:2023-12-31"
        dim_sig = "segment=Commercial;product=Software"
        unit = NormalizedUnit(measures=("{iso4217}USD",), is_numeric=True)

        result = canonical_signature_p001(
            concept_clark, entity_scheme, entity_identifier, period_sig, dim_sig, unit
        )

        expected = (
            b"v1|P001|{http://example.com/gaap/2023}Revenue|http://www.sec.gov/CIK|"
            b"0000123456|instant:2023-12-31|segment=Commercial;product=Software|{iso4217}USD"
        )
        self.assertEqual(result, expected)

    def test_p001_no_unit(self):
        """Test P001 signature with no unit."""
        result = canonical_signature_p001(
            "{http://test}Concept", "scheme", "entity", "period", "dims", None
        )
        expected = b"v1|P001|{http://test}Concept|scheme|entity|period|dims|"
        self.assertEqual(result, expected)

    def test_p001_empty_dimensions(self):
        """Test P001 signature with empty dimensions."""
        result = canonical_signature_p001(
            "{http://test}Concept", "scheme", "entity", "period", "", None
        )
        expected = b"v1|P001|{http://test}Concept|scheme|entity|period||"
        self.assertEqual(result, expected)


class TestP002Signatures(TestCase):
    """Test P002 extension anchoring signature generation."""

    def test_golden_p002_signature(self):
        """Test P002 signature with golden expected output."""
        extension_concept = "{http://company.com/ext/2023}CustomRevenue"
        issue_codes = ["missing_standard_anchor", "weak_calculation_link"]

        result = canonical_signature_p002(extension_concept, issue_codes)

        expected = (
            b"v1|P002|{http://company.com/ext/2023}CustomRevenue|"
            b"missing_standard_anchor,weak_calculation_link"
        )
        self.assertEqual(result, expected)

    def test_p002_sorted_issue_codes(self):
        """Test that P002 issue codes are sorted deterministically."""
        extension_concept = "{http://test}Concept"
        issue_codes = ["z_last", "a_first", "m_middle"]

        result = canonical_signature_p002(extension_concept, issue_codes)

        expected = b"v1|P002|{http://test}Concept|a_first,m_middle,z_last"
        self.assertEqual(result, expected)

    def test_p002_single_issue_code(self):
        """Test P002 with single issue code."""
        result = canonical_signature_p002("{http://test}Concept", ["single_issue"])
        expected = b"v1|P002|{http://test}Concept|single_issue"
        self.assertEqual(result, expected)


class TestP004Signatures(TestCase):
    """Test P004 numeric/type issue signature generation."""

    def test_golden_p004_signature(self):
        """Test P004 signature with golden expected output."""
        concept_clark = "{http://example.com/gaap/2023}NetIncome"
        context_id = "FD2023Q4"
        unit = NormalizedUnit(measures=("{iso4217}USD",), is_numeric=True)
        issue_code = "invalid_numeric_format"

        result = canonical_signature_p004(concept_clark, context_id, unit, issue_code)

        expected = (
            b"v1|P004|{http://example.com/gaap/2023}NetIncome|FD2023Q4|{iso4217}USD|"
            b"invalid_numeric_format"
        )
        self.assertEqual(result, expected)

    def test_p004_no_unit(self):
        """Test P004 signature with no unit."""
        result = canonical_signature_p004(
            "{http://test}Concept", "ctx123", None, "text_format_error"
        )
        expected = b"v1|P004|{http://test}Concept|ctx123||text_format_error"
        self.assertEqual(result, expected)

    def test_p004_multi_measure_unit(self):
        """Test P004 with multi-measure unit (ratio)."""
        unit = NormalizedUnit(measures=("{iso4217}USD", "{xbrli}shares"), is_numeric=True)
        result = canonical_signature_p004(
            "{http://test}EPS", "ctx", unit, "division_by_zero"
        )
        expected = b"v1|P004|{http://test}EPS|ctx|{iso4217}USD;{xbrli}shares|division_by_zero"
        self.assertEqual(result, expected)


class TestP005Signatures(TestCase):
    """Test P005 taxonomy version mismatch signature generation."""

    def test_golden_p005_signature(self):
        """Test P005 signature with golden expected output."""
        issue_code = "mixed_taxonomy_versions"
        schema_refs = [
            "https://xbrl.sec.gov/dei/2022/dei-2022.xsd",
            "https://xbrl.sec.gov/gaap/2023/gaap-2023.xsd"
        ]
        namespaces = [
            "http://xbrl.sec.gov/dei/2022",
            "http://xbrl.sec.gov/gaap/2023"
        ]

        result = canonical_signature_p005(issue_code, schema_refs, namespaces)

        # Calculate expected hashes for deterministic comparison
        sorted_schema_refs = sorted(schema_refs)
        sorted_namespaces = sorted(namespaces)
        schema_hash = hashlib.sha256('\n'.join(sorted_schema_refs).encode('utf-8')).hexdigest()
        ns_hash = hashlib.sha256('\n'.join(sorted_namespaces).encode('utf-8')).hexdigest()

        expected_str = f"v1|P005|mixed_taxonomy_versions|schemaRefSha256={schema_hash}|nsSha256={ns_hash}"
        expected = expected_str.encode('ascii')

        self.assertEqual(result, expected)

    def test_p005_deterministic_hashing(self):
        """Test that P005 hashing is deterministic regardless of input order."""
        issue_code = "test_issue"
        schema_refs_ordered = ["a.xsd", "b.xsd", "c.xsd"]
        schema_refs_unordered = ["c.xsd", "a.xsd", "b.xsd"]
        namespaces_ordered = ["ns1", "ns2", "ns3"]
        namespaces_unordered = ["ns3", "ns1", "ns2"]

        result1 = canonical_signature_p005(issue_code, schema_refs_ordered, namespaces_ordered)
        result2 = canonical_signature_p005(issue_code, schema_refs_unordered, namespaces_unordered)

        self.assertEqual(result1, result2)


class TestP007Signatures(TestCase):
    """Test P007 orphan facts signature generation."""

    def test_golden_p007_signature(self):
        """Test P007 signature with golden expected output."""
        entity_scheme = "http://www.sec.gov/CIK"
        entity_identifier = "0000123456"
        period_sig = "duration:2023-01-01..2023-12-31"
        dim_sig = "segment=Retail"

        result = canonical_signature_p007(entity_scheme, entity_identifier, period_sig, dim_sig)

        expected = (
            b"v1|P007|http://www.sec.gov/CIK|0000123456|"
            b"duration:2023-01-01..2023-12-31|segment=Retail"
        )
        self.assertEqual(result, expected)

    def test_p007_empty_dimensions(self):
        """Test P007 signature with empty dimensions."""
        result = canonical_signature_p007("scheme", "entity", "period", "")
        expected = b"v1|P007|scheme|entity|period|"
        self.assertEqual(result, expected)


class TestInstanceIdGeneration(TestCase):
    """Test deterministic instance ID generation from signatures."""

    def test_instance_id_deterministic(self):
        """Test that instance ID generation is deterministic."""
        signature = b"v1|P001|concept|entity|period|dims|unit"

        id1 = instance_id_from_signature(signature)
        id2 = generate_instance_id(signature)
        id3 = instance_id_from_signature(signature)

        self.assertEqual(id1, id2)
        self.assertEqual(id2, id3)
        self.assertEqual(len(id1), 64)  # SHA256 hex digest length

    def test_golden_instance_id(self):
        """Test instance ID with golden expected output."""
        signature = b"v1|P001|{http://test}Revenue|scheme|123|instant:2023-12-31||{iso4217}USD"
        result = instance_id_from_signature(signature)

        # Calculate expected hash manually for golden test
        expected = hashlib.sha256(signature).hexdigest()
        self.assertEqual(result, expected)

    def test_different_signatures_different_ids(self):
        """Test that different signatures produce different instance IDs."""
        sig1 = b"v1|P001|concept1|entity|period|dims|unit"
        sig2 = b"v1|P001|concept2|entity|period|dims|unit"

        id1 = instance_id_from_signature(sig1)
        id2 = instance_id_from_signature(sig2)

        self.assertNotEqual(id1, id2)


class TestComponentSerialization(TestCase):
    """Test individual component serialization functions."""

    def test_period_signature_instant(self):
        """Test instant period signature."""
        result = period_signature("instant", instant="2023-12-31")
        expected = "instant:2023-12-31"
        self.assertEqual(result, expected)

    def test_period_signature_duration(self):
        """Test duration period signature."""
        result = period_signature("duration", start="2023-01-01", end="2023-12-31")
        expected = "duration:2023-01-01..2023-12-31"
        self.assertEqual(result, expected)

    def test_period_signature_validation(self):
        """Test period signature validation."""
        with self.assertRaises(ValueError):
            period_signature("instant")  # Missing instant
        with self.assertRaises(ValueError):
            period_signature("duration", start="2023-01-01")  # Missing end
        with self.assertRaises(ValueError):
            period_signature("invalid_type")

    def test_dimension_signature_sorted(self):
        """Test dimension signature sorting."""
        dimensions = [("z_dim", "z_member"), ("a_dim", "a_member"), ("m_dim", "m_member")]
        result = dimension_signature(dimensions)
        expected = "a_dim=a_member;m_dim=m_member;z_dim=z_member"
        self.assertEqual(result, expected)

    def test_dimension_signature_empty(self):
        """Test empty dimension signature."""
        result = dimension_signature(None)
        self.assertEqual(result, "")
        result = dimension_signature([])
        self.assertEqual(result, "")

    def test_unit_signature_single_measure(self):
        """Test unit signature with single measure."""
        unit = NormalizedUnit(measures=("{iso4217}USD",), is_numeric=True)
        result = unit_signature(unit)
        expected = "{iso4217}USD"
        self.assertEqual(result, expected)

    def test_unit_signature_multi_measure(self):
        """Test unit signature with multiple measures."""
        unit = NormalizedUnit(measures=("{iso4217}USD", "{xbrli}shares"), is_numeric=True)
        result = unit_signature(unit)
        expected = "{iso4217}USD;{xbrli}shares"
        self.assertEqual(result, expected)

    def test_unit_signature_none(self):
        """Test unit signature with None unit."""
        result = unit_signature(None)
        self.assertEqual(result, "")


class TestNormalizedUnit(TestCase):
    """Test NormalizedUnit validation and behavior."""

    def test_normalized_unit_sorted_measures(self):
        """Test that NormalizedUnit enforces sorted measures."""
        # Should work with pre-sorted measures
        unit = NormalizedUnit(measures=("a", "b", "c"), is_numeric=True)
        self.assertEqual(unit.measures, ("a", "b", "c"))

        # Should fail with unsorted measures
        with self.assertRaises(ValueError):
            NormalizedUnit(measures=("c", "a", "b"), is_numeric=True)

    def test_normalize_unit_measures(self):
        """Test unit measure normalization."""
        measures = ["{iso4217}USD", "{xbrli}shares", "{gaap}dollars"]
        result = normalize_unit_measures(measures)
        expected = ("{gaap}dollars", "{iso4217}USD", "{xbrli}shares")
        self.assertEqual(result, expected)

    def test_normalize_unit_measures_clark_validation(self):
        """Test that unit measures must be in Clark notation."""
        with self.assertRaises(ValueError):
            normalize_unit_measures(["not_clark_notation"])
        with self.assertRaises(ValueError):
            normalize_unit_measures(["missing_closing_brace{"])


class TestHelperFunctions(TestCase):
    """Test utility helper functions."""

    def test_sorted_csv(self):
        """Test sorted CSV generation."""
        values = ["zebra", "alpha", "beta"]
        result = _sorted_csv(values, "test")
        expected = "alpha,beta,zebra"
        self.assertEqual(result, expected)

    def test_sha256_joined_sorted(self):
        """Test SHA256 of sorted joined values."""
        values = ["c", "a", "b"]
        result = _sha256_joined_sorted(values, "test")

        # Calculate expected hash
        joined = "a\nb\nc"
        expected = hashlib.sha256(joined.encode('utf-8')).hexdigest()
        self.assertEqual(result, expected)

    def test_sha256_joined_sorted_deterministic(self):
        """Test that SHA256 joined sorting is deterministic."""
        values1 = ["c", "a", "b"]
        values2 = ["b", "c", "a"]

        result1 = _sha256_joined_sorted(values1, "test")
        result2 = _sha256_joined_sorted(values2, "test")

        self.assertEqual(result1, result2)

    def test_ensure_ascii(self):
        """Test ASCII validation."""
        # Should work with ASCII
        result = _ensure_ascii("valid_ascii_123", "test")
        self.assertEqual(result, "valid_ascii_123")

        # Should fail with non-ASCII
        with self.assertRaises(ValueError):
            _ensure_ascii("unicode_€_symbol", "test")


class TestCrossPatternConsistency(TestCase):
    """Test consistency across different pattern signatures."""

    def test_version_consistency(self):
        """Test that all patterns use same version by default."""
        # Get signatures from different patterns
        p001_sig = canonical_signature_p001("{http://test}C", "s", "e", "p", "d", None)
        p002_sig = canonical_signature_p002("{http://test}C", ["issue"])
        p004_sig = canonical_signature_p004("{http://test}C", "ctx", None, "issue")
        p005_sig = canonical_signature_p005("issue", ["schema"], ["ns"])
        p007_sig = canonical_signature_p007("s", "e", "p", "d")

        # All should start with the same version prefix
        version_prefix = f"{CANONICAL_SIGNATURE_VERSION}|".encode('ascii')
        self.assertTrue(p001_sig.startswith(version_prefix))
        self.assertTrue(p002_sig.startswith(version_prefix))
        self.assertTrue(p004_sig.startswith(version_prefix))
        self.assertTrue(p005_sig.startswith(version_prefix))
        self.assertTrue(p007_sig.startswith(version_prefix))

    def test_ascii_enforcement_across_patterns(self):
        """Test that ASCII enforcement works across all patterns."""
        unicode_concept = "concept_with_€"

        with self.assertRaises(ValueError):
            canonical_signature_p001(unicode_concept, "s", "e", "p", "d", None)
        with self.assertRaises(ValueError):
            canonical_signature_p002(unicode_concept, ["issue"])
        with self.assertRaises(ValueError):
            canonical_signature_p004(unicode_concept, "ctx", None, "issue")
        with self.assertRaises(ValueError):
            canonical_signature_p007("s", unicode_concept, "p", "d")


class TestRegressionPrevention(TestCase):
    """Test cases to prevent regressions in canonical signatures."""

    def test_canonical_signature_format_stability(self):
        """Test that canonical signature format remains stable."""
        # This test locks the exact format to prevent accidental changes

        # P001 format test
        p001 = canonical_signature_p001(
            "{http://test}Revenue", "http://cik", "123", "instant:2023-12-31", "seg=A",
            NormalizedUnit(("{iso4217}USD",), True)
        )
        self.assertEqual(
            p001,
            b"v1|P001|{http://test}Revenue|http://cik|123|instant:2023-12-31|seg=A|{iso4217}USD"
        )

        # P002 format test
        p002 = canonical_signature_p002("{http://test}Custom", ["anchor_missing", "calc_weak"])
        self.assertEqual(
            p002,
            b"v1|P002|{http://test}Custom|anchor_missing,calc_weak"
        )

        # P004 format test
        p004 = canonical_signature_p004("{http://test}Income", "ctx123", None, "invalid_type")
        self.assertEqual(
            p004,
            b"v1|P004|{http://test}Income|ctx123||invalid_type"
        )

    def test_empty_and_boundary_cases(self):
        """Test empty values and boundary cases for stability."""
        # Empty dimension signature
        empty_dims = dimension_signature([])
        self.assertEqual(empty_dims, "")

        # Empty issue codes (should still work)
        p002_empty = canonical_signature_p002("{http://test}C", [])
        self.assertEqual(p002_empty, b"v1|P002|{http://test}C|")

        # Single character values
        p007_minimal = canonical_signature_p007("s", "e", "p", "")
        self.assertEqual(p007_minimal, b"v1|P007|s|e|p|")


if __name__ == '__main__':
    unittest.main()