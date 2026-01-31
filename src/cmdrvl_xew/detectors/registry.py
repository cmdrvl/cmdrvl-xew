"""Detector registry for XEW pattern detection."""

import logging
from typing import Dict, List, Type, Set
from pathlib import Path
import importlib
import json

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorError

logger = logging.getLogger(__name__)


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

                # Enrich findings with rule basis and issue codes
                for finding in detector_findings:
                    if not finding.rule_basis:
                        finding.rule_basis = self.get_rule_basis(pattern_id)

                findings.extend(detector_findings)
                self.logger.info(f"Detector {pattern_id} produced {len(detector_findings)} findings")

            except Exception as e:
                self.logger.error(f"Detector {pattern_id} failed: {e}")
                # In production, we might want to continue with other detectors
                # For now, re-raise to fail fast during development
                raise DetectorError(pattern_id, f"Detection failed: {e}", e)

        self.logger.info(f"All detectors completed, {len(findings)} total findings")
        return findings

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