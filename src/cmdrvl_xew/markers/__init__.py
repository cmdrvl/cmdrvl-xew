"""Adaptation markers for XEW findings."""

from .m001_taxonomy_refresh import (
    TaxonomyRefreshThresholds,
    TaxonomySchemaSnapshot,
    detect_taxonomy_refresh_marker,
)
from .m002_extension_refactor import (
    ExtensionRefactorThresholds,
    ExtensionSnapshot,
    detect_extension_refactor_marker,
)
from .m003_anchoring_retrofit import (
    AnchoringCoverageSnapshot,
    AnchoringRetrofitThresholds,
    detect_anchoring_retrofit_marker,
)
from .m004_context_model_rewrite import (
    ContextModelSnapshot,
    ContextModelRewriteThresholds,
    detect_context_model_rewrite_marker,
)
from .m005_duplicate_cleanup import (
    DuplicateCleanupThresholds,
    DuplicateSignatureSnapshot,
    DEFAULT_THRESHOLDS,
    detect_duplicate_cleanup_marker,
    detect_duplicate_cleanup_from_findings,
)

__all__ = [
    # M001 - Taxonomy Refresh Detection
    "TaxonomyRefreshThresholds",
    "TaxonomySchemaSnapshot",
    "detect_taxonomy_refresh_marker",
    # M002 - Extension Refactor Detection
    "ExtensionRefactorThresholds",
    "ExtensionSnapshot",
    "detect_extension_refactor_marker",
    # M003 - Anchoring Retrofit Detection
    "AnchoringCoverageSnapshot",
    "AnchoringRetrofitThresholds",
    "detect_anchoring_retrofit_marker",
    # M004 - Context Model Rewrite Detection
    "ContextModelSnapshot",
    "ContextModelRewriteThresholds",
    "detect_context_model_rewrite_marker",
    # M005 - Duplicate Cleanup Detection
    "DuplicateCleanupThresholds",
    "DuplicateSignatureSnapshot",
    "DEFAULT_THRESHOLDS",
    "detect_duplicate_cleanup_marker",
    "detect_duplicate_cleanup_from_findings",
]
