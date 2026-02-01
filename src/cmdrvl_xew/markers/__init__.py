"""Adaptation markers for XEW findings."""

from dataclasses import asdict
from typing import Dict

from .m001_taxonomy_refresh import (
    DEFAULT_THRESHOLDS as M001_DEFAULT_THRESHOLDS,
    TaxonomyRefreshThresholds,
    TaxonomySchemaSnapshot,
    detect_taxonomy_refresh_marker,
)
from .m002_extension_refactor import (
    DEFAULT_THRESHOLDS as M002_DEFAULT_THRESHOLDS,
    ExtensionRefactorThresholds,
    ExtensionSnapshot,
    detect_extension_refactor_marker,
)
from .m003_anchoring_retrofit import (
    DEFAULT_THRESHOLDS as M003_DEFAULT_THRESHOLDS,
    AnchoringCoverageSnapshot,
    AnchoringRetrofitThresholds,
    detect_anchoring_retrofit_marker,
)
from .m004_context_model_rewrite import (
    DEFAULT_THRESHOLDS as M004_DEFAULT_THRESHOLDS,
    ContextModelSnapshot,
    ContextModelRewriteThresholds,
    detect_context_model_rewrite_marker,
)
from .m005_duplicate_cleanup import (
    DEFAULT_THRESHOLDS as M005_DEFAULT_THRESHOLDS,
    DuplicateCleanupThresholds,
    DuplicateSignatureSnapshot,
    detect_duplicate_cleanup_marker,
    detect_duplicate_cleanup_from_findings,
)

# Backwards-compatible alias for prior export (M005 defaults).
DEFAULT_THRESHOLDS = M005_DEFAULT_THRESHOLDS


def marker_thresholds_config() -> Dict[str, Dict[str, object]]:
    """Return default marker thresholds for toolchain reproducibility."""
    return {
        "XEW-M001": asdict(M001_DEFAULT_THRESHOLDS),
        "XEW-M002": asdict(M002_DEFAULT_THRESHOLDS),
        "XEW-M003": asdict(M003_DEFAULT_THRESHOLDS),
        "XEW-M004": asdict(M004_DEFAULT_THRESHOLDS),
        "XEW-M005": asdict(M005_DEFAULT_THRESHOLDS),
    }

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
    # Shared config helpers
    "marker_thresholds_config",
]
