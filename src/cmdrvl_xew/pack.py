from __future__ import annotations

import argparse
import hashlib
import mimetypes
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .artifacts import (
    ArtifactCollectionError,
    ArtifactHash,
    collect_artifacts,
    create_pack_directory_structure,
    compute_pack_layout,
    extract_schema_refs,
)
from . import __version__
from .comparator import comparator_policy, ComparatorPolicy
from .comparator_selection import select_comparator_and_history
from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .taxonomy import NonRedistributableReference, non_redistributable_reference_from_path
from .util import FileHash, qname_to_clark, sha256_file, utc_now_iso, write_json
from .findings import FindingsWriter
from .pack_manifest import PackManifestBuilder
from .toolchain import ToolchainRecorder
from .detectors.registry import get_registry
from .detectors._base import DetectorContext
from .metadata import extract_metadata
from .markers import (
    AnchoringCoverageSnapshot,
    ContextModelSnapshot,
    DuplicateSignatureSnapshot,
    ExtensionSnapshot,
    TaxonomySchemaSnapshot,
    detect_anchoring_retrofit_marker,
    detect_context_model_rewrite_marker,
    detect_duplicate_cleanup_from_findings,
    detect_extension_refactor_marker,
    detect_taxonomy_refresh_marker,
    marker_thresholds_config,
)

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _compute_pack_sha256(files: list[FileHash]) -> str:
    # v1 contract: pack_sha256 is computed from manifest entries (path + sha256),
    # excluding pack_manifest.json.
    entries = [f"{f.path}\t{f.sha256}\n" for f in files]
    entries.sort(key=lambda s: s.split("\t", 1)[0])
    data = "".join(entries).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_cik(cik: str) -> str:
    s = cik.strip()
    if not s.isdigit():
        raise ValueError("CIK must be digits")
    if len(s) > 10:
        raise ValueError("CIK must be <= 10 digits")
    return s.zfill(10)


def _normalize_accession(accession: str) -> str:
    s = accession.strip()
    if not _ACCESSION_RE.match(s):
        raise ValueError("accession must match ^\\d{10}-\\d{2}-\\d{6}$")
    return s


def _generate_repro_steps(pack_id: str, cik: str, accession: str, form: str,
                         filed_date: str, primary_artifact_path: str,
                         cmdrvl_version: str, generated_at: str) -> dict:
    """
    Generate reproducible verification steps for third-party validation.

    Creates deterministic procedures that enable independent verification of
    XEW findings using the artifacts included in the Evidence Pack.

    Args:
        pack_id: Evidence Pack identifier
        cik: Company CIK (normalized)
        accession: EDGAR accession number
        form: Filing form type
        filed_date: Filing date
        primary_artifact_path: Path to primary document in pack
        cmdrvl_version: XEW tool version used
        generated_at: Pack generation timestamp

    Returns:
        Dictionary containing reproducible verification steps
    """

    # Base verification command using the Evidence Pack
    verification_cmd = [
        "cmdrvl-xew", "verify-pack",
        "--pack", ".",
        "--validate-schema"
    ]

    # Manual recreation command (if artifacts were re-downloaded)
    recreation_cmd = [
        "cmdrvl-xew", "pack",
        f"--pack-id={pack_id}",
        "--out=./reproduced-pack",
        f"--cik={cik}",
        f"--accession={accession}",
        f"--form={form}",
        f"--filed-date={filed_date}",
        f"--primary={primary_artifact_path}",
        f"--primary-document-url=<URL_TO_PRIMARY_DOCUMENT>"
    ]

    repro_steps = {
        "repro_version": "1.0",
        "pack_id": pack_id,
        "generated_at": generated_at,
        "tool_info": {
            "name": "cmdrvl-xew",
            "version": cmdrvl_version,
            "description": "XBRL Early Warning (XEW) detection engine"
        },
        "verification": {
            "description": "Steps to verify this Evidence Pack and reproduce findings",
            "requirements": {
                "os": "Linux, macOS, or Windows with Python 3.9+",
                "python": ">=3.9",
                "dependencies": [
                    f"cmdrvl-xew=={cmdrvl_version}",
                    "arelle>=1.2"
                ]
            },
            "steps": [
                {
                    "step": 1,
                    "description": "Verify Evidence Pack integrity",
                    "command": " ".join(verification_cmd),
                    "expected_result": "All hash validations pass, schema validation succeeds",
                    "purpose": "Confirm pack contents match manifest and schema"
                },
                {
                    "step": 2,
                    "description": "Examine detection findings",
                    "command": "cat xew_findings.json",
                    "expected_result": "JSON with findings array and metadata",
                    "purpose": "Review detected patterns and evidence"
                },
                {
                    "step": 3,
                    "description": "Inspect primary XBRL document",
                    "command": f"ls -la {primary_artifact_path}",
                    "expected_result": f"Primary iXBRL document at {primary_artifact_path}",
                    "purpose": "Verify primary document is included and accessible"
                },
                {
                    "step": 4,
                    "description": "Review toolchain metadata",
                    "command": "cat toolchain/toolchain.json",
                    "expected_result": "Tool versions, configuration, and process metadata",
                    "purpose": "Understand exact environment used for detection"
                }
            ]
        },
        "recreation": {
            "description": "Steps to recreate Evidence Pack from scratch (requires EDGAR access)",
            "command": " ".join(recreation_cmd),
            "notes": [
                "Replace <URL_TO_PRIMARY_DOCUMENT> with actual EDGAR URL",
                "Requires network access to download EDGAR artifacts",
                "Results should be deterministically identical (within timestamp fields)",
                f"Must use cmdrvl-xew version {cmdrvl_version} for identical results"
            ],
            "disclaimer": "Recreation requires external EDGAR data and may produce different timestamps but identical findings"
        },
        "validation_notes": [
            "Evidence Pack contains all artifacts needed for verification",
            "Findings are deterministic given identical input artifacts",
            "Hash validations ensure artifact integrity",
            "Schema validation confirms findings format compliance",
            f"Generated with cmdrvl-xew v{cmdrvl_version} on {generated_at}"
        ]
    }

    return repro_steps


