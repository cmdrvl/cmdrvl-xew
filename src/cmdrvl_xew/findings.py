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

        # Build observed instances
        observed_instances = []
        for instance in sorted(finding.instances, key=lambda i: i.instance_id):
            instance_json = self._convert_instance_to_json(instance, finding.pattern_id)
            observed_instances.append(instance_json)

        # Build finding JSON
        finding_json = {
            "finding_id": finding.finding_id,
            "pattern_id": finding.pattern_id,
            "pattern_name": finding.pattern_name,
            "alert_eligible": finding.alert_eligible,
            "status": finding.status,
            "human_review_required": finding.human_review_required,
            "break_triggers": sorted(finding.break_triggers, key=lambda t: t.get('id', '')),
            "observed": {
                "instance_count": len(finding.instances),
                "instances": observed_instances
            },
            "mechanism": finding.mechanism,
            "why_not_fatal_yet": finding.why_not_fatal_yet
        }

        # Add optional fields
        if finding.suppression_reason:
            finding_json["suppression_reason"] = finding.suppression_reason

        if finding.rule_basis:
            finding_json["rule_basis"] = sorted(
                finding.rule_basis,
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

        # Add pattern-specific data fields
        if pattern_id == "XEW-P001":
            instance_json.update(self._format_p001_data(instance.data))
        elif pattern_id == "XEW-P002":
            instance_json.update(self._format_p002_data(instance.data))
        elif pattern_id == "XEW-P004":
            instance_json.update(self._format_p004_data(instance.data))
        elif pattern_id == "XEW-P005":
            instance_json.update(self._format_p005_data(instance.data))
        else:
            # Generic data handling for unknown patterns
            instance_json["data"] = instance.data

        return instance_json

    def _format_p001_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P001-specific instance data."""
        result = {}

        if "concept_clark" in data:
            result["concept"] = {"clark": data["concept_clark"]}

        if "duplicate_count" in data:
            result["duplicate_count"] = data["duplicate_count"]

        if "has_value_conflicts" in data:
            result["has_value_conflicts"] = data["has_value_conflicts"]

        if "raw_values" in data:
            result["raw_values"] = data["raw_values"]

        if "normalized_values" in data:
            result["normalized_values"] = data["normalized_values"]

        return result

    def _format_p002_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P002-specific instance data."""
        result = {}

        if "extension_concept_clark" in data:
            result["extension_concept"] = {"clark": data["extension_concept_clark"]}

        if "anchor_concept_clark" in data:
            result["anchor_concept"] = {"clark": data["anchor_concept_clark"]}

        if "defect_code" in data:
            result["defect_code"] = data["defect_code"]

        return result

    def _format_p004_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P004-specific instance data."""
        result = {}

        if "concept_clark" in data:
            result["concept"] = {"clark": data["concept_clark"]}

        if "violation_code" in data:
            result["violation_code"] = data["violation_code"]

        if "context_ref" in data:
            result["context_ref"] = data["context_ref"]

        if "unit_ref" in data:
            result["unit_ref"] = data["unit_ref"]

        return result

    def _format_p005_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format P005-specific instance data."""
        result = {}

        if "schema_refs" in data:
            result["schema_refs"] = data["schema_refs"]

        if "fact_namespaces" in data:
            result["fact_namespaces"] = data["fact_namespaces"]

        if "inconsistency_type" in data:
            result["inconsistency_type"] = data["inconsistency_type"]

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