"""
XEW-M004: Context Model Rewrite Marker.

Detects significant changes in context counts and dimension-member set
signatures across filings. This marker is not an alert by itself; it provides
triage context for structural shifts in reporting contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Dict

from ..util import validate_accession_number


@dataclass(frozen=True)
class ContextModelSnapshot:
    """Snapshot of context model characteristics for a filing."""

    accession: str
    context_count: int
    dimension_member_signatures: Sequence[str]


@dataclass(frozen=True)
class ContextModelRewriteThresholds:
    """Thresholds for declaring a context model rewrite marker."""

    min_context_count_change_ratio: float = 0.4
    min_context_count_change: int = 25
    min_previous_context_count: int = 50
    min_dim_member_churn_ratio: float = 0.4
    min_dim_member_churn_count: int = 10
    min_previous_dim_member_count: int = 25


DEFAULT_THRESHOLDS = ContextModelRewriteThresholds()


def detect_context_model_rewrite_marker(
    *,
    current_accession: str,
    current_context_count: int,
    current_dimension_member_signatures: Iterable[str],
    history_snapshots: Sequence[ContextModelSnapshot],
    thresholds: ContextModelRewriteThresholds = DEFAULT_THRESHOLDS,
    max_examples: int = 10,
) -> Optional[Dict[str, object]]:
    """
    Detect a context model rewrite marker (XEW-M004).

    Args:
        current_accession: Accession of the current filing (NNNNNNNNNN-NN-NNNNNN)
        current_context_count: Number of contexts in current filing
        current_dimension_member_signatures: Dimension-member set signatures
        history_snapshots: Prior filing snapshots with context model data
        thresholds: Thresholds for flagging rewrite events
        max_examples: Max number of examples to include for new/retired sets

    Returns:
        Marker dict compliant with xew_findings schema, or None if no marker.
    """
    current_norm = validate_accession_number(current_accession)
    previous_snapshot = _select_prior_snapshot(history_snapshots, current_norm)
    if previous_snapshot is None:
        return None

    previous_norm = validate_accession_number(previous_snapshot.accession)
    prev_context_count = _normalize_count(previous_snapshot.context_count)
    curr_context_count = _normalize_count(current_context_count)

    prev_dim_sets = _normalize_signatures(previous_snapshot.dimension_member_signatures)
    curr_dim_sets = _normalize_signatures(current_dimension_member_signatures)

    prev_dim_count = len(prev_dim_sets)
    curr_dim_count = len(curr_dim_sets)

    has_context_baseline = prev_context_count >= thresholds.min_previous_context_count
    has_dim_baseline = prev_dim_count >= thresholds.min_previous_dim_member_count

    if not has_context_baseline and not has_dim_baseline:
        return None

    context_change = abs(curr_context_count - prev_context_count)
    context_change_ratio = context_change / prev_context_count if prev_context_count else 0.0

    new_sets = sorted(set(curr_dim_sets) - set(prev_dim_sets))
    retired_sets = sorted(set(prev_dim_sets) - set(curr_dim_sets))
    dim_churn_count = len(new_sets) + len(retired_sets)
    dim_churn_ratio = dim_churn_count / prev_dim_count if prev_dim_count else 0.0

    context_trigger = (
        has_context_baseline
        and context_change >= thresholds.min_context_count_change
        and context_change_ratio >= thresholds.min_context_count_change_ratio
    )
    dim_trigger = (
        has_dim_baseline
        and dim_churn_count >= thresholds.min_dim_member_churn_count
        and dim_churn_ratio >= thresholds.min_dim_member_churn_ratio
    )

    if not (context_trigger or dim_trigger):
        return None

    max_examples = max(0, max_examples)
    new_examples = new_sets[:max_examples] if max_examples else []
    retired_examples = retired_sets[:max_examples] if max_examples else []

    evidence = {
        "previous_context_count": prev_context_count,
        "current_context_count": curr_context_count,
        "context_count_change": context_change,
        "context_count_change_ratio": round(context_change_ratio, 6),
        "previous_dimension_member_set_count": prev_dim_count,
        "current_dimension_member_set_count": curr_dim_count,
        "dimension_member_churn_count": dim_churn_count,
        "dimension_member_churn_ratio": round(dim_churn_ratio, 6),
        "new_dimension_member_set_count": len(new_sets),
        "retired_dimension_member_set_count": len(retired_sets),
        "new_dimension_member_set_examples": new_examples,
        "retired_dimension_member_set_examples": retired_examples,
        "context_change_triggered": context_trigger,
        "dimension_member_change_triggered": dim_trigger,
        "thresholds": {
            "min_context_count_change_ratio": thresholds.min_context_count_change_ratio,
            "min_context_count_change": thresholds.min_context_count_change,
            "min_previous_context_count": thresholds.min_previous_context_count,
            "min_dim_member_churn_ratio": thresholds.min_dim_member_churn_ratio,
            "min_dim_member_churn_count": thresholds.min_dim_member_churn_count,
            "min_previous_dim_member_count": thresholds.min_previous_dim_member_count,
        },
    }

    return {
        "marker_id": "XEW-M004",
        "boundary": {
            "from_accession": previous_norm,
            "to_accession": current_norm,
        },
        "evidence": evidence,
    }


def _select_prior_snapshot(
    history_snapshots: Sequence[ContextModelSnapshot],
    current_accession: str,
) -> Optional[ContextModelSnapshot]:
    """Select the most recent snapshot prior to current accession."""
    candidates: List[ContextModelSnapshot] = []
    for snapshot in history_snapshots:
        try:
            accession_norm = validate_accession_number(snapshot.accession)
        except ValueError:
            continue
        if accession_norm < current_accession:
            candidates.append(snapshot)

    if not candidates:
        return None

    candidates.sort(key=lambda s: validate_accession_number(s.accession))
    return candidates[-1]


def _normalize_signatures(signatures: Iterable[str]) -> List[str]:
    """Normalize and deduplicate signatures deterministically."""
    seen = set()
    normalized: List[str] = []
    for signature in signatures:
        value = str(signature)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    normalized.sort()
    return normalized


def _normalize_count(value: int) -> int:
    """Normalize context count to a non-negative integer."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, count)