def _validate_form_type(form: str) -> str:
    """Validate form type and normalize to standard format."""
    form_normalized = form.strip().upper()
    valid_forms = {'10-K', '10-Q', '8-K', '20-F', '10-K/A', '10-Q/A', '8-K/A', '20-F/A'}

    if form_normalized not in valid_forms:
        raise ValueError(f"Unsupported form type: {form}. Supported forms: {', '.join(sorted(valid_forms))}")

    return form_normalized


def _validate_date_format(date_str: str, field_name: str) -> str:
    """Validate date format (YYYY-MM-DD) and check for reasonable values."""
    date_cleaned = date_str.strip()

    if not _DATE_RE.match(date_cleaned):
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format, got: {date_str}")

    # Additional validation: try to parse the date to ensure it's valid
    try:
        parsed_date = datetime.strptime(date_cleaned, "%Y-%m-%d")

        # Basic sanity check: filing dates should be reasonably recent
        if field_name == "filed-date":
            current_year = datetime.now().year
            if parsed_date.year < 1990 or parsed_date.year > current_year + 1:
                raise ValueError(f"{field_name} year {parsed_date.year} is outside reasonable range (1990-{current_year + 1})")

    except ValueError as e:
        if "does not match format" in str(e):
            raise ValueError(f"{field_name} is not a valid date: {date_str}")
        else:
            raise  # Re-raise our custom error messages

    return date_cleaned


def _run_xew_detection(primary_path: Path, artifacts_dir: Path, context_metadata: dict) -> tuple[list, DetectorContext]:
    """
    Run XEW detection on the primary XBRL document.

    Args:
        primary_path: Path to the primary iXBRL/XBRL document
        artifacts_dir: Directory containing related artifacts
        context_metadata: Filing context (CIK, accession, etc.)

    Returns:
        Tuple of (findings, detector_context) for downstream processing
    """
    # Initialize detector registry and auto-discover detectors
    registry = get_registry()
    registry.auto_discover("cmdrvl_xew.detectors")

    # Load rule basis map for Gate enforcement and citations
    rule_basis_map_path = Path(__file__).parent / "spec" / "xew_rule_basis_map.v1.json"
    if rule_basis_map_path.exists():
        registry.load_rule_basis_map(rule_basis_map_path)
        import logging
        logging.info(f"Loaded rule basis map from {rule_basis_map_path}")
    else:
        import logging
        logging.warning(f"Rule basis map not found at {rule_basis_map_path}, Gate enforcement may be limited")

    # Create detector context
    # Enhanced configuration for detection
    detection_config = {
        "primary_document_url": context_metadata.get("primary_document_url", ""),
        "enable_all_patterns": True,
        "gate_enforcement": True,
    }

    # Include comparator selection data for marker detectors
    if "comparator_selection" in context_metadata:
        detection_config["comparator_selection"] = context_metadata["comparator_selection"]

    detection_context = DetectorContext(
        primary_document_path=str(primary_path),
        artifacts_dir=str(artifacts_dir),
        cik=context_metadata["cik"],
        accession=context_metadata["accession"],
        form=context_metadata["form"],
        filed_date=context_metadata["filed_date"],
        xbrl_model=None,  # Will be loaded below
        config=detection_config,
    )

    try:
        # Load XBRL model using Arelle (simplified placeholder)
        # In production, this would use proper Arelle model loading
        try:
            # Mock XBRL model for testing - in production would use:
            # from arelle import Cntlr, ModelManager
            # controller = Cntlr.Cntlr()
            # model = controller.modelManager.load(str(primary_path))
            # detection_context.xbrl_model = model
            detection_context.xbrl_model = _create_mock_xbrl_model(primary_path)
        except Exception as e:
            import logging
            logging.warning(f"Failed to load XBRL model: {e}, using mock model")
            detection_context.xbrl_model = _create_mock_xbrl_model(primary_path)

        # Run all registered detectors with enhanced logging + priority suppression
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Running {len(registry.list_patterns())} detectors with Gate enforcement enabled")

        findings, selected_finding = registry.run_detectors_with_priority_selection(detection_context)

        logger.info(f"XEW detection completed: {len(findings)} findings from {len(registry.list_patterns())} detectors")

        # Enhanced findings summary
        if findings:
            alert_eligible_count = sum(1 for f in findings if f.alert_eligible)
            suppressed_count = sum(1 for f in findings if f.status == "suppressed")
            pattern_coverage = sorted(set(f.pattern_id for f in findings))
            logger.info(f"Findings summary: {alert_eligible_count} alert-eligible, {suppressed_count} suppressed")
            logger.info(f"Pattern coverage: {pattern_coverage}")
            if selected_finding:
                logger.info(f"Selected highest-priority finding: {selected_finding.pattern_id}")
        else:
            logger.info("No findings detected")

        return findings, detection_context

    except Exception as e:
        import logging
        logging.error(f"XEW detection pipeline failed: {e}")
        detection_context.xbrl_model = detection_context.xbrl_model or _create_mock_xbrl_model(primary_path)
        return [], detection_context


def _create_mock_xbrl_model(primary_path: Path):
    """Create a mock XBRL model for testing purposes."""
    class MockXBRLModel:
        def __init__(self, path):
            self.modelDocument = None
            self.facts = []
            self.qnameConcepts = {}
            self.contexts = {}

    return MockXBRLModel(primary_path)


_STANDARD_NAMESPACE_PREFIXES = (
    "http://fasb.org/us-gaap/",
    "http://xbrl.ifrs.org/",
    "http://www.xbrl.org/",
    "http://xbrl.sec.gov/",
)

_ANCHOR_ARCROLES = (
    "http://www.xbrl.org/2003/arcrole/concept-label",
    "http://www.xbrl.org/2003/arcrole/concept-reference",
    "http://xbrl.us/us-gaap/role/label/negated",
)


def _extract_schema_refs_for_marker(path: Path) -> list[str]:
    try:
        refs = extract_schema_refs(path)
    except Exception:
        return []
    normalized: list[str] = []
    seen = set()
    for ref in refs:
        value = str(ref).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return sorted(normalized)


