"""
Unit tests for XEW-M001 Taxonomy Refresh Marker.
"""

import unittest
from typing import Dict, Any, List

from cmdrvl_xew.markers.m001_taxonomy_refresh import TaxonomyRefreshMarker
from cmdrvl_xew.markers.base import MarkerEvidence


class TestTaxonomyRefreshMarker(unittest.TestCase):
    """Test cases for M001 taxonomy refresh marker."""

    def setUp(self):
        """Set up test fixtures."""
        self.marker = TaxonomyRefreshMarker()

    def test_marker_properties(self):
        """Test basic marker properties."""
        self.assertEqual(self.marker.marker_id, "XEW-M001")
        self.assertEqual(self.marker.marker_name, "Taxonomy Refresh Detection")

        thresholds = self.marker.default_thresholds
        self.assertIn("min_schema_ref_changes", thresholds)
        self.assertIn("major_change_threshold", thresholds)
        self.assertIsInstance(thresholds["extension_schema_weight"], float)

    def test_no_history_window(self):
        """Test analysis when no history window is available."""
        current_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=[]
        )

        result = self.marker.analyze(current_filing, [], None)

        self.assertFalse(result.detected)
        self.assertEqual(result.marker_id, "XEW-M001")
        self.assertEqual(result.boundary["current"], "0000123456-25-000001")
        self.assertEqual(len(result.evidence), 0)
        self.assertEqual(result.analysis_metadata["total_filings_analyzed"], 0)

    def test_no_schema_changes(self):
        """Test when schemas are identical between filings."""
        schema_refs = [
            {"href": "https://xbrl.sec.gov/dei/2023/dei-2023.xsd", "namespace": "http://xbrl.sec.gov/dei/2023", "type": "standard", "basename": "dei-2023"},
            {"href": "https://example.com/ext-2023.xsd", "namespace": "http://example.com/ext/2023", "type": "extension", "basename": "ext-2023"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000002",
            form="10-Q",
            schema_refs=schema_refs
        )

        reference_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=schema_refs
        )

        result = self.marker.analyze(current_filing, [reference_filing], None)

        self.assertFalse(result.detected)
        self.assertEqual(len(result.evidence), 0)
        self.assertEqual(result.analysis_metadata["change_score"], 0.0)

    def test_schema_added(self):
        """Test detection when new schemas are added."""
        reference_schemas = [
            {"href": "https://xbrl.sec.gov/dei/2023/dei-2023.xsd", "namespace": "http://xbrl.sec.gov/dei/2023", "type": "standard", "basename": "dei-2023"}
        ]

        current_schemas = reference_schemas + [
            {"href": "https://example.com/new-ext.xsd", "namespace": "http://example.com/new", "type": "extension", "basename": "new-ext"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000002",
            form="10-Q",
            schema_refs=current_schemas
        )

        reference_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=reference_schemas
        )

        result = self.marker.analyze(current_filing, [reference_filing], None)

        # Should detect change (extension weight = 2.0, threshold = 3.0, so not detected by default)
        self.assertFalse(result.detected)  # Score 2.0 < 3.0 threshold
        self.assertEqual(result.analysis_metadata["changes_detected"], 1)
        self.assertEqual(result.analysis_metadata["change_score"], 2.0)

        # Test with lower threshold
        custom_thresholds = {"major_change_threshold": 1.5}
        result_detected = self.marker.analyze(current_filing, [reference_filing], custom_thresholds)
        self.assertTrue(result_detected.detected)

    def test_schema_removed(self):
        """Test detection when schemas are removed."""
        current_schemas = [
            {"href": "https://xbrl.sec.gov/dei/2023/dei-2023.xsd", "namespace": "http://xbrl.sec.gov/dei/2023", "type": "standard", "basename": "dei-2023"}
        ]

        reference_schemas = current_schemas + [
            {"href": "https://example.com/old-ext.xsd", "namespace": "http://example.com/old", "type": "extension", "basename": "old-ext"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000002",
            form="10-Q",
            schema_refs=current_schemas
        )

        reference_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=reference_schemas
        )

        result = self.marker.analyze(current_filing, [reference_filing], None)

        # Should detect schema removal
        self.assertFalse(result.detected)  # Score 2.0 < 3.0 threshold
        self.assertEqual(result.analysis_metadata["changes_detected"], 1)
        self.assertEqual(result.analysis_metadata["change_score"], 2.0)

    def test_namespace_change(self):
        """Test detection of namespace version changes."""
        reference_schemas = [
            {"href": "https://xbrl.sec.gov/dei/2022/dei-2022.xsd", "namespace": "http://xbrl.sec.gov/dei/2022", "type": "standard", "basename": "dei"},
            {"href": "https://example.com/ext-v1.xsd", "namespace": "http://example.com/ext/v1", "type": "extension", "basename": "ext"}
        ]

        current_schemas = [
            {"href": "https://xbrl.sec.gov/dei/2023/dei-2023.xsd", "namespace": "http://xbrl.sec.gov/dei/2023", "type": "standard", "basename": "dei"},
            {"href": "https://example.com/ext-v2.xsd", "namespace": "http://example.com/ext/v2", "type": "extension", "basename": "ext"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000002",
            form="10-Q",
            schema_refs=current_schemas
        )

        reference_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=reference_schemas
        )

        result = self.marker.analyze(current_filing, [reference_filing], None)

        # Should detect: 2 removed + 2 added + 2 namespace changes = 6 changes
        # Score: 2*1.0 (std removed) + 2*1.0 (std added) + 2*2.0 (ext removed) + 2*2.0 (ext added) + 2*1.5 (ns change) = 13.0
        self.assertTrue(result.detected)
        self.assertEqual(result.analysis_metadata["changes_detected"], 6)
        self.assertGreater(result.analysis_metadata["change_score"], 3.0)

    def test_major_taxonomy_refresh(self):
        """Test detection of major taxonomy refresh with multiple changes."""
        reference_schemas = [
            {"href": "https://xbrl.sec.gov/dei/2022/dei-2022.xsd", "namespace": "http://xbrl.sec.gov/dei/2022", "type": "standard", "basename": "dei"},
            {"href": "https://example.com/old-ext.xsd", "namespace": "http://example.com/old", "type": "extension", "basename": "old-ext"}
        ]

        current_schemas = [
            {"href": "https://xbrl.sec.gov/dei/2023/dei-2023.xsd", "namespace": "http://xbrl.sec.gov/dei/2023", "type": "standard", "basename": "dei"},
            {"href": "https://example.com/new-ext1.xsd", "namespace": "http://example.com/new1", "type": "extension", "basename": "new-ext1"},
            {"href": "https://example.com/new-ext2.xsd", "namespace": "http://example.com/new2", "type": "extension", "basename": "new-ext2"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000002",
            form="10-Q",
            schema_refs=current_schemas
        )

        reference_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=reference_schemas
        )

        result = self.marker.analyze(current_filing, [reference_filing], None)

        # Should detect major refresh
        # 1 removed extension (2.0) + 2 added extensions (4.0) + 1 namespace change (1.5) = 7.5 > 3.0
        self.assertTrue(result.detected)
        self.assertGreater(result.analysis_metadata["change_score"], 3.0)
        self.assertGreater(len(result.evidence), 0)

    def test_evidence_generation(self):
        """Test that evidence is generated correctly."""
        reference_schemas = [
            {"href": "https://example.com/old.xsd", "namespace": "http://example.com/old", "type": "extension", "basename": "old"}
        ]

        current_schemas = [
            {"href": "https://example.com/new.xsd", "namespace": "http://example.com/new", "type": "extension", "basename": "new"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000002",
            form="10-Q",
            schema_refs=current_schemas
        )

        reference_filing = self._create_test_filing(
            accession="0000123456-25-000001",
            form="10-Q",
            schema_refs=reference_schemas
        )

        # Use low threshold to trigger detection
        result = self.marker.analyze(current_filing, [reference_filing], {"major_change_threshold": 1.0})

        self.assertTrue(result.detected)
        self.assertGreater(len(result.evidence), 0)

        # Check evidence structure
        evidence_types = [e.evidence_type for e in result.evidence]
        self.assertIn("taxonomy_change_summary", evidence_types)

        # Check summary evidence details
        summary_evidence = next(e for e in result.evidence if e.evidence_type == "taxonomy_change_summary")
        self.assertIn("current_accession", summary_evidence.details)
        self.assertIn("reference_accession", summary_evidence.details)
        self.assertIn("change_count", summary_evidence.details)

    def test_threshold_validation(self):
        """Test threshold validation."""
        # Valid thresholds
        valid_thresholds = {
            "min_schema_ref_changes": 1,
            "significant_namespace_change": True,
            "extension_schema_weight": 2.0,
            "standard_taxonomy_weight": 1.0,
            "major_change_threshold": 3.0
        }

        errors = self.marker.validate_thresholds(valid_thresholds)
        self.assertEqual(len(errors), 0)

        # Missing required threshold
        incomplete_thresholds = {
            "min_schema_ref_changes": 1
        }

        errors = self.marker.validate_thresholds(incomplete_thresholds)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("Missing required threshold" in error for error in errors))

    def test_multiple_history_filings(self):
        """Test with multiple filings in history window."""
        schema_refs_old = [
            {"href": "https://example.com/old.xsd", "namespace": "http://example.com/old", "type": "extension", "basename": "old"}
        ]

        schema_refs_current = [
            {"href": "https://example.com/new.xsd", "namespace": "http://example.com/new", "type": "extension", "basename": "new"}
        ]

        current_filing = self._create_test_filing(
            accession="0000123456-25-000003",
            form="10-Q",
            schema_refs=schema_refs_current
        )

        # Multiple history filings - should use most recent as reference
        history_window = [
            self._create_test_filing(
                accession="0000123456-25-000001",
                form="10-Q",
                schema_refs=schema_refs_old
            ),
            self._create_test_filing(
                accession="0000123456-25-000002",
                form="10-Q",
                schema_refs=schema_refs_old
            )
        ]

        result = self.marker.analyze(current_filing, history_window, {"major_change_threshold": 1.0})

        self.assertTrue(result.detected)
        self.assertEqual(result.analysis_metadata["total_filings_analyzed"], 2)
        # Should use most recent filing (000002) as reference
        self.assertEqual(result.boundary["reference"], "0000123456-25-000002")

    def _create_test_filing(self, accession: str, form: str, schema_refs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Create a test filing with the specified schema references."""
        return {
            "accession": accession,
            "form": form,
            "filed_date": "2025-11-15",
            "cik": "0000123456",
            "issuer_name": "Test Company Inc.",
            "period_end": "2025-09-30",
            "schema_references": schema_refs,
            "primary_artifact": {
                "local_path": f"{accession}_primary.htm",
                "source_url": f"https://sec.gov/{accession}/primary.htm"
            },
            "extension_artifacts": []
        }


if __name__ == '__main__':
    unittest.main()