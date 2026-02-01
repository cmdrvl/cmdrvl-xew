"""
XEW-M003: Anchoring Retrofit Marker.

Detects significant improvements in anchoring coverage across filings. This
marker is not an alert by itself; it provides triage context for remediation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Dict, Set

from ..util import validate_accession_number


@dataclass(frozen=True)
class AnchoringCoverageSnapshot:
    """Snapshot of extension anchoring coverage for a filing."""

    accession: str
    extension_qnames: Sequence[str]
    anchored_qnames: Sequence[str]


@dataclass(frozen=True)
class AnchoringRetrofitThresholds:
    """Thresholds for declaring an anchoring retrofit marker."""

    min_coverage_increase: float = 0.2
    min_anchored_increase_count: int = 10
    min_previous_extension_count: int = 25


DEFAULT_THRESHOLDS = AnchoringRetrofitThresholds()


def detect_anchoring_retrofit_marker(
    *,
    current_accession: str,
    current_extension_qnames: Iterable[str],
    current_anchored_qnames: Iterable[str],
    history_snapshots: Sequence[AnchoringCoverageSnapshot],
    thresholds: AnchoringRetrofitThresholds = DEFAULT_THRESHOLDS,
    max_examples: int = 10,
) -> Optional[Dict[str, object]]:
    """
    Detect an anchoring retrofit marker (XEW-M003).

    Args:
        current_accession: Accession of the current filing (NNNNNNNNNN-NN-NNNNNN)
        current_extension_qnames: Extension concept QNames in current filing
        current_anchored_qnames: Anchored extension concept QNames in current filing
        history_snapshots: Prior filing snapshots with anchoring coverage data
        thresholds: Thresholds for flagging retrofit events
        max_examples: Max number of newly anchored examples to include

    Returns:
        Marker dict compliant with xew_findings schema, or None if no marker.
    """
    current_norm = validate_accession_number(current_accession)
    previous_snapshot = _select_prior_snapshot(history_snapshots, current_norm)
    if previous_snapshot is None:
        return None

    previous_norm = validate_accession_number(previous_snapshot.accession)

    previous_extensions = _normalize_qnames(previous_snapshot.extension_qnames)
    previous_anchored = _normalize_qnames(previous_snapshot.anchored_qnames)
    current_extensions = _normalize_qnames(current_extension_qnames)
    current_anchored = _normalize_qnames(current_anchored_qnames)

    previous_total = len(previous_extensions)
    if previous_total < thresholds.min_previous_extension_count:
        return None

    prev_anchored_count = _coverage_count(previous_anchored, previous_extensions)
    curr_anchored_count = _coverage_count(current_anchored, current_extensions)

    prev_ratio = _coverage_ratio(prev_anchored_count, previous_total)
    curr_ratio = _coverage_ratio(curr_anchored_count, len(current_extensions))

    coverage_increase = curr_ratio - prev_ratio
    anchored_increase = curr_anchored_count - prev_anchored_count

    if (
        coverage_increase < thresholds.min_coverage_increase
        or anchored_increase < thresholds.min_anchored_increase_count
    ):
        return None

    newly_anchored = sorted(set(current_anchored) - set(previous_anchored))
    max_examples = max(0, max_examples)
    examples = newly_anchored[:max_examples] if max_examples else []

    evidence = {
        "previous_extension_count": previous_total,
        "current_extension_count": len(current_extensions),
        "previous_anchored_count": prev_anchored_count,
        "current_anchored_count": curr_anchored_count,
        "previous_anchoring_coverage": round(prev_ratio, 6),
        "current_anchoring_coverage": round(curr_ratio, 6),
        "coverage_increase": round(coverage_increase, 6),
        "anchored_increase": anchored_increase,
        "thresholds": {
            "min_coverage_increase": thresholds.min_coverage_increase,
            "min_anchored_increase_count": thresholds.min_anchored_increase_count,
            "min_previous_extension_count": thresholds.min_previous_extension_count,
        },
        "newly_anchored_count": len(newly_anchored),
        "newly_anchored_examples": examples,
    }

    return {
        "marker_id": "XEW-M003",
        "boundary": {
            "from_accession": previous_norm,
            "to_accession": current_norm,
        },
        "evidence": evidence,
    }


def _select_prior_snapshot(
    history_snapshots: Sequence[AnchoringCoverageSnapshot],
    current_accession: str,
) -> Optional[AnchoringCoverageSnapshot]:
    """Select the most recent snapshot prior to current accession."""
    candidates: List[AnchoringCoverageSnapshot] = []
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
    """Normalize and deduplicate QNames deterministically."""
    seen: Set[str] = set()
    normalized: List[str] = []
    for qname in qnames:
        value = str(qname)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    normalized.sort()
    return normalized


def _coverage_count(anchored: List[str], extensions: List[str]) -> int:
    """Count anchored extension concepts, scoped to known extensions."""
    if not extensions or not anchored:
        return 0
    extension_set = set(extensions)
    return len([qname for qname in anchored if qname in extension_set])


def _coverage_ratio(anchored_count: int, total_extensions: int) -> float:
    if total_extensions <= 0:
        return 0.0
    return anchored_count / total_extensions