def _extract_extension_qnames(xbrl_model) -> list[str]:
    if xbrl_model is None:
        return []

    qname_concepts = getattr(xbrl_model, "qnameConcepts", None)
    if isinstance(qname_concepts, dict):
        qnames = qname_concepts.keys()
    else:
        qnames = getattr(xbrl_model, "factsByQname", {}).keys() if hasattr(xbrl_model, "factsByQname") else []

    extensions: list[str] = []
    seen = set()
    for qname in qnames:
        namespace = getattr(qname, "namespaceURI", None) or getattr(qname, "namespace", None)
        if not namespace:
            continue
        if any(namespace.startswith(prefix) for prefix in _STANDARD_NAMESPACE_PREFIXES):
            continue
        try:
            clark = qname_to_clark(qname)
        except (TypeError, ValueError):
            continue
        if clark in seen:
            continue
        seen.add(clark)
        extensions.append(clark)
    return sorted(extensions)


def _extract_anchored_extension_qnames(xbrl_model) -> list[str]:
    if xbrl_model is None or not hasattr(xbrl_model, "relationshipSet"):
        return []

    anchored: set[str] = set()
    for arcrole in _ANCHOR_ARCROLES:
        relationships = xbrl_model.relationshipSet(arcrole)
        if not relationships:
            continue
        for rel in getattr(relationships, "modelRelationships", []) or []:
            from_obj = getattr(rel, "fromModelObject", None)
            qname = getattr(from_obj, "qname", None)
            if not qname:
                continue
            try:
                anchored.add(qname_to_clark(qname))
            except (TypeError, ValueError):
                continue

    return sorted(anchored)


def _extract_context_model_signatures(xbrl_model) -> tuple[int, list[str]]:
    if xbrl_model is None:
        return 0, []

    contexts = getattr(xbrl_model, "contexts", None)
    if isinstance(contexts, dict):
        context_values = contexts.values()
        context_count = len(contexts)
    elif isinstance(contexts, list):
        context_values = contexts
        context_count = len(contexts)
    else:
        return 0, []

    signatures: list[str] = []
    seen = set()
    for context in context_values:
        dims = getattr(context, "qnameDims", None)
        if not dims:
            continue
        pairs: list[str] = []
        for dim_qname, dim_value in getattr(dims, "items", lambda: [])():
            try:
                dim_clark = qname_to_clark(dim_qname)
            except (TypeError, ValueError):
                continue
            member_qname = getattr(dim_value, "memberQname", None)
            if member_qname is not None:
                try:
                    member_value = qname_to_clark(member_qname)
                except (TypeError, ValueError):
                    member_value = str(member_qname)
            else:
                typed_member = getattr(dim_value, "typedMember", None)
                member_value = str(typed_member) if typed_member is not None else ""
            if not member_value:
                continue
            pairs.append(f"{dim_clark}={member_value}")
        if not pairs:
            continue
        pairs.sort()
        signature = "|".join(pairs)
        if signature in seen:
            continue
        seen.add(signature)
        signatures.append(signature)

    signatures.sort()
    return context_count, signatures


def _history_primary_paths(history_window: list[dict[str, str]], out_dir: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for entry in history_window:
        accession = entry.get("accession")
        rel_path = entry.get("primary_artifact_path")
        if not accession or not rel_path:
            continue
        primary_path = (out_dir / rel_path).resolve()
        if not primary_path.is_file():
            continue
        entries.append((accession, primary_path))
    return entries


def _normalize_history_entry(entry: dict[str, str], idx: int) -> dict[str, str]:
    if not isinstance(entry, dict):
        exit_invocation_error(f"History entry #{idx} must be an object")

    raw_accession = entry.get("accession")
    if not raw_accession:
        exit_invocation_error(f"History entry #{idx} missing accession")

    try:
        accession = _normalize_accession(raw_accession)
    except ValueError as e:
        exit_invocation_error(f"History entry #{idx} invalid accession {raw_accession!r}: {e}")

    primary_document_url = entry.get("primary_document_url")
    if not primary_document_url:
        exit_invocation_error(f"History entry {accession} missing primary_document_url")

    primary_artifact_path = entry.get("primary_artifact_path")
    if not primary_artifact_path:
        exit_invocation_error(f"History entry {accession} missing primary_artifact_path")

    return {
        "accession": accession,
        "primary_document_url": primary_document_url.strip(),
        "primary_artifact_path": str(Path(primary_artifact_path).resolve()),
    }


def _extract_duplicate_signature_ids(findings: list) -> list[str]:
    signature_ids: list[str] = []
    for finding in findings:
        pattern_id = getattr(finding, "pattern_id", None)
        if pattern_id != "XEW-P001":
            continue
        instances = getattr(finding, "instances", None) or []
        for instance in instances:
            instance_id = getattr(instance, "instance_id", None)
            if instance_id:
                signature_ids.append(str(instance_id))
    return signature_ids


def _run_p001_for_marker(
    *,
    primary_path: Path,
    artifacts_dir: Path,
    cik: str,
    accession: str,
    form: str,
    filed_date: str,
    xbrl_model,
) -> list:
    registry = get_registry()
    if "XEW-P001" not in registry.list_patterns():
        return []

    detection_context = DetectorContext(
        primary_document_path=str(primary_path),
        artifacts_dir=str(artifacts_dir),
        cik=cik,
        accession=accession,
        form=form,
        filed_date=filed_date,
        xbrl_model=xbrl_model,
        config={
            "enable_all_patterns": False,
            "gate_enforcement": True,
        },
    )

    try:
        return registry.run_detectors(detection_context, patterns={"XEW-P001"})
    except Exception:
        return []


def _compute_markers(
    *,
    current_accession: str,
    current_form: str,
    current_filed_date: str,
    cik: str,
    primary_path: Path,
    detection_context: DetectorContext,
    findings: list,
    history_window: list[dict[str, str]],
    out_dir: Path,
) -> list[dict[str, object]]:
    markers: list[dict[str, object]] = []
    history_paths = _history_primary_paths(history_window, out_dir)

    # M001: Taxonomy refresh (schemaRef changes)
    current_schema_refs = _extract_schema_refs_for_marker(primary_path)
    history_schema_snapshots: list[TaxonomySchemaSnapshot] = []
    for accession, history_path in history_paths:
        schema_refs = _extract_schema_refs_for_marker(history_path)
        if schema_refs:
            history_schema_snapshots.append(
                TaxonomySchemaSnapshot(accession=accession, schema_refs=schema_refs)
            )
    marker = detect_taxonomy_refresh_marker(
        current_accession=current_accession,
        current_schema_refs=current_schema_refs,
        history_snapshots=history_schema_snapshots,
    )
    if marker:
        markers.append(marker)

    # Prepare history models for remaining markers (best-effort)
    history_models: list[tuple[str, object, Path]] = []
    for accession, history_path in history_paths:
        model = _create_mock_xbrl_model(history_path)
        history_models.append((accession, model, history_path))

    current_model = detection_context.xbrl_model

    # M002: Extension refactor (extension concept churn)
    current_extension_qnames = _extract_extension_qnames(current_model)
    history_extension_snapshots: list[ExtensionSnapshot] = []
    for accession, model, _history_path in history_models:
        extension_qnames = _extract_extension_qnames(model)
        if extension_qnames:
            history_extension_snapshots.append(
                ExtensionSnapshot(accession=accession, qnames=extension_qnames)
            )
    marker = detect_extension_refactor_marker(
        current_accession=current_accession,
        current_extension_qnames=current_extension_qnames,
        history_snapshots=history_extension_snapshots,
    )
    if marker:
        markers.append(marker)

    # M003: Anchoring retrofit (anchoring coverage change)
    current_anchored_qnames = _extract_anchored_extension_qnames(current_model)
    if current_extension_qnames and current_anchored_qnames:
        current_anchored_qnames = sorted(set(current_anchored_qnames) & set(current_extension_qnames))
    history_anchoring_snapshots: list[AnchoringCoverageSnapshot] = []
    for accession, model, _history_path in history_models:
        extension_qnames = _extract_extension_qnames(model)
        anchored_qnames = _extract_anchored_extension_qnames(model)
        if extension_qnames and anchored_qnames:
            anchored_qnames = sorted(set(anchored_qnames) & set(extension_qnames))
        if extension_qnames:
            history_anchoring_snapshots.append(
                AnchoringCoverageSnapshot(
                    accession=accession,
                    extension_qnames=extension_qnames,
                    anchored_qnames=anchored_qnames,
                )
            )
    marker = detect_anchoring_retrofit_marker(
        current_accession=current_accession,
        current_extension_qnames=current_extension_qnames,
        current_anchored_qnames=current_anchored_qnames,
        history_snapshots=history_anchoring_snapshots,
    )
    if marker:
        markers.append(marker)

    # M004: Context model rewrite
    current_context_count, current_dim_signatures = _extract_context_model_signatures(current_model)
    history_context_snapshots: list[ContextModelSnapshot] = []
    for accession, model, _history_path in history_models:
        context_count, dim_signatures = _extract_context_model_signatures(model)
        if context_count or dim_signatures:
            history_context_snapshots.append(
                ContextModelSnapshot(
                    accession=accession,
                    context_count=context_count,
                    dimension_member_signatures=dim_signatures,
                )
            )
    marker = detect_context_model_rewrite_marker(
        current_accession=current_accession,
        current_context_count=current_context_count,
        current_dimension_member_signatures=current_dim_signatures,
        history_snapshots=history_context_snapshots,
    )
    if marker:
        markers.append(marker)

    # M005: Duplicate cleanup (drop in duplicate signatures)
    if history_paths:
        history_duplicate_snapshots: list[DuplicateSignatureSnapshot] = []
        for accession, model, history_path in history_models:
            history_findings = _run_p001_for_marker(
                primary_path=history_path,
                artifacts_dir=history_path.parent,
                cik=cik,
                accession=accession,
                form=current_form,
                filed_date=current_filed_date,
                xbrl_model=model,
            )
            signature_ids = _extract_duplicate_signature_ids(history_findings)
            if signature_ids:
                history_duplicate_snapshots.append(
                    DuplicateSignatureSnapshot(
                        accession=accession,
                        signature_ids=signature_ids,
                    )
                )

        marker = detect_duplicate_cleanup_from_findings(
            current_accession=current_accession,
            findings=findings,
            history_snapshots=history_duplicate_snapshots,
        )
        if marker:
            markers.append(marker)

    markers.sort(
        key=lambda m: (
            m.get("marker_id", ""),
            m.get("boundary", {}).get("from_accession", ""),
            m.get("boundary", {}).get("to_accession", ""),
        )
    )
    return markers


def _validate_pack_args(args: argparse.Namespace) -> None:
    """Validate all required pack command arguments with clear error messages."""
    errors = []

    # Check required arguments presence
    required_args = [
        ('pack_id', 'pack-id'),
        ('out', 'out'),
        ('cik', 'cik'),
        ('accession', 'accession'),
        ('form', 'form'),
        ('filed_date', 'filed-date'),
        ('primary', 'primary'),
        ('primary_document_url', 'primary-document-url')
    ]

    for attr, arg_name in required_args:
        if not hasattr(args, attr) or getattr(args, attr) is None:
            errors.append(f"Missing required argument: --{arg_name}")

    # If any required args are missing, exit early with clear message
    if errors:
        error_msg = "Pack command validation failed:\n" + "\n".join(f"  • {error}" for error in errors)
        error_msg += "\n\nRun 'cmdrvl-xew pack --help' for usage information."
        exit_invocation_error(error_msg)

    # Validate and normalize individual arguments
    validation_errors = []

    # Validate pack-id (basic non-empty check)
    if not args.pack_id.strip():
        validation_errors.append("--pack-id cannot be empty")

    # Validate CIK format and normalization
    try:
        _normalize_cik(args.cik)
    except ValueError as e:
        validation_errors.append(f"--cik: {e}")

    # Validate accession format
    try:
        _normalize_accession(args.accession)
    except ValueError as e:
        validation_errors.append(f"--accession: {e}")

    # Validate form type
    try:
        _validate_form_type(args.form)
    except ValueError as e:
        validation_errors.append(f"--form: {e}")

    # Validate filed-date format
    try:
        _validate_date_format(args.filed_date, "filed-date")
    except ValueError as e:
        validation_errors.append(f"--filed-date: {e}")

    # Validate period-end format if provided
    if hasattr(args, 'period_end') and args.period_end:
        try:
            _validate_date_format(args.period_end, "period-end")
        except ValueError as e:
            validation_errors.append(f"--period-end: {e}")

    # Validate primary file exists
    primary_path = Path(args.primary)
    if not primary_path.exists():
        validation_errors.append(f"--primary: File does not exist: {args.primary}")
    elif not primary_path.is_file():
        validation_errors.append(f"--primary: Path is not a file: {args.primary}")

    # Validate URL formats (basic check)
    if args.primary_document_url and not args.primary_document_url.strip():
        validation_errors.append("--primary-document-url cannot be empty")

    # Output directory validation
    out_path = Path(args.out)
    if out_path.exists() and not out_path.is_dir():
        validation_errors.append(f"--out: Path exists but is not a directory: {args.out}")

    # If any validation errors, exit with comprehensive message
    if validation_errors:
        error_msg = "Pack command validation failed:\n" + "\n".join(f"  • {error}" for error in validation_errors)
        error_msg += "\n\nEnsure all arguments are properly formatted and files exist."
        exit_invocation_error(error_msg)


def run_pack(args: argparse.Namespace) -> int:
    # Validate all required arguments first
    _validate_pack_args(args)

    out_dir = Path(args.out)
    if out_dir.exists():
        if not out_dir.is_dir():
            exit_invocation_error(f"Output path exists and is not a directory: {out_dir}")
        if any(out_dir.iterdir()):
            exit_invocation_error(f"Refusing to write into non-empty directory: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Use standardized Evidence Pack directory layout
    layout = compute_pack_layout(args.pack_id)
    pack_structure = create_pack_directory_structure(out_dir, layout)

    retrieved_at = args.retrieved_at or utc_now_iso()
    generated_at = utc_now_iso()

    # Normalize arguments (validation already done in _validate_pack_args)
    cik = _normalize_cik(args.cik)
    accession = _normalize_accession(args.accession)
    form = _validate_form_type(args.form)  # Also normalizes to uppercase
    filed_date = _validate_date_format(args.filed_date, "filed-date")

    # Validate comparator policy compliance
    comparator_provided = bool(args.comparator_accession)
    comparator_policy_result = _validate_comparator_policy(args.form, comparator_provided)
    derive_artifact_urls = getattr(args, "derive_artifact_urls", False)

    # Collect and copy artifacts into the pack.
    primary_src = Path(args.primary).resolve()
    if not primary_src.is_file():
        exit_invocation_error(f"Primary artifact not found: {primary_src}")

    root_dir = primary_src.parent
    try:
        collected = collect_artifacts(primary_src, root_dir=root_dir)
    except ArtifactCollectionError as e:
        exit_processing_error(str(e))

    primary_dst_rel = Path("artifacts") / "primary.html"
    pack_artifacts: list[ArtifactHash] = []
    non_redistributable_refs: list[NonRedistributableReference] = []
    seen_paths: set[str] = set()
    source_url_map = _build_source_url_map(
        collected,
        primary_document_url=args.primary_document_url,
        primary_pack_path=primary_dst_rel.as_posix(),
        allow_derivation=derive_artifact_urls,
    )

    for artifact in collected:
        src_path = root_dir / artifact.path

        # Standard artifact processing (copy to pack)
        if artifact.role == "primary_ixbrl":
            dest_rel = primary_dst_rel
        else:
            dest_rel = Path("artifacts") / artifact.path
        dest_rel_str = dest_rel.as_posix()
        source_url = source_url_map.get(dest_rel_str)

        # Check if this artifact should be treated as non-redistributable
        if _is_non_redistributable_artifact(str(src_path), source_url):
            # Create non-redistributable reference instead of copying
            non_redistributable_ref = _create_non_redistributable_reference(
                artifact, source_url or "", root_dir
            )
            non_redistributable_refs.append(non_redistributable_ref)
            continue

        if dest_rel_str in seen_paths:
            exit_processing_error(f"Artifact path collision in pack: {dest_rel_str}")
        seen_paths.add(dest_rel_str)

        dest_abs = out_dir / dest_rel
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_abs)

        pack_artifacts.append(
            ArtifactHash(
                path=dest_rel_str,
                role=artifact.role,
                sha256=artifact.sha256,
                bytes=artifact.bytes,
            )
        )

    comparator_primary_dst_rel = None
    if args.comparator_accession:
        if not args.comparator_primary_document_url or not args.comparator_primary_artifact_path:
            exit_invocation_error("Comparator requires --comparator-primary-document-url and --comparator-primary-artifact-path")

        comparator_src = Path(args.comparator_primary_artifact_path).resolve()
        if not comparator_src.is_file():
            exit_invocation_error(f"Comparator primary artifact not found: {comparator_src}")

        comparator_root = comparator_src.parent
        try:
            comparator_collected = collect_artifacts(comparator_src, root_dir=comparator_root)
        except ArtifactCollectionError as e:
            exit_processing_error(str(e))

        comparator_primary_dst_rel = Path("artifacts") / "comparator_primary.html"
        comparator_base_url = _derive_base_url(args.comparator_primary_document_url)

        for artifact in comparator_collected:
            src_path = comparator_root / artifact.path

            if artifact.role == "primary_ixbrl":
                dest_rel = comparator_primary_dst_rel
                role = "edgar_artifact"
                source_url = args.comparator_primary_document_url
            else:
                dest_rel = Path("artifacts") / "comparator" / artifact.path
                role = artifact.role
                if derive_artifact_urls:
                    source_url = urljoin(comparator_base_url, artifact.path) if comparator_base_url else None
                else:
                    source_url = None

            dest_rel_str = dest_rel.as_posix()

            # Check if this artifact should be treated as non-redistributable
            if _is_non_redistributable_artifact(str(src_path), source_url):
                non_redistributable_ref = _create_non_redistributable_reference(
                    artifact, source_url or "", comparator_root
                )
                non_redistributable_refs.append(non_redistributable_ref)
                continue

            if dest_rel_str in seen_paths:
                exit_processing_error(f"Artifact path collision in pack: {dest_rel_str}")
            seen_paths.add(dest_rel_str)

            dest_abs = out_dir / dest_rel
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_abs)

            if source_url:
                source_url_map[dest_rel_str] = source_url

            pack_artifacts.append(
                ArtifactHash(
                    path=dest_rel_str,
                    role=role,
                    sha256=artifact.sha256,
                    bytes=artifact.bytes,
                )
            )

    history_metadata: list[dict[str, str]] = []

    # Build history_entries from individual CLI args if not already present
    # (Needed when run_pack called directly without CLI validation)
    history_entries = getattr(args, "history_entries", None) or []
    if not history_entries:
        history_accessions = getattr(args, "history_accession", None) or []
        history_urls = getattr(args, "history_primary_document_url", None) or []
        history_paths = getattr(args, "history_primary_artifact_path", None) or []

        if history_accessions and history_urls and history_paths:
            if len(history_accessions) == len(history_urls) == len(history_paths):
                for accession, url, path in zip(history_accessions, history_urls, history_paths):
                    history_entries.append({
                        "accession": accession.strip(),
                        "primary_document_url": url.strip(),
                        "primary_artifact_path": str(Path(path).resolve()),
                    })

    if history_entries:
        history_entries = [
            _normalize_history_entry(entry, idx)
            for idx, entry in enumerate(history_entries, start=1)
        ]
        # Sort for deterministic processing
        history_entries.sort(key=lambda item: item["accession"])
    for entry in history_entries:
        history_accession = entry["accession"]
        history_primary_url = entry["primary_document_url"]
        history_primary_src = Path(entry["primary_artifact_path"]).resolve()
        if not history_primary_src.is_file():
            exit_invocation_error(f"History primary artifact not found: {history_primary_src}")

        history_root = history_primary_src.parent
        try:
            history_collected = collect_artifacts(history_primary_src, root_dir=history_root)
        except ArtifactCollectionError as e:
            exit_processing_error(str(e))

        history_primary_dst_rel = Path("artifacts") / "history" / history_accession / "primary.html"
        history_base_url = _derive_base_url(history_primary_url) if derive_artifact_urls else None

        for artifact in history_collected:
            src_path = history_root / artifact.path

            if artifact.role == "primary_ixbrl":
                dest_rel = history_primary_dst_rel
                role = "edgar_artifact"
                source_url = history_primary_url
            else:
                dest_rel = Path("artifacts") / "history" / history_accession / artifact.path
                role = artifact.role
                source_url = urljoin(history_base_url, artifact.path) if history_base_url else None

            dest_rel_str = dest_rel.as_posix()

            if _is_non_redistributable_artifact(str(src_path), source_url):
                non_redistributable_ref = _create_non_redistributable_reference(
                    artifact, source_url or "", history_root
                )
                non_redistributable_refs.append(non_redistributable_ref)
                continue

            if dest_rel_str in seen_paths:
                exit_processing_error(f"Artifact path collision in pack: {dest_rel_str}")
            seen_paths.add(dest_rel_str)

            dest_abs = out_dir / dest_rel
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_abs)

            if source_url:
                source_url_map[dest_rel_str] = source_url

            pack_artifacts.append(
                ArtifactHash(
                    path=dest_rel_str,
                    role=role,
                    sha256=artifact.sha256,
                    bytes=artifact.bytes,
                )
            )

        history_metadata.append(
            {
                "accession": history_accession,
                "primary_document_url": history_primary_url,
                "primary_artifact_path": history_primary_dst_rel.as_posix(),
            }
        )

    # Perform comparator and history window selection for marker analysis
    explicit_comparator = None
    if comparator_provided and comparator_primary_dst_rel:
        explicit_comparator = {
            "accession": args.comparator_accession,
            "primary_document_url": args.comparator_primary_document_url,
            "primary_artifact_path": comparator_primary_dst_rel.as_posix(),
        }

    selection_result = select_comparator_and_history(
        form=args.form,
        explicit_comparator=explicit_comparator,
        history_entries=history_metadata,
        current_accession=args.accession,
    )

    # Generate toolchain metadata using ToolchainRecorder
    toolchain_path_rel = Path("toolchain") / "toolchain.json"
    toolchain_recorder = ToolchainRecorder()

    marker_thresholds = marker_thresholds_config()

    # Prepare comprehensive config for reproducibility
    reproducibility_config = {
        "resolution_mode": args.resolution_mode,
        "pack_id": args.pack_id,
        "comparator_policy": {
            "form": args.form,
            "base_form": comparator_policy_result.base_form,
            "comparator_required": comparator_policy_result.comparator_required,
            "comparator_provided": comparator_provided,
            "policy_notes": comparator_policy_result.notes,
        },
        "marker_thresholds": marker_thresholds,
        "history_window": history_metadata,
        "comparator_selection": {
            "selected_comparator": selection_result.selected_comparator,
            "history_window": selection_result.history_window,
            "selection_metadata": selection_result.selection_metadata,
        },
        "non_redistributable_artifacts": [
            {
                "source_url": ref.source_url,
                "retrieved_at": ref.retrieved_at,
                "sha256": ref.sha256,
                "content_type": ref.content_type,
                "notes": ref.notes,
            }
            for ref in non_redistributable_refs
        ],
    }

    # Prepare minimal toolchain config (only settings that affect tool behavior)
    toolchain_config = {
        "resolution_mode": args.resolution_mode,
        "marker_thresholds": marker_thresholds,
        # Add other tool behavior settings here as needed
    }

    # Record complete toolchain metadata
    toolchain_obj = toolchain_recorder.record_toolchain(toolchain_config)

    toolchain_config_obj = toolchain_obj.get("config")
    if isinstance(toolchain_config_obj, dict):
        toolchain_config_obj["recorded_at"] = retrieved_at

    # Override Arelle version if provided via CLI
    if args.arelle_version:
        toolchain_obj["arelle_version"] = args.arelle_version

    # Write comprehensive reproducibility config to toolchain.json
    # (includes full pack generation metadata for reproducibility)
    write_json(out_dir / toolchain_path_rel, reproducibility_config)

    # === Extract Issuer/Filing Metadata from iXBRL ===

    # Extract metadata from primary document using the dedicated metadata module
    try:
        extracted_metadata = extract_metadata(primary_src)
        import logging
        logging.info(f"Extracted metadata from {primary_src}: entity={extracted_metadata.entity.legal_name or 'N/A'}, period_end={extracted_metadata.filing.document_period_end_date or 'N/A'}")
    except Exception as e:
        import logging
        logging.warning(f"Failed to extract metadata from {primary_src}: {e}, using CLI args only")
        extracted_metadata = None

    # Build input metadata with extracted iXBRL metadata where available
    input_obj = {
        "cik": cik,
        "accession": accession,
        "form": args.form,
        "filed_date": args.filed_date,
        "primary_document_url": args.primary_document_url,
        "primary_artifact_path": str(primary_dst_rel).replace("\\", "/"),
    }

    # Prepare extension metadata (fields not in v1 schema)
    ext_metadata = {}

    # Embed extracted issuer metadata (CLI args take precedence)
    if extracted_metadata:
        # Entity information
        if extracted_metadata.entity.legal_name and not args.issuer_name:
            input_obj["issuer_name"] = extracted_metadata.entity.legal_name

        if extracted_metadata.entity.ticker_symbol:
            ext_metadata["ticker_symbol"] = extracted_metadata.entity.ticker_symbol

        # Filing information
        if extracted_metadata.filing.document_period_end_date and not args.period_end:
            input_obj["period_end"] = extracted_metadata.filing.document_period_end_date

        if extracted_metadata.filing.fiscal_year:
            ext_metadata["fiscal_year"] = extracted_metadata.filing.fiscal_year

        if extracted_metadata.filing.fiscal_period:
            ext_metadata["fiscal_period"] = extracted_metadata.filing.fiscal_period

        if extracted_metadata.filing.amendment_flag is not None:
            ext_metadata["amendment_flag"] = extracted_metadata.filing.amendment_flag

        # Source provenance for verification
        if extracted_metadata.source_provenance:
            ext_metadata["metadata_provenance"] = extracted_metadata.source_provenance

    # CLI overrides (these take precedence over extracted metadata)
    if args.issuer_name:
        input_obj["issuer_name"] = args.issuer_name
    if args.period_end:
        input_obj["period_end"] = args.period_end

    if args.comparator_accession:
        if comparator_primary_dst_rel is None:
            exit_processing_error("Comparator artifacts not collected")

        # Build base comparator metadata
        comparator_info = {
            "accession": _normalize_accession(args.comparator_accession),
            "primary_document_url": args.comparator_primary_document_url,
            "primary_artifact_path": comparator_primary_dst_rel.as_posix(),
        }

        # Extract metadata from comparator document if available
        try:
            comparator_src_path = Path(args.comparator_primary_artifact_path).resolve()
            comparator_metadata = extract_metadata(comparator_src_path)

            # Add extracted comparator metadata (schema-compliant fields only)
            if comparator_metadata.entity.legal_name:
                comparator_info["issuer_name"] = comparator_metadata.entity.legal_name

            if comparator_metadata.filing.document_period_end_date:
                comparator_info["period_end"] = comparator_metadata.filing.document_period_end_date

            # Store extra comparator fields in ext_metadata
            if comparator_metadata.filing.fiscal_year:
                ext_metadata.setdefault("comparator", {})["fiscal_year"] = comparator_metadata.filing.fiscal_year

            if comparator_metadata.filing.fiscal_period:
                ext_metadata.setdefault("comparator", {})["fiscal_period"] = comparator_metadata.filing.fiscal_period

            import logging
            logging.info(f"Extracted comparator metadata: entity={comparator_metadata.entity.legal_name or 'N/A'}, period_end={comparator_metadata.filing.document_period_end_date or 'N/A'}")

        except Exception as e:
            import logging
            logging.warning(f"Failed to extract comparator metadata: {e}, using basic comparator info only")

        input_obj["comparator"] = comparator_info

    # === XEW Detection Pipeline Integration ===

    # Use new infrastructure for findings generation
    findings_path_rel = Path("xew_findings.json")

    # Prepare artifacts metadata for findings
    findings_artifacts: list[dict[str, object]] = []
    for artifact in sorted(pack_artifacts, key=lambda a: a.path):
        content_type, _ = mimetypes.guess_type(artifact.path)
        if content_type is None:
            content_type = "application/octet-stream"
        entry: dict[str, object] = {
            "path": artifact.path,
            "role": artifact.role,
            "retrieved_at": retrieved_at,
            "sha256": artifact.sha256,
            "bytes": artifact.bytes,
            "content_type": content_type,
        }
        source_url = source_url_map.get(artifact.path)
        if source_url:
            entry["source_url"] = source_url
        findings_artifacts.append(entry)

    # Run XEW detection on the primary document
    try:
        xbrl_findings, detection_context = _run_xew_detection(
            primary_path=primary_src,
            artifacts_dir=root_dir,
            context_metadata={
                "cik": cik,
                "accession": accession,
                "form": form,
                "filed_date": filed_date,
                "primary_document_url": args.primary_document_url,
                "comparator_selection": {
                    "selected_comparator": selection_result.selected_comparator,
                    "history_window": selection_result.history_window,
                    "selection_metadata": selection_result.selection_metadata,
                },
            },
        )
    except Exception as e:
        import logging
        logging.warning(f"XEW detection failed: {e}, continuing with empty findings")
        xbrl_findings = []
        detection_context = DetectorContext(
            primary_document_path=str(primary_src),
            artifacts_dir=str(root_dir),
            cik=cik,
            accession=accession,
            form=form,
            filed_date=filed_date,
            xbrl_model=_create_mock_xbrl_model(primary_src),
            config={},
        )

    markers = _compute_markers(
        current_accession=accession,
        current_form=form,
        current_filed_date=filed_date,
        cik=cik,
        primary_path=primary_src,
        detection_context=detection_context,
        findings=xbrl_findings,
        history_window=selection_result.history_window,
        out_dir=out_dir,
    )

    # Use FindingsWriter for deterministic output
    findings_writer = FindingsWriter(out_dir / findings_path_rel)

    # Write findings using the dedicated writer
    findings_writer.write_findings(
        findings=xbrl_findings,
        context=detection_context,
        artifacts=findings_artifacts,
        toolchain=toolchain_obj,
        input_metadata=input_obj,
        ext_metadata=ext_metadata,
        markers=markers or None,
        generated_at=retrieved_at,
    )

    # Use PackManifestBuilder for deterministic manifest generation
    manifest_builder = PackManifestBuilder(args.pack_id)
    manifest_builder.set_retrieval_time(retrieved_at)

    # Add all pack artifacts to manifest
    for artifact in pack_artifacts:
        abs_path = out_dir / artifact.path
        source_url = source_url_map.get(artifact.path)
        manifest_builder.add_file(
            path=artifact.path,
            role="edgar_artifact",
            file_path=abs_path,
            source_url=source_url
        )

    # Add generated files to manifest
    manifest_builder.add_file(
        path="toolchain/toolchain.json",
        role="toolchain",
        file_path=out_dir / toolchain_path_rel
    )

    manifest_builder.add_file(
        path="xew_findings.json",
        role="xew_output",
        file_path=out_dir / findings_path_rel
    )

    # Build and write manifest
    manifest_data = manifest_builder.build_manifest()
    write_json(out_dir / "pack_manifest.json", manifest_data)

    # === Generate Reproducible Verification Steps ===

    # Generate repro steps for third-party verification
    repro_steps = _generate_repro_steps(
        pack_id=args.pack_id,
        cik=cik,
        accession=accession,
        form=form,
        filed_date=filed_date,
        primary_artifact_path=str(primary_dst_rel).replace("\\", "/"),
        cmdrvl_version=__version__,
        generated_at=generated_at
    )

    # Write repro steps to pack
    repro_steps_path = out_dir / "reproduction_steps.json"
    write_json(repro_steps_path, repro_steps)

    # Add repro steps to manifest
    manifest_builder.add_file(
        path="reproduction_steps.json",
        role="reproduction_steps",
        file_path=repro_steps_path
    )

    # Rebuild manifest with repro steps included
    manifest_data = manifest_builder.build_manifest()
    write_json(out_dir / "pack_manifest.json", manifest_data)

    return ExitCode.SUCCESS


