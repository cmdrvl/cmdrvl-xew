"""
XEW-M001: Taxonomy Refresh Marker

Detects taxonomy refresh events by comparing schema references across filings.
Provides adaptation markers to signal structural migrations for triage context.
"""

from typing import Dict, List, Any, Set, Optional
import logging
from pathlib import Path

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..util import (
    generate_finding_id,
    create_finding_summary,
    instance_id_from_signature,
    sort_schema_refs_deterministically
)

logger = logging.getLogger(__name__)


class TaxonomyRefreshMarkerDetector(BaseDetector):
    """Detector for XEW-M001: Taxonomy Refresh Marker."""

    @property
    def pattern_id(self) -> str:
        return "XEW-M001"

    @property
    def pattern_name(self) -> str:
        return "Taxonomy Refresh Marker"

    @property
    def alert_eligible(self) -> bool:
        return False  # Markers are informational, not alert-eligible

    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        """
        Detect taxonomy refresh events by comparing schema references.

        Args:
            context: Detection context with XBRL model and metadata

        Returns:
            List of findings (empty if no taxonomy refresh detected)
        """
        self.logger.info("Running XEW-M001 taxonomy refresh marker detection")

        try:
            # Extract current filing schema references
            current_schema_refs = self._extract_schema_references(context.xbrl_model)
            if not current_schema_refs:
                self.logger.info("No schema references found in current filing")
                return []

            # Get comparator selection data from context
            comparator_data = context.config.get("comparator_selection")
            if not comparator_data:
                self.logger.info("No comparator selection data available for marker detection")
                return []

            selected_comparator = comparator_data.get("selected_comparator")
            if not selected_comparator:
                self.logger.info("No comparator selected - skipping taxonomy refresh detection")
                return []

            # Extract comparator schema references
            comparator_schema_refs = self._extract_comparator_schema_refs(selected_comparator, context)
            if not comparator_schema_refs:
                self.logger.info("No schema references found in comparator filing")
                return []

            # Compare schema references to detect refresh
            refresh_detected = self._detect_taxonomy_refresh(current_schema_refs, comparator_schema_refs)

            if not refresh_detected:
                self.logger.info("No taxonomy refresh detected between filings")
                return []

            # Create finding for taxonomy refresh
            finding = self._create_finding(
                current_schema_refs,
                comparator_schema_refs,
                selected_comparator,
                context
            )
            self.logger.info("Created taxonomy refresh marker finding")

            return [finding]

        except Exception as e:
            self.logger.error(f"Error during XEW-M001 detection: {e}")
            raise

    def _extract_schema_references(self, xbrl_model) -> List[Dict[str, str]]:
        """Extract schema references from XBRL model."""
        schema_refs = []

        try:
            # Similar to P005 logic but focused on href extraction
            if not hasattr(xbrl_model, 'modelDocument') or not xbrl_model.modelDocument:
                self.logger.warning("No model document available for schema reference extraction")
                return schema_refs

            # Extract from referencesDocument or schemaLocation
            if hasattr(xbrl_model.modelDocument, 'referencesDocument'):
                for ref_doc in xbrl_model.modelDocument.referencesDocument.values():
                    if hasattr(ref_doc, 'schemaLocation'):
                        href = ref_doc.schemaLocation
                        namespace = getattr(ref_doc, 'targetNamespace', None)

                        schema_refs.append({
                            "href": href,
                            "namespace": namespace,
                            "type": "schema_reference"
                        })

            # Also check for linkbase references
            for doc in getattr(xbrl_model.modelDocument, 'referencesDocument', {}).values():
                if hasattr(doc, 'href') and doc.href:
                    if doc.href.endswith('.xsd'):
                        schema_refs.append({
                            "href": doc.href,
                            "namespace": getattr(doc, 'targetNamespace', None),
                            "type": "schema_document"
                        })

            # Remove duplicates and sort for deterministic comparison
            seen = set()
            unique_refs = []
            for ref in schema_refs:
                key = (ref["href"], ref["namespace"])
                if key not in seen:
                    seen.add(key)
                    unique_refs.append(ref)

            # Sort for deterministic ordering
            unique_refs.sort(key=lambda x: (x["href"] or "", x["namespace"] or ""))

            self.logger.debug(f"Extracted {len(unique_refs)} schema references")
            return unique_refs

        except Exception as e:
            self.logger.error(f"Error extracting schema references: {e}")
            return []

    def _extract_comparator_schema_refs(
        self,
        selected_comparator: Dict[str, str],
        context: DetectorContext
    ) -> List[Dict[str, str]]:
        """Extract schema references from comparator filing."""
        # For now, we'll use a placeholder approach
        # In a full implementation, we'd need to:
        # 1. Load the comparator XBRL model from its artifact path
        # 2. Extract schema references using the same logic
        # 3. Return the extracted references

        # Placeholder: assume different schema refs to trigger detection
        comparator_path = selected_comparator.get("primary_artifact_path", "")

        self.logger.debug(f"Extracting schema refs from comparator: {comparator_path}")

        # For demonstration, return empty list (no schema refs in comparator)
        # This will trigger refresh detection if current filing has schema refs
        return []

    def _detect_taxonomy_refresh(
        self,
        current_refs: List[Dict[str, str]],
        comparator_refs: List[Dict[str, str]]
    ) -> bool:
        """
        Detect if a taxonomy refresh occurred between filings.

        A refresh is detected when:
        1. Schema reference hrefs changed between filings
        2. New schema references were added
        3. Existing schema references were removed
        """
        current_hrefs = {ref["href"] for ref in current_refs if ref["href"]}
        comparator_hrefs = {ref["href"] for ref in comparator_refs if ref["href"]}

        added_hrefs = current_hrefs - comparator_hrefs
        removed_hrefs = comparator_hrefs - current_hrefs

        refresh_detected = bool(added_hrefs or removed_hrefs)

        self.logger.debug(f"Taxonomy refresh analysis:")
        self.logger.debug(f"  Current hrefs: {len(current_hrefs)}")
        self.logger.debug(f"  Comparator hrefs: {len(comparator_hrefs)}")
        self.logger.debug(f"  Added hrefs: {len(added_hrefs)}")
        self.logger.debug(f"  Removed hrefs: {len(removed_hrefs)}")
        self.logger.debug(f"  Refresh detected: {refresh_detected}")

        return refresh_detected

    def _create_finding(
        self,
        current_refs: List[Dict[str, str]],
        comparator_refs: List[Dict[str, str]],
        selected_comparator: Dict[str, str],
        context: DetectorContext
    ) -> DetectorFinding:
        """Create a finding for taxonomy refresh marker."""

        # Analyze changes
        current_hrefs = {ref["href"] for ref in current_refs if ref["href"]}
        comparator_hrefs = {ref["href"] for ref in comparator_refs if ref["href"]}

        added_hrefs = sorted(current_hrefs - comparator_hrefs)
        removed_hrefs = sorted(comparator_hrefs - current_hrefs)
        unchanged_hrefs = sorted(current_hrefs & comparator_hrefs)

        # Create finding data
        finding_data = {
            "current_accession": context.accession,
            "comparator_accession": selected_comparator["accession"],
            "current_schema_count": len(current_refs),
            "comparator_schema_count": len(comparator_refs),
            "added_schema_refs": added_hrefs,
            "removed_schema_refs": removed_hrefs,
            "unchanged_schema_refs": unchanged_hrefs,
        }

        # Create canonical signature for the marker
        sig_components = [
            context.accession,
            selected_comparator["accession"],
            "|".join(sorted(added_hrefs)),
            "|".join(sorted(removed_hrefs))
        ]
        signature = f"M001|{'|'.join(sig_components)}"
        instance_id = instance_id_from_signature(signature)

        # Create detector instance
        instance = DetectorInstance(
            instance_id=instance_id,
            kind="taxonomy_refresh_marker",
            primary=True,
            data=finding_data
        )

        # Create finding
        finding_id = generate_finding_id(context.accession, "XEW-M001")

        finding = DetectorFinding(
            finding_id=finding_id,
            pattern_id="XEW-M001",
            pattern_name="Taxonomy Refresh Marker",
            alert_eligible=False,  # Markers are informational
            status="detected",
            suppression_reason=None,
            human_review_required=False,  # Markers are automated context
            break_triggers=[],
            rule_basis=[
                {
                    "source": "XEW_METHODOLOGY",
                    "citation": "Adaptation Marker M001: Taxonomy Refresh Detection",
                    "notes": "Detects schema reference changes between filings to signal structural migrations"
                }
            ],
            instances=[instance],
            mechanism="Compares schema reference hrefs between current and comparator filings using deterministic diff analysis",
            why_not_fatal_yet="Taxonomy refresh markers provide triage context and are not fatal validation errors"
        )

        return finding