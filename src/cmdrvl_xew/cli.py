from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .exit_codes import ExitCode
from .arelle_setup import run_arelle_install_packages
from .canon_snapshot import run_p008_snapshot_from_canon
from .fetch import run_fetch
from .flatten import run_flatten
from .identity_fragility import run_p008_identity_fragility
from .orchestrator_manifest import run_p008_manifest_from_orchestrator
from .p008_scan import run_p008_scan_corpus
from .p009_scan import run_p009_scan_corpus
from .p009_workflow import run_p009_identity_drift_workflow
from .pack import run_pack
from .registry_materialize import run_p008_materialize_registry
from .s3_source import run_fetch_s3
from .verify import run_verify_pack
from .doctor import run_doctor


def _load_env_file(path: Path, *, original_env_keys: set[str], override: bool) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Keep scope narrow: only support XEW_* vars + AWS_PROFILE for S3 bundles.
        if not (key.startswith("XEW_") or key == "AWS_PROFILE"):
            continue

        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        # Do not override externally-provided env vars.
        if key in original_env_keys:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def _load_local_env() -> None:
    """Load optional local config from .env / .env.local in the current working directory.

    Precedence (highest to lowest): external env > .env.local > .env.
    """
    original_keys = set(os.environ.keys())
    _load_env_file(Path(".env"), original_env_keys=original_keys, override=False)
    _load_env_file(Path(".env.local"), original_env_keys=original_keys, override=True)


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
        elif primary_path.suffix.lower() not in ['.htm', '.html', '.xml']:
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

    # Validate Arelle flags consistency
    if getattr(args, "require_arelle", False) and getattr(args, "no_arelle", False):
        errors.append("Cannot use both --require-arelle and --no-arelle")

    p008_snapshot = getattr(args, "p008_registry_snapshot", None)
    p008_required = getattr(args, "p008_require_registry", False)
    if p008_required and not p008_snapshot:
        errors.append("--p008-require-registry requires --p008-registry-snapshot")
    if p008_snapshot:
        snapshot_path = Path(p008_snapshot)
        if not snapshot_path.exists():
            errors.append(f"P008 registry snapshot does not exist: {p008_snapshot}")
        elif not snapshot_path.is_file():
            errors.append(f"P008 registry snapshot is not a file: {p008_snapshot}")

    for p009_path in getattr(args, "p009_observations", None) or []:
        observation_path = Path(p009_path)
        if not observation_path.exists():
            errors.append(f"P009 observations file does not exist: {p009_path}")
        elif not observation_path.is_file():
            errors.append(f"P009 observations path is not a file: {p009_path}")

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

    _load_local_env()

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
        "--require-arelle",
        action="store_true",
        help="Fail if Arelle cannot be used to load a real XBRL model (no mock fallback).",
    )
    pack.add_argument(
        "--no-arelle",
        action="store_true",
        help="Disable Arelle model loading and run detectors against a mock model (debug/testing only).",
    )
    pack.add_argument(
        "--arelle-xdg-config-home",
        help="Override XDG_CONFIG_HOME for Arelle runtime files (defaults to a writable temp directory).",
    )
    pack.add_argument(
        "--derive-artifact-urls",
        action="store_true",
        help="Derive artifact source_url from primary document URL base (EDGAR-driven only)",
    )
    pack.add_argument(
        "--p001-conflict-mode",
        choices=["rounded", "strict"],
        default="rounded",
        help=(
            "How XEW-P001 flags value_conflict for numeric duplicate fact sets. "
            "'rounded' treats rounding-consistent values (per decimals/precision) as non-conflicts (default). "
            "'strict' flags any numeric mismatch as a conflict."
        ),
    )
    pack.add_argument(
        "--p008-registry-snapshot",
        help=(
            "Local canon/OpenFIGI registry snapshot JSON for XEW-P008. "
            "cmdrvl-xew consumes this file only; it never calls OpenFIGI or canon at runtime."
        ),
    )
    pack.add_argument(
        "--p008-require-registry",
        action="store_true",
        help="Fail pack generation when XEW-P008 is enabled but no local registry snapshot is supplied.",
    )
    pack.add_argument(
        "--p009-observations",
        action="append",
        help=(
            "Source-neutral P009 observations JSONL/CSV. Repeatable. Files are copied into the "
            "Evidence Pack and consumed locally; pack never calls OpenFIGI, canon, SEC, or a parser-specific provider."
        ),
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

    fetch_s3 = sub.add_parser("fetch-s3", help="Materialize cached EDGAR artifacts from S3 into a flat directory")
    fetch_s3.add_argument("--s3-uri", help="S3 URI for extracted/ prefix or xbrl/ .nc object")
    fetch_s3.add_argument("--bucket", default="edgar-data-full", help="S3 bucket when constructing URI from date/accession")
    fetch_s3.add_argument("--date-partition", help="Filing date partition YYYYMMDD")
    fetch_s3.add_argument("--accession", help="EDGAR accession NNNNNNNNNN-NN-NNNNNN")
    fetch_s3.add_argument("--source-layout", choices=["extracted", "xbrl", "auto"], default="auto")
    fetch_s3.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE") or None)
    fetch_s3.add_argument("--out", required=True, help="Output flat artifact directory")
    fetch_s3.add_argument("--force", action="store_true", help="Overwrite matching output files in an existing directory")

    doctor = sub.add_parser("doctor", help="Check environment configuration for deterministic packs")
    doctor.add_argument(
        "--arelle-xdg-config-home",
        help=(
            "Arelle XDG_CONFIG_HOME to check (defaults to $XEW_ARELLE_XDG_CONFIG_HOME or /tmp/cmdrvl-xew-arelle). "
            "Use the same path you pass to `cmdrvl-xew arelle install-packages` and `cmdrvl-xew pack`."
        ),
    )

    arelle = sub.add_parser("arelle", help="Manage Arelle config (taxonomy packages)")
    arelle_sub = arelle.add_subparsers(dest="arelle_cmd", required=True)

    arelle_install = arelle_sub.add_parser(
        "install-packages",
        help="Install/register local taxonomy packages for offline Arelle resolution",
    )
    arelle_install.add_argument(
        "--arelle-xdg-config-home",
        help=(
            "Override XDG_CONFIG_HOME for Arelle (use a persistent writable path in production). "
            "Defaults to $XEW_ARELLE_XDG_CONFIG_HOME or a temp directory."
        ),
    )
    arelle_install.add_argument(
        "--bundle-uri",
        default=os.environ.get("XEW_ARELLE_BUNDLE_URI") or None,
        help=(
            "Taxonomy bundle tarball to fetch and unpack before installing packages. "
            "Supports s3://, http(s)://, file://, or a local path. "
            "Defaults to $XEW_ARELLE_BUNDLE_URI (if set)."
        ),
    )
    arelle_install.add_argument(
        "--bundle-sha256",
        default=os.environ.get("XEW_ARELLE_BUNDLE_SHA256") or None,
        help=(
            "Optional sha256 for the bundle tarball (integrity check). "
            "Defaults to $XEW_ARELLE_BUNDLE_SHA256 (if set)."
        ),
    )
    arelle_install.add_argument(
        "--aws-profile",
        default=os.environ.get("AWS_PROFILE") or None,
        help="AWS profile name to use for s3:// bundle downloads (default: $AWS_PROFILE).",
    )
    arelle_install.add_argument(
        "--no-bundle",
        action="store_true",
        help="Do not fetch/unpack the bundle; only install from --package and/or --url.",
    )
    arelle_install.add_argument(
        "--package",
        action="append",
        help="Path to a local taxonomy package (.zip) or package directory. Repeatable.",
    )
    arelle_install.add_argument(
        "--url",
        action="append",
        help=(
            "Download a taxonomy URL before installing. Repeatable. "
            "Supports Arelle taxonomy package .zip URLs, and directory URLs (trailing /) that will be mirrored "
            "by downloading all .xsd files and generating a local catalog.xml."
        ),
    )
    arelle_install.add_argument(
        "--download-dir",
        help="Directory to store downloaded packages (default: <XDG_CONFIG_HOME>/arelle/taxonomy-packages).",
    )
    arelle_install.add_argument(
        "--user-agent",
        help="User-Agent string for downloads (required when using --url; or set XEW_USER_AGENT).",
    )
    arelle_install.add_argument(
        "--min-interval",
        type=float,
        default=0.2,
        help="Minimum seconds between download requests (default: 0.2).",
    )
    arelle_install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing downloaded files.",
    )

    p008 = sub.add_parser("p008", help="Manage XEW-P008 helper artifacts")
    p008_sub = p008.add_subparsers(dest="p008_cmd", required=True)
    p008_snapshot = p008_sub.add_parser(
        "snapshot-from-canon",
        help="Convert a local canon OpenFIGI registry directory into a P008 snapshot JSON",
    )
    p008_snapshot.add_argument("--registry-dir", required=True, help="canon registry build output directory")
    p008_snapshot.add_argument("--out", required=True, help="Output P008 registry snapshot JSON")
    p008_snapshot.add_argument(
        "--overlay",
        help="Optional local JSON overlay adding security_title, canonical_signature, exchange, or other P008 row fields",
    )
    p008_snapshot.add_argument("--snapshot-id", help="Stable snapshot identifier; default uses canon registry id/version")
    p008_snapshot.add_argument("--generated-at", help="UTC ISO timestamp; default is current UTC")
    p008_materialize = p008_sub.add_parser(
        "materialize-registry",
        help="Build corpus-scoped CUSIP/ISIN/SEDOL seed files and optionally run canon registry build",
    )
    p008_materialize.add_argument("--corpus-id", required=True)
    p008_materialize.add_argument("--out-dir", required=True)
    p008_materialize.add_argument("--filing-manifest", help="CSV or JSONL with optional cusip, isin, and sedol columns")
    p008_materialize.add_argument("--seed-file", action="append", help="CSV/JSONL seed file with exactly one cusip/isin/sedol column")
    p008_materialize.add_argument("--version", required=True, help="Registry version passed to canon registry build")
    p008_materialize.add_argument("--provider-source", default="openfigi", help="canon registry build source (default: openfigi)")
    p008_materialize.add_argument("--provider-config", action="append", help="Provider option key=value; repeatable")
    p008_materialize.add_argument("--canon-bin", default="canon", help="canon binary to use when --run-canon is set")
    p008_materialize.add_argument("--run-canon", action="store_true", help="Actually run canon registry build after writing seed files")
    p008_materialize.add_argument("--incremental", action="store_true", help="Pass --incremental to canon registry build")
    p008_materialize.add_argument(
        "--allow-live-provider",
        action="store_true",
        help="Allow maintenance-time live OpenFIGI provider use when no local twin base_url is configured",
    )
    p008_identity = p008_sub.add_parser(
        "prove-identity-fragility",
        help="Run or dry-run the cached MSFT P008 identity-fragility proof path",
    )
    p008_identity.add_argument("--work-dir", required=True)
    p008_identity.add_argument("--bucket", default="edgar-data-full")
    p008_identity.add_argument("--source-layout", choices=["extracted", "xbrl", "auto"], default="extracted")
    p008_identity.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE") or None)
    p008_identity.add_argument("--taxonomy-home", help="Arelle XDG config home with installed taxonomy packages")
    p008_identity.add_argument("--pack-id", default="XEW-P008-MSFT-20260429")
    p008_identity.add_argument("--retrieved-at", default="2026-06-09T00:00:00Z")
    p008_identity.add_argument("--p008-registry-snapshot", help="Optional local canon/OpenFIGI P008 snapshot")
    p008_identity.add_argument("--p008-require-registry", action="store_true")
    p008_identity.add_argument("--dry-run", action="store_true")
    p008_identity.add_argument("--force", action="store_true")
    p008_identity.add_argument("--verbose", action="store_true", help="Stream raw fetch/pack/verify step output")
    p008_scan = p008_sub.add_parser(
        "scan-corpus",
        help="Rank a filing corpus for P008 identity-fragility candidates",
    )
    p008_scan.add_argument("--manifest", required=True, help="CSV or JSONL corpus manifest")
    p008_scan.add_argument("--out-dir", required=True)
    p008_scan.add_argument("--run-packs", action="store_true", help="Run fetch-s3 and pack for rows without pack_path")
    p008_scan.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE") or None)
    p008_scan.add_argument("--bucket", default="edgar-data-full")
    p008_scan.add_argument("--taxonomy-home")
    p008_scan.add_argument("--p008-registry-snapshot")
    p008_scan.add_argument("--max-filings", type=int)
    p008_scan.add_argument("--keep-packs", action="store_true")
    p008_scan.add_argument("--continue-on-error", action="store_true")
    p008_scan.add_argument("--fail-fast", action="store_true")
    p008_manifest = p008_sub.add_parser(
        "manifest-from-orchestrator",
        help="Normalize a cmdrvl-cli orchestrator filing-list response into a P008 corpus manifest",
    )
    p008_manifest.add_argument("--query", required=True)
    p008_manifest.add_argument("--tenant", default="salt")
    p008_manifest.add_argument("--out", required=True)
    p008_manifest.add_argument("--response-json", help="Use a saved orchestrator JSON response instead of querying")
    p008_manifest.add_argument("--cmdrvl-project", help="cmdrvl-cli project path for live orchestrator queries")
    p008_manifest.add_argument("--dry-run", action="store_true")

    p009 = sub.add_parser("p009", help="Manage XEW-P009 helper artifacts")
    p009_sub = p009.add_subparsers(dest="p009_cmd", required=True)
    p009_scan = p009_sub.add_parser(
        "scan-corpus",
        help="Scan a source-neutral corpus for temporal instrument identity fragility",
    )
    p009_scan.add_argument("--manifest", required=True, help="P009 corpus manifest JSONL/CSV")
    p009_scan.add_argument("--observations", help="P009 normalized observations JSONL/CSV")
    p009_scan.add_argument("--registry-snapshot", help="Local canon/OpenFIGI registry snapshot JSON")
    p009_scan.add_argument("--out-dir", required=True)
    p009_scan.add_argument("--limit", type=int)
    p009_workflow = p009_sub.add_parser(
        "prove-identity-drift",
        help="Run or dry-run the P009 broad-corpus scan, registry seed, pack, and verify workflow",
    )
    p009_workflow.add_argument("--manifest", required=True, help="P009 corpus manifest JSONL/CSV")
    p009_workflow.add_argument("--observations", help="P009 normalized observations JSONL/CSV")
    p009_workflow.add_argument("--registry-snapshot", help="Local canon/OpenFIGI registry snapshot JSON")
    p009_workflow.add_argument("--artifacts-root", required=True, help="Root for manifest local_path cached artifacts")
    p009_workflow.add_argument("--out", required=True, help="Workflow output directory")
    p009_workflow.add_argument("--select-rank", type=int, default=1, help="Ranked P009 candidate to package")
    p009_workflow.add_argument("--limit", type=int, help="Optional scan candidate limit")
    p009_workflow.add_argument("--dry-run", action="store_true", help="Print the deterministic plan without writing artifacts")
    p009_workflow.add_argument("--stop-after", choices=["scan", "seeds"], help="Stop after scan outputs or seed generation")
    p009_workflow.add_argument("--pack-id", help="Evidence Pack id; defaults to selected P009 candidate id prefix")
    p009_workflow.add_argument("--retrieved-at", help="Fixed retrieval timestamp for reproducible pack output")
    p009_workflow.add_argument("--issuer-name")
    p009_workflow.add_argument("--cik")
    p009_workflow.add_argument("--form")
    p009_workflow.add_argument("--filed-date")
    p009_workflow.add_argument("--period-end")
    p009_workflow.add_argument("--primary-document-url")
    p009_workflow.add_argument("--require-arelle", action="store_true")
    p009_workflow.add_argument("--corpus-id", help="Corpus id for registry materialization planning")
    p009_workflow.add_argument("--registry-version", default="p009")
    p009_workflow.add_argument("--provider-source", default="openfigi")
    p009_workflow.add_argument("--provider-config", action="append", help="Provider option key=value; secrets are redacted in outputs")
    p009_workflow.add_argument("--canon-bin", default="canon")
    p009_workflow.add_argument("--materialize-registry", action="store_true", help="Write registry materialization manifest before pack")
    p009_workflow.add_argument("--run-canon", action="store_true", help="Execute canon registry build during materialization")
    p009_workflow.add_argument("--incremental", action="store_true")
    p009_workflow.add_argument("--allow-live-provider", action="store_true")
    p009_workflow.add_argument("--verbose", action="store_true", help="Stream raw pack/verify output")

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
    if args.cmd == "fetch-s3":
        return run_fetch_s3(args)
    if args.cmd == "doctor":
        return run_doctor(args)
    if args.cmd == "arelle":
        if args.arelle_cmd == "install-packages":
            return run_arelle_install_packages(args)
        p.error(f"unknown arelle command: {args.arelle_cmd}")
    if args.cmd == "p008":
        if args.p008_cmd == "snapshot-from-canon":
            return run_p008_snapshot_from_canon(args)
        if args.p008_cmd == "materialize-registry":
            return run_p008_materialize_registry(args)
        if args.p008_cmd == "prove-identity-fragility":
            return run_p008_identity_fragility(args)
        if args.p008_cmd == "scan-corpus":
            return run_p008_scan_corpus(args)
        if args.p008_cmd == "manifest-from-orchestrator":
            return run_p008_manifest_from_orchestrator(args)
        p.error(f"unknown p008 command: {args.p008_cmd}")
    if args.cmd == "p009":
        if args.p009_cmd == "scan-corpus":
            return run_p009_scan_corpus(args)
        if args.p009_cmd == "prove-identity-drift":
            return run_p009_identity_drift_workflow(args)
        p.error(f"unknown p009 command: {args.p009_cmd}")

    p.error(f"unknown command: {args.cmd}")
    return ExitCode.CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
