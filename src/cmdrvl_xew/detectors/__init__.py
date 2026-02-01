"""XEW Pattern Detection Framework.

This package provides the infrastructure for implementing and running
XBRL Early Warning (XEW) pattern detectors.

Usage:
    from cmdrvl_xew.detectors import BaseDetector, register_detector, run_detectors

    class MyDetector(BaseDetector):
        @property
        def pattern_id(self) -> str:
            return "XEW-P001"

        def detect(self, context):
            # Implementation here
            pass

    register_detector(MyDetector)
"""

# Core interfaces
from ._base import (
    BaseDetector,
    DetectorContext,
    DetectorFinding,
    DetectorInstance,
    DetectorError,
)

# Registry functionality
from .registry import (
    DetectorRegistry,
    get_registry,
    register_detector,
    run_detectors,
)

__all__ = [
    # Base classes and data structures
    'BaseDetector',
    'DetectorContext',
    'DetectorFinding',
    'DetectorInstance',
    'DetectorError',

    # Registry and execution
    'DetectorRegistry',
    'get_registry',
    'register_detector',
    'run_detectors',
]

# Version info
__version__ = "0.1.0"

# Auto-discover detectors when package is imported
def _auto_discover_detectors():
    """Auto-discover detector modules in this package."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        registry = get_registry()
        registry.auto_discover(__name__)
        logger.debug("Detector auto-discovery completed")
    except Exception as e:
        # Don't fail package import if auto-discovery fails
        logger.warning(f"Detector auto-discovery failed: {e}")

# Auto-discover detector modules
_auto_discover_detectors()