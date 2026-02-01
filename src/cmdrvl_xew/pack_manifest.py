"""Pack manifest writer for Evidence Pack integrity verification.

This module generates pack_manifest.json with deterministic ordering and
tamper-evident SHA256 hashing per the Evidence Pack contract v1.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from .util import sha256_file, utc_now_iso

logger = logging.getLogger(__name__)


class PackManifestError(Exception):
    """Exception raised during pack manifest generation."""
    pass


class PackManifestBuilder:
    """Builder for pack_manifest.json with deterministic ordering."""

    def __init__(self, pack_id: str):
        self.pack_id = pack_id
        self.files: List[Dict[str, Any]] = []
        self.retrieved_at: Optional[str] = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def set_retrieval_time(self, retrieved_at: str) -> None:
        """Set the ISO 8601 timestamp for when artifacts were retrieved."""
        self.retrieved_at = retrieved_at

    def add_file(self,
                path: str,
                role: str,
                file_path: Path,
                source_url: Optional[str] = None) -> None:
        """
        Add a file to the pack manifest.

        Args:
            path: Pack-relative path (e.g., 'artifacts/primary.html')
            role: File role ('xew_output', 'edgar_artifact', 'taxonomy_input', 'toolchain')
            file_path: Actual filesystem path to compute hash
            source_url: Source URL for fetched files
        """
        if not file_path.exists():
            raise PackManifestError(f"File not found: {file_path}")

        # Compute file hash and size
        sha256_hash, file_size = sha256_file(file_path)

        file_entry = {
            "path": path,
            "sha256": sha256_hash,
            "bytes": file_size,
            "role": role
        }

        # Add source URL for fetched artifacts
        if source_url:
            file_entry["source_url"] = source_url

        self.files.append(file_entry)
        self.logger.debug(f"Added file to manifest: {path} ({role}, {file_size} bytes)")

    def add_xew_output(self, path: str, file_path: Path) -> None:
        """Add an XEW output file (e.g., xew_findings.json)."""
        self.add_file(path, "xew_output", file_path)

    def add_edgar_artifact(self, path: str, file_path: Path, source_url: str) -> None:
        """Add an EDGAR artifact file."""
        self.add_file(path, "edgar_artifact", file_path, source_url)

    def add_toolchain_file(self, path: str, file_path: Path) -> None:
        """Add a toolchain file (e.g., toolchain.json)."""
        self.add_file(path, "toolchain", file_path)

    def build_manifest(self) -> Dict[str, Any]:
        """
        Build the complete pack manifest.

        Returns:
            Dictionary containing the pack manifest data
        """
        if not self.retrieved_at:
            self.retrieved_at = utc_now_iso()

        # Sort files deterministically by path
        sorted_files = sorted(self.files, key=lambda f: f["path"])

        # Compute pack integrity hash
        pack_sha256 = self._compute_pack_integrity_hash(sorted_files)

        manifest = {
            "pack_id": self.pack_id,
            "retrieved_at": self.retrieved_at,
            "pack_sha256": pack_sha256,
            "files": sorted_files
        }

        self.logger.info(f"Built manifest for pack {self.pack_id} with {len(sorted_files)} files")
        return manifest

    def _compute_pack_integrity_hash(self, sorted_files: List[Dict[str, Any]]) -> str:
        """
        Compute pack integrity hash per Evidence Pack contract v1.

        Algorithm:
        1. Build entries as "<path>\\t<sha256>\\n" strings
        2. Sort by path (already sorted)
        3. Concatenate and SHA256 hash
        """
        entries = []
        for file_entry in sorted_files:
            # Skip pack_manifest.json itself to avoid self-referential hashing
            if file_entry["path"] == "pack_manifest.json":
                continue

            entry = f"{file_entry['path']}\t{file_entry['sha256']}\n"
            entries.append(entry)

        # Concatenate all entries
        manifest_content = ''.join(entries)

        # Compute SHA256
        pack_hash = hashlib.sha256(manifest_content.encode('utf-8')).hexdigest()

        self.logger.debug(f"Computed pack integrity hash: {pack_hash}")
        return pack_hash

    def write_manifest(self, output_path: Path) -> None:
        """
        Write the pack manifest to JSON file.

        Args:
            output_path: Path to write pack_manifest.json
        """
        manifest = self.build_manifest()

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with deterministic formatting
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(
                manifest,
                f,
                indent=2,
                sort_keys=True,  # Deterministic key ordering
                ensure_ascii=False,
                separators=(',', ': ')
            )

        self.logger.info(f"Written pack manifest to {output_path}")


# Factory functions for convenience
def create_pack_manifest_builder(pack_id: str) -> PackManifestBuilder:
    """Create a pack manifest builder for the specified pack ID."""
    return PackManifestBuilder(pack_id)


def build_pack_manifest(pack_id: str,
                       file_specs: List[Dict[str, Any]],
                       retrieved_at: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to build a pack manifest from file specifications.

    Args:
        pack_id: Unique pack identifier
        file_specs: List of file specifications with 'path', 'file_path', 'role', optional 'source_url'
        retrieved_at: Optional retrieval timestamp (defaults to current time)

    Returns:
        Complete pack manifest dictionary

    Example:
        file_specs = [
            {'path': 'xew_findings.json', 'file_path': Path('/tmp/findings.json'), 'role': 'xew_output'},
            {'path': 'artifacts/primary.html', 'file_path': Path('/tmp/primary.html'), 'role': 'edgar_artifact', 'source_url': 'https://...'}
        ]
    """
    builder = create_pack_manifest_builder(pack_id)

    if retrieved_at:
        builder.set_retrieval_time(retrieved_at)

    for spec in file_specs:
        builder.add_file(
            spec['path'],
            spec['role'],
            spec['file_path'],
            spec.get('source_url')
        )

    return builder.build_manifest()


def write_pack_manifest(pack_id: str,
                       file_specs: List[Dict[str, Any]],
                       output_path: Path,
                       retrieved_at: Optional[str] = None) -> None:
    """
    Convenience function to build and write a pack manifest.

    Args:
        pack_id: Unique pack identifier
        file_specs: List of file specifications
        output_path: Path to write pack_manifest.json
        retrieved_at: Optional retrieval timestamp
    """
    builder = create_pack_manifest_builder(pack_id)

    if retrieved_at:
        builder.set_retrieval_time(retrieved_at)

    for spec in file_specs:
        builder.add_file(
            spec['path'],
            spec['role'],
            spec['file_path'],
            spec.get('source_url')
        )

    builder.write_manifest(output_path)