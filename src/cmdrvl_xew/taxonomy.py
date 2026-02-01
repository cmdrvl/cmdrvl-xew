"""Taxonomy resolution policy for deterministic XBRL processing.

Defines how XEW resolves taxonomy references to ensure reproducible validation
and Evidence Pack generation across environments.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from .util import sha256_file, utc_now_iso, _ensure_ascii


class ResolutionMode(Enum):
    """Taxonomy resolution strategy for reproducible processing."""

    OFFLINE_ONLY = "offline_only"
    """Use only local/pinned taxonomy packages. Fail if not available locally."""

    OFFLINE_PREFERRED = "offline_preferred"
    """Prefer local packages, fall back to online if needed (default)."""

    ONLINE_ONLY = "online_only"
    """Always resolve from official online sources (for testing/validation)."""

    HYBRID = "hybrid"
    """Use local for standard taxonomies, online for extension schemas."""


@dataclass(frozen=True)
class TaxonomyPackage:
    """Pinned taxonomy package with deterministic metadata."""

    name: str  # e.g., "us-gaap", "dei", "ifrs"
    version: str  # e.g., "2025-01-31"
    namespace_uri: str  # Primary namespace URI
    entry_point: str  # Main schema file path
    local_path: Optional[Path] = None  # Local package location
    official_url: Optional[str] = None  # Official download URL
    sha256: Optional[str] = None  # Package integrity hash
    retrieved_at: Optional[str] = None  # ISO 8601 retrieval timestamp

    def __post_init__(self):
        """Validate package metadata."""
        _ensure_ascii(self.name, "taxonomy package name")
        _ensure_ascii(self.version, "taxonomy package version")
        _ensure_ascii(self.namespace_uri, "namespace URI")


@dataclass(frozen=True)
class NonRedistributableReference:
    """Reference to external bytes that cannot be bundled in the pack."""

    source_url: str
    retrieved_at: str
    sha256: str
    content_type: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self):
        _ensure_ascii(self.source_url, "source URL")
        _ensure_ascii(self.retrieved_at, "retrieved_at")
        _ensure_ascii(self.sha256, "sha256")
        if self.content_type:
            _ensure_ascii(self.content_type, "content type")
        if self.notes:
            _ensure_ascii(self.notes, "notes")

    def to_metadata(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "sha256": self.sha256,
        }
        if self.content_type:
            data["content_type"] = self.content_type
        if self.notes:
            data["notes"] = self.notes
        return data


@dataclass
class TaxonomyResolutionConfig:
    """Configuration for deterministic taxonomy resolution."""

    resolution_mode: ResolutionMode = ResolutionMode.OFFLINE_PREFERRED

    # Package registry (pinned taxonomy packages)
    packages: Dict[str, TaxonomyPackage] = field(default_factory=dict)

    # Cache settings
    cache_directory: Optional[Path] = None
    enable_cache: bool = True

    # Network settings
    timeout_seconds: int = 30
    user_agent: str = "cmdrvl-xew/1.0 (XBRL Early Warning)"

    # Validation settings
    validate_packages: bool = True
    enforce_signatures: bool = False  # Future: cryptographic signatures

    def add_standard_packages(self) -> None:
        """Add commonly used standard taxonomy packages."""

        # US GAAP 2025
        self.packages["us-gaap-2025"] = TaxonomyPackage(
            name="us-gaap",
            version="2025-01-31",
            namespace_uri="http://fasb.org/us-gaap/2025-01-31",
            entry_point="elts/us-gaap-2025-01-31.xsd",
            official_url="https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-2025-01-31.zip"
        )

        # DEI (Document Entity Information) 2025
        self.packages["dei-2025"] = TaxonomyPackage(
            name="dei",
            version="2025-01-31",
            namespace_uri="http://xbrl.sec.gov/dei/2025-01-31",
            entry_point="dei-2025-01-31.xsd",
            official_url="https://xbrl.sec.gov/dei/2025/dei-2025-01-31.zip"
        )

        # SEC Country codes
        self.packages["country-2025"] = TaxonomyPackage(
            name="country",
            version="2025-01-31",
            namespace_uri="http://xbrl.sec.gov/country/2025-01-31",
            entry_point="country-2025-01-31.xsd",
            official_url="https://xbrl.sec.gov/country/2025/country-2025-01-31.zip"
        )

        # SEC Currency codes
        self.packages["currency-2025"] = TaxonomyPackage(
            name="currency",
            version="2025-01-31",
            namespace_uri="http://xbrl.sec.gov/currency/2025-01-31",
            entry_point="currency-2025-01-31.xsd",
            official_url="https://xbrl.sec.gov/currency/2025/currency-2025-01-31.zip"
        )


@dataclass
class TaxonomyResolutionResult:
    """Result of taxonomy resolution with metadata for toolchain recording."""

    resolved_packages: List[TaxonomyPackage]
    resolution_mode_used: ResolutionMode
    resolution_timestamp: str
    cache_hits: int = 0
    network_requests: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    non_redistributable_references: List[NonRedistributableReference] = field(default_factory=list)

    # Arelle integration metadata
    arelle_plugin_config: Optional[Dict[str, Any]] = None
    validation_settings: Optional[Dict[str, Any]] = None

    def to_toolchain_metadata(self) -> Dict[str, Any]:
        """Generate metadata for toolchain.json recording."""
        return {
            "taxonomy_resolution": {
                "mode": self.resolution_mode_used.value,
                "timestamp": self.resolution_timestamp,
                "packages_resolved": [
                    {
                        "name": pkg.name,
                        "version": pkg.version,
                        "namespace_uri": pkg.namespace_uri,
                        "sha256": pkg.sha256,
                        "source": "local" if pkg.local_path else "remote"
                    }
                    for pkg in self.resolved_packages
                ],
                "cache_performance": {
                    "cache_hits": self.cache_hits,
                    "network_requests": self.network_requests
                },
                "validation_config": self.validation_settings or {}
            },
            "non_redistributable_references": [
                ref.to_metadata() for ref in self.non_redistributable_references
            ],
        }


class TaxonomyResolver:
    """Deterministic taxonomy resolver for reproducible XBRL processing."""

    def __init__(self, config: TaxonomyResolutionConfig):
        self.config = config

    def resolve_for_filing(
        self,
        required_namespaces: List[str],
        schema_refs: Optional[List[str]] = None
    ) -> TaxonomyResolutionResult:
        """Resolve taxonomies needed for a specific filing.

        Args:
            required_namespaces: Namespace URIs found in the filing
            schema_refs: Schema reference hrefs from the filing

        Returns:
            TaxonomyResolutionResult with resolved packages and metadata
        """
        result = TaxonomyResolutionResult(
            resolved_packages=[],
            resolution_mode_used=self.config.resolution_mode,
            resolution_timestamp=utc_now_iso()
        )

        # Resolve each required namespace
        for namespace in required_namespaces:
            package = self._resolve_namespace(namespace, result)
            if package:
                result.resolved_packages.append(package)
            else:
                result.errors.append(f"Could not resolve namespace: {namespace}")

        # Remove duplicates while preserving order
        seen = set()
        unique_packages = []
        for pkg in result.resolved_packages:
            pkg_key = (pkg.name, pkg.version, pkg.namespace_uri)
            if pkg_key not in seen:
                seen.add(pkg_key)
                unique_packages.append(pkg)
        result.resolved_packages = unique_packages

        return result

    def _resolve_namespace(self, namespace_uri: str, result: TaxonomyResolutionResult) -> Optional[TaxonomyPackage]:
        """Resolve a single namespace URI to a taxonomy package."""

        # Check pinned packages first
        for package in self.config.packages.values():
            if package.namespace_uri == namespace_uri:
                if self._validate_package_availability(package, result):
                    return package

        # Handle resolution based on mode
        if self.config.resolution_mode == ResolutionMode.OFFLINE_ONLY:
            result.errors.append(f"Namespace {namespace_uri} not found in pinned packages (offline-only mode)")
            return None

        # For other modes, could implement dynamic resolution here
        # For now, warn about unknown namespaces
        result.warnings.append(f"No pinned package for namespace: {namespace_uri}")

        return None

    def _validate_package_availability(self, package: TaxonomyPackage, result: TaxonomyResolutionResult) -> bool:
        """Check if a taxonomy package is available and valid."""

        # Check local availability
        if package.local_path and package.local_path.exists():
            if self.config.validate_packages and package.sha256:
                # Validate integrity if hash is available
                actual_hash, _ = sha256_file(package.local_path)
                if actual_hash != package.sha256:
                    result.errors.append(f"Package {package.name} integrity check failed")
                    return False

            result.cache_hits += 1
            return True

        # Handle online resolution if allowed
        if self.config.resolution_mode in (ResolutionMode.OFFLINE_PREFERRED, ResolutionMode.ONLINE_ONLY, ResolutionMode.HYBRID):
            if package.official_url:
                result.warnings.append(f"Package {package.name} would require network download (not implemented)")
                result.network_requests += 1
                # TODO: Implement actual download logic
                return False

        return False

    def get_arelle_config(self, resolution_result: TaxonomyResolutionResult) -> Dict[str, Any]:
        """Generate Arelle configuration from resolution result."""

        # Package locations for Arelle
        package_mappings = {}
        for package in resolution_result.resolved_packages:
            if package.local_path:
                package_mappings[package.namespace_uri] = str(package.local_path)

        config = {
            "taxonomy_package_mappings": package_mappings,
            "offline_mode": self.config.resolution_mode == ResolutionMode.OFFLINE_ONLY,
            "validate_packages": self.config.validate_packages,
            "user_agent": self.config.user_agent,
            "timeout": self.config.timeout_seconds
        }

        # Store for toolchain metadata
        resolution_result.arelle_plugin_config = config

        return config


# Default configuration factory
def create_default_resolver() -> TaxonomyResolver:
    """Create a taxonomy resolver with standard configuration."""
    config = TaxonomyResolutionConfig()
    config.add_standard_packages()
    return TaxonomyResolver(config)


# Utility functions for toolchain integration
def record_taxonomy_metadata(resolution_result: TaxonomyResolutionResult) -> Dict[str, Any]:
    """Record taxonomy resolution metadata for Evidence Pack toolchain.json."""
    return resolution_result.to_toolchain_metadata()


def non_redistributable_reference_from_bytes(
    source_url: str,
    content_bytes: bytes,
    *,
    retrieved_at: Optional[str] = None,
    content_type: Optional[str] = None,
    notes: Optional[str] = None,
) -> NonRedistributableReference:
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    return NonRedistributableReference(
        source_url=source_url,
        retrieved_at=retrieved_at or utc_now_iso(),
        sha256=sha256,
        content_type=content_type,
        notes=notes,
    )


def non_redistributable_reference_from_path(
    source_url: str,
    path: Path,
    *,
    retrieved_at: Optional[str] = None,
    content_type: Optional[str] = None,
    notes: Optional[str] = None,
) -> NonRedistributableReference:
    sha256, _ = sha256_file(path)
    return NonRedistributableReference(
        source_url=source_url,
        retrieved_at=retrieved_at or utc_now_iso(),
        sha256=sha256,
        content_type=content_type,
        notes=notes,
    )


def validate_namespace_consistency(schema_refs: List[str], facts_namespaces: List[str]) -> List[str]:
    """Validate that schema references match namespaces used in facts.

    Returns list of inconsistency warnings for XEW-P005 detection.
    """
    issues = []

    # This would be used by P005 detector to check for namespace/schemaRef mismatches
    # Implementation depends on actual schema parsing, which happens in Arelle integration

    return issues
