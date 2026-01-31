"""Flatten EDGAR directory structure into Arelle-compatible flat layout.

EDGAR downloads use typed directories:
    0000034903-25-000063/
    ├── 10-Q/frt-20250930.htm           (primary iXBRL)
    ├── EX-101.SCH/frt-20250930.xsd     (extension schema)
    ├── EX-101.CAL/frt-20250930_cal.xml
    ├── EX-101.DEF/frt-20250930_def.xml
    ├── EX-101.LAB/frt-20250930_lab.xml
    └── EX-101.PRE/frt-20250930_pre.xml

But iXBRL/schema references use flat relative paths:
    <link:schemaRef xlink:href="frt-20250930.xsd"/>

This module flattens the EDGAR structure so Arelle can resolve references.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

# Namespaces for XBRL/iXBRL parsing
_XLINK_NS = "http://www.w3.org/1999/xlink"
_LINK_NS = "http://www.xbrl.org/2003/linkbase"

# EDGAR exhibit type directories and their typical file extensions
_EDGAR_EXHIBIT_DIRS = {
    "EX-101.SCH": ".xsd",
    "EX-101.CAL": "_cal.xml",
    "EX-101.DEF": "_def.xml",
    "EX-101.LAB": "_lab.xml",
    "EX-101.PRE": "_pre.xml",
}

# Form type directories (where the primary iXBRL lives)
_FORM_DIRS = {"10-Q", "10-K", "10-K/A", "10-Q/A", "20-F", "6-K", "8-K", "8-K/A"}


def _find_primary_ixbrl(edgar_dir: Path) -> Path | None:
    """Find the primary iXBRL HTML in an EDGAR directory.

    Looks in form-type subdirectories (10-Q/, 10-K/, etc.) for .htm/.html files.
    Returns the first match (typically there's only one primary document).
    """
    for form_dir in _FORM_DIRS:
        form_path = edgar_dir / form_dir
        if form_path.is_dir():
            for f in form_path.iterdir():
                if f.is_file() and f.suffix.lower() in (".htm", ".html"):
                    # Skip exhibit files (e.g., ex31-1.htm)
                    if not f.name.lower().startswith("ex"):
                        return f
    return None


def _extract_schema_ref(ixbrl_path: Path) -> str | None:
    """Extract the schemaRef href from an iXBRL document.

    Looks for patterns like:
        <link:schemaRef xlink:href="foo-20250930.xsd"/>

    Returns the href value (e.g., "foo-20250930.xsd") or None if not found.

    Uses regex rather than XML parsing because real iXBRL files often have
    encoding issues or garbage bytes that break strict XML parsers.
    """
    # The schemaRef is typically in the first ~50KB of the file (in ix:header).
    # Read a chunk to avoid loading multi-MB files fully.
    try:
        content = ixbrl_path.read_bytes()[:64 * 1024].decode("utf-8", errors="ignore")
    except Exception:
        return None

    # Match <link:schemaRef ... xlink:href="..." /> or <schemaRef ... href="..." />
    # The href attribute may come before or after xlink:type
    pattern = r'<(?:link:)?schemaRef[^>]*?(?:xlink:)?href\s*=\s*["\']([^"\']+)["\']'
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def _find_extension_files(edgar_dir: Path, schema_basename: str) -> dict[str, Path]:
    """Find extension schema and linkbase files in EDGAR exhibit directories.

    Args:
        edgar_dir: EDGAR accession directory
        schema_basename: Base name from schemaRef (e.g., "frt-20250930")

    Returns:
        Dict mapping target filename to source path.
        E.g., {"frt-20250930.xsd": Path("EX-101.SCH/frt-20250930.xsd")}
    """
    found: dict[str, Path] = {}

    for exhibit_dir, suffix in _EDGAR_EXHIBIT_DIRS.items():
        exhibit_path = edgar_dir / exhibit_dir
        if not exhibit_path.is_dir():
            continue

        # Look for files matching the schema basename
        for f in exhibit_path.iterdir():
            if not f.is_file():
                continue
            # Match by basename pattern (schema_basename + expected suffix)
            if suffix == ".xsd":
                if f.name == f"{schema_basename}.xsd":
                    found[f.name] = f
            else:
                # Linkbases: schema_basename + _cal.xml, _def.xml, etc.
                expected_name = f"{schema_basename}{suffix}"
                if f.name == expected_name:
                    found[f.name] = f

    return found


def _find_all_extension_files_by_scan(edgar_dir: Path) -> dict[str, Path]:
    """Fallback: scan all EX-101.* directories for any XBRL files.

    Used when we can't determine the schema basename from the iXBRL.
    """
    found: dict[str, Path] = {}

    for exhibit_dir in _EDGAR_EXHIBIT_DIRS:
        exhibit_path = edgar_dir / exhibit_dir
        if not exhibit_path.is_dir():
            continue

        for f in exhibit_path.iterdir():
            if f.is_file() and f.suffix.lower() in (".xsd", ".xml"):
                found[f.name] = f

    return found


def run_flatten(args: argparse.Namespace) -> int:
    """Flatten an EDGAR directory into a flat Arelle-compatible layout."""
    edgar_dir = Path(args.edgar_dir)
    out_dir = Path(args.out)

    if not edgar_dir.is_dir():
        raise SystemExit(f"EDGAR directory not found: {edgar_dir}")

    if out_dir.exists():
        if not out_dir.is_dir():
            raise SystemExit(f"Output path exists and is not a directory: {out_dir}")
        if any(out_dir.iterdir()) and not args.force:
            raise SystemExit(f"Output directory not empty (use --force to overwrite): {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Find primary iXBRL
    primary = _find_primary_ixbrl(edgar_dir)
    if primary is None:
        raise SystemExit(f"No primary iXBRL found in {edgar_dir} (looked in {_FORM_DIRS})")

    print(f"Primary iXBRL: {primary.relative_to(edgar_dir)}")

    # Step 2: Extract schemaRef to determine extension basename
    schema_ref = _extract_schema_ref(primary)
    if schema_ref:
        # Strip path and extension to get basename (e.g., "frt-20250930")
        schema_basename = Path(schema_ref).stem
        print(f"Schema reference: {schema_ref} (basename: {schema_basename})")
        extension_files = _find_extension_files(edgar_dir, schema_basename)
    else:
        print("Warning: Could not extract schemaRef; scanning all EX-101.* directories")
        extension_files = _find_all_extension_files_by_scan(edgar_dir)

    # Step 3: Copy files to flat output directory
    copied = []

    # Copy primary iXBRL
    primary_dst = out_dir / primary.name
    shutil.copyfile(primary, primary_dst)
    copied.append(primary.name)

    # Copy extension files
    for filename, src_path in extension_files.items():
        dst_path = out_dir / filename
        shutil.copyfile(src_path, dst_path)
        copied.append(filename)

    print(f"Copied {len(copied)} files to {out_dir}:")
    for name in sorted(copied):
        print(f"  {name}")

    # Step 4: Warn about missing expected files
    if schema_ref:
        expected_schema = f"{schema_basename}.xsd"
        if expected_schema not in extension_files:
            print(f"Warning: Extension schema not found: {expected_schema}")

        expected_linkbases = [
            f"{schema_basename}_cal.xml",
            f"{schema_basename}_def.xml",
            f"{schema_basename}_lab.xml",
            f"{schema_basename}_pre.xml",
        ]
        missing = [f for f in expected_linkbases if f not in extension_files]
        if missing:
            print(f"Warning: Expected linkbases not found: {missing}")

    return 0
