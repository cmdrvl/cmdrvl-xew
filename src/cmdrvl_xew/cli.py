from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .exit_codes import ExitCode
from .fetch import run_fetch
from .flatten import run_flatten
from .pack import run_pack
from .verify import run_verify_pack


def validate_pack_args(args: argparse.Namespace) -> list[str]:
    """
    Validate and normalize pack command arguments.

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    accession_pattern = re.compile(r"^\d{10}-\d{2}-\d{6}$")

    # Validate and normalize CIK (must be 10 digits, zero-padded)
    try:
        cik = args.cik.strip()
        if not cik.isdigit():
            errors.append("CIK must contain only digits")
        elif len(cik) > 10:
            errors.append("CIK must be 10 digits or fewer")
        else:
            # Zero-pad to 10 digits
            args.cik = cik.zfill(10)
    except AttributeError:
        errors.append("CIK is required")

    # Validate accession format (must match NNNNNNNNNN-NN-NNNNNN)
    try:
        accession = args.accession.strip()
        if not accession_pattern.match(accession):
            errors.append("Accession must match format: NNNNNNNNNN-NN-NNNNNN (e.g., 0000123456-12-345678)")
        else:
            args.accession = accession
    except AttributeError:
        errors.append("Accession is required")

    # Validate form type (support common forms)
    try:
        form = args.form.strip().upper()
        supported_forms = [
            "10-Q", "10-Q/A", "10-K", "10-K/A",
            "20-F", "20-F/A", "6-K", "6-K/A",
            "8-K", "8-K/A"
        ]
        if form not in supported_forms:
            errors.append(f"Form '{args.form}' not supported. Supported forms: {', '.join(supported_forms)}")
        else:
            args.form = form
    except AttributeError:
        errors.append("Form is required")

    # Validate filed-date format (ISO date: YYYY-MM-DD)
    try:
        filed_date = args.filed_date.strip()
        try:
            datetime.strptime(filed_date, "%Y-%m-%d")
            args.filed_date = filed_date
        except ValueError:
            errors.append("Filed date must be in format YYYY-MM-DD (e.g., 2026-01-31)")
    except AttributeError:
        errors.append("Filed date is required")

    # Validate period-end format if provided
    if hasattr(args, 'period_end') and args.period_end:
        try:
            period_end = args.period_end.strip()
            datetime.strptime(period_end, "%Y-%m-%d")
            args.period_end = period_end
        except ValueError:
            errors.append("Period end must be in format YYYY-MM-DD (e.g., 2026-01-31)")

    # Validate primary-document-url format
    try:
        primary_url = args.primary_document_url.strip()
        parsed = urlparse(primary_url)
        if not parsed.scheme or not parsed.netloc:
            errors.append("Primary document URL must be a valid URL with scheme and domain")
        else:
            args.primary_document_url = primary_url
    except AttributeError:
        errors.append("Primary document URL is required")

    # Validate pack-id format (alphanumeric, hyphens, underscores)
    try:
        pack_id = args.pack_id.strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", pack_id):
            errors.append("Pack ID must contain only letters, numbers, hyphens, and underscores")
        elif len(pack_id) < 3:
            errors.append("Pack ID must be at least 3 characters")
        elif len(pack_id) > 64:
            errors.append("Pack ID must be 64 characters or fewer")
        else:
            args.pack_id = pack_id
    except AttributeError:
        errors.append("Pack ID is required")

    # Validate comparator arguments consistency
    comparator_args = [
        args.comparator_accession,
        args.comparator_primary_document_url,
        args.comparator_primary_artifact_path
    ]
    comparator_provided = [arg for arg in comparator_args if arg]

    if comparator_provided:
        # If any comparator arg is provided, all must be provided
        if len(comparator_provided) != len(comparator_args):
            missing = []
            if not args.comparator_accession:
                missing.append("--comparator-accession")
            if not args.comparator_primary_document_url:
                missing.append("--comparator-primary-document-url")
            if not args.comparator_primary_artifact_path:
                missing.append("--comparator-primary-artifact-path")
            errors.append(f"When using comparator, all three arguments are required: {', '.join(missing)}")
        else:
            # Validate comparator accession format
            comp_accession = args.comparator_accession.strip()
            if not accession_pattern.match(comp_accession):
                errors.append("Comparator accession must match format: NNNNNNNNNN-NN-NNNNNN")

            # Validate comparator URL
            comp_url = args.comparator_primary_document_url.strip()
            parsed_comp = urlparse(comp_url)
            if not parsed_comp.scheme or not parsed_comp.netloc:
                errors.append("Comparator primary document URL must be a valid URL")

    # Validate primary file exists and is readable
    try:
        primary_path = Path(args.primary)
        if not primary_path.exists():
            errors.append(f"Primary file does not exist: {args.primary}")
        elif not primary_path.is_file():
            errors.append(f"Primary path is not a file: {args.primary}")
        elif not primary_path.suffix.lower() in ['.htm', '.html', '.xml']:
            errors.append(f"Primary file must be HTML or XML format (got {primary_path.suffix}): {args.primary}")
        else:
            # Try to read the file to verify accessibility
            try:
                primary_path.read_text(encoding='utf-8', errors='ignore')
                # Convert to absolute path for consistency
                args.primary = str(primary_path.resolve())
            except (PermissionError, OSError) as e:
                errors.append(f"Cannot read primary file: {e}")
    except AttributeError:
        errors.append("Primary file path is required")

    # Validate output directory
    try:
        out_path = Path(args.out)
        if out_path.exists():
            if not out_path.is_dir():
                errors.append(f"Output path exists but is not a directory: {args.out}")
            elif any(out_path.iterdir()):
                errors.append(f"Output directory must be empty: {args.out}")
        # Note: Directory will be created if it doesn't exist
    except AttributeError:
        errors.append("Output directory is required")

    # Validate comparator file if specified
    if hasattr(args, 'comparator_primary_artifact_path') and args.comparator_primary_artifact_path:
        comp_path = Path(args.comparator_primary_artifact_path)
        if not comp_path.exists():
            errors.append(f"Comparator primary file does not exist: {args.comparator_primary_artifact_path}")
        elif not comp_path.is_file():
            errors.append(f"Comparator primary path is not a file: {args.comparator_primary_artifact_path}")

    # Validate resolution mode
    if hasattr(args, 'resolution_mode') and args.resolution_mode:
        valid_modes = ["offline_only", "offline_preferred", "online_only", "hybrid"]
        if args.resolution_mode not in valid_modes:
            errors.append(f"Resolution mode must be one of: {', '.join(valid_modes)}")

    # Validate derive-artifact-urls flag usage
    if hasattr(args, 'derive_artifact_urls') and args.derive_artifact_urls:
        # This flag is only meaningful with EDGAR-sourced URLs
        if hasattr(args, 'primary_document_url') and args.primary_document_url:
            parsed = urlparse(args.primary_document_url)
            if parsed.netloc not in ['www.sec.gov', 'data.sec.gov', 'xbrl.sec.gov']:
                errors.append("--derive-artifact-urls should only be used with SEC EDGAR URLs")
        else:
            errors.append("--derive-artifact-urls requires --primary-document-url to be provided")


    # Validate output directory constraints
    try:
        out_path = Path(args.out)
        if out_path.exists():
            if not out_path.is_dir():
                errors.append(f"Output path exists but is not a directory: {args.out}")
            elif any(out_path.iterdir()):
                errors.append(f"Output directory is not empty (Evidence Pack requires empty directory): {args.out}")
        else:
            # Check if parent directory exists and is writable
            parent = out_path.parent
            if not parent.exists():
                errors.append(f"Output parent directory does not exist: {parent}")
            elif not os.access(parent, os.W_OK):
                errors.append(f"Output parent directory is not writable: {parent}")
    except AttributeError:
        errors.append("Output directory is required")

    # Enhanced URL validation with specific checks
    def validate_url(url: str, field_name: str) -> bool:
        """Validate URL format with SEC-specific checks."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme:
                errors.append(f"{field_name} must include URL scheme (http/https)")
                return False
            if parsed.scheme not in ['http', 'https']:
                errors.append(f"{field_name} must use http or https scheme")
                return False
            if not parsed.netloc:
                errors.append(f"{field_name} must include domain name")
                return False
            if not parsed.path or parsed.path == '/':
                errors.append(f"{field_name} must include document path")
                return False
            return True
        except Exception:
            errors.append(f"{field_name} is not a valid URL")
            return False

    # Re-validate primary document URL with enhanced checks
    if hasattr(args, 'primary_document_url') and args.primary_document_url:
        validate_url(args.primary_document_url.strip(), "Primary document URL")

    # Validate comparator URL if provided
    if hasattr(args, 'comparator_primary_document_url') and args.comparator_primary_document_url:
        validate_url(args.comparator_primary_document_url.strip(), "Comparator primary document URL")

    # Validate history window inputs if provided
    history_accessions = getattr(args, "history_accession", None)
    history_urls = getattr(args, "history_primary_document_url", None)
    history_paths = getattr(args, "history_primary_artifact_path", None)
    history_lists = [lst for lst in (history_accessions, history_urls, history_paths) if lst]

    if history_lists:
        if not (history_accessions and history_urls and history_paths):
            errors.append(
                "History inputs require all three flags: --history-accession, "
                "--history-primary-document-url, --history-primary-artifact-path"
            )
        elif not (len(history_accessions) == len(history_urls) == len(history_paths)):
            errors.append("History input lists must be the same length")
        else:
            history_entries = []
            for accession, url, path in zip(history_accessions, history_urls, history_paths):
                if not accession_pattern.match(accession.strip()):
                    errors.append(f"History accession must match format: NNNNNNNNNN-NN-NNNNNN ({accession})")
                    continue
                if not validate_url(url.strip(), "History primary document URL"):
                    continue
                hist_path = Path(path)
                if not hist_path.exists():
                    errors.append(f"History primary file does not exist: {path}")
                    continue
                if not hist_path.is_file():
                    errors.append(f"History primary path is not a file: {path}")
                    continue

                history_entries.append(
                    {
                        "accession": accession.strip(),
                        "primary_document_url": url.strip(),
                        "primary_artifact_path": str(hist_path.resolve()),
                    }
                )

            if len(history_entries) == len(history_accessions):
                history_entries.sort(key=lambda item: item["accession"])
                args.history_entries = history_entries
                args.history_accession = [entry["accession"] for entry in history_entries]
                args.history_primary_document_url = [entry["primary_document_url"] for entry in history_entries]
                args.history_primary_artifact_path = [entry["primary_artifact_path"] for entry in history_entries]

    return errors


