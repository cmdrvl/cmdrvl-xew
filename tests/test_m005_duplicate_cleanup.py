"""
Unit tests for XEW-M005 Duplicate Cleanup Marker.
"""

import unittest

from cmdrvl_xew.detectors._base import DetectorFinding, DetectorInstance
from cmdrvl_xew.markers.m005_duplicate_cleanup import (
    DuplicateCleanupThresholds,
    DuplicateSignatureSnapshot,
    detect_duplicate_cleanup_marker,
    detect_duplicate_cleanup_from_findings,
)


class TestDuplicateCleanupMarker(unittest.TestCase):
    """Test cases for M005 duplicate cleanup marker detection."""

    def _snapshot(self, accession: str, signature_ids):
        return DuplicateSignatureSnapshot(accession=accession, signature_ids=signature_ids)

    def test_no_history_returns_none(self):
        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=["a", "b"],
            history_snapshots=[],
        )
        self.assertIsNone(result)

    def test_previous_below_min_previous_count(self):
        thresholds = DuplicateCleanupThresholds(min_previous_count=5)
        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=["a"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["a", "b", "c", "d"])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_no_drop_returns_none(self):
        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=["a", "b", "c"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["a", "b", "c"])],
        )
        self.assertIsNone(result)

    def test_drop_below_thresholds_returns_none(self):
        thresholds = DuplicateCleanupThresholds(min_drop_ratio=0.5, min_drop_count=10, min_previous_count=20)
        previous_ids = [f"sig{i}" for i in range(40)]
        current_ids = previous_ids[:30]  # drop 10, ratio 0.25

        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=current_ids,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_ids)],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_detects_cleanup_and_builds_evidence(self):
        thresholds = DuplicateCleanupThresholds(min_drop_ratio=0.5, min_drop_count=10, min_previous_count=20)
        previous_ids = [f"sig{i}" for i in range(50)]
        current_ids = previous_ids[:20]  # drop 30, ratio 0.6

        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=current_ids,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_ids)],
            thresholds=thresholds,
            max_examples=5,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["marker_id"], "XEW-M005")
        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")
        self.assertEqual(result["boundary"]["to_accession"], "0000123456-25-000010")

        evidence = result["evidence"]
        self.assertEqual(evidence["previous_duplicate_signature_count"], 50)
        self.assertEqual(evidence["current_duplicate_signature_count"], 20)
        self.assertEqual(evidence["drop_count"], 30)
        self.assertAlmostEqual(evidence["drop_ratio"], 0.6)
        self.assertEqual(evidence["removed_signature_count"], 30)
        self.assertLessEqual(len(evidence["removed_signature_examples"]), 5)

    def test_examples_are_sorted_and_limited(self):
        previous_ids = [f"sig{i:02d}" for i in range(30)]
        current_ids = ["sig00", "sig01", "sig02"]

        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=current_ids,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_ids)],
            thresholds=DuplicateCleanupThresholds(min_drop_ratio=0.1, min_drop_count=1, min_previous_count=1),
            max_examples=3,
        )

        evidence = result["evidence"]
        examples = evidence["removed_signature_examples"]
        self.assertEqual(examples, sorted(examples))
        self.assertEqual(len(examples), 3)

    def test_selects_most_recent_prior_snapshot(self):
        history = [
            self._snapshot("0000123456-25-000005", ["a", "b", "c", "d", "e"]),
            self._snapshot("0000123456-25-000009", ["a", "b", "c", "d", "e", "f", "g"]),
            self._snapshot("0000123456-25-000008", ["a", "b", "c", "d"]),
        ]

        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=["a"],
            history_snapshots=history,
            thresholds=DuplicateCleanupThresholds(min_drop_ratio=0.1, min_drop_count=1, min_previous_count=1),
        )

        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")

    def test_invalid_history_accessions_are_ignored(self):
        history = [
            self._snapshot("not-an-accession", ["a", "b", "c"]),
        ]

        result = detect_duplicate_cleanup_marker(
            current_accession="0000123456-25-000010",
            current_signature_ids=["a"],
            history_snapshots=history,
            thresholds=DuplicateCleanupThresholds(min_drop_ratio=0.1, min_drop_count=1, min_previous_count=1),
        )

        self.assertIsNone(result)

    def test_detects_cleanup_from_findings(self):
        previous_ids = [f"sig{i}" for i in range(30)]
        current_ids = previous_ids[:10]

        findings = [
            DetectorFinding(
                finding_id="XEW-F-0000123456-25-000010-XEW-P001",
                pattern_id="XEW-P001",
                pattern_name="Duplicate Facts",
                alert_eligible=True,
                status="detected",
                instances=[
                    DetectorInstance(
                        instance_id=value,
                        kind="duplicate_fact_set",
                        primary=True,
                        data={},
                    )
                    for value in current_ids
                ],
            ),
            DetectorFinding(
                finding_id="XEW-F-0000123456-25-000010-XEW-P005",
                pattern_id="XEW-P005",
                pattern_name="Taxonomy",
                alert_eligible=True,
                status="detected",
                instances=[],
            ),
        ]

        result = detect_duplicate_cleanup_from_findings(
            current_accession="0000123456-25-000010",
            findings=findings,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_ids)],
            thresholds=DuplicateCleanupThresholds(min_drop_ratio=0.1, min_drop_count=1, min_previous_count=1),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["marker_id"], "XEW-M005")


if __name__ == "__main__":
    unittest.main()
