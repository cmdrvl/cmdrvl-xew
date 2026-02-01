"""
Unit tests for XEW-M004 Context Model Rewrite Marker.
"""

import unittest

from cmdrvl_xew.markers.m004_context_model_rewrite import (
    ContextModelSnapshot,
    ContextModelRewriteThresholds,
    detect_context_model_rewrite_marker,
)


class TestContextModelRewriteMarker(unittest.TestCase):
    """Test cases for M004 context model rewrite marker detection."""

    def _snapshot(self, accession: str, context_count: int, dim_sets):
        return ContextModelSnapshot(
            accession=accession,
            context_count=context_count,
            dimension_member_signatures=dim_sets,
        )

    def test_no_history_returns_none(self):
        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=120,
            current_dimension_member_signatures=["dim=A"],
            history_snapshots=[],
        )
        self.assertIsNone(result)

    def test_insufficient_baseline_returns_none(self):
        thresholds = ContextModelRewriteThresholds(
            min_previous_context_count=50,
            min_previous_dim_member_count=10,
        )
        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=10,
            current_dimension_member_signatures=["dim=A"],
            history_snapshots=[self._snapshot("0000123456-25-000009", 5, ["dim=A"])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_context_change_below_thresholds_returns_none(self):
        thresholds = ContextModelRewriteThresholds(
            min_context_count_change_ratio=0.5,
            min_context_count_change=50,
            min_previous_context_count=10,
            min_previous_dim_member_count=1,
        )
        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=120,
            current_dimension_member_signatures=["dim=A"],
            history_snapshots=[self._snapshot("0000123456-25-000009", 100, ["dim=A"])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_dim_churn_below_thresholds_returns_none(self):
        thresholds = ContextModelRewriteThresholds(
            min_dim_member_churn_ratio=0.6,
            min_dim_member_churn_count=10,
            min_previous_dim_member_count=5,
            min_previous_context_count=1,
        )
        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=100,
            current_dimension_member_signatures=["dim=A", "dim=B"],
            history_snapshots=[self._snapshot("0000123456-25-000009", 100, ["dim=A", "dim=C", "dim=D", "dim=E", "dim=F"])],
            thresholds=thresholds,
        )
        self.assertIsNone(result)

    def test_detects_context_change(self):
        thresholds = ContextModelRewriteThresholds(
            min_context_count_change_ratio=0.4,
            min_context_count_change=25,
            min_previous_context_count=50,
            min_previous_dim_member_count=1,
        )
        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=170,
            current_dimension_member_signatures=["dim=A"],
            history_snapshots=[self._snapshot("0000123456-25-000009", 100, ["dim=A"])],
            thresholds=thresholds,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["marker_id"], "XEW-M004")
        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")
        self.assertEqual(result["boundary"]["to_accession"], "0000123456-25-000010")
        evidence = result["evidence"]
        self.assertTrue(evidence["context_change_triggered"])
        self.assertGreaterEqual(evidence["context_count_change"], 25)

    def test_detects_dimension_member_churn(self):
        thresholds = ContextModelRewriteThresholds(
            min_dim_member_churn_ratio=0.4,
            min_dim_member_churn_count=5,
            min_previous_dim_member_count=5,
            min_previous_context_count=1,
        )
        previous_dim_sets = [f"dim=A{i:02d}" for i in range(10)]
        current_dim_sets = [f"dim=B{i:02d}" for i in range(10)]

        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=100,
            current_dimension_member_signatures=current_dim_sets,
            history_snapshots=[self._snapshot("0000123456-25-000009", 100, previous_dim_sets)],
            thresholds=thresholds,
            max_examples=3,
        )

        self.assertIsNotNone(result)
        evidence = result["evidence"]
        self.assertTrue(evidence["dimension_member_change_triggered"])
        self.assertEqual(evidence["new_dimension_member_set_count"], 10)
        self.assertEqual(evidence["retired_dimension_member_set_count"], 10)
        self.assertEqual(len(evidence["new_dimension_member_set_examples"]), 3)
        self.assertEqual(len(evidence["retired_dimension_member_set_examples"]), 3)

    def test_examples_sorted_and_limited(self):
        previous_dim_sets = [f"dim=A{i:02d}" for i in range(10)]
        current_dim_sets = [f"dim=B{i:02d}" for i in range(10)]

        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=100,
            current_dimension_member_signatures=current_dim_sets,
            history_snapshots=[self._snapshot("0000123456-25-000009", 100, previous_dim_sets)],
            thresholds=ContextModelRewriteThresholds(
                min_dim_member_churn_ratio=0.1,
                min_dim_member_churn_count=1,
                min_previous_dim_member_count=1,
                min_previous_context_count=1,
            ),
            max_examples=4,
        )

        evidence = result["evidence"]
        new_examples = evidence["new_dimension_member_set_examples"]
        retired_examples = evidence["retired_dimension_member_set_examples"]
        self.assertEqual(new_examples, sorted(new_examples))
        self.assertEqual(retired_examples, sorted(retired_examples))
        self.assertEqual(len(new_examples), 4)
        self.assertEqual(len(retired_examples), 4)

    def test_selects_most_recent_prior_snapshot(self):
        history = [
            self._snapshot("0000123456-25-000005", 100, ["dim=A"]),
            self._snapshot("0000123456-25-000009", 100, ["dim=A", "dim=B"]),
            self._snapshot("0000123456-25-000008", 100, ["dim=A"]),
        ]

        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=160,
            current_dimension_member_signatures=["dim=A", "dim=B"],
            history_snapshots=history,
            thresholds=ContextModelRewriteThresholds(
                min_context_count_change_ratio=0.1,
                min_context_count_change=1,
                min_previous_context_count=1,
                min_previous_dim_member_count=1,
            ),
        )

        self.assertEqual(result["boundary"]["from_accession"], "0000123456-25-000009")

    def test_invalid_history_accessions_are_ignored(self):
        history = [
            self._snapshot("bad-accession", 100, ["dim=A"]),
        ]

        result = detect_context_model_rewrite_marker(
            current_accession="0000123456-25-000010",
            current_context_count=200,
            current_dimension_member_signatures=["dim=A", "dim=B"],
            history_snapshots=history,
            thresholds=ContextModelRewriteThresholds(
                min_context_count_change_ratio=0.1,
                min_context_count_change=1,
                min_previous_context_count=1,
                min_previous_dim_member_count=1,
            ),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
