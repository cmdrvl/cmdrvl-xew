"""Detector registry for XEW pattern detection."""

import logging
from typing import Dict, List, Type, Set, Any, Optional, Union, Tuple
from pathlib import Path
import importlib
import json

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorError

logger = logging.getLogger(__name__)


# Pattern priority order for v1 shipping set (highest to lowest)
# When multiple patterns are detected, select highest priority for external alerts
PATTERN_PRIORITIES = {
    "XEW-P001": 1,  # Duplicate facts - highest priority (data integrity)
    "XEW-P004": 2,  # Type/unit/numeric violations - high priority (validation critical)
    "XEW-P005": 3,  # Taxonomy inconsistencies - medium priority (structural)
    "XEW-P002": 4,  # Anchoring defects - lower priority (taxonomy quality)
}


class DetectorRegistry:
    """Central registry for XEW pattern detectors."""

    def __init__(self):
        self._detectors: Dict[str, BaseDetector] = {}
        self._detector_classes: Dict[str, Type[BaseDetector]] = {}
        self._rule_basis_map: Dict[str, List[Dict]] = {}
        self._issue_codes_map: Dict[str, List[str]] = {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def register(self, detector_class: Type[BaseDetector]) -> None:
        """
        Register a detector class.

        Args:
            detector_class: Class that inherits from BaseDetector
        """
        # Instantiate to get pattern info
        instance = detector_class()
        pattern_id = instance.pattern_id

        if pattern_id in self._detector_classes:
            self.logger.warning(f"Overwriting existing detector for {pattern_id}")

        self._detector_classes[pattern_id] = detector_class
        self._detectors[pattern_id] = instance

        self.logger.info(f"Registered detector: {pattern_id} ({detector_class.__name__})")

    def unregister(self, pattern_id: str) -> None:
        """Unregister a detector by pattern ID."""
        if pattern_id in self._detectors:
            del self._detectors[pattern_id]
            del self._detector_classes[pattern_id]
            self.logger.info(f"Unregistered detector: {pattern_id}")

    def get_detector(self, pattern_id: str) -> BaseDetector:
        """Get a detector instance by pattern ID."""
        if pattern_id not in self._detectors:
            raise ValueError(f"No detector registered for pattern {pattern_id}")
        return self._detectors[pattern_id]

    def list_patterns(self) -> List[str]:
        """Return list of registered pattern IDs."""
        return list(self._detectors.keys())

    def list_alert_eligible_patterns(self) -> List[str]:
        """Return list of pattern IDs that are alert-eligible."""
        return [
            pattern_id for pattern_id, detector in self._detectors.items()
            if detector.alert_eligible
        ]

    def load_rule_basis_map(self, rule_basis_path: Path) -> None:
        """
        Load rule basis map from JSON file.

        Args:
            rule_basis_path: Path to xew_rule_basis_map.v1.json
        """
        try:
            with open(rule_basis_path, 'r') as f:
                data = json.load(f)

            # Index rule basis by pattern_id for efficient lookup
            self._rule_basis_map = {}
            for rule in data.get('rules', []):
                pattern_id = rule.get('pattern_id')
                if pattern_id:
                    if pattern_id not in self._rule_basis_map:
                        self._rule_basis_map[pattern_id] = []
                    self._rule_basis_map[pattern_id].append(rule)

            self.logger.info(f"Loaded rule basis for {len(self._rule_basis_map)} patterns")

        except Exception as e:
            self.logger.error(f"Failed to load rule basis map: {e}")
            raise DetectorError("Registry", f"Could not load rule basis map: {e}")

    def load_issue_codes_map(self, issue_codes_path: Path) -> None:
        """
        Load issue codes map from JSON file.

        Args:
            issue_codes_path: Path to xew_issue_codes.v1.json
        """
        try:
            with open(issue_codes_path, 'r') as f:
                data = json.load(f)

            self._issue_codes_map = data.get('patterns', {})
            self.logger.info(f"Loaded issue codes for {len(self._issue_codes_map)} patterns")

        except Exception as e:
            self.logger.error(f"Failed to load issue codes map: {e}")
            raise DetectorError("Registry", f"Could not load issue codes map: {e}")

    def get_rule_basis(self, pattern_id: str) -> List[Dict]:
        """Get rule basis citations for a pattern."""
        return self._rule_basis_map.get(pattern_id, [])

    def get_issue_codes(self, pattern_id: str) -> List[str]:
        """Get issue codes for a pattern."""
        pattern_data = self._issue_codes_map.get(pattern_id, {})
        return pattern_data.get('issue_codes', [])

    def run_detectors(self, context: DetectorContext,
                     patterns: Set[str] = None) -> List[DetectorFinding]:
        """
        Run detectors and return all findings.

        Args:
            context: Detection context with XBRL model and metadata
            patterns: Optional set of pattern IDs to run (default: all registered)

        Returns:
            List of all findings from all detectors
        """
        if patterns is None:
            patterns = set(self._detectors.keys())

        findings = []

        for pattern_id in patterns:
            if pattern_id not in self._detectors:
                self.logger.warning(f"Pattern {pattern_id} not registered, skipping")
                continue

            detector = self._detectors[pattern_id]

            try:
                # Check if detector should run
                if not detector.should_run(context):
                    self.logger.debug(f"Skipping {pattern_id} (should_run returned False)")
                    continue

                # Run detector
                self.logger.info(f"Running detector: {pattern_id}")
                detector_findings = detector.detect(context)

                # Enrich findings with rule basis, issue codes, and break triggers
                for finding in detector_findings:
                    if not finding.rule_basis:
                        finding.rule_basis = self.get_rule_basis(pattern_id)

                    # Apply Gate enforcement: demote findings without valid rule basis
                    finding = self.apply_gate_enforcement(finding, pattern_id)

                    # Select the most specific break trigger
                    if not finding.break_triggers:
                        selected_trigger = self.select_break_trigger(pattern_id)
                        if selected_trigger:
                            finding.break_triggers = [selected_trigger]

                findings.extend(detector_findings)
                self.logger.info(f"Detector {pattern_id} produced {len(detector_findings)} findings")

            except Exception as e:
                self.logger.error(f"Detector {pattern_id} failed: {e}")
                # In production, we might want to continue with other detectors
                # For now, re-raise to fail fast during development
                raise DetectorError(pattern_id, f"Detection failed: {e}", e)

        self.logger.info(f"All detectors completed, {len(findings)} total findings")
        return findings

    def select_highest_priority_finding(self, findings: List[DetectorFinding]) -> Optional[DetectorFinding]:
        """
        Select the highest priority finding for external alerts.

        When multiple patterns are detected, v1 Evidence Pack engine sends at most
        one external alert per filing by default. This method implements deterministic
        selection based on pattern priority order.

        Args:
            findings: List of all detected findings

        Returns:
            Single highest-priority finding for external alert, or None if no eligible findings
        """
        if not findings:
            return None

        # Filter to alert-eligible findings only
        alert_eligible_findings = [f for f in findings if f.alert_eligible]

        if not alert_eligible_findings:
            self.logger.info("No alert-eligible findings for priority selection")
            return None

        self.logger.debug(f"Selecting priority from {len(alert_eligible_findings)} alert-eligible findings")

        # Sort by pattern priority (lower number = higher priority)
        def get_priority(finding: DetectorFinding) -> int:
            return PATTERN_PRIORITIES.get(finding.pattern_id, 999)  # 999 for unknown patterns

        # Deterministic tie-breakers for equal priority
        def sort_key(finding: DetectorFinding) -> tuple[int, str, str]:
            return (get_priority(finding), finding.pattern_id, finding.finding_id)

        prioritized_findings = sorted(alert_eligible_findings, key=sort_key)
        selected_finding = prioritized_findings[0]

        self.logger.info(f"Selected highest priority finding: {selected_finding.pattern_id} "
                        f"(priority {get_priority(selected_finding)}) from {len(findings)} total findings")

        return selected_finding

    def get_pattern_priority(self, pattern_id: str) -> int:
        """
        Get priority level for a pattern ID.

        Args:
            pattern_id: Pattern ID (e.g., 'XEW-P001')

        Returns:
            Priority level (lower number = higher priority)
        """
        return PATTERN_PRIORITIES.get(pattern_id, 999)

    def run_detectors_with_priority_selection(self, context: DetectorContext,
                                            patterns: Set[str] = None) -> Tuple[List[DetectorFinding], Optional[DetectorFinding]]:
        """
        Run detectors and return both all findings and the highest-priority finding.

        This is the main detection orchestration method that:
        1. Runs all specified detectors
        2. Records all findings internally
        3. Selects the highest-priority finding for external alerts

        Args:
            context: Detection context with XBRL model and metadata
            patterns: Optional set of pattern IDs to run (default: all registered)

        Returns:
            Tuple of (all_findings, highest_priority_finding)
            - all_findings: Complete list of findings for internal recording
            - highest_priority_finding: Single finding for external alert (or None)
        """
        # Run all detectors to get complete findings
        all_findings = self.run_detectors(context, patterns)

        # Select highest priority finding for external alert
        priority_finding = self.select_highest_priority_finding(all_findings)

        if priority_finding:
            self.logger.info(f"Priority selection: {priority_finding.pattern_id} selected "
                           f"from {len(all_findings)} total findings for external alert")
        else:
            self.logger.info(f"Priority selection: No alert-eligible findings from "
                           f"{len(all_findings)} total findings")

        return all_findings, priority_finding

    def list_patterns_by_priority(self) -> List[str]:
        """
        Return registered pattern IDs ordered by priority (highest to lowest).

        Returns:
            List of pattern IDs sorted by priority level
        """
        registered_patterns = self.list_patterns()

        # Sort by priority level
        def get_priority(pattern_id: str) -> int:
            return PATTERN_PRIORITIES.get(pattern_id, 999)

        prioritized_patterns = sorted(registered_patterns, key=get_priority)

        self.logger.debug(f"Patterns by priority: {prioritized_patterns}")
        return prioritized_patterns

    def select_break_trigger(self, pattern_id: str) -> Dict[str, str]:
        """
        Select the most specific break trigger for a pattern.

        Implements deterministic break trigger selection based on specificity rules.
        Lower numbered triggers (BT001, BT002, etc.) are considered more specific.

        Args:
            pattern_id: Pattern ID (e.g., 'XEW-P001')

        Returns:
            Single break trigger dict with 'id' and 'summary', or empty dict if none available
        """
        if pattern_id not in self._detectors:
            return {}

        detector = self._detectors[pattern_id]

        try:
            available_triggers = detector.get_break_triggers()

            if not available_triggers:
                self.logger.warning(f"No break triggers available for {pattern_id}")
                return {}

            # Sort by trigger ID for deterministic selection
            # Lower numbers are more specific (BT001 > BT002 > BT003 > BT004)
            sorted_triggers = sorted(available_triggers, key=lambda t: t.get('id', 'ZZZ'))

            selected = sorted_triggers[0]
            self.logger.debug(f"Selected break trigger for {pattern_id}: {selected.get('id')}")

            return selected

        except Exception as e:
            self.logger.error(f"Failed to select break trigger for {pattern_id}: {e}")
            return {}

    def apply_gate_enforcement(self, finding: DetectorFinding, pattern_id: str) -> DetectorFinding:
        """
        Apply Gate enforcement: suppress findings without valid rule basis.

        The Gate requires that every finding shipped as an alert must have:
        1. At least one pinned rule basis citation
        2. Valid retrieved_at and sha256 for reproducibility

        If these requirements are not met, the finding is suppressed (status="suppressed")
        but preserved for analysis and debugging.

        Args:
            finding: DetectorFinding to check and potentially demote
            pattern_id: Pattern ID for logging

        Returns:
            DetectorFinding with potentially updated alert eligibility
        """
        try:
            # Check if finding has valid rule basis
            if not self._has_valid_rule_basis(finding, pattern_id):
                self.logger.warning(f"Gate enforcement: demoting {pattern_id} finding due to missing/invalid rule basis")

                # Suppress to satisfy schema (status enum: detected|suppressed)
                finding.alert_eligible = False
                finding.status = "suppressed"

                # Record suppression reason
                finding.suppression_reason = "Missing or invalid rule basis citation"

                # Ensure human review is required for demoted findings
                finding.human_review_required = True

                self.logger.info(f"Finding {finding.finding_id} demoted by Gate enforcement")
            else:
                self.logger.debug(f"Finding {finding.finding_id} passed Gate enforcement")

            return finding

        except Exception as e:
            self.logger.error(f"Error during Gate enforcement for {pattern_id}: {e}")
            # In case of error, demote for safety
            finding.alert_eligible = False
            finding.status = "suppressed"
            finding.suppression_reason = f"Gate enforcement error: {e}"
            return finding

    def _has_valid_rule_basis(self, finding: DetectorFinding, pattern_id: str) -> bool:
        """
        Check if finding has valid rule basis citations for Gate enforcement.

        Args:
            finding: Finding to validate
            pattern_id: Pattern ID for context

        Returns:
            True if valid rule basis exists, False otherwise
        """
        try:
            # Check if rule basis is present
            if not finding.rule_basis:
                self.logger.debug(f"No rule basis found for {pattern_id}")
                return False

            # Validate each citation
            valid_citations = 0
            for citation in finding.rule_basis:
                if self._is_valid_citation(citation):
                    valid_citations += 1

            if valid_citations == 0:
                self.logger.debug(f"No valid citations found for {pattern_id}")
                return False

            self.logger.debug(f"Found {valid_citations} valid citations for {pattern_id}")
            return True

        except Exception as e:
            self.logger.warning(f"Error validating rule basis for {pattern_id}: {e}")
            return False

    def _is_valid_citation(self, citation: Dict[str, Any]) -> bool:
        """
        Validate a single rule basis citation.

        A valid citation must have:
        - source: Authority source (e.g., "XBRL Specification 2.1")
        - retrieved_at: ISO 8601 timestamp
        - sha256: Content integrity hash
        - url or title: Reference location

        Args:
            citation: Citation dictionary to validate

        Returns:
            True if citation meets Gate requirements
        """
        try:
            # Required fields for Gate compliance
            required_fields = ['source', 'retrieved_at', 'sha256']

            # Check required fields exist and are non-empty
            for field in required_fields:
                if field not in citation or not citation[field]:
                    self.logger.debug(f"Citation missing required field: {field}")
                    return False

            # Check that at least url or title is present
            if not citation.get('url') and not citation.get('title'):
                self.logger.debug("Citation missing both url and title")
                return False

            # Validate sha256 format (64 hex characters)
            sha256 = citation['sha256']
            if len(sha256) != 64 or not all(c in '0123456789abcdefABCDEF' for c in sha256):
                self.logger.debug(f"Invalid sha256 format: {sha256}")
                return False

            # Basic retrieved_at format check (should be ISO 8601)
            retrieved_at = citation['retrieved_at']
            if 'T' not in retrieved_at or 'Z' not in retrieved_at:
                self.logger.debug(f"Invalid retrieved_at format: {retrieved_at}")
                return False

            return True

        except Exception as e:
            self.logger.debug(f"Error validating citation: {e}")
            return False

    def auto_discover(self, package_path: str = "cmdrvl_xew.detectors") -> None:
        """
        Auto-discover and register detectors from a package.

        Looks for modules with names matching p{NNN}_*.py and attempts
        to import and register detector classes.

        Args:
            package_path: Package path to scan for detectors
        """
        try:
            # Import the package to get its path
            package = importlib.import_module(package_path)
            package_dir = Path(package.__file__).parent

            # Look for detector modules (p001_*.py, p002_*.py, etc.)
            detector_modules = []
            for module_file in package_dir.glob("p[0-9][0-9][0-9]_*.py"):
                module_name = module_file.stem
                full_module_name = f"{package_path}.{module_name}"
                detector_modules.append(full_module_name)

            # Import modules and register detectors
            for module_name in detector_modules:
                try:
                    module = importlib.import_module(module_name)

                    # Look for detector classes (subclasses of BaseDetector)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            issubclass(attr, BaseDetector) and
                            attr != BaseDetector):
                            self.register(attr)
                            break  # Only register one detector per module

                except Exception as e:
                    self.logger.warning(f"Failed to import detector module {module_name}: {e}")

            self.logger.info(f"Auto-discovery completed, found {len(detector_modules)} detector modules")

        except Exception as e:
            self.logger.error(f"Auto-discovery failed: {e}")


# Global registry instance
_registry = DetectorRegistry()

def get_registry() -> DetectorRegistry:
    """Get the global detector registry."""
    return _registry

def register_detector(detector_class: Type[BaseDetector]) -> None:
    """Register a detector class with the global registry."""
    _registry.register(detector_class)

def run_detectors(context: DetectorContext, patterns: Set[str] = None) -> List[DetectorFinding]:
    """Run detectors using the global registry."""
    return _registry.run_detectors(context, patterns)

def run_detectors_with_priority_selection(context: DetectorContext, patterns: Set[str] = None) -> Tuple[List[DetectorFinding], Optional[DetectorFinding]]:
    """Run detectors with priority selection using the global registry."""
    return _registry.run_detectors_with_priority_selection(context, patterns)

def select_highest_priority_finding(findings: List[DetectorFinding]) -> Optional[DetectorFinding]:
    """Select highest priority finding using the global registry."""
    return _registry.select_highest_priority_finding(findings)
