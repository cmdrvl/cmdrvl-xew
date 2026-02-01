"""
XEW-M001: Taxonomy Refresh Marker

Detects significant taxonomy/schema reference changes across filing history
that indicate structural migrations, extension refreshes, or standard updates.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from urllib.parse import urlparse

from .base import BaseMarker, MarkerResult, MarkerEvidence

logger = logging.getLogger(__name__)


class TaxonomyRefreshMarker(BaseMarker):
    """Detects taxonomy refresh events across filing history."""

    @property
    def marker_id(self) -> str:
        return "XEW-M001"

    @property
    def marker_name(self) -> str:
        return "Taxonomy Refresh Detection"

    @property
    def default_thresholds(self) -> Dict[str, Any]:
        """Default thresholds for taxonomy refresh detection."""
        return {
            "min_schema_ref_changes": 1,        # Minimum schemaRef changes to trigger
            "significant_namespace_change": True,  # Flag major namespace changes
            "extension_schema_weight": 2.0,     # Weight for extension schema changes
            "standard_taxonomy_weight": 1.0,    # Weight for standard taxonomy changes
            "major_change_threshold": 3.0       # Combined score threshold for major changes
        }

    def analyze(
        self,
        current_filing: Dict[str, Any],
        history_window: List[Dict[str, Any]],
        thresholds: Optional[Dict[str, Any]] = None
    ) -> MarkerResult:
        """
        Analyze filing history for taxonomy refresh patterns.

        Args:
            current_filing: Current filing with schema references
            history_window: Historical filings for comparison
            thresholds: Override default detection thresholds

        Returns:
            MarkerResult with taxonomy refresh detection status and evidence
        """
        effective_thresholds = self._merge_thresholds(thresholds)

        # Extract current filing metadata
        current_metadata = self._extract_filing_metadata(current_filing)
        current_accession = current_metadata["accession"]

        if not history_window:
            return MarkerResult(
                marker_id=self.marker_id,
                detected=False,
                boundary=self._create_boundary(current_accession),
                evidence=[],
                threshold_config=effective_thresholds,
                analysis_metadata={
                    "total_filings_analyzed": 0,
                    "schema_refs_current": 0,
                    "change_score": 0.0,
                    "analysis_notes": "No history window available for comparison"
                }
            )

        # Extract schema references from current filing
        current_schema_refs = self._extract_schema_references(current_filing)

        # Find best reference filing for comparison
        reference_filing = self._select_reference_filing(history_window)
        reference_metadata = self._extract_filing_metadata(reference_filing)
        reference_schema_refs = self._extract_schema_references(reference_filing)

        # Analyze changes between current and reference
        change_analysis = self._analyze_schema_changes(
            current_schema_refs,
            reference_schema_refs,
            current_metadata,
            reference_metadata,
            effective_thresholds
        )

        # Determine if changes meet threshold for marker detection
        detected = change_analysis["change_score"] >= effective_thresholds["major_change_threshold"]

        # Create boundary
        boundary = self._create_boundary(current_accession, reference_metadata["accession"])

        # Generate evidence
        evidence = self._generate_evidence(change_analysis, current_metadata, reference_metadata)

        # Analysis metadata
        analysis_metadata = {
            "total_filings_analyzed": len(history_window),
            "schema_refs_current": len(current_schema_refs),
            "schema_refs_reference": len(reference_schema_refs),
            "change_score": change_analysis["change_score"],
            "reference_filing_selected": reference_metadata["accession"],
            "changes_detected": len(change_analysis["changes"]),
            "analysis_notes": change_analysis.get("notes", "")
        }

        return MarkerResult(
            marker_id=self.marker_id,
            detected=detected,
            boundary=boundary,
            evidence=evidence,
            threshold_config=effective_thresholds,
            analysis_metadata=analysis_metadata
        )

    def _extract_schema_references(self, filing: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract schema references from filing artifacts."""
        schema_refs = []

        # Check for pre-extracted schema references in filing metadata
        if "schema_references" in filing:
            return filing["schema_references"]

        # Try to extract from primary artifact if available
        primary_artifact = filing.get("primary_artifact")
        if primary_artifact:
            # This would normally parse the XBRL/iXBRL for schemaRef elements
            # For now, simulate extraction with placeholder logic
            schema_refs.extend(self._parse_schema_refs_from_artifact(primary_artifact))

        # Check extension artifacts
        extension_artifacts = filing.get("extension_artifacts", [])
        for artifact in extension_artifacts:
            if artifact.get("role") == "extension_schema":
                schema_refs.append({
                    "href": artifact.get("source_url", ""),
                    "namespace": artifact.get("target_namespace", ""),
                    "type": "extension",
                    "basename": self._extract_schema_basename(artifact.get("source_url", ""))
                })

        return schema_refs

    def _parse_schema_refs_from_artifact(self, artifact: Dict[str, Any]) -> List[Dict[str, str]]:
        """Parse schemaRef elements from primary artifact content."""
        # In a real implementation, this would parse the iXBRL/XBRL content
        # For this marker implementation, we'll return a placeholder structure

        schema_refs = []
        artifact_path = artifact.get("local_path", "")

        # Simulate standard GAAP taxonomy reference
        schema_refs.append({
            "href": "https://xbrl.sec.gov/dei/2023/dei-2023.xsd",
            "namespace": "http://xbrl.sec.gov/dei/2023",
            "type": "standard",
            "basename": "dei-2023"
        })

        # Simulate company extension
        if "extension" in artifact_path.lower() or "ext" in artifact_path.lower():
            schema_refs.append({
                "href": artifact.get("source_url", ""),
                "namespace": "",  # Would be extracted from actual content
                "type": "extension",
                "basename": self._extract_schema_basename(artifact.get("source_url", ""))
            })

        return schema_refs

    def _extract_schema_basename(self, url: str) -> str:
        """Extract schema basename from URL."""
        try:
            parsed = urlparse(url)
            path = parsed.path
            if path.endswith('.xsd'):
                return path.split('/')[-1][:-4]  # Remove .xsd extension
            return path.split('/')[-1]
        except Exception:
            return ""

    def _select_reference_filing(self, history_window: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Select the best reference filing for comparison."""
        # Use the most recent filing in the history window
        # History window is already sorted chronologically (oldest first)
        return history_window[-1] if history_window else {}

    def _analyze_schema_changes(
        self,
        current_refs: List[Dict[str, str]],
        reference_refs: List[Dict[str, str]],
        current_metadata: Dict[str, Any],
        reference_metadata: Dict[str, Any],
        thresholds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze changes between current and reference schema references."""

        changes = []
        change_score = 0.0

        # Create sets for comparison
        current_hrefs = {ref.get("href", "") for ref in current_refs}
        reference_hrefs = {ref.get("href", "") for ref in reference_refs}

        # Detect added schemas
        added_hrefs = current_hrefs - reference_hrefs
        for href in added_hrefs:
            ref_info = next((r for r in current_refs if r.get("href") == href), {})
            weight = (thresholds["extension_schema_weight"]
                     if ref_info.get("type") == "extension"
                     else thresholds["standard_taxonomy_weight"])

            changes.append({
                "type": "schema_added",
                "href": href,
                "namespace": ref_info.get("namespace", ""),
                "schema_type": ref_info.get("type", "unknown"),
                "weight": weight
            })
            change_score += weight

        # Detect removed schemas
        removed_hrefs = reference_hrefs - current_hrefs
        for href in removed_hrefs:
            ref_info = next((r for r in reference_refs if r.get("href") == href), {})
            weight = (thresholds["extension_schema_weight"]
                     if ref_info.get("type") == "extension"
                     else thresholds["standard_taxonomy_weight"])

            changes.append({
                "type": "schema_removed",
                "href": href,
                "namespace": ref_info.get("namespace", ""),
                "schema_type": ref_info.get("type", "unknown"),
                "weight": weight
            })
            change_score += weight

        # Detect namespace changes (same basename, different version/namespace)
        namespace_changes = self._detect_namespace_changes(current_refs, reference_refs)
        for change in namespace_changes:
            changes.append(change)
            change_score += change["weight"]

        # Analysis notes
        notes = []
        if len(changes) >= thresholds["min_schema_ref_changes"]:
            notes.append(f"Detected {len(changes)} schema reference changes")
        if change_score >= thresholds["major_change_threshold"]:
            notes.append(f"Change score {change_score:.1f} exceeds major change threshold")

        return {
            "changes": changes,
            "change_score": change_score,
            "notes": "; ".join(notes) if notes else "No significant changes detected"
        }

    def _detect_namespace_changes(
        self,
        current_refs: List[Dict[str, str]],
        reference_refs: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Detect namespace/version changes for similar schemas."""
        namespace_changes = []

        # Group by basename to detect version changes
        current_by_basename = {}
        reference_by_basename = {}

        for ref in current_refs:
            basename = ref.get("basename", "")
            if basename:
                current_by_basename[basename] = ref

        for ref in reference_refs:
            basename = ref.get("basename", "")
            if basename:
                reference_by_basename[basename] = ref

        # Find namespace changes for same basename
        for basename in current_by_basename:
            if basename in reference_by_basename:
                current_ns = current_by_basename[basename].get("namespace", "")
                reference_ns = reference_by_basename[basename].get("namespace", "")

                if current_ns != reference_ns:
                    namespace_changes.append({
                        "type": "namespace_change",
                        "basename": basename,
                        "old_namespace": reference_ns,
                        "new_namespace": current_ns,
                        "schema_type": current_by_basename[basename].get("type", "unknown"),
                        "weight": 1.5  # Namespace changes are moderately significant
                    })

        return namespace_changes

    def _generate_evidence(
        self,
        change_analysis: Dict[str, Any],
        current_metadata: Dict[str, Any],
        reference_metadata: Dict[str, Any]
    ) -> List[MarkerEvidence]:
        """Generate evidence for taxonomy refresh detection."""
        evidence = []
        changes = change_analysis["changes"]

        if not changes:
            return evidence

        # Summary evidence
        change_types = set(change["type"] for change in changes)
        evidence.append(MarkerEvidence(
            evidence_type="taxonomy_change_summary",
            description=f"Detected {len(changes)} taxonomy changes between {reference_metadata['accession']} and {current_metadata['accession']}",
            details={
                "current_accession": current_metadata["accession"],
                "reference_accession": reference_metadata["accession"],
                "change_count": len(changes),
                "change_types": list(change_types),
                "change_score": change_analysis["change_score"]
            }
        ))

        # Detailed evidence for each change type
        for change_type in change_types:
            type_changes = [c for c in changes if c["type"] == change_type]

            if change_type == "schema_added":
                hrefs = [c["href"] for c in type_changes]
                evidence.append(MarkerEvidence(
                    evidence_type="schemas_added",
                    description=f"Added {len(type_changes)} new schema references",
                    details={
                        "added_schemas": hrefs,
                        "total_weight": sum(c["weight"] for c in type_changes)
                    }
                ))

            elif change_type == "schema_removed":
                hrefs = [c["href"] for c in type_changes]
                evidence.append(MarkerEvidence(
                    evidence_type="schemas_removed",
                    description=f"Removed {len(type_changes)} schema references",
                    details={
                        "removed_schemas": hrefs,
                        "total_weight": sum(c["weight"] for c in type_changes)
                    }
                ))

            elif change_type == "namespace_change":
                ns_changes = [(c["basename"], c["old_namespace"], c["new_namespace"]) for c in type_changes]
                evidence.append(MarkerEvidence(
                    evidence_type="namespace_changes",
                    description=f"Changed namespaces for {len(type_changes)} schemas",
                    details={
                        "namespace_changes": ns_changes,
                        "total_weight": sum(c["weight"] for c in type_changes)
                    }
                ))

        return evidence