"""
Unit tests for XEW-M002 Extension Refactor Marker.
"""

import unittest

from cmdrvl_xew.markers.m002_extension_refactor import (
    ExtensionRefactorThresholds,
    ExtensionSnapshot,
    detect_extension_refactor_marker,
)


class TestExtensionRefactorMarker(unittest.TestCase):
    """Test cases for M002 extension refactor marker detection."""

    def _snapshot(self, accession: str, qnames):
        return ExtensionSnapshot(accession=accession, qnames=qnames)

    def test_no_history_returns_none(self):
        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:One"],
            history_snapshots=[],
        )
        self.assertIsNone(result)

    def test_previous_below_min_previous_count(self):
        thresholds = ExtensionRefactorThresholds(min_previous_count=5)
        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:One"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["ex:A", "ex:B", "ex:C", "ex:D"])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_no_churn_returns_none(self):
        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:A", "ex:B"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["ex:A", "ex:B"])],
        )
        self.assertIsNone(result)

    def test_churn_below_thresholds_returns_none(self):
        thresholds = ExtensionRefactorThresholds(min_churn_ratio=0.5, min_new_count=5, min_retired_count=5, min_previous_count=10)
        previous = [f"ex:Old{i}" for i in range(20)]
        current = previous[:18] + ["ex:New1", "ex:New2"]

        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=current,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous)],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_detects_refactor_and_builds_evidence(self):
        thresholds = ExtensionRefactorThresholds(min_churn_ratio=0.25, min_new_count=3, min_retired_count=3, min_previous_count=10)
        previous = [f"ex:Old{i}" for i in range(20)]
        current = [f"ex:Old{i}" for i in range(10)] + [f"ex:New{i}" for i in range(10)]

        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=current,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous)],
            thresholds=thresholds,
            max_examples=4,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["marker_id"], "XEW-M002")
        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")
        self.assertEqual(result["boundary"]["to_accession"], "0000123456-25-000010")

        evidence = result["evidence"]
        self.assertEqual(evidence["previous_extension_count"], 20)
        self.assertEqual(evidence["current_extension_count"], 20)
        self.assertEqual(evidence["new_extension_count"], 10)
        self.assertEqual(evidence["retired_extension_count"], 10)
        self.assertEqual(evidence["churn_count"], 20)
        self.assertGreaterEqual(evidence["churn_ratio"], 0.25)
        self.assertLessEqual(len(evidence["new_extension_examples"]), 4)
        self.assertLessEqual(len(evidence["retired_extension_examples"]), 4)

    def test_examples_sorted_and_limited(self):
        previous = [f"ex:Old{i:02d}" for i in range(20)]
        current = ["ex:Old00", "ex:Old01"] + [f"ex:New{i:02d}" for i in range(10)]

        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=current,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous)],
            thresholds=ExtensionRefactorThresholds(min_churn_ratio=0.1, min_new_count=1, min_retired_count=1, min_previous_count=1),
            max_examples=3,
        )

        evidence = result["evidence"]
        self.assertEqual(evidence["new_extension_examples"], sorted(evidence["new_extension_examples"]))
        self.assertEqual(evidence["retired_extension_examples"], sorted(evidence["retired_extension_examples"]))
        self.assertEqual(len(evidence["new_extension_examples"]), 3)
        self.assertEqual(len(evidence["retired_extension_examples"]), 3)

    def test_selects_most_recent_prior_snapshot(self):
        history = [
            self._snapshot("0000123456-25-000005", ["ex:A", "ex:B"]),
            self._snapshot("0000123456-25-000009", ["ex:A", "ex:B", "ex:C"]),
            self._snapshot("0000123456-25-000008", ["ex:A"]),
        ]

        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:Z"],
            history_snapshots=history,
            thresholds=ExtensionRefactorThresholds(min_churn_ratio=0.1, min_new_count=1, min_retired_count=1, min_previous_count=1),
        )

        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")

    def test_invalid_history_accessions_are_ignored(self):
        history = [
            self._snapshot("bad-accession", ["ex:A", "ex:B"]),
        ]

        result = detect_extension_refactor_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:Z"],
            history_snapshots=history,
            thresholds=ExtensionRefactorThresholds(min_churn_ratio=0.1, min_new_count=1, min_retired_count=1, min_previous_count=1),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
