"""Base detector interface and shared utilities for XEW pattern detection."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class DetectorInstance:
    """Represents a single detected instance within a finding."""
    instance_id: str  # sha256 of canonical signature
    kind: str  # instance type (duplicate_fact_set, extension_anchoring_issue, etc.)
    primary: bool  # whether this is the primary representative instance
    data: Dict[str, Any]  # instance-specific data


@dataclass
class DetectorFinding:
    """Represents a complete finding from a detector."""
    finding_id: str  # XEW-F-<accession>-<pattern_id>
    pattern_id: str  # XEW-P001, XEW-P002, etc.
    pattern_name: str
    alert_eligible: bool
    status: str  # "detected", "suppressed"
    suppression_reason: Optional[str] = None
    human_review_required: bool = True
    break_triggers: List[Dict[str, str]] = None  # List of {id, summary}
    rule_basis: List[Dict[str, Any]] = None  # Rule basis citations
    instances: List[DetectorInstance] = None
    mechanism: str = ""  # Technical explanation
    why_not_fatal_yet: str = ""  # Risk context

    def __post_init__(self):
        if self.break_triggers is None:
            self.break_triggers = []
        if self.rule_basis is None:
            self.rule_basis = []
        if self.instances is None:
            self.instances = []


@dataclass
class DetectorContext:
    """Context passed to detectors during execution."""
    primary_document_path: str
    artifacts_dir: str
    cik: str
    accession: str
    form: str
    filed_date: str
    xbrl_model: Any  # Arelle model object
    config: Dict[str, Any]  # Configuration parameters


class BaseDetector(ABC):
    """Abstract base class for XEW pattern detectors."""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    @abstractmethod
    def pattern_id(self) -> str:
        """Return the pattern ID (e.g., 'XEW-P001')."""
        pass

    @property
    @abstractmethod
    def pattern_name(self) -> str:
        """Return the human-readable pattern name."""
        pass

    @property
    @abstractmethod
    def alert_eligible(self) -> bool:
        """Return whether this pattern generates alert-eligible findings."""
        pass

    @abstractmethod
    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        """
        Execute detection logic and return findings.

        Args:
            context: Detection context with XBRL model and metadata

        Returns:
            List of findings (may be empty if no issues detected)
        """
        pass

    def should_run(self, context: DetectorContext) -> bool:
        """
        Determine if this detector should run for the given context.

        Default implementation always returns True.
        Override for form-specific or conditional detection.
        """
        return True

    def compute_canonical_signature(self, **kwargs) -> str:
        """
        Compute canonical signature for instance ID generation.

        This should be implemented by each detector to create deterministic
        instance IDs based on the pattern-specific signature elements.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement compute_canonical_signature")

    def generate_finding_id(self, context: DetectorContext) -> str:
        """Generate finding ID in format XEW-F-<accession>-<pattern_id>."""
        return f"XEW-F-{context.accession}-{self.pattern_id}"

    def load_rule_basis(self) -> List[Dict[str, Any]]:
        """
        Load rule basis citations for this pattern.

        Default implementation returns empty list.
        Override to load from rule basis map.
        """
        return []

    def get_break_triggers(self) -> List[Dict[str, str]]:
        """
        Get applicable break triggers for this pattern.

        Default implementation returns empty list.
        Override to specify pattern-specific break triggers.
        """
        return []


class DetectorError(Exception):
    """Exception raised during detector execution."""

    def __init__(self, detector_name: str, message: str, cause: Exception = None):
        self.detector_name = detector_name
        self.message = message
        self.cause = cause
        super().__init__(f"Detector {detector_name}: {message}")