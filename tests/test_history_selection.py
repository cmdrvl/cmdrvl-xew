"""
Unit tests for history window and comparator selection logic.
"""

import unittest
from datetime import date, datetime
from typing import List

from cmdrvl_xew.history_selection import (
    FilingReference,
    SelectionCriteria,
    SelectionResult,
    select_comparator_and_history,
    _filter_compatible_filings,
    _select_comparator,
    _find_same_quarter_prior_year,
    _find_previous_period,
    filing_reference_from_dict,
    filing_reference_to_dict
)


class TestFilingReference(unittest.TestCase):
    """Test cases for FilingReference data structure."""

    def test_filing_reference_creation(self):
        """Test FilingReference creation with all fields."""
        ref = FilingReference(
            cik="0000123456",
            accession="0000123456-12-000001",
            form="10-Q",
            filed_date="2025-11-15",
            period_end="2025-09-30",
            fiscal_year=2025,
            fiscal_period="Q3"
        )

        self.assertEqual(ref.cik, "0000123456")
        self.assertEqual(ref.accession, "0000123456-12-000001")
        self.assertEqual(ref.form, "10-Q")
        self.assertEqual(ref.filed_date, "2025-11-15")
        self.assertEqual(ref.period_end, "2025-09-30")
        self.assertEqual(ref.fiscal_year, 2025)
        self.assertEqual(ref.fiscal_period, "Q3")

    def test_filing_reference_minimal(self):
        """Test FilingReference with only required fields."""
        ref = FilingReference(
            cik="0000123456",
            accession="0000123456-12-000001",
            form="8-K",
            filed_date="2025-11-15"
        )

        self.assertEqual(ref.cik, "0000123456")
        self.assertEqual(ref.form, "8-K")
        self.assertIsNone(ref.period_end)
        self.assertIsNone(ref.fiscal_year)
        self.assertIsNone(ref.fiscal_period)

    def test_filing_reference_serialization(self):
        """Test conversion to/from dictionary."""
        original = FilingReference(
            cik="0000123456",
            accession="0000123456-12-000001",
            form="10-K",
            filed_date="2025-03-01",
            period_end="2024-12-31",
            fiscal_year=2024,
            fiscal_period="FY"
        )

        # Convert to dict and back
        data = filing_reference_to_dict(original)
        restored = filing_reference_from_dict(data)

        self.assertEqual(original, restored)


class TestSelectionCriteria(unittest.TestCase):
    """Test cases for SelectionCriteria data structure."""

    def test_selection_criteria_defaults(self):
        """Test SelectionCriteria with default values."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15"
        )

        self.assertEqual(criteria.max_history_count, 5)
        self.assertEqual(criteria.max_lookback_years, 3)
        self.assertIsNone(criteria.target_period_end)

    def test_selection_criteria_custom(self):
        """Test SelectionCriteria with custom values."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-K",
            target_filed_date="2025-03-01",
            target_period_end="2024-12-31",
            max_history_count=10,
            max_lookback_years=5
        )

        self.assertEqual(criteria.max_history_count, 10)
        self.assertEqual(criteria.max_lookback_years, 5)
        self.assertEqual(criteria.target_period_end, "2024-12-31")


class TestFilterCompatibleFilings(unittest.TestCase):
    """Test cases for _filter_compatible_filings function."""

    def setUp(self):
        """Set up test data."""
        self.criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15",
            max_lookback_years=2
        )

        self.available_filings = [
            # Same CIK, compatible forms
            FilingReference("0000123456", "0000123456-25-000001", "10-Q", "2025-08-15"),  # Recent Q3
            FilingReference("0000123456", "0000123456-25-000002", "10-Q", "2025-05-15"),  # Recent Q2
            FilingReference("0000123456", "0000123456-24-000003", "10-Q", "2024-11-15"),  # Prior year Q3
            FilingReference("0000123456", "0000123456-24-000004", "10-K", "2024-03-15"),  # Annual report
            FilingReference("0000123456", "0000123456-23-000005", "10-Q", "2023-08-15"),  # Too old

            # Different CIK (should be excluded)
            FilingReference("0000654321", "0000654321-25-000001", "10-Q", "2025-08-15"),

            # Future date (should be excluded)
            FilingReference("0000123456", "0000123456-25-000006", "10-Q", "2025-12-15"),
        ]

    def test_filter_same_cik_only(self):
        """Test that only same CIK filings are included."""
        filtered = _filter_compatible_filings(self.criteria, self.available_filings)

        for filing in filtered:
            self.assertEqual(filing.cik, "0000123456")

    def test_filter_excludes_future_dates(self):
        """Test that future-dated filings are excluded."""
        filtered = _filter_compatible_filings(self.criteria, self.available_filings)

        for filing in filtered:
            filing_date = datetime.fromisoformat(filing.filed_date).date()
            target_date = datetime.fromisoformat(self.criteria.target_filed_date).date()
            self.assertLess(filing_date, target_date)

    def test_filter_respects_lookback_window(self):
        """Test that filings outside lookback window are excluded."""
        filtered = _filter_compatible_filings(self.criteria, self.available_filings)

        # Should exclude 2023 filing (outside 2-year window)
        accessions = [f.accession for f in filtered]
        self.assertNotIn("0000123456-23-000005", accessions)

    def test_filter_sorted_by_date(self):
        """Test that results are sorted by filed date (newest first)."""
        filtered = _filter_compatible_filings(self.criteria, self.available_filings)

        dates = [f.filed_date for f in filtered]
        self.assertEqual(dates, sorted(dates, reverse=True))


class TestComparatorSelection(unittest.TestCase):
    """Test cases for comparator selection logic."""

    def setUp(self):
        """Set up test data for 10-Q filings."""
        self.quarterly_criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15",
            target_period_end="2025-09-30"  # Q3 2025
        )

        self.quarterly_filings = [
            FilingReference("0000123456", "0000123456-25-000001", "10-Q", "2025-08-15", "2025-06-30"),  # Q2 2025
            FilingReference("0000123456", "0000123456-25-000002", "10-Q", "2025-05-15", "2025-03-31"),  # Q1 2025
            FilingReference("0000123456", "0000123456-24-000003", "10-Q", "2024-11-15", "2024-09-30"), # Q3 2024 (same quarter prior year)
            FilingReference("0000123456", "0000123456-24-000004", "10-Q", "2024-08-15", "2024-06-30"), # Q2 2024
        ]

        # Event-driven filing setup
        self.event_criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="8-K",
            target_filed_date="2025-11-15"
        )

    def test_quarterly_same_quarter_prior_year_preferred(self):
        """Test that same quarter from prior year is preferred for 10-Q."""
        from cmdrvl_xew.comparator import comparator_policy
        policy = comparator_policy(self.quarterly_criteria.target_form)

        comparator = _select_comparator(self.quarterly_criteria, self.quarterly_filings, policy)

        # Should select Q3 2024 (same quarter from prior year)
        self.assertIsNotNone(comparator)
        self.assertEqual(comparator.period_end, "2024-09-30")

    def test_quarterly_previous_quarter_fallback(self):
        """Test fallback to previous quarter when same quarter not available."""
        # Remove same quarter from prior year
        filings_without_same_quarter = [
            f for f in self.quarterly_filings
            if f.period_end != "2024-09-30"
        ]

        from cmdrvl_xew.comparator import comparator_policy
        policy = comparator_policy(self.quarterly_criteria.target_form)

        comparator = _select_comparator(self.quarterly_criteria, filings_without_same_quarter, policy)

        # Should select most recent previous quarter (Q2 2025)
        self.assertIsNotNone(comparator)
        self.assertEqual(comparator.period_end, "2025-06-30")

    def test_event_driven_no_comparator(self):
        """Test that event-driven filings don't get automatic comparators."""
        from cmdrvl_xew.comparator import comparator_policy
        policy = comparator_policy(self.event_criteria.target_form)

        comparator = _select_comparator(self.event_criteria, [], policy)

        # Should not select comparator for 8-K
        self.assertIsNone(comparator)


