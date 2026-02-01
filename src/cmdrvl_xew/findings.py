"""Deterministic xew_findings.json writer.

This module converts DetectorFinding objects into the v1 xew_findings.json format
with deterministic ordering and schema compliance.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from .detectors._base import DetectorFinding, DetectorInstance, DetectorContext

logger = logging.getLogger(__name__)


class FindingsWriter:
    """Writer for deterministic xew_findings.json output."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def write_findings(self,
                      findings: List[DetectorFinding],
                      context: DetectorContext,
                      artifacts: List[Dict[str, Any]],
                      toolchain: Dict[str, Any],
                      input_metadata: Dict[str, Any]) -> None:
        """
        Write findings to JSON file with deterministic ordering.

        Args:
            findings: List of detector findings
            context: Detection context
            artifacts: List of artifact metadata
            toolchain: Toolchain information
            input_metadata: Input filing metadata
        """
        # Generate complete findings document
        findings_doc = self._build_findings_document(
            findings, context, artifacts, toolchain, input_metadata
        )

        # Write with deterministic formatting
        self._write_json_deterministically(findings_doc)

        self.logger.info(f"Written {len(findings)} findings to {self.output_path}")

    def _build_findings_document(self,
                               findings: List[DetectorFinding],
                               context: DetectorContext,
                               artifacts: List[Dict[str, Any]],
                               toolchain: Dict[str, Any],
                               input_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Build the complete findings JSON document."""

        # Convert findings to schema format with deterministic ordering
        findings_json = []
        for finding in sorted(findings, key=lambda f: f.finding_id):
            finding_json = self._convert_finding_to_json(finding)
            findings_json.append(finding_json)

        # Build complete document
        document = {
            "schema_id": "cmdrvl.xew_findings",
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "toolchain": toolchain,
            "input": input_metadata,
            "artifacts": artifacts,
            "findings": findings_json
        }

        return document

    def _convert_finding_to_json(self, finding: DetectorFinding) -> Dict[str, Any]:
        """Convert DetectorFinding to JSON schema format."""

        # Build observed instances with schema compliance
        observed_instances = []
        for instance in sorted(finding.instances, key=lambda i: i.instance_id):
            instance_json = self._convert_instance_to_json(instance, finding.pattern_id)
            observed_instances.append(instance_json)

        # Apply truncation for large instance lists (deterministic)
        max_instances = 100  # Schema compliance limit
        truncated = len(observed_instances) > max_instances
        if truncated:
            observed_instances = observed_instances[:max_instances]

        # Build finding JSON with schema-compliant observed block
        finding_json = {
            "finding_id": finding.finding_id,
            "pattern_id": finding.pattern_id,
            "pattern_name": finding.pattern_name,
            "alert_eligible": finding.alert_eligible,
            "status": finding.status,
            "human_review_required": finding.human_review_required,
            "break_triggers": sorted(finding.break_triggers, key=lambda t: t.get('id', '')),
            "observed": {
                "instance_count_total": len(finding.instances),
                "instance_count_included": len(observed_instances),
                "truncated": truncated,
                "instances": observed_instances
            },
            "mechanism": finding.mechanism,
            "why_not_fatal_yet": finding.why_not_fatal_yet
        }

        # Add optional fields
        if finding.suppression_reason:
            finding_json["suppression_reason"] = finding.suppression_reason

        if finding.rule_basis:
            # Normalize and validate rule basis citations for schema compliance
            normalized_citations = []
            for citation in finding.rule_basis:
                normalized = self._normalize_rule_basis_citation(citation)
                if normalized:  # Only include valid citations
                    normalized_citations.append(normalized)

            if normalized_citations:
                finding_json["rule_basis"] = sorted(
                    normalized_citations,
                    key=lambda r: (r.get('source', ''), r.get('citation', ''))
                )

        return finding_json

    def _convert_instance_to_json(self, instance: DetectorInstance, pattern_id: str) -> Dict[str, Any]:
        """Convert DetectorInstance to JSON schema format."""

        instance_json = {
            "instance_id": instance.instance_id,
            "kind": instance.kind,
            "primary": instance.primary
        }

        # Add pattern-specific data fields in schema-compliant format
        if pattern_id == "XEW-P001":
            instance_json["data"] = self._format_p001_data(instance.data)
        elif pattern_id == "XEW-P002":
            instance_json["data"] = self._format_p002_data(instance.data)
        elif pattern_id == "XEW-P004":
            instance_json["data"] = self._format_p004_data(instance.data)
        elif pattern_id == "XEW-P005":
            instance_json["data"] = self._format_p005_data(instance.data)
        else:
            # Generic data handling for unknown patterns
            instance_json["data"] = instance.data

        return instance_json

    def _normalize_rule_basis_citation(self, citation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalize rule basis citation to schema format.

        Args:
            citation: Raw citation from detector

        Returns:
            Schema-compliant citation dict or None if invalid
        """
        try:
            # Extract and normalize source
            raw_source = citation.get('source', '').upper()
            source_mapping = {
                'XBRL SPECIFICATION 2.1': 'XBRL_SPEC',
                'XBRL_21': 'XBRL_SPEC',
                'XBRL SPEC': 'XBRL_SPEC',
                'SEC EFM': 'SEC_EFM',
                'EFM': 'SEC_EFM',
                'ARELLE': 'ARELLE_VALIDATION',
                'DQCRT': 'DQCRT',
                'OTHER': 'OTHER'
            }

            # Map source to schema enum
            source = None
            for key, value in source_mapping.items():
                if key in raw_source:
                    source = value
                    break

            if not source:
                source = 'OTHER'  # Default fallback

            # Build normalized citation
            normalized = {
                'source': source,
                'citation': str(citation.get('citation', citation.get('title', ''))),
            }

            # Add optional fields if present and valid
            if citation.get('url'):
                normalized['url'] = citation['url']

            if citation.get('retrieved_at'):
                normalized['retrieved_at'] = citation['retrieved_at']

            if citation.get('sha256'):
                sha256 = citation['sha256']
                # Validate SHA256 format (64 hex chars)
                if len(sha256) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256):
                    normalized['sha256'] = sha256.lower()

            if citation.get('notes'):
                normalized['notes'] = citation['notes']

            # Validate minimum required fields
            if not normalized['citation']:
                return None

            return normalized

        except Exception as e:
            self.logger.warning(f"Failed to normalize rule basis citation: {e}")
            return None

    def _format_p001_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P001-specific instance data with evidence snippets."""
        result = {}

        # Handle concept from actual P001 structure
        if "concept" in data and isinstance(data["concept"], dict):
            result["concept"] = data["concept"]
        elif "concept_clark" in data:
            result["concept"] = {"clark": data["concept_clark"]}

        # Use context_ref from data
        result["context_ref"] = data.get("context_ref", "ctx_placeholder")

        # Map fact_count and include actual facts as evidence
        if "facts" in data:
            # Use actual fact data from P001 detector
            result["facts"] = data["facts"]
            result["fact_count"] = len(data["facts"])

            # Include facts as evidence snippets
            result["evidence_snippets"] = {
                "duplicate_facts": data["facts"]
            }
        else:
            # Fallback for legacy structure
            result["fact_count"] = data.get("duplicate_count", 2)

            # Build facts array from raw values
            facts = []
            raw_values = data.get("raw_values", [])

            for i, value in enumerate(raw_values):
                fact_ref = {
                    "concept": result["concept"],
                    "context_ref": f"{result['context_ref']}_{i}" if len(raw_values) > 1 else result["context_ref"],
                    "value": str(value) if value is not None else ""
                }

                if data.get("unit_ref"):
                    fact_ref["unit_ref"] = data["unit_ref"]
                    result["unit_ref"] = data["unit_ref"]

                facts.append(fact_ref)

            result["facts"] = facts
            result["evidence_snippets"] = {
                "duplicate_facts": facts
            }

        # Add issue codes and value conflict detection
        if "issue_codes" in data:
            result["issue_codes"] = data["issue_codes"]
        elif data.get("has_value_conflicts"):
            result["issue_codes"] = ["duplicate_fact", "value_conflict"]
        else:
            result["issue_codes"] = ["duplicate_fact"]

        if "value_conflict" in data:
            result["value_conflict"] = data["value_conflict"]
        else:
            result["value_conflict"] = data.get("has_value_conflicts", False)

        return result

    def _format_p002_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P002-specific instance data with evidence snippets."""
        result = {}

        # Handle extension concept (qname object from actual P002 detector)
        if "extension_concept" in data:
            result["extension_concept"] = data["extension_concept"]
        elif "extension_concept_clark" in data:
            result["extension_concept"] = {"clark": data["extension_concept_clark"]}

        if "anchor_concept_clark" in data:
            result["anchor_concept"] = {"clark": data["anchor_concept_clark"]}

        # Map issue_codes to defect_code for schema compatibility
        if "issue_codes" in data:
            result["defect_code"] = data["issue_codes"][0] if data["issue_codes"] else "unanchored"
        elif "defect_code" in data:
            result["defect_code"] = data["defect_code"]

        # Include evidence snippets - fact examples showing extension concept usage
        if "used_fact_examples" in data:
            result["evidence_snippets"] = {
                "used_fact_examples": data["used_fact_examples"]
            }

        # Include anchoring evidence
        if "anchors" in data:
            if "evidence_snippets" not in result:
                result["evidence_snippets"] = {}
            result["evidence_snippets"]["anchoring_relationships"] = data["anchors"]

        return result

    def _format_p004_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P004-specific instance data with evidence snippets."""
        result = {}

        # Handle concept from actual P004 detector structure
        if "fact" in data and isinstance(data["fact"], dict):
            fact = data["fact"]
            if "concept" in fact:
                result["concept"] = fact["concept"]
            if "context_ref" in fact:
                result["context_ref"] = fact["context_ref"]
            if "unit_ref" in fact:
                result["unit_ref"] = fact["unit_ref"]

            # Include the fact as evidence snippet
            result["evidence_snippets"] = {
                "violating_fact": fact
            }
        else:
            # Fallback for legacy structure
            if "concept_clark" in data:
                result["concept"] = {"clark": data["concept_clark"]}
            if "context_ref" in data:
                result["context_ref"] = data["context_ref"]
            if "unit_ref" in data:
                result["unit_ref"] = data["unit_ref"]

        # Map issue_code to violation_code for schema compatibility
        if "issue_code" in data:
            result["violation_code"] = data["issue_code"]
        elif "violation_code" in data:
            result["violation_code"] = data["violation_code"]

        # Include concept type and unit measures as evidence
        if "concept_type" in data:
            if "evidence_snippets" not in result:
                result["evidence_snippets"] = {}
            result["evidence_snippets"]["concept_type"] = data["concept_type"]

        if "unit_measures" in data:
            if "evidence_snippets" not in result:
                result["evidence_snippets"] = {}
            result["evidence_snippets"]["unit_measures"] = data["unit_measures"]

        return result

    def _format_p005_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P005-specific instance data with evidence snippets."""
        result = {}

        # Map issue_code to schema format
        issue_code = data.get("issue_code", "namespace_schema_ref_mismatch")

        # Schema only accepts specific issue codes
        valid_issue_codes = ["mixed_taxonomy_versions", "namespace_schema_ref_mismatch"]
        if issue_code not in valid_issue_codes:
            # Map common variants to valid codes
            if "version" in issue_code.lower() or "mismatch" in issue_code.lower():
                result["issue_code"] = "mixed_taxonomy_versions"
            else:
                result["issue_code"] = "namespace_schema_ref_mismatch"
        else:
            result["issue_code"] = issue_code

        # Add schema references as evidence
        if "schema_refs" in data:
            result["schema_refs"] = data["schema_refs"]
            # Include schema references as evidence
            result["evidence_snippets"] = {
                "schema_references": data["schema_refs"]
            }
        elif "affected_schema_refs" in data:
            result["schema_refs"] = data["affected_schema_refs"]
            result["evidence_snippets"] = {
                "schema_references": data["affected_schema_refs"]
            }

        # Include namespaces found in facts as evidence
        if "namespaces_in_facts" in data:
            if "evidence_snippets" not in result:
                result["evidence_snippets"] = {}
            result["evidence_snippets"]["fact_namespaces"] = data["namespaces_in_facts"]

        # Include detailed mismatch information
        if "details" in data:
            if "evidence_snippets" not in result:
                result["evidence_snippets"] = {}
            result["evidence_snippets"]["details"] = data["details"]

        return result

    def _write_json_deterministically(self, document: Dict[str, Any]) -> None:
        """Write JSON with deterministic formatting."""

        # Ensure parent directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with deterministic formatting
        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(
                document,
                f,
                indent=2,
                sort_keys=True,  # Deterministic key ordering
                ensure_ascii=False,
                separators=(',', ': ')
            )


# Factory functions for convenience
def create_findings_writer(output_path: Path) -> FindingsWriter:
    """Create a findings writer for the specified output path."""
    return FindingsWriter(output_path)


def write_findings_json(findings: List[DetectorFinding],
                       context: DetectorContext,
                       artifacts: List[Dict[str, Any]],
                       toolchain: Dict[str, Any],
                       input_metadata: Dict[str, Any],
                       output_path: Path) -> None:
    """
    Convenience function to write findings JSON in one call.

    Args:
        findings: List of detector findings
        context: Detection context
        artifacts: List of artifact metadata
        toolchain: Toolchain information
        input_metadata: Input filing metadata
        output_path: Path to write JSON file
    """
    writer = create_findings_writer(output_path)
    writer.write_findings(findings, context, artifacts, toolchain, input_metadata)