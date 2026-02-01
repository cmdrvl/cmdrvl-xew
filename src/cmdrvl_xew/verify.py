from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import NamedTuple

from .exit_codes import ExitCode
from .util import sha256_file


class VerificationResult(NamedTuple):
    """Result of verification with detailed status."""
    success: bool
    error_count: int
    warning_count: int
    files_checked: int
    files_skipped: int


def _compute_pack_sha256(files: list[dict]) -> str:
    entries = [f"{f['path']}\t{f['sha256']}\n" for f in files]
    entries.sort(key=lambda s: s.split("\t", 1)[0])
    data = "".join(entries).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def run_verify_pack(args: argparse.Namespace) -> int:
    """
    Verify an Evidence Pack with configurable verbosity and validation options.

    Returns:
        ExitCode.SUCCESS (0): Verification successful
        ExitCode.CONFIG_ERROR (1): Configuration/argument error
        ExitCode.PROCESSING_ERROR (3): Verification failed
    """
    pack_dir = Path(args.pack)
    quiet = getattr(args, 'quiet', False)
    verbose = getattr(args, 'verbose', False)
    check_only = getattr(args, 'check_only', False)
    fail_fast = getattr(args, 'fail_fast', False)

    def log_error(msg: str) -> None:
        """Print error message to stderr."""
        print(f"ERROR: {msg}", file=sys.stderr)

    def log_warning(msg: str) -> None:
        """Print warning message if not quiet."""
        if not quiet:
            print(f"WARNING: {msg}", file=sys.stderr)

    def log_info(msg: str) -> None:
        """Print info message if verbose."""
        if verbose:
            print(f"INFO: {msg}")

    def log_success(msg: str) -> None:
        """Print success message if not quiet."""
        if not quiet:
            print(f"OK: {msg}")

    # Step 1: Load and validate manifest
    manifest_path = pack_dir / "pack_manifest.json"
    if not manifest_path.is_file():
        log_error(f"Evidence Pack missing required pack_manifest.json: {manifest_path}")
        return ExitCode.PROCESSING_ERROR

    try:
        log_info(f"Loading manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        log_error(f"Failed to parse pack_manifest.json: {e}")
        return ExitCode.PROCESSING_ERROR

    expected_pack_sha256 = manifest.get("pack_sha256")
    files = manifest.get("files")

    if not expected_pack_sha256 or not isinstance(expected_pack_sha256, str):
        log_error("pack_manifest.json missing or invalid pack_sha256 field")
        return ExitCode.PROCESSING_ERROR
    if not files or not isinstance(files, list):
        log_error("pack_manifest.json missing or invalid files[] field")
        return ExitCode.PROCESSING_ERROR

    log_info(f"Manifest contains {len(files)} file entries")

    # Step 2: Verify file structure and optionally check hashes
    error_count = 0
    warning_count = 0
    files_checked = 0
    files_skipped = 0

    for i, f in enumerate(files):
        rel = f.get("path")
        exp_sha = f.get("sha256")
        exp_bytes = f.get("bytes")

        if not rel or not exp_sha or exp_bytes is None:
            error_count += 1
            log_error(f"Invalid manifest entry #{i}: missing path/sha256/bytes: {f}")
            if fail_fast:
                return ExitCode.PROCESSING_ERROR
            continue

        abs_path = pack_dir / rel
        if not abs_path.is_file():
            error_count += 1
            log_error(f"File missing from Evidence Pack: {rel}")
            if fail_fast:
                return ExitCode.PROCESSING_ERROR
            continue

        # Check file exists and basic properties
        try:
            file_size = abs_path.stat().st_size
            if file_size != exp_bytes:
                error_count += 1
                log_error(f"File size mismatch: {rel}: expected {exp_bytes} bytes, got {file_size}")
                if fail_fast:
                    return ExitCode.PROCESSING_ERROR
                continue
        except OSError as e:
            error_count += 1
            log_error(f"Cannot access file: {rel}: {e}")
            if fail_fast:
                return ExitCode.PROCESSING_ERROR
            continue

        # Hash verification (skip if check_only mode)
        if check_only:
            files_skipped += 1
            log_info(f"Skipped hash check: {rel} (--check-only mode)")
            continue

        try:
            log_info(f"Verifying file: {rel}")
            sha, n = sha256_file(abs_path)
            if sha != exp_sha:
                error_count += 1
                log_error(f"SHA256 mismatch: {rel}: expected {exp_sha}, got {sha}")
                if fail_fast:
                    return ExitCode.PROCESSING_ERROR
            else:
                log_info(f"SHA256 verified: {rel}")
            files_checked += 1
        except Exception as e:
            error_count += 1
            log_error(f"Failed to compute hash for {rel}: {e}")
            if fail_fast:
                return ExitCode.PROCESSING_ERROR

    # Step 3: Verify pack-level SHA256 (skip if check_only mode)
    if not check_only:
        log_info("Computing overall pack SHA256...")
        calc_pack_sha256 = _compute_pack_sha256(files)
        if calc_pack_sha256 != expected_pack_sha256:
            error_count += 1
            log_error(f"Evidence Pack SHA256 mismatch: expected {expected_pack_sha256}, got {calc_pack_sha256}")
            if fail_fast:
                return ExitCode.PROCESSING_ERROR
        else:
            log_success(f"Evidence Pack SHA256 verified: {calc_pack_sha256}")

    # Step 4: Toolchain metadata checks
    tc_errors, tc_warnings = _check_toolchain_metadata(pack_dir, quiet=quiet, verbose=verbose)
    error_count += tc_errors
    warning_count += tc_warnings
    if tc_errors and fail_fast:
        return ExitCode.PROCESSING_ERROR

    # Step 5: Schema validation if requested
    if getattr(args, 'validate_schema', False):
        log_info("Validating xew_findings.json schema...")
        schema_result = _validate_findings_schema(pack_dir, quiet=quiet, verbose=verbose)
        if not schema_result.success:
            if schema_result.is_missing_optional:
                warning_count += 1
            else:
                error_count += 1
                if fail_fast:
                    return ExitCode.PROCESSING_ERROR

    # Step 6: Final status report
    if not quiet or verbose:
        print("\n" + "="*50)
        print("VERIFICATION SUMMARY")
        print("="*50)
        print(f"Files in manifest: {len(files)}")
        print(f"Files checked: {files_checked}")
        if check_only:
            print(f"Files skipped (--check-only): {files_skipped}")
        print(f"Errors: {error_count}")
        print(f"Warnings: {warning_count}")
        print("="*50)

    if error_count == 0:
        if not quiet:
            print("✓ Evidence Pack verification PASSED")
        return ExitCode.SUCCESS
    else:
        log_error(f"Evidence Pack verification FAILED ({error_count} errors)")
        return ExitCode.PROCESSING_ERROR


class SchemaValidationResult(NamedTuple):
    """Result of schema validation with detailed status."""
    success: bool
    is_missing_optional: bool
    error_message: str = ""


def _validate_findings_schema(pack_dir: Path, quiet: bool = False, verbose: bool = False) -> SchemaValidationResult:
    """
    Validate xew_findings.json against JSON schema.

    Args:
        pack_dir: Evidence Pack directory
        quiet: Suppress non-error output
        verbose: Show detailed information

    Returns:
        SchemaValidationResult with success status and details
    """
    findings_path = pack_dir / "xew_findings.json"

    def log_error(msg: str) -> None:
        if not quiet:
            print(f"ERROR: {msg}", file=sys.stderr)

    def log_warning(msg: str) -> None:
        if not quiet:
            print(f"WARNING: {msg}", file=sys.stderr)

    def log_info(msg: str) -> None:
        if verbose:
            print(f"INFO: {msg}")

    if not findings_path.is_file():
        log_warning("xew_findings.json not found - schema validation skipped")
        return SchemaValidationResult(success=True, is_missing_optional=True, error_message="xew_findings.json not found")

    try:
        log_info("Parsing xew_findings.json...")
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
        log_info(f"Loaded findings JSON with {len(findings.get('findings', []))} findings")
    except Exception as e:
        error_msg = f"Failed to parse xew_findings.json: {e}"
        log_error(error_msg)
        return SchemaValidationResult(success=False, is_missing_optional=False, error_message=error_msg)

    try:
        import jsonschema  # type: ignore
        from importlib import resources

        log_info("Loading JSON schema...")
        schema_text = resources.files("cmdrvl_xew").joinpath("schemas/xew_findings.schema.v1.json").read_text(
            encoding="utf-8"
        )
        schema = json.loads(schema_text)

        log_info("Validating findings against schema...")
        try:
            format_checker = jsonschema.FormatChecker()
        except AttributeError:
            format_checker = None

        if format_checker is None:
            jsonschema.validate(instance=findings, schema=schema)
        else:
            jsonschema.validate(instance=findings, schema=schema, format_checker=format_checker)

        if not quiet:
            print("✓ xew_findings.json schema validation PASSED")
        return SchemaValidationResult(success=True, is_missing_optional=False)

    except ModuleNotFoundError:
        log_warning("jsonschema package not installed - schema validation skipped")
        return SchemaValidationResult(success=True, is_missing_optional=True, error_message="jsonschema not installed")
    except jsonschema.ValidationError as e:
        error_msg = f"Schema validation failed: {e.message}"
        if e.absolute_path:
            error_msg += f" at path: {'.'.join(str(p) for p in e.absolute_path)}"
        log_error(error_msg)
        return SchemaValidationResult(success=False, is_missing_optional=False, error_message=error_msg)
    except Exception as e:
        error_msg = f"Schema validation error: {e}"
        log_error(error_msg)
        return SchemaValidationResult(success=False, is_missing_optional=False, error_message=error_msg)


def _check_toolchain_metadata(pack_dir: Path, quiet: bool = False, verbose: bool = False) -> tuple[int, int]:
    """Return (error_count, warning_count) for toolchain/toolchain.json checks."""
    toolchain_path = pack_dir / "toolchain" / "toolchain.json"
    errors = 0
    warnings = 0

    def log_error(msg: str) -> None:
        nonlocal errors
        errors += 1
        if not quiet:
            print(f"ERROR: {msg}", file=sys.stderr)

    def log_warning(msg: str) -> None:
        nonlocal warnings
        warnings += 1
        if not quiet:
            print(f"WARNING: {msg}", file=sys.stderr)

    def log_info(msg: str) -> None:
        if verbose:
            print(f"INFO: {msg}")

    if not toolchain_path.is_file():
        log_warning("toolchain/toolchain.json not found")
        return errors, warnings

    try:
        log_info("Parsing toolchain/toolchain.json...")
        toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
    except Exception as e:
        log_error(f"Failed to parse toolchain/toolchain.json: {e}")
        return errors, warnings

    if not isinstance(toolchain, dict):
        log_warning("toolchain/toolchain.json is not a JSON object")
        return errors, warnings

    _warn_missing_or_unknown(toolchain, "cmdrvl_xew_version", log_warning)
    _warn_missing_or_unknown(toolchain, "arelle_version", log_warning)

    config = toolchain.get("config")
    if config is None:
        log_warning("toolchain/config missing")
    elif not isinstance(config, dict):
        log_warning("toolchain/config is not an object")

    return errors, warnings


def _warn_missing_or_unknown(toolchain: dict, key: str, log_warning: callable) -> None:
    value = toolchain.get(key)
    if value is None:
        log_warning(f"toolchain/{key} missing")
        return
    if not isinstance(value, str) or not value.strip():
        log_warning(f"toolchain/{key} not a non-empty string")
        return
    if value.strip().lower() == "unknown":
        log_warning(f"toolchain/{key} is 'unknown'")