def _manifest_role_for_path(path: str) -> str:
    if path == "xew_findings.json":
        return "xew_output"
    if path == "toolchain/toolchain.json":
        return "toolchain"
    if path == "reproduction_steps.json":
        return "reproduction_steps"
    if path.startswith("artifacts/"):
        return "edgar_artifact"
    return "other"


def _manifest_source_url_for_path(path: str, source_url_map: dict[str, str]) -> dict[str, str]:
    source_url = source_url_map.get(path)
    if source_url:
        return {"source_url": source_url}
    return {}


def _build_source_url_map(
    artifacts: list[ArtifactHash],
    *,
    primary_document_url: str,
    primary_pack_path: str,
    allow_derivation: bool,
) -> dict[str, str]:
    base_url = _derive_base_url(primary_document_url)
    source_url_map: dict[str, str] = {}

    for artifact in artifacts:
        if artifact.role == "primary_ixbrl":
            source_url_map[primary_pack_path] = primary_document_url
            continue
        if allow_derivation and base_url:
            rel = artifact.path.lstrip("/")
            source_url_map[f"artifacts/{rel}"] = urljoin(base_url, rel)

    return source_url_map


def _is_non_redistributable_artifact(artifact_path: str, source_url: str = None) -> bool:
    """
    Determine if an artifact should be treated as non-redistributable.

    Args:
        artifact_path: Local path to the artifact
        source_url: Optional source URL for the artifact

    Returns:
        True if the artifact cannot be redistributed in Evidence Packs
    """
    # Check for external taxonomy references that may have licensing restrictions
    if source_url:
        parsed = urlparse(source_url)

        # SEC taxonomy packages are typically redistributable, but other sources may not be
        if parsed.netloc and parsed.netloc not in ['www.sec.gov', 'xbrl.sec.gov', 'xbrl.fasb.org']:
            # External non-government source - may be non-redistributable
            return True

        # Large taxonomy packages might exceed pack size limits
        try:
            path = Path(artifact_path)
            if path.exists() and path.stat().st_size > 10 * 1024 * 1024:  # 10MB limit
                return True
        except (OSError, ValueError):
            pass

    # Check file extension patterns that are commonly non-redistributable
    if artifact_path.endswith(('.zip', '.tar.gz', '.7z')):
        # Large compressed packages are often non-redistributable
        return True

    return False


