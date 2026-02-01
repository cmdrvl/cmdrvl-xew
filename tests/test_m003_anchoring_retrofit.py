"""
Unit tests for XEW-M003 Anchoring Retrofit Marker.
"""

import unittest

from cmdrvl_xew.markers.m003_anchoring_retrofit import (
    AnchoringCoverageSnapshot,
    AnchoringRetrofitThresholds,
    detect_anchoring_retrofit_marker,
)


class TestAnchoringRetrofitMarker(unittest.TestCase):
    """Test cases for M003 anchoring retrofit marker detection."""

    def _snapshot(self, accession: str, extensions, anchored):
        return AnchoringCoverageSnapshot(
            accession=accession,
            extension_qnames=extensions,
            anchored_qnames=anchored,
        )

    def test_no_history_returns_none(self):
        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:A"],
            current_anchored_qnames=["ex:A"],
            history_snapshots=[],
        )
        self.assertIsNone(result)

    def test_previous_below_min_previous_count(self):
        thresholds = AnchoringRetrofitThresholds(min_previous_extension_count=5)
        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:A"],
            current_anchored_qnames=["ex:A"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["ex:A"], [])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_no_coverage_increase_returns_none(self):
        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:A", "ex:B"],
            current_anchored_qnames=["ex:A"],
            history_snapshots=[self._snapshot("0000123456-25-000009", ["ex:A", "ex:B"], ["ex:A"])],
            thresholds=AnchoringRetrofitThresholds(min_coverage_increase=0.1, min_anchored_increase_count=1, min_previous_extension_count=1),
        )
        self.assertIsNone(result)

    def test_increase_below_thresholds_returns_none(self):
        thresholds = AnchoringRetrofitThresholds(min_coverage_increase=0.5, min_anchored_increase_count=5, min_previous_extension_count=10)
        previous_extensions = [f"ex:Old{i}" for i in range(20)]
        previous_anchored = previous_extensions[:5]
        current_extensions = previous_extensions
        current_anchored = previous_extensions[:10]

        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=current_extensions,
            current_anchored_qnames=current_anchored,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_extensions, previous_anchored)],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_detects_retrofit_and_builds_evidence(self):
        thresholds = AnchoringRetrofitThresholds(min_coverage_increase=0.2, min_anchored_increase_count=5, min_previous_extension_count=10)
        previous_extensions = [f"ex:Old{i}" for i in range(20)]
        previous_anchored = previous_extensions[:2]
        current_extensions = previous_extensions
        current_anchored = previous_extensions[:10]

        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=current_extensions,
            current_anchored_qnames=current_anchored,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_extensions, previous_anchored)],
            thresholds=thresholds,
            max_examples=4,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["marker_id"], "XEW-M003")
        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")
        self.assertEqual(result["boundary"]["to_accession"], "0000123456-25-000010")

        evidence = result["evidence"]
        self.assertEqual(evidence["previous_extension_count"], 20)
        self.assertEqual(evidence["current_extension_count"], 20)
        self.assertEqual(evidence["previous_anchored_count"], 2)
        self.assertEqual(evidence["current_anchored_count"], 10)
        self.assertGreaterEqual(evidence["coverage_increase"], 0.2)
        self.assertEqual(evidence["anchored_increase"], 8)
        self.assertLessEqual(len(evidence["newly_anchored_examples"]), 4)

    def test_examples_sorted_and_limited(self):
        previous_extensions = [f"ex:Old{i:02d}" for i in range(20)]
        previous_anchored = ["ex:Old00"]
        current_extensions = previous_extensions
        current_anchored = previous_extensions[:10]

        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=current_extensions,
            current_anchored_qnames=current_anchored,
            history_snapshots=[self._snapshot("0000123456-25-000009", previous_extensions, previous_anchored)],
            thresholds=AnchoringRetrofitThresholds(min_coverage_increase=0.1, min_anchored_increase_count=1, min_previous_extension_count=1),
            max_examples=3,
        )

        evidence = result["evidence"]
        examples = evidence["newly_anchored_examples"]
        self.assertEqual(examples, sorted(examples))
        self.assertEqual(len(examples), 3)

    def test_selects_most_recent_prior_snapshot(self):
        history = [
            self._snapshot("0000123456-25-000005", ["ex:A"], ["ex:A"]),
            self._snapshot("0000123456-25-000009", ["ex:A", "ex:B"], ["ex:A"]),
            self._snapshot("0000123456-25-000008", ["ex:A"], []),
        ]

        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:A", "ex:B"],
            current_anchored_qnames=["ex:A", "ex:B"],
            history_snapshots=history,
            thresholds=AnchoringRetrofitThresholds(min_coverage_increase=0.1, min_anchored_increase_count=1, min_previous_extension_count=1),
        )

        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")

    def test_invalid_history_accessions_are_ignored(self):
        history = [
            self._snapshot("bad-accession", ["ex:A"], ["ex:A"]),
        ]

        result = detect_anchoring_retrofit_marker(
            current_accession="0000123456-25-000010",
            current_extension_qnames=["ex:A"],
            current_anchored_qnames=["ex:A"],
            history_snapshots=history,
            thresholds=AnchoringRetrofitThresholds(min_coverage_increase=0.1, min_anchored_increase_count=1, min_previous_extension_count=1),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
