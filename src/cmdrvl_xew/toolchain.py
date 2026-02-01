"""Toolchain metadata recording for reproducible Evidence Pack generation.

This module captures toolchain information (versions, config) required for
reproducible XEW findings generation per Evidence Pack contract v1.
"""

import json
import logging
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from .util import utc_now_iso

logger = logging.getLogger(__name__)


class ToolchainRecorder:
    """Records toolchain metadata for Evidence Pack reproducibility."""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._cached_versions = {}

    def record_toolchain(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record complete toolchain metadata.

        Args:
            config: Configuration settings that affect reproducibility

        Returns:
            Complete toolchain metadata dictionary
        """
        # Create expanded config that includes recording metadata and system info
        # These go in config since the toolchain object has additionalProperties=false
        expanded_config = config.copy()
        expanded_config.update({
            "recorded_at": utc_now_iso(),
            "system_info": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "architecture": platform.machine()
            }
        })

        toolchain = {
            "cmdrvl_xew_version": self._get_cmdrvl_xew_version(),
            "arelle_version": self._get_arelle_version(),
            "config": expanded_config,
        }

        # Add optional components when available
        arelle_sec_version = self._get_arelle_sec_plugin_version()
        if arelle_sec_version:
            toolchain["arelle_sec_plugin_version"] = arelle_sec_version

        dqcrt_version = self._get_dqcrt_version()
        if dqcrt_version:
            toolchain["dqcrt_version"] = dqcrt_version

        self.logger.info(f"Recorded toolchain: cmdrvl-xew {toolchain['cmdrvl_xew_version']}, "
                        f"Arelle {toolchain['arelle_version']}")

        return toolchain

    def _get_cmdrvl_xew_version(self) -> str:
        """Get cmdrvl-xew version (git SHA or semver)."""
        if "cmdrvl_xew_version" in self._cached_versions:
            return self._cached_versions["cmdrvl_xew_version"]

        try:
            # Try to get git SHA from current directory
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent.parent,  # Go to repo root
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.strip()[:12]  # Short SHA
                self._cached_versions["cmdrvl_xew_version"] = version
                return version
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
            pass

        # Fallback to 'dev' if git not available
        version = "dev"
        self._cached_versions["cmdrvl_xew_version"] = version
        return version

    def _get_arelle_version(self) -> str:
        """Get Arelle version."""
        if "arelle_version" in self._cached_versions:
            return self._cached_versions["arelle_version"]

        try:
            # Try to import arelle and get version
            import arelle
            if hasattr(arelle, '__version__'):
                version = arelle.__version__
            elif hasattr(arelle, 'Version'):
                version = getattr(arelle.Version, 'version', 'unknown')
            else:
                version = "unknown"

            self._cached_versions["arelle_version"] = version
            return version

        except ImportError:
            # Arelle not available
            version = "not_installed"
            self._cached_versions["arelle_version"] = version
            return version

    def _get_arelle_sec_plugin_version(self) -> Optional[str]:
        """Get Arelle SEC plugin version if available."""
        if "arelle_sec_plugin_version" in self._cached_versions:
            return self._cached_versions["arelle_sec_plugin_version"]

        try:
            # Try to detect SEC plugin version
            # This is a placeholder - actual implementation depends on how SEC plugin exposes version
            import arelle
            # Check for SEC-specific modules
            if hasattr(arelle, 'plugin') or hasattr(arelle, 'EdgarRenderer'):
                version = "detected"  # Placeholder
                self._cached_versions["arelle_sec_plugin_version"] = version
                return version

        except ImportError:
            pass

        self._cached_versions["arelle_sec_plugin_version"] = None
        return None

    def _get_dqcrt_version(self) -> Optional[str]:
        """Get XBRL US Data Quality Committee Rules version if available."""
        if "dqcrt_version" in self._cached_versions:
            return self._cached_versions["dqcrt_version"]

        try:
            # Try to detect DQCRT version
            import dqc
            if hasattr(dqc, '__version__'):
                version = dqc.__version__
                self._cached_versions["dqcrt_version"] = version
                return version

        except ImportError:
            pass

        self._cached_versions["dqcrt_version"] = None
        return None

    def write_toolchain_json(self, config: Dict[str, Any], output_path: Path) -> None:
        """
        Write toolchain metadata to JSON file.

        Args:
            config: Configuration settings affecting reproducibility
            output_path: Path to write toolchain.json
        """
        toolchain = self.record_toolchain(config)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with deterministic formatting
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(
                toolchain,
                f,
                indent=2,
                sort_keys=True,  # Deterministic key ordering
                ensure_ascii=False,
                separators=(',', ': ')
            )

        self.logger.info(f"Written toolchain metadata to {output_path}")


# Factory functions
def create_toolchain_recorder() -> ToolchainRecorder:
    """Create a toolchain recorder."""
    return ToolchainRecorder()


def record_toolchain_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to record toolchain metadata.

    Args:
        config: Configuration settings affecting reproducibility

    Returns:
        Complete toolchain metadata dictionary
    """
    recorder = create_toolchain_recorder()
    return recorder.record_toolchain(config)


def write_toolchain_json(config: Dict[str, Any], output_path: Path) -> None:
    """
    Convenience function to write toolchain metadata to JSON file.

    Args:
        config: Configuration settings affecting reproducibility
        output_path: Path to write toolchain.json
    """
    recorder = create_toolchain_recorder()
    recorder.write_toolchain_json(config, output_path)