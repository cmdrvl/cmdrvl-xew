from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Dict, Any

from .util import sha256_file

_SCHEMA_REF_RE = re.compile(
    r'<(?:link:)?schemaRef\b[^>]*?(?:xlink:)?href\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_LINKBASE_REF_RE = re.compile(
    r'<(?:link:)?linkbaseRef\b[^>]*?(?:xlink:)?href\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class ArtifactCollectionError(Exception):
    pass


@dataclass(frozen=True)
class ArtifactHash:
    path: str
    role: str
    sha256: str
    bytes: int


def collect_artifacts(primary_path: Path, *, root_dir: Path | None = None) -> list[ArtifactHash]:
    """Collect primary iXBRL + referenced schema/linkbase artifacts and hash them.

    The returned list is ordered deterministically by pack-relative path.
    """
    primary_path = primary_path.resolve()
    if not primary_path.is_file():
        raise ArtifactCollectionError(f"Primary artifact not found: {primary_path}")

    root_dir = (root_dir or primary_path.parent).resolve()

    schema_refs = _extract_schema_refs(primary_path)
    if not schema_refs:
        raise ArtifactCollectionError("No schemaRef hrefs found in primary iXBRL")

    linkbase_refs = _extract_linkbase_refs(primary_path)

    artifacts: dict[str, tuple[Path, str]] = {}
    _add_artifact(artifacts, root_dir, primary_path, role="primary_ixbrl")

    errors: list[str] = []
    schema_paths: list[Path] = []

    for href in schema_refs:
        resolved, reason = _resolve_href(href, base_dir=primary_path.parent, root_dir=root_dir)
        if resolved is None:
            if reason == "external":
                # External taxonomy references are not local artifacts; skip for now.
                continue
            errors.append(f"unsupported schemaRef ({reason}): {href}")
            continue
        if not resolved.is_file():
            errors.append(f"missing schemaRef file: {href}")
            continue
        schema_paths.append(resolved)
        _add_artifact(artifacts, root_dir, resolved, role="edgar_artifact")

    for href in linkbase_refs:
        resolved, reason = _resolve_href(href, base_dir=primary_path.parent, root_dir=root_dir)
        if resolved is None:
            if reason == "external":
                # External taxonomy references are not local artifacts; skip for now.
                continue
            errors.append(f"unsupported linkbaseRef ({reason}): {href}")
            continue
        if not resolved.is_file():
            errors.append(f"missing linkbaseRef file: {href}")
            continue
        _add_artifact(artifacts, root_dir, resolved, role="edgar_artifact")

    for schema_path in schema_paths:
        for href in _extract_linkbase_refs(schema_path):
            resolved, reason = _resolve_href(href, base_dir=schema_path.parent, root_dir=root_dir)
            if resolved is None:
                if reason == "external":
                    # External taxonomy references are not local artifacts; skip for now.
                    continue
                errors.append(f"unsupported linkbaseRef ({reason}): {href}")
                continue
            if not resolved.is_file():
                errors.append(f"missing linkbaseRef file: {href}")
                continue
            _add_artifact(artifacts, root_dir, resolved, role="edgar_artifact")

    if errors:
        detail = "\\n".join(f"- {e}" for e in errors)
        raise ArtifactCollectionError(f"Artifact collection failed:\\n{detail}")

    hashed: list[ArtifactHash] = []
    for rel_path in sorted(artifacts):
        abs_path, role = artifacts[rel_path]
        sha, nbytes = sha256_file(abs_path)
        hashed.append(ArtifactHash(path=rel_path, role=role, sha256=sha, bytes=nbytes))

    return hashed


def _add_artifact(artifacts: dict[str, tuple[Path, str]], root_dir: Path, path: Path, *, role: str) -> None:
    rel = _relpath(root_dir, path)
    existing = artifacts.get(rel)
    if existing:
        _existing_path, existing_role = existing
        if existing_role == "primary_ixbrl" or role != "primary_ixbrl":
            return
    artifacts[rel] = (path, role)


def _relpath(root_dir: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(root_dir)
    except ValueError:
        raise ArtifactCollectionError(f"Referenced path escapes root: {path}")
    return rel.as_posix()


def _extract_schema_refs(path: Path) -> list[str]:
    text = _read_text(path)
    return _SCHEMA_REF_RE.findall(text)


def _extract_linkbase_refs(path: Path) -> list[str]:
    text = _read_text(path)
    return _LINKBASE_REF_RE.findall(text)


def extract_schema_refs(path: Path) -> list[str]:
    """Public helper to extract schemaRef hrefs from an artifact."""
    return _extract_schema_refs(path)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _resolve_href(href: str, *, base_dir: Path, root_dir: Path) -> tuple[Path | None, str]:
    href = href.strip()
    if not href:
        return None, "empty"
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None, "external"
    if not parsed.path:
        return None, "empty"
    ref_path = Path(parsed.path)
    if ref_path.is_absolute():
        return None, "absolute"
    resolved = (base_dir / ref_path).resolve()
    _relpath(root_dir, resolved)
    return resolved, "ok"


# Evidence Pack directory layout functions
def compute_pack_layout(pack_id: str) -> Dict[str, str]:
    """
    Compute Evidence Pack directory layout paths.

    Args:
        pack_id: Unique pack identifier

    Returns:
        Dictionary mapping component names to relative paths
    """
    return {
        "pack_root": f"XEW-EP-{pack_id}",
        "artifacts_dir": "artifacts",
        "toolchain_dir": "toolchain",
        "manifest_file": "pack_manifest.json",
        "findings_file": "xew_findings.json",
        "toolchain_file": "toolchain/toolchain.json"
    }


def generate_artifact_path(original_path: Path, role: str) -> str:
    """
    Generate stable pack-relative path for an artifact.

    Args:
        original_path: Original file path
        role: Artifact role ('primary_ixbrl', 'edgar_artifact', etc.)

    Returns:
        Pack-relative path string
    """
    # Preserve original filename, place in artifacts/ directory
    filename = original_path.name

    # Add role prefix for non-primary files to avoid collisions
    if role == "primary_ixbrl":
        return f"artifacts/{filename}"
    elif role == "edgar_artifact":
        return f"artifacts/{filename}"
    elif role == "taxonomy_input":
        return f"artifacts/taxonomy/{filename}"
    else:
        # Generic artifacts
        return f"artifacts/{role}/{filename}"


def create_pack_directory_structure(pack_dir: Path, layout: Optional[Dict[str, str]] = None) -> Dict[str, Path]:
    """
    Create Evidence Pack directory structure.

    Args:
        pack_dir: Base pack directory path
        layout: Optional layout specification (defaults to standard layout)

    Returns:
        Dictionary mapping component names to absolute paths
    """
    if layout is None:
        layout = compute_pack_layout("default")

    # Create directories
    artifacts_dir = pack_dir / layout["artifacts_dir"]
    toolchain_dir = pack_dir / layout["toolchain_dir"]

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    toolchain_dir.mkdir(parents=True, exist_ok=True)

    # Return absolute paths for all components
    return {
        "pack_root": pack_dir,
        "artifacts_dir": artifacts_dir,
        "toolchain_dir": toolchain_dir,
        "manifest_path": pack_dir / layout["manifest_file"],
        "findings_path": pack_dir / layout["findings_file"],
        "toolchain_path": pack_dir / layout["toolchain_file"]
    }


def validate_pack_structure(pack_dir: Path) -> Dict[str, Any]:
    """
    Validate Evidence Pack directory structure.

    Args:
        pack_dir: Pack directory path

    Returns:
        Validation result with status and any issues
    """
    issues = []

    # Check required directories
    artifacts_dir = pack_dir / "artifacts"
    toolchain_dir = pack_dir / "toolchain"

    if not artifacts_dir.exists():
        issues.append("Missing artifacts/ directory")
    elif not artifacts_dir.is_dir():
        issues.append("artifacts/ is not a directory")

    if not toolchain_dir.exists():
        issues.append("Missing toolchain/ directory")
    elif not toolchain_dir.is_dir():
        issues.append("toolchain/ is not a directory")

    # Check required files
    manifest_file = pack_dir / "pack_manifest.json"
    findings_file = pack_dir / "xew_findings.json"
    toolchain_file = pack_dir / "toolchain" / "toolchain.json"

    if not manifest_file.exists():
        issues.append("Missing pack_manifest.json")
    elif not manifest_file.is_file():
        issues.append("pack_manifest.json is not a file")

    if not findings_file.exists():
        issues.append("Missing xew_findings.json")
    elif not findings_file.is_file():
        issues.append("xew_findings.json is not a file")

    if not toolchain_file.exists():
        issues.append("Missing toolchain/toolchain.json")
    elif not toolchain_file.is_file():
        issues.append("toolchain/toolchain.json is not a file")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "checked_paths": {
            "artifacts_dir": str(artifacts_dir),
            "toolchain_dir": str(toolchain_dir),
            "manifest_file": str(manifest_file),
            "findings_file": str(findings_file),
            "toolchain_file": str(toolchain_file)
        }
    }
