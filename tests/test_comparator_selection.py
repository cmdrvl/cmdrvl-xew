"""Tests for comparator and history selection helpers."""

import unittest

from cmdrvl_xew.comparator_selection import select_comparator_and_history


def _entry(accession: str, token: str) -> dict[str, str]:
    return {
        "accession": accession,
        "primary_document_url": f"https://example.com/{token}.html",
        "primary_artifact_path": f"/tmp/{token}.html",
    }


class TestComparatorSelection(unittest.TestCase):
    """Validate comparator selection and history window ordering."""

    def test_explicit_comparator_wins(self):
        explicit = _entry("0000123456-26-000005", "explicit")
        history = [
            _entry("0000123456-25-000100", "h1"),
            _entry("0000123456-26-000004", "h2"),
        ]

        result = select_comparator_and_history(
            form="10-Q",
            explicit_comparator=explicit,
            history_entries=history,
            current_accession="0000123456-26-000010",
        )

        self.assertEqual(result.selected_comparator, explicit)
        self.assertEqual(result.selection_metadata["selection_reason"], "explicit_user_provided")
        self.assertIn(explicit, result.history_window)

    def test_selects_most_recent_prior_accession(self):
        history = [
            _entry("0000123456-25-000100", "h1"),
            _entry("0000123456-26-000005", "h2"),
            _entry("0000123456-26-000009", "h3"),
            _entry("0000123456-26-000010", "h4"),
        ]

        result = select_comparator_and_history(
            form="10-Q",
            explicit_comparator=None,
            history_entries=history,
            current_accession="0000123456-26-000010",
        )

        self.assertIsNotNone(result.selected_comparator)
        self.assertEqual(result.selected_comparator["accession"], "0000123456-26-000009")
        self.assertEqual(result.selection_metadata["selection_reason"], "auto_selected_from_history")

    def test_comparator_not_required_for_event_forms(self):
        history = [
            _entry("0000123456-26-000005", "h1"),
            _entry("0000123456-26-000006", "h2"),
        ]

        result = select_comparator_and_history(
            form="8-K",
            explicit_comparator=None,
            history_entries=history,
            current_accession="0000123456-26-000010",
        )

        self.assertIsNone(result.selected_comparator)
        self.assertEqual(result.selection_metadata["selection_reason"], "not_required_by_policy")

    def test_history_window_is_limited_and_ordered(self):
        history = [
            _entry("0000123456-25-000100", "h1"),
            _entry("0000123456-25-000101", "h2"),
            _entry("0000123456-25-000102", "h3"),
            _entry("0000123456-25-000103", "h4"),
            _entry("0000123456-25-000104", "h5"),
            _entry("0000123456-25-000105", "h6"),
        ]

        result = select_comparator_and_history(
            form="10-K",
            explicit_comparator=None,
            history_entries=history,
            current_accession="0000123456-26-000010",
        )

        self.assertEqual(len(result.history_window), 5)
        accessions = [entry["accession"] for entry in result.history_window]
        self.assertEqual(accessions, sorted(accessions))


if __name__ == "__main__":
    unittest.main()
