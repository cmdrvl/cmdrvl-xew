"""
History window and comparator selection logic for Evidence Pack generation.

This module provides deterministic selection of prior comparable filings and
history windows for marker detection when comparators are not explicitly provided.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from .comparator import comparator_policy, validate_comparator_compatibility

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilingReference:
    """Reference to a filing for comparator/history selection."""

    cik: str
    accession: str
    form: str
    filed_date: str  # ISO format YYYY-MM-DD
    period_end: Optional[str] = None  # ISO format YYYY-MM-DD
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None


@dataclass(frozen=True)
class SelectionResult:
    """Result of history window and comparator selection."""

    comparator: Optional[FilingReference]
    history_window: List[FilingReference]
    selection_rationale: str
    policy_compliance: bool


@dataclass(frozen=True)
class SelectionCriteria:
    """Criteria for selecting comparators and history window."""

    target_cik: str
    target_form: str
    target_filed_date: str
    target_period_end: Optional[str] = None
    max_history_count: int = 5
    max_lookback_years: int = 3


def select_comparator_and_history(
    criteria: SelectionCriteria,
    available_filings: List[FilingReference],
) -> SelectionResult:
    """
    Select comparator and history window based on form policy and available filings.

    Args:
        criteria: Selection criteria for the target filing
        available_filings: Available historical filings to choose from

    Returns:
        SelectionResult with selected comparator, history window, and rationale
    """
    try:
        policy = comparator_policy(criteria.target_form)
    except ValueError as e:
        return SelectionResult(
            comparator=None,
            history_window=[],
            selection_rationale=f"Unsupported form type for selection: {e}",
            policy_compliance=False
        )

    # Filter available filings to same entity and compatible forms
    compatible_filings = _filter_compatible_filings(criteria, available_filings)

    if not compatible_filings:
        if policy.comparator_required:
            rationale = f"No suitable comparator found for required {criteria.target_form} (no compatible filings available)"
        else:
            rationale = f"No comparator required for {criteria.target_form} (event-driven filing); no historical filings available"

        return SelectionResult(
            comparator=None,
            history_window=[],
            selection_rationale=rationale,
            policy_compliance=not policy.comparator_required
        )

    # Select comparator based on form-specific logic
    comparator = _select_comparator(criteria, compatible_filings, policy)

    # Select history window (broader set for marker analysis)
    history_window = _select_history_window(criteria, compatible_filings, comparator)

    # Generate rationale
    rationale = _generate_selection_rationale(criteria, comparator, history_window, policy)

    # Check policy compliance
    policy_compliant = not policy.comparator_required or comparator is not None

    return SelectionResult(
        comparator=comparator,
        history_window=history_window,
        selection_rationale=rationale,
        policy_compliance=policy_compliant
    )


def _filter_compatible_filings(
    criteria: SelectionCriteria,
    available_filings: List[FilingReference]
) -> List[FilingReference]:
    """Filter filings to same CIK and compatible form types."""
    compatible = []
    target_date = datetime.fromisoformat(criteria.target_filed_date).date()
    # Cutoff date is max_lookback_years before the target date
    cutoff_year = target_date.year - criteria.max_lookback_years
    cutoff_date = date(cutoff_year, target_date.month, target_date.day)

    for filing in available_filings:
        # Must be same entity
        if filing.cik != criteria.target_cik:
            continue

        # Must be filed before target filing
        filing_date = datetime.fromisoformat(filing.filed_date).date()
        if filing_date >= target_date:
            continue

        # Must be within lookback window
        if filing_date < cutoff_date:
            continue

        # Must be compatible form type
        try:
            if validate_comparator_compatibility(criteria.target_form, filing.form):
                compatible.append(filing)
        except ValueError:
            # Skip unsupported form types
            continue

    # Sort by filed date (newest first)
    compatible.sort(key=lambda f: f.filed_date, reverse=True)
    return compatible


def _select_comparator(
    criteria: SelectionCriteria,
    compatible_filings: List[FilingReference],
    policy: Any
) -> Optional[FilingReference]:
    """Select the most appropriate comparator filing."""
    if not compatible_filings:
        return None

    # For periodic filings (10-Q, 10-K, 20-F), select most recent compatible filing
    if policy.comparator_required:
        # Prefer filings with period end information for better temporal matching
        period_filings = [f for f in compatible_filings if f.period_end]

        if period_filings and criteria.target_period_end:
            # Try to find same period from previous year for 10-Q
            if criteria.target_form.startswith("10-Q"):
                comparator = _find_same_quarter_prior_year(criteria, period_filings)
                if comparator:
                    return comparator

            # Try to find previous period of same type
            comparator = _find_previous_period(criteria, period_filings)
            if comparator:
                return comparator

        # Fall back to most recent compatible filing
        return compatible_filings[0] if compatible_filings else None

    # For event-driven filings (8-K, 6-K), no default comparator
    return None


def _select_history_window(
    criteria: SelectionCriteria,
    compatible_filings: List[FilingReference],
    selected_comparator: Optional[FilingReference]
) -> List[FilingReference]:
    """Select history window for marker analysis."""
    # Include comparator in history if selected
    history = []
    if selected_comparator:
        history.append(selected_comparator)

    # Add additional historical filings up to max count
    for filing in compatible_filings:
        if filing == selected_comparator:
            continue  # Already included

        if len(history) >= criteria.max_history_count:
            break

        history.append(filing)

    # Sort by filed date (oldest first for chronological analysis)
    history.sort(key=lambda f: f.filed_date)
    return history


def _find_same_quarter_prior_year(
    criteria: SelectionCriteria,
    period_filings: List[FilingReference]
) -> Optional[FilingReference]:
    """Find same quarter from previous year for 10-Q filings."""
    if not criteria.target_period_end:
        return None

    try:
        target_period = datetime.fromisoformat(criteria.target_period_end).date()
        target_quarter = (target_period.month - 1) // 3 + 1

        # Look for same quarter in previous year(s)
        for filing in period_filings:
            if not filing.period_end:
                continue

            filing_period = datetime.fromisoformat(filing.period_end).date()
            filing_quarter = (filing_period.month - 1) // 3 + 1

            # Same quarter, different year
            if filing_quarter == target_quarter and filing_period.year < target_period.year:
                return filing

    except (ValueError, AttributeError):
        pass

    return None


def _find_previous_period(
    criteria: SelectionCriteria,
    period_filings: List[FilingReference]
) -> Optional[FilingReference]:
    """Find the most recent previous period filing."""
    if not criteria.target_period_end:
        return period_filings[0] if period_filings else None

    try:
        target_period = datetime.fromisoformat(criteria.target_period_end).date()

        # Find most recent filing with earlier period end
        for filing in period_filings:
            if not filing.period_end:
                continue

            filing_period = datetime.fromisoformat(filing.period_end).date()
            if filing_period < target_period:
                return filing

    except (ValueError, AttributeError):
        pass

    return period_filings[0] if period_filings else None


def _generate_selection_rationale(
    criteria: SelectionCriteria,
    comparator: Optional[FilingReference],
    history_window: List[FilingReference],
    policy: Any
) -> str:
    """Generate human-readable rationale for selection decisions."""
    parts = []

    # Comparator selection rationale
    if comparator:
        parts.append(f"Selected comparator: {comparator.form} filed {comparator.filed_date}")
        if comparator.period_end:
            parts.append(f" (period end: {comparator.period_end})")
    elif policy.comparator_required:
        parts.append(f"No suitable comparator found for required {criteria.target_form}")
    else:
        parts.append(f"No comparator required for {criteria.target_form} (event-driven filing)")

    # History window rationale
    if history_window:
        parts.append(f"History window: {len(history_window)} filings from {history_window[0].filed_date} to {history_window[-1].filed_date}")
    else:
        parts.append("No historical filings available for marker analysis")

    return "; ".join(parts)


def create_selection_criteria_from_pack_args(args: Any) -> SelectionCriteria:
    """Create SelectionCriteria from pack command arguments."""
    return SelectionCriteria(
        target_cik=args.cik,
        target_form=args.form,
        target_filed_date=args.filed_date,
        target_period_end=getattr(args, "period_end", None),
        max_history_count=getattr(args, "max_history_count", 5),
        max_lookback_years=getattr(args, "max_lookback_years", 3)
    )


def filing_reference_from_dict(data: Dict[str, Any]) -> FilingReference:
    """Create FilingReference from dictionary data."""
    return FilingReference(
        cik=data["cik"],
        accession=data["accession"],
        form=data["form"],
        filed_date=data["filed_date"],
        period_end=data.get("period_end"),
        fiscal_year=data.get("fiscal_year"),
        fiscal_period=data.get("fiscal_period")
    )


def filing_reference_to_dict(ref: FilingReference) -> Dict[str, Any]:
    """Convert FilingReference to dictionary for serialization."""
    return {
        "cik": ref.cik,
        "accession": ref.accession,
        "form": ref.form,
        "filed_date": ref.filed_date,
        "period_end": ref.period_end,
        "fiscal_year": ref.fiscal_year,
        "fiscal_period": ref.fiscal_period
    }