"""
Base classes for XEW Historical Adaptation Markers.

Markers analyze filing history windows to detect structural changes that
signal adaptation events or migration patterns for enhanced triage context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkerEvidence:
    """Evidence supporting a marker detection."""

    evidence_type: str  # e.g., "schema_ref_change", "extension_modification"
    description: str    # Human-readable description
    details: Dict[str, Any]  # Structured details (accessions, URIs, etc.)


@dataclass(frozen=True)
class MarkerResult:
    """Result of marker analysis."""

    marker_id: str  # e.g., "XEW-M001"
    detected: bool
    boundary: Dict[str, str]  # Current and reference accessions
    evidence: List[MarkerEvidence]
    threshold_config: Dict[str, Any]  # Thresholds used for detection
    analysis_metadata: Dict[str, Any]  # Analysis context and statistics


class BaseMarker(ABC):
    """Base class for all XEW markers."""

    @property
    @abstractmethod
    def marker_id(self) -> str:
        """Unique marker identifier (e.g., 'XEW-M001')."""
        pass

    @property
    @abstractmethod
    def marker_name(self) -> str:
        """Human-readable marker name."""
        pass

    @property
    @abstractmethod
    def default_thresholds(self) -> Dict[str, Any]:
        """Default threshold configuration for this marker."""
        pass

    @abstractmethod
    def analyze(
        self,
        current_filing: Dict[str, Any],
        history_window: List[Dict[str, Any]],
        thresholds: Optional[Dict[str, Any]] = None
    ) -> MarkerResult:
        """
        Analyze filing history for marker patterns.

        Args:
            current_filing: Current filing metadata and artifacts
            history_window: Historical filings for comparison (chronologically ordered)
            thresholds: Override default thresholds for detection

        Returns:
            MarkerResult with detection status and evidence
        """
        pass

    def validate_thresholds(self, thresholds: Dict[str, Any]) -> List[str]:
        """
        Validate threshold configuration.

        Args:
            thresholds: Threshold configuration to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check required threshold keys
        for required_key in self.default_thresholds.keys():
            if required_key not in thresholds:
                errors.append(f"Missing required threshold: {required_key}")

        return errors

    def _create_boundary(self, current_accession: str, reference_accession: Optional[str] = None) -> Dict[str, str]:
        """Create boundary object for marker result."""
        boundary = {"current": current_accession}
        if reference_accession:
            boundary["reference"] = reference_accession
        return boundary

    def _extract_filing_metadata(self, filing: Dict[str, Any]) -> Dict[str, Any]:
        """Extract standardized metadata from filing object."""
        return {
            "accession": filing.get("accession", ""),
            "form": filing.get("form", ""),
            "filed_date": filing.get("filed_date", ""),
            "period_end": filing.get("period_end"),
            "issuer_name": filing.get("issuer_name"),
            "cik": filing.get("cik", "")
        }

    def _merge_thresholds(self, custom_thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge custom thresholds with defaults."""
        merged = self.default_thresholds.copy()
        if custom_thresholds:
            merged.update(custom_thresholds)
        return merged