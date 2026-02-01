"""
XEW-M001: Taxonomy Refresh Marker.

Detects schemaRef/taxonomy reference changes across filings. This marker is
not an alert by itself; it provides triage context for structural migrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Dict

from ..util import validate_accession_number, sort_schema_refs_deterministically


@dataclass(frozen=True)
class TaxonomySchemaSnapshot:
    """Snapshot of schemaRef hrefs for a filing."""

    accession: str
    schema_refs: Sequence[str]


@dataclass(frozen=True)
class TaxonomyRefreshThresholds:
    """Thresholds for declaring a taxonomy refresh marker."""

    min_change_count: int = 1
    min_change_ratio: float = 0.2
    min_previous_count: int = 1


DEFAULT_THRESHOLDS = TaxonomyRefreshThresholds()


def detect_taxonomy_refresh_marker(
    *,
    current_accession: str,
    current_schema_refs: Iterable[str],
    history_snapshots: Sequence[TaxonomySchemaSnapshot],
    thresholds: TaxonomyRefreshThresholds = DEFAULT_THRESHOLDS,
) -> Optional[Dict[str, object]]:
    """
    Detect a taxonomy refresh marker (XEW-M001).

    Args:
        current_accession: Accession of the current filing (NNNNNNNNNN-NN-NNNNNN)
        current_schema_refs: SchemaRef hrefs for the current filing
        history_snapshots: Prior filing snapshots with schemaRef hrefs
        thresholds: Thresholds for flagging taxonomy refresh events

    Returns:
        Marker dict compliant with xew_findings schema, or None if no marker.
    """
    current_norm = validate_accession_number(current_accession)
    previous_snapshot = _select_prior_snapshot(history_snapshots, current_norm)
    if previous_snapshot is None:
        return None

    previous_norm = validate_accession_number(previous_snapshot.accession)
    previous_refs = _normalize_schema_refs(previous_snapshot.schema_refs)
    current_refs = _normalize_schema_refs(current_schema_refs)

    prev_count = len(previous_refs)
    curr_count = len(current_refs)

    if prev_count < thresholds.min_previous_count:
        return None

    added_refs = sorted(set(current_refs) - set(previous_refs))
    removed_refs = sorted(set(previous_refs) - set(current_refs))
    change_count = len(added_refs) + len(removed_refs)

    if change_count == 0:
        return None

    change_ratio = change_count / prev_count if prev_count else 0.0

    if change_count < thresholds.min_change_count or change_ratio < thresholds.min_change_ratio:
        return None

    evidence = {
        "previous_schema_ref_count": prev_count,
        "current_schema_ref_count": curr_count,
        "schema_ref_change_count": change_count,
        "schema_ref_change_ratio": round(change_ratio, 6),
        "previous_schema_refs": previous_refs,
        "current_schema_refs": current_refs,
        "added_schema_refs": added_refs,
        "removed_schema_refs": removed_refs,
        "thresholds": {
            "min_change_count": thresholds.min_change_count,
            "min_change_ratio": thresholds.min_change_ratio,
            "min_previous_count": thresholds.min_previous_count,
        },
    }

    return {
        "marker_id": "XEW-M001",
        "boundary": {
            "from_accession": previous_norm,
            "to_accession": current_norm,
        },
        "evidence": evidence,
    }


def _select_prior_snapshot(
    history_snapshots: Sequence[TaxonomySchemaSnapshot],
    current_accession: str,
) -> Optional[TaxonomySchemaSnapshot]:
    """Select the most recent snapshot prior to current accession."""
    candidates: List[TaxonomySchemaSnapshot] = []
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


def _normalize_schema_refs(schema_refs: Iterable[str]) -> List[str]:
    """Normalize and deduplicate schemaRef hrefs deterministically."""
    normalized: List[str] = []
    seen = set()
    for ref in schema_refs:
        value = str(ref).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return sort_schema_refs_deterministically(normalized)
