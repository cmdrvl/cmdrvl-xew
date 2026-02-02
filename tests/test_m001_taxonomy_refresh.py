"""
Unit tests for XEW-M001 Taxonomy Refresh Marker.
"""

import unittest

from cmdrvl_xew.markers.m001_taxonomy_refresh import (
    TaxonomyRefreshThresholds,
    TaxonomySchemaSnapshot,
    detect_taxonomy_refresh_marker,
)


class TestTaxonomyRefreshMarker(unittest.TestCase):
    """Test cases for M001 taxonomy refresh marker detection."""

    def _snapshot(self, accession: str, schema_refs):
        return TaxonomySchemaSnapshot(accession=accession, schema_refs=schema_refs)

    def test_no_history_returns_none(self):
        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=["a.xsd"],
            history_snapshots=[],
        )
        self.assertIsNone(result)

    def test_previous_below_min_previous_count(self):
        thresholds = TaxonomyRefreshThresholds(min_previous_count=3)
        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=["a.xsd"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["a.xsd", "b.xsd"])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_no_change_returns_none(self):
        schema_refs = ["a.xsd", "b.xsd"]
        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=schema_refs,
            history_snapshots=[self._snapshot("0000123456-25-000009", schema_refs)],
        )
        self.assertIsNone(result)

    def test_change_below_thresholds_returns_none(self):
        thresholds = TaxonomyRefreshThresholds(min_change_count=2, min_change_ratio=0.8, min_previous_count=1)
        previous_refs = ["a.xsd", "b.xsd", "c.xsd"]
        current_refs = ["a.xsd", "b.xsd", "d.xsd"]  # change_count=2, ratio=0.666

        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=current_refs,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_refs)],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_detects_refresh_and_builds_evidence(self):
        previous_refs = ["a.xsd", "b.xsd"]
        current_refs = ["a.xsd", "c.xsd"]

        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=current_refs,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_refs)],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["marker_id"], "XEW-M001")
        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")
        self.assertEqual(result["boundary"]["to_accession"], "0000123456-25-000010")

        evidence = result["evidence"]
        self.assertEqual(evidence["previous_schema_ref_count"], 2)
        self.assertEqual(evidence["current_schema_ref_count"], 2)
        self.assertEqual(evidence["schema_ref_change_count"], 2)
        self.assertEqual(evidence["schema_ref_change_ratio"], 1.0)
        self.assertEqual(evidence["added_schema_refs"], ["c.xsd"])
        self.assertEqual(evidence["removed_schema_refs"], ["b.xsd"])
        self.assertIn("thresholds", evidence)

    def test_selects_most_recent_prior_snapshot(self):
        history = [
            self._snapshot("0000123456-25-000005", ["a.xsd"]),
            self._snapshot("0000123456-25-000009", ["a.xsd", "b.xsd"]),
            self._snapshot("0000123456-25-000008", ["a.xsd"]),
        ]

        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=["a.xsd", "c.xsd"],
            history_snapshots=history,
            thresholds=TaxonomyRefreshThresholds(min_change_ratio=0.1, min_change_count=1, min_previous_count=1),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")

    def test_invalid_history_accessions_are_ignored(self):
        history = [
            self._snapshot("not-an-accession", ["a.xsd"]),
        ]

        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=["a.xsd", "b.xsd"],
            history_snapshots=history,
        )

        self.assertIsNone(result)

    def test_schema_refs_are_deduped_and_sorted(self):
        previous_refs = ["b.xsd", "a.xsd"]
        current_refs = ["b.xsd", "a.xsd", "a.xsd", "c.xsd", " "]

        result = detect_taxonomy_refresh_marker(
            current_accession="0000123456-25-000010",
            current_schema_refs=current_refs,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_refs)],
        )

        evidence = result["evidence"]
        self.assertEqual(evidence["previous_schema_refs"], ["a.xsd", "b.xsd"])
        self.assertEqual(evidence["current_schema_refs"], ["a.xsd", "b.xsd", "c.xsd"])


if __name__ == "__main__":
    unittest.main()
