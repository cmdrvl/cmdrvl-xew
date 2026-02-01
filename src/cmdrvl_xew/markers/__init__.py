"""Adaptation markers for XEW findings."""

from .m001_taxonomy_refresh import TaxonomyRefreshMarker
from .m005_duplicate_cleanup import (
    DuplicateCleanupThresholds,
    DuplicateSignatureSnapshot,
    DEFAULT_THRESHOLDS,
    detect_duplicate_cleanup_marker,
)

__all__ = [
    # M001 - Taxonomy Refresh Detection
    "TaxonomyRefreshMarker",
    # M005 - Duplicate Cleanup Detection
    "DuplicateCleanupThresholds",
    "DuplicateSignatureSnapshot",
    "DEFAULT_THRESHOLDS",
    "detect_duplicate_cleanup_marker",
]
