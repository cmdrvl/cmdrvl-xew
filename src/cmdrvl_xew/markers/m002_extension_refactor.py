"""
XEW-M002: Extension Refactor Marker.

Detects churn in extension concept QNames across filings. This marker is
not an alert by itself; it provides triage context for structural refactors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Dict

from ..util import validate_accession_number


@dataclass(frozen=True)
class ExtensionSnapshot:
    """Snapshot of extension concept QNames for a filing."""

    accession: str
    qnames: Sequence[str]


@dataclass(frozen=True)
class ExtensionRefactorThresholds:
    """Thresholds for declaring an extension refactor marker."""

    min_churn_ratio: float = 0.25
    min_new_count: int = 5
    min_retired_count: int = 5
    min_previous_count: int = 10


DEFAULT_THRESHOLDS = ExtensionRefactorThresholds()


def detect_extension_refactor_marker(
    *,
    current_accession: str,
    current_extension_qnames: Iterable[str],
    history_snapshots: Sequence[ExtensionSnapshot],
    thresholds: ExtensionRefactorThresholds = DEFAULT_THRESHOLDS,
    max_examples: int = 10,
) -> Optional[Dict[str, object]]:
    """
    Detect an extension refactor marker (XEW-M002).

    Args:
        current_accession: Accession of the current filing (NNNNNNNNNN-NN-NNNNNN)
        current_extension_qnames: Extension concept QNames for the current filing
        history_snapshots: Prior filing snapshots with extension QNames
        thresholds: Thresholds for flagging refactor events
        max_examples: Max number of new/retired QName examples to include

    Returns:
        Marker dict compliant with xew_findings schema, or None if no marker.
    """
    current_norm = validate_accession_number(current_accession)
    previous_snapshot = _select_prior_snapshot(history_snapshots, current_norm)
    if previous_snapshot is None:
        return None

    previous_norm = validate_accession_number(previous_snapshot.accession)
    previous_qnames = _normalize_qnames(previous_snapshot.qnames)
    current_qnames = _normalize_qnames(current_extension_qnames)

    prev_count = len(previous_qnames)
    curr_count = len(current_qnames)

    if prev_count < thresholds.min_previous_count:
        return None

    new_qnames = sorted(set(current_qnames) - set(previous_qnames))
    retired_qnames = sorted(set(previous_qnames) - set(current_qnames))

    new_count = len(new_qnames)
    retired_count = len(retired_qnames)
    churn_count = new_count + retired_count

    if churn_count == 0:
        return None

    churn_ratio = churn_count / prev_count if prev_count else 0.0

    if (
        churn_ratio < thresholds.min_churn_ratio
        or new_count < thresholds.min_new_count
        or retired_count < thresholds.min_retired_count
    ):
        return None

    max_examples = max(0, max_examples)
    new_examples = new_qnames[:max_examples] if max_examples else []
    retired_examples = retired_qnames[:max_examples] if max_examples else []

    evidence = {
        "previous_extension_count": prev_count,
        "current_extension_count": curr_count,
        "new_extension_count": new_count,
        "retired_extension_count": retired_count,
        "churn_count": churn_count,
        "churn_ratio": round(churn_ratio, 6),
        "thresholds": {
            "min_churn_ratio": thresholds.min_churn_ratio,
            "min_new_count": thresholds.min_new_count,
            "min_retired_count": thresholds.min_retired_count,
            "min_previous_count": thresholds.min_previous_count,
        },
        "new_extension_examples": new_examples,
        "retired_extension_examples": retired_examples,
    }

    return {
        "marker_id": "XEW-M002",
        "boundary": {
            "from_accession": previous_norm,
            "to_accession": current_norm,
        },
        "evidence": evidence,
    }


def _select_prior_snapshot(
    history_snapshots: Sequence[ExtensionSnapshot],
    current_accession: str,
) -> Optional[ExtensionSnapshot]:
    """Select the most recent snapshot prior to current accession."""
    candidates: List[ExtensionSnapshot] = []
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


def _normalize_qnames(qnames: Iterable[str]) -> List[str]:
    """Normalize and deduplicate extension QNames deterministically."""
    seen = set()
    normalized: List[str] = []
    for qname in qnames:
        value = str(qname)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    normalized.sort()
    return normalized