class TestSameQuarterSelection(unittest.TestCase):
    """Test cases for same quarter prior year selection."""

    def test_find_same_quarter_prior_year(self):
        """Test finding same quarter from previous year."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15",
            target_period_end="2025-09-30"  # Q3
        )

        period_filings = [
            FilingReference("0000123456", "0000123456-25-000001", "10-Q", "2025-08-15", "2025-06-30"),  # Q2 2025
            FilingReference("0000123456", "0000123456-24-000002", "10-Q", "2024-11-15", "2024-09-30"),  # Q3 2024
            FilingReference("0000123456", "0000123456-24-000003", "10-Q", "2024-08-15", "2024-06-30"),  # Q2 2024
        ]

        result = _find_same_quarter_prior_year(criteria, period_filings)

        self.assertIsNotNone(result)
        self.assertEqual(result.period_end, "2024-09-30")  # Q3 2024

    def test_find_same_quarter_not_found(self):
        """Test when same quarter from prior year is not available."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15",
            target_period_end="2025-09-30"  # Q3
        )

        period_filings = [
            FilingReference("0000123456", "0000123456-25-000001", "10-Q", "2025-08-15", "2025-06-30"),  # Q2 2025
            FilingReference("0000123456", "0000123456-24-000003", "10-Q", "2024-08-15", "2024-06-30"),  # Q2 2024 (different quarter)
        ]

        result = _find_same_quarter_prior_year(criteria, period_filings)

        self.assertIsNone(result)


class TestHistoryWindowSelection(unittest.TestCase):
    """Test cases for history window selection."""

    def setUp(self):
        """Set up test data."""
        self.criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15",
            max_history_count=3
        )

        self.available_filings = [
            FilingReference("0000123456", "0000123456-25-000001", "10-Q", "2025-08-15"),
            FilingReference("0000123456", "0000123456-25-000002", "10-Q", "2025-05-15"),
            FilingReference("0000123456", "0000123456-24-000003", "10-Q", "2024-11-15"),
            FilingReference("0000123456", "0000123456-24-000004", "10-Q", "2024-08-15"),
            FilingReference("0000123456", "0000123456-24-000005", "10-Q", "2024-05-15"),
        ]

    def test_end_to_end_selection(self):
        """Test complete selection process."""
        result = select_comparator_and_history(self.criteria, self.available_filings)

        # Should have a comparator for 10-Q
        self.assertIsNotNone(result.comparator)
        self.assertTrue(result.policy_compliance)

        # Should have history window (limited by max_history_count)
        self.assertLessEqual(len(result.history_window), self.criteria.max_history_count)

        # History should be sorted chronologically (oldest first)
        history_dates = [f.filed_date for f in result.history_window]
        self.assertEqual(history_dates, sorted(history_dates))

        # Should have meaningful rationale
        self.assertTrue(len(result.selection_rationale) > 0)

    def test_no_available_filings(self):
        """Test when no compatible filings are available."""
        result = select_comparator_and_history(self.criteria, [])

        self.assertIsNone(result.comparator)
        self.assertEqual(len(result.history_window), 0)
        self.assertFalse(result.policy_compliance)  # 10-Q requires comparator

    def test_event_driven_form_compliance(self):
        """Test that event-driven forms show policy compliance without comparators."""
        event_criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="8-K",
            target_filed_date="2025-11-15"
        )

        result = select_comparator_and_history(event_criteria, [])

        self.assertIsNone(result.comparator)
        self.assertEqual(len(result.history_window), 0)
        self.assertTrue(result.policy_compliance)  # 8-K doesn't require comparator


class TestSelectionRationale(unittest.TestCase):
    """Test cases for selection rationale generation."""

    def test_rationale_with_comparator(self):
        """Test rationale when comparator is selected."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-Q",
            target_filed_date="2025-11-15"
        )

        available_filings = [
            FilingReference("0000123456", "0000123456-25-000001", "10-Q", "2025-08-15", "2025-06-30"),
        ]

        result = select_comparator_and_history(criteria, available_filings)

        self.assertIn("Selected comparator", result.selection_rationale)
        self.assertIn("10-Q", result.selection_rationale)
        self.assertIn("2025-08-15", result.selection_rationale)

    def test_rationale_no_comparator_required(self):
        """Test rationale when no comparator is required."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="8-K",
            target_filed_date="2025-11-15"
        )

        result = select_comparator_and_history(criteria, [])

        self.assertIn("No comparator required", result.selection_rationale)
        self.assertIn("event-driven", result.selection_rationale)

    def test_rationale_missing_required_comparator(self):
        """Test rationale when required comparator is missing."""
        criteria = SelectionCriteria(
            target_cik="0000123456",
            target_form="10-K",
            target_filed_date="2025-03-15"
        )

        result = select_comparator_and_history(criteria, [])

        self.assertIn("No suitable comparator found", result.selection_rationale)
        self.assertIn("required", result.selection_rationale)


if __name__ == '__main__':
    unittest.main()