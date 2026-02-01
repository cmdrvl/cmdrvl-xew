"""
XEW-M005: Duplicate Cleanup Marker.

Detects sharp drops in duplicate fact signatures across filings. This marker is
not an alert by itself; it provides triage context for structural cleanups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Dict, Any

from ..util import validate_accession_number


@dataclass(frozen=True)
class DuplicateSignatureSnapshot:
    """Snapshot of duplicate signature IDs for a filing."""

    accession: str
    signature_ids: Sequence[str]


@dataclass(frozen=True)
class DuplicateCleanupThresholds:
    """Thresholds for declaring a duplicate cleanup marker."""

    min_drop_ratio: float = 0.5
    min_drop_count: int = 10
    min_previous_count: int = 20


DEFAULT_THRESHOLDS = DuplicateCleanupThresholds()


def detect_duplicate_cleanup_marker(
    *,
    current_accession: str,
    current_signature_ids: Iterable[str],
    history_snapshots: Sequence[DuplicateSignatureSnapshot],
    thresholds: DuplicateCleanupThresholds = DEFAULT_THRESHOLDS,
    max_examples: int = 10,
) -> Optional[Dict[str, object]]:
    """
    Detect a duplicate cleanup marker (XEW-M005).

    Args:
        current_accession: Accession of the current filing (NNNNNNNNNN-NN-NNNNNN)
        current_signature_ids: Duplicate signature IDs for the current filing
        history_snapshots: Prior filing snapshots with duplicate signature IDs
        thresholds: Thresholds for flagging cleanup events
        max_examples: Max number of removed signature examples to include

    Returns:
        Marker dict compliant with xew_findings schema, or None if no marker.
    """
    current_norm = validate_accession_number(current_accession)
    previous_snapshot = _select_prior_snapshot(history_snapshots, current_norm)
    if previous_snapshot is None:
        return None

    previous_norm = validate_accession_number(previous_snapshot.accession)
    previous_ids = _normalize_signature_ids(previous_snapshot.signature_ids)
    current_ids = _normalize_signature_ids(current_signature_ids)

    prev_count = len(previous_ids)
    curr_count = len(current_ids)

    if prev_count < thresholds.min_previous_count:
        return None

    drop_count = prev_count - curr_count
    if drop_count <= 0:
        return None

    drop_ratio = drop_count / prev_count

    if drop_count < thresholds.min_drop_count or drop_ratio < thresholds.min_drop_ratio:
        return None

    removed = sorted(set(previous_ids) - set(current_ids))
    examples = removed[: max(0, max_examples)] if max_examples else []

    evidence = {
        "previous_duplicate_signature_count": prev_count,
        "current_duplicate_signature_count": curr_count,
        "drop_count": drop_count,
        "drop_ratio": round(drop_ratio, 6),
        "thresholds": {
            "min_drop_ratio": thresholds.min_drop_ratio,
            "min_drop_count": thresholds.min_drop_count,
            "min_previous_count": thresholds.min_previous_count,
        },
        "removed_signature_count": len(removed),
        "removed_signature_examples": examples,
    }

    return {
        "marker_id": "XEW-M005",
        "boundary": {
            "from_accession": previous_norm,
            "to_accession": current_norm,
        },
        "evidence": evidence,
    }


def detect_duplicate_cleanup_from_findings(
    *,
    current_accession: str,
    findings: Iterable[Any],
    history_snapshots: Sequence[DuplicateSignatureSnapshot],
    thresholds: DuplicateCleanupThresholds = DEFAULT_THRESHOLDS,
    max_examples: int = 10,
) -> Optional[Dict[str, object]]:
    """
    Detect M005 using detector findings (extracting P001 instance IDs).

    Args:
        current_accession: Accession of the current filing (NNNNNNNNNN-NN-NNNNNN)
        findings: Iterable of DetectorFinding-like objects or dicts
        history_snapshots: Prior filing snapshots with duplicate signature IDs
        thresholds: Thresholds for flagging cleanup events
        max_examples: Max number of removed signature examples to include

    Returns:
        Marker dict compliant with xew_findings schema, or None if no marker.
    """
    signature_ids = _extract_duplicate_signatures(findings)
    return detect_duplicate_cleanup_marker(
        current_accession=current_accession,
        current_signature_ids=signature_ids,
        history_snapshots=history_snapshots,
        thresholds=thresholds,
        max_examples=max_examples,
    )


def _select_prior_snapshot(
    history_snapshots: Sequence[DuplicateSignatureSnapshot],
    current_accession: str,
) -> Optional[DuplicateSignatureSnapshot]:
    """Select the most recent snapshot prior to current accession."""
    candidates: List[DuplicateSignatureSnapshot] = []
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


def _normalize_signature_ids(signature_ids: Iterable[str]) -> List[str]:
    """Normalize and deduplicate signature IDs deterministically."""
    seen = set()
    normalized: List[str] = []
    for sig in signature_ids:
        value = str(sig)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    normalized.sort()
    return normalized


def _extract_duplicate_signatures(findings: Iterable[Any]) -> List[str]:
    """Extract P001 instance IDs from detector findings."""
    signature_ids: List[str] = []
    for finding in findings:
        pattern_id = None
        instances = None
        if isinstance(finding, dict):
            pattern_id = finding.get("pattern_id")
            instances = finding.get("instances")
        else:
            pattern_id = getattr(finding, "pattern_id", None)
            instances = getattr(finding, "instances", None)

        if pattern_id != "XEW-P001" or not instances:
            continue

        for instance in instances:
            if isinstance(instance, dict):
                instance_id = instance.get("instance_id")
            else:
                instance_id = getattr(instance, "instance_id", None)
            if instance_id:
                signature_ids.append(str(instance_id))

    return signature_ids