def validate_verify_args(args: argparse.Namespace) -> list[str]:
    """
    Validate and normalize verify-pack command arguments.

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Validate Evidence Pack directory exists and contains required files
    try:
        pack_path = Path(args.pack)
        if not pack_path.exists():
            errors.append(f"Evidence Pack directory does not exist: {args.pack}")
        elif not pack_path.is_dir():
            errors.append(f"Evidence Pack path is not a directory: {args.pack}")
        else:
            # Check for required manifest file
            manifest_path = pack_path / "pack_manifest.json"
            if not manifest_path.is_file():
                errors.append(f"Evidence Pack missing pack_manifest.json: {manifest_path}")
            else:
                # Normalize to absolute path
                args.pack = str(pack_path.resolve())
    except AttributeError:
        errors.append("Evidence Pack directory is required")

    # Validate mutually exclusive flags
    if hasattr(args, 'quiet') and hasattr(args, 'verbose') and args.quiet and args.verbose:
        errors.append("Cannot use both --quiet and --verbose flags")

    return errors


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    p = argparse.ArgumentParser(prog="cmdrvl-xew")
    sub = p.add_subparsers(dest="cmd", required=True)

    # flatten: normalize EDGAR directory structure
    flatten = sub.add_parser(
        "flatten",
        help="Flatten EDGAR directory into Arelle-compatible flat layout",
    )
    flatten.add_argument(
        "edgar_dir",
        help="EDGAR accession directory (e.g., sample/0000034903-25-000063)",
    )
    flatten.add_argument(
        "--out",
        required=True,
        help="Output directory for flattened files",
    )
    flatten.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in output directory",
    )

    # pack: generate Evidence Pack
    pack = sub.add_parser("pack", help="Generate an Evidence Pack from flat artifacts directory")
    pack.add_argument("--pack-id", required=True)
    pack.add_argument("--out", required=True, help="Output directory (will be created)")

    pack.add_argument("--primary", required=True, help="Path to primary inline XBRL HTML")

    pack.add_argument("--issuer-name")
    pack.add_argument("--cik", required=True)
    pack.add_argument("--accession", required=True)
    pack.add_argument("--form", required=True)
    pack.add_argument("--filed-date", required=True)
    pack.add_argument("--period-end")
    pack.add_argument("--primary-document-url", required=True)

    pack.add_argument("--comparator-accession")
    pack.add_argument("--comparator-primary-document-url")
    pack.add_argument("--comparator-primary-artifact-path")
    pack.add_argument("--history-accession", action="append",
                     help="Historical filing accession (NNNNNNNNNN-NN-NNNNNN format) for adaptation markers. Can be specified multiple times.")
    pack.add_argument("--history-primary-document-url", action="append",
                     help="Historical filing primary document URL. Must match count of --history-accession.")
    pack.add_argument("--history-primary-artifact-path", action="append",
                     help="Path to historical filing primary artifact file. Must match count of --history-accession.")

    pack.add_argument("--retrieved-at", help="ISO 8601 UTC timestamp; default: now")
    pack.add_argument("--arelle-version", help="Record the Arelle version used")
    pack.add_argument("--resolution-mode", default="offline_preferred")
    pack.add_argument(
        "--derive-artifact-urls",
        action="store_true",
        help="Derive artifact source_url from primary document URL base (EDGAR-driven only)",
    )

    verify = sub.add_parser("verify-pack", help="Verify an Evidence Pack")
    verify.add_argument("--pack", required=True, help="Evidence Pack directory")
    verify.add_argument("--validate-schema", action="store_true", help="Validate xew_findings.json against JSON schema")
    verify.add_argument("--quiet", "-q", action="store_true", help="Only output errors and warnings")
    verify.add_argument("--verbose", "-v", action="store_true", help="Show detailed verification information")
    verify.add_argument("--check-only", action="store_true", help="Check pack structure without validating file hashes (faster)")
    verify.add_argument("--fail-fast", action="store_true", help="Stop verification on first error")

    fetch = sub.add_parser("fetch", help="Download EDGAR accession artifacts into a flat directory")
    fetch.add_argument("--cik", required=True)
    fetch.add_argument("--accession", required=True)
    fetch.add_argument("--out", required=True, help="Output directory for downloaded artifacts")
    fetch.add_argument("--user-agent", required=True, help="SEC-compliant User-Agent string")
    fetch.add_argument("--min-interval", type=float, default=0.2, help="Minimum seconds between requests (default: 0.2)")
    fetch.add_argument("--force", action="store_true", help="Overwrite existing files in output directory")

    args = p.parse_args(argv)

    if args.cmd == "flatten":
        return run_flatten(args)
    if args.cmd == "pack":
        args._invocation_argv = ["cmdrvl-xew", *argv]
        # Validate and normalize pack command arguments
        validation_errors = validate_pack_args(args)
        if validation_errors:
            for error in validation_errors:
                print(f"Error: {error}", file=sys.stderr)
            return ExitCode.CONFIG_ERROR
        return run_pack(args)
    if args.cmd == "verify-pack":
        # Validate verify-pack command arguments
        validation_errors = validate_verify_args(args)
        if validation_errors:
            for error in validation_errors:
                print(f"Error: {error}", file=sys.stderr)
            return ExitCode.CONFIG_ERROR
        return run_verify_pack(args)
    if args.cmd == "fetch":
        return run_fetch(args)

    p.error(f"unknown command: {args.cmd}")
    return ExitCode.CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