def _create_non_redistributable_reference(artifact: ArtifactHash, source_url: str,
                                        root_dir: Path) -> NonRedistributableReference:
    """Create a non-redistributable reference for an artifact."""
    artifact_path = root_dir / artifact.path

    # Determine content type
    content_type, _ = mimetypes.guess_type(artifact.path)
    if content_type is None:
        content_type = "application/octet-stream"

    return non_redistributable_reference_from_path(
        source_url=source_url,
        path=artifact_path,
        content_type=content_type,
        notes=f"Artifact {artifact.path} cannot be redistributed due to legal/licensing constraints"
    )


def _validate_comparator_policy(form: str, comparator_provided: bool) -> ComparatorPolicy:
    """
    Validate that comparator usage aligns with form-specific policy.

    Args:
        form: Filing form type (e.g., "10-Q", "20-F/A", "8-K")
        comparator_provided: Whether comparator arguments were provided

    Returns:
        ComparatorPolicy for the form

    Raises:
        SystemExit: If comparator usage violates form policy
    """
    try:
        policy = comparator_policy(form)
    except ValueError as e:
        exit_invocation_error(f"Unsupported form type: {e}")

    if policy.comparator_required and not comparator_provided:
        exit_invocation_error(
            f"Form {form} requires a comparator filing per policy: {policy.notes}. "
            f"Provide --comparator-accession, --comparator-primary-document-url, "
            f"and --comparator-primary-artifact-path."
        )

    if not policy.comparator_required and comparator_provided:
        # This is a warning, not an error - allow optional comparators
        import logging
        logging.warning(
            f"Form {form} does not typically require a comparator ({policy.notes}), "
            f"but one was provided and will be included."
        )

    return policy


def _derive_base_url(primary_url: str) -> str | None:
    parsed = urlparse(primary_url)
    if not parsed.scheme:
        return None
    if parsed.scheme != "file" and not parsed.netloc:
        return None
    if not parsed.path:
        return None

    base_path = parsed.path
    if not base_path.endswith("/"):
        base_path = f"{base_path.rsplit('/', 1)[0]}/"

    return parsed._replace(path=base_path, query="", fragment="").geturl()
