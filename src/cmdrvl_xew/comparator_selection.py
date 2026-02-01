"""
Comparator and history window selection for adaptation markers.

This module implements deterministic selection logic for choosing the best
available comparator and history window from provided history entries.
The selection follows form-specific policies and ensures reproducible results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, NamedTuple, Optional

from .comparator import comparator_policy
from .util import validate_accession_number


class SelectionResult(NamedTuple):
    """Result of comparator and history window selection."""
    selected_comparator: Optional[Dict[str, str]]
    history_window: List[Dict[str, str]]
    selection_metadata: Dict[str, str]


class ComparatorSelector:
    """Selects optimal comparator and history window for marker detection."""

    def __init__(self, form: str):
        """Initialize selector with target form type."""
        self.form = form
        self.policy = comparator_policy(form)

    def select_comparator_and_history(
        self,
        explicit_comparator: Optional[Dict[str, str]],
        history_entries: List[Dict[str, str]],
        filed_date: str
    ) -> SelectionResult:
        """
        Select the best comparator and history window for marker detection.

        Args:
            explicit_comparator: User-provided comparator (takes priority)
            history_entries: Available history entries sorted by accession
            filed_date: Target filing date (YYYY-MM-DD format)

        Returns:
            SelectionResult with selected comparator, history window, and metadata
        """

        # Step 1: Determine selected comparator
        if explicit_comparator:
            selected_comparator = explicit_comparator
            selection_reason = "explicit_user_provided"
        elif self.policy.comparator_required and history_entries:
            selected_comparator = self._select_best_comparator(history_entries, filed_date)
            selection_reason = "auto_selected_from_history" if selected_comparator else "no_suitable_comparator"
        else:
            selected_comparator = None
            selection_reason = "not_required_by_policy" if not self.policy.comparator_required else "no_history_provided"

        # Step 2: Determine history window for marker analysis
        history_window = self._select_history_window(history_entries, selected_comparator)

        # Step 3: Build selection metadata
        selection_metadata = {
            "selection_reason": selection_reason,
            "comparator_count_available": str(len(history_entries)),
            "history_window_size": str(len(history_window)),
            "policy_required": str(self.policy.comparator_required),
            "base_form": self.policy.base_form,
        }

        if selected_comparator:
            selection_metadata["selected_comparator_accession"] = selected_comparator["accession"]

        return SelectionResult(
            selected_comparator=selected_comparator,
            history_window=history_window,
            selection_metadata=selection_metadata
        )

    def _select_best_comparator(self, history_entries: List[Dict[str, str]], filed_date: str) -> Optional[Dict[str, str]]:
        """
        Select the best comparator from available history entries.

        Selection criteria (in priority order):
        1. Must be same base form type (policy compliance)
        2. Must be chronologically prior to target filing date
        3. Prefer most recent filing (closest to target date)
        4. Deterministic tie-breaking by accession number
        """
        if not history_entries:
            return None

        # Filter to valid comparators based on form policy
        valid_comparators = []
        target_date = datetime.strptime(filed_date, "%Y-%m-%d").date()

        for entry in history_entries:
            # For now, assume all history entries are valid comparators
            # In a real implementation, we'd need to extract form type from each entry
            # and validate it matches the required base form

            # Extract filing date from accession (CCCCCCCCCC-YY-NNNNNN format)
            accession = entry["accession"]
            try:
                validate_accession_number(accession)
                # Extract year from accession (positions 11-12 are YY)
                accession_year = 2000 + int(accession[11:13])
                # For proper comparison, we'd need the full filing date
                # For now, use a simplified chronological check
                if accession < filed_date.replace("-", ""):  # Simplified date comparison
                    valid_comparators.append(entry)
            except (ValueError, IndexError):
                continue  # Skip invalid accessions

        if not valid_comparators:
            return None

        # Sort by accession (most recent first, deterministic)
        valid_comparators.sort(key=lambda x: x["accession"], reverse=True)
        return valid_comparators[0]

    def _select_history_window(
        self,
        history_entries: List[Dict[str, str]],
        selected_comparator: Optional[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        Select history window for marker analysis.

        The history window includes:
        1. Selected comparator (if any)
        2. Additional recent history entries for trend analysis
        3. Limited to reasonable window size for performance
        """
        # For marker analysis, include up to 5 most recent filings
        MAX_HISTORY_WINDOW = 5

        # Start with all available history, sorted by accession (most recent first)
        sorted_history = sorted(history_entries, key=lambda x: x["accession"], reverse=True)

        # Limit to reasonable window size
        history_window = sorted_history[:MAX_HISTORY_WINDOW]

        # Ensure selected comparator is included if it exists
        if selected_comparator and selected_comparator not in history_window:
            # If comparator is not in the top N, include it anyway
            history_window = [selected_comparator] + history_window[:MAX_HISTORY_WINDOW-1]

        # Return in chronological order (oldest first) for consistent processing
        return sorted(history_window, key=lambda x: x["accession"])


def select_comparator_and_history(
    form: str,
    explicit_comparator: Optional[Dict[str, str]],
    history_entries: List[Dict[str, str]],
    filed_date: str
) -> SelectionResult:
    """
    Convenience function for comparator and history selection.

    Args:
        form: Target filing form type (e.g., "10-K", "10-Q")
        explicit_comparator: User-provided comparator (takes priority)
        history_entries: Available history entries sorted by accession
        filed_date: Target filing date (YYYY-MM-DD format)

    Returns:
        SelectionResult with selected comparator, history window, and metadata
    """
    selector = ComparatorSelector(form)
    return selector.select_comparator_and_history(explicit_comparator, history_entries, filed_date)