"""
Comparator and history window selection for adaptation markers.

This module implements deterministic selection logic for choosing the best
available comparator and history window from provided history entries.
The selection follows form-specific policies and ensures reproducible results.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from .comparator import comparator_policy, select_prior_accession
from .util import validate_accession_number

_DEFAULT_HISTORY_WINDOW = 5


def _entry_identity(entry: Dict[str, str]) -> Tuple[str, str, str]:
    return (
        entry.get("accession", ""),
        entry.get("primary_document_url", ""),
        entry.get("primary_artifact_path", ""),
    )


def _entry_sort_key(entry: Dict[str, str]) -> Tuple[str, str, str]:
    return _entry_identity(entry)


def _filter_history_entries(
    history_entries: Iterable[Dict[str, str]],
    current_accession: str,
) -> List[Dict[str, str]]:
    current_norm = validate_accession_number(current_accession)
    filtered: List[Dict[str, str]] = []
    for entry in history_entries:
        accession = entry.get("accession", "")
        try:
            normalized = validate_accession_number(accession)
        except ValueError:
            continue
        if normalized < current_norm:
            filtered.append(entry)
    return filtered


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
        current_accession: str,
    ) -> SelectionResult:
        """
        Select the best comparator and history window for marker detection.

        Args:
            explicit_comparator: User-provided comparator (takes priority)
            history_entries: Available history entries sorted by accession
            current_accession: Target filing accession (NNNNNNNNNN-NN-NNNNNN)

        Returns:
            SelectionResult with selected comparator, history window, and metadata
        """

        # Step 1: Determine selected comparator
        if explicit_comparator:
            selected_comparator = explicit_comparator
            selection_reason = "explicit_user_provided"
        elif self.policy.comparator_required and history_entries:
            selected_comparator = self._select_best_comparator(history_entries, current_accession)
            selection_reason = "auto_selected_from_history" if selected_comparator else "no_suitable_comparator"
        else:
            selected_comparator = None
            selection_reason = "not_required_by_policy" if not self.policy.comparator_required else "no_history_provided"

        # Step 2: Determine history window for marker analysis
        history_window = self._select_history_window(history_entries, current_accession, selected_comparator)

        # Step 3: Build selection metadata
        valid_history_count = len(_filter_history_entries(history_entries, current_accession))
        selection_metadata = {
            "selection_reason": selection_reason,
            "comparator_count_available": str(valid_history_count),
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

    def _select_best_comparator(
        self,
        history_entries: List[Dict[str, str]],
        current_accession: str,
    ) -> Optional[Dict[str, str]]:
        """
        Select the best comparator from available history entries.

        Selection criteria (in priority order):
        1. Must be same base form type (policy compliance)
        2. Must be chronologically prior to target filing accession
        3. Prefer most recent filing (closest to target date)
        4. Deterministic tie-breaking by accession number
        """
        if not history_entries:
            return None

        candidate_accession = select_prior_accession(
            current_accession,
            (entry.get("accession", "") for entry in history_entries),
        )
        if not candidate_accession:
            return None

        valid_entries: List[Dict[str, str]] = []
        for entry in history_entries:
            accession = entry.get("accession", "")
            try:
                normalized = validate_accession_number(accession)
            except ValueError:
                continue
            if normalized == candidate_accession:
                valid_entries.append(entry)

        if not valid_entries:
            return None

        valid_entries.sort(key=_entry_sort_key)
        return valid_entries[0]

    def _select_history_window(
        self,
        history_entries: List[Dict[str, str]],
        current_accession: str,
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
        filtered_history = _filter_history_entries(history_entries, current_accession)

        # Start with most recent history entries, deterministically ordered
        sorted_history = sorted(filtered_history, key=_entry_sort_key, reverse=True)
        history_window = sorted_history[:_DEFAULT_HISTORY_WINDOW]

        # Ensure selected comparator is included if it exists
        if selected_comparator:
            comparator_id = _entry_identity(selected_comparator)
            existing_ids = {_entry_identity(entry) for entry in history_window}
            if comparator_id not in existing_ids:
                history_window = history_window + [selected_comparator]

        # Return in chronological order (oldest first) for consistent processing
        return sorted(history_window, key=_entry_sort_key)


def select_comparator_and_history(
    form: str,
    explicit_comparator: Optional[Dict[str, str]],
    history_entries: List[Dict[str, str]],
    current_accession: str,
) -> SelectionResult:
    """
    Convenience function for comparator and history selection.

    Args:
        form: Target filing form type (e.g., "10-K", "10-Q")
        explicit_comparator: User-provided comparator (takes priority)
        history_entries: Available history entries sorted by accession
        current_accession: Target filing accession (NNNNNNNNNN-NN-NNNNNN)

    Returns:
        SelectionResult with selected comparator, history window, and metadata
    """
    selector = ComparatorSelector(form)
    return selector.select_comparator_and_history(explicit_comparator, history_entries, current_accession)
