"""P009 broad-corpus identity-fragility workflow coordinator."""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .instrument_registry import InstrumentRegistrySnapshot, RegistrySnapshotError
from .p009_corpus import P009CorpusSource, load_p009_corpus
from .p009_identity_ledger import InstrumentRegistryP009Lookup
from .p009_observations import P009InstrumentObservation
from .p009_scan import P009ScanCandidate, scan_p009_corpus, write_p009_scan_outputs
from .pack import run_pack
from .registry_materialize import RegistryMaterializationError, materialize_registry_from_corpus
from .util import sha256_file, write_json
from .verify import run_verify_pack


class P009WorkflowError(ValueError):
    """Raised when the P009 broad-corpus workflow cannot proceed."""


_SUPPORTED_REGISTRY_SEED_TYPES = {"cusip", "isin", "sedol", "figi"}


def run_p009_identity_drift_workflow(args: argparse.Namespace) -> int:
    """CLI entry point for the P009 broad-corpus workflow."""

    try:
        summary = run_p009_workflow(args)
    except P009WorkflowError as exc:
        exit_processing_error(str(exc))
    except RegistryMaterializationError as exc:
        exit_processing_error(str(exc))
    except OSError as exc:
        exit_invocation_error(str(exc))

    print(json.dumps(summary, indent=2, sort_keys=True))
    return ExitCode.SUCCESS


def run_p009_workflow(args: argparse.Namespace) -> dict[str, object]:
    """Run or dry-run scan -> select -> seed -> pack -> verify for P009."""

    manifest_path = Path(args.manifest).expanduser().resolve()
    observations_path = Path(args.observations).expanduser().resolve() if args.observations else None
    registry_snapshot_path = (
        Path(args.registry_snapshot).expanduser().resolve() if args.registry_snapshot else None
    )
    artifacts_root = Path(args.artifacts_root).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    dry_run = bool(args.dry_run)
    stop_after = str(getattr(args, "stop_after", "") or "")

    if not manifest_path.is_file():
        raise P009WorkflowError(f"P009 corpus manifest not found: {manifest_path}")
    if observations_path is not None and not observations_path.is_file():
        raise P009WorkflowError(f"P009 observations file not found: {observations_path}")
    if registry_snapshot_path is not None and not registry_snapshot_path.is_file():
        raise P009WorkflowError(f"P009 registry snapshot not found: {registry_snapshot_path}")
    if not artifacts_root.is_dir():
        raise P009WorkflowError(f"P009 artifacts root is not a directory: {artifacts_root}")
    if stop_after and stop_after not in {"scan", "seeds"}:
        raise P009WorkflowError("--stop-after must be one of: scan, seeds")

    registry_provider = _registry_provider(registry_snapshot_path)
    corpus = load_p009_corpus(manifest_path, observations_path=observations_path)
    result = scan_p009_corpus(corpus, registry_snapshot=registry_provider, limit=getattr(args, "limit", None))
    selected = _candidate_by_rank(result.candidates, int(getattr(args, "select_rank", 1) or 1))

    paths = _workflow_paths(out_dir)
    issue_counts = _issue_counts(result.candidates)
    summary: dict[str, object] = {
        "schema_id": "cmdrvl.xew.p009_identity_fragility_workflow",
        "schema_version": "1.0",
        "mode": "dry_run" if dry_run else "execute",
        "inputs": {
            "manifest": str(manifest_path),
            "observations": str(observations_path) if observations_path else "",
            "registry_snapshot": str(registry_snapshot_path) if registry_snapshot_path else "",
            "artifacts_root": str(artifacts_root),
            "select_rank": int(getattr(args, "select_rank", 1) or 1),
            "limit": int(args.limit) if getattr(args, "limit", None) is not None else None,
        },
        "scan": {
            "manifest_input_sha256": result.manifest_input_sha256,
            "observations_input_sha256": result.observations_input_sha256,
            "manifest_row_count": result.manifest_row_count,
            "observation_row_count": result.observation_row_count,
            "source_count": result.source_count,
            "observation_count": result.observation_count,
            "candidate_count": len(result.candidates),
            "issue_code_counts": issue_counts,
            "output_dir": str(paths["scan_dir"]),
            "status": "planned" if dry_run else "pending",
        },
        "selected_candidate": _candidate_summary(selected),
        "registry_plan": {},
        "pack": {},
        "verify": {},
        "diagnostics": list(result.diagnostics),
        "no_live_sec": True,
        "no_live_openfigi": not bool(getattr(args, "allow_live_provider", False)),
    }

    selected_sources = _sources_for_candidate(corpus.sources, selected)
    current_source, history_sources = _select_current_and_history(selected_sources)
    selected_observations = _observations_for_candidate(corpus.observations, selected)

    registry_seed_plan = _registry_seed_plan(
        selected,
        seed_dir=paths["seed_dir"],
        corpus_id=_corpus_id(args, selected),
        provider_configs=list(getattr(args, "provider_config", None) or []),
        provider_source=str(getattr(args, "provider_source", "openfigi") or "openfigi"),
        registry_work_dir=paths["registry_work_dir"],
        registry_version=str(getattr(args, "registry_version", "") or "p009"),
        canon_bin=str(getattr(args, "canon_bin", "") or "canon"),
        incremental=bool(getattr(args, "incremental", False)),
        allow_live_provider=bool(getattr(args, "allow_live_provider", False)),
    )
    summary["registry_plan"] = registry_seed_plan

    pack_plan = _safe_pack_plan(
        args,
        selected=selected,
        current_source=current_source,
        history_sources=history_sources,
        selected_observations=selected_observations,
        selected_observations_path=paths["selected_observations"],
        pack_dir=paths["pack_dir"],
        registry_snapshot_path=registry_snapshot_path,
        artifacts_root=artifacts_root,
        allow_unavailable=dry_run or bool(stop_after),
    )
    summary["pack"] = pack_plan
    summary["verify"] = {
        "status": "planned",
        "command": ["cmdrvl-xew", "verify-pack", "--pack", str(paths["pack_dir"]), "--validate-schema"],
    }

    if dry_run:
        return summary

    _ensure_output_paths_available(paths, stop_after=stop_after, materialize=_materialize_requested(args))
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_paths = write_p009_scan_outputs(result, paths["scan_dir"])
    summary["scan"] = {
        **summary["scan"],
        "status": "completed",
        "outputs": scan_paths,
    }
    if stop_after == "scan":
        summary["status"] = "stopped_after_scan"
        _write_summary(paths["summary"], summary)
        return summary

    _write_seed_outputs(selected, paths["seed_dir"], registry_seed_plan)
    summary["registry_plan"] = {
        **registry_seed_plan,
        "status": "seeds_written",
        "seed_files": _seed_file_metadata(paths["seed_dir"]),
    }

    if stop_after == "seeds":
        summary["status"] = "stopped_after_seeds"
        _write_summary(paths["summary"], summary)
        return summary

    if _materialize_requested(args):
        materialization = materialize_registry_from_corpus(
            corpus_id=_corpus_id(args, selected),
            out_dir=paths["registry_work_dir"],
            filing_manifest=None,
            seed_files=[Path(item["path"]) for item in summary["registry_plan"]["seed_files"]],
            version=str(getattr(args, "registry_version", "") or "p009"),
            provider_source=str(getattr(args, "provider_source", "openfigi") or "openfigi"),
            provider_configs=list(getattr(args, "provider_config", None) or []),
            canon_bin=str(getattr(args, "canon_bin", "") or "canon"),
            run_canon=bool(getattr(args, "run_canon", False)),
            incremental=bool(getattr(args, "incremental", False)),
            allow_live_provider=bool(getattr(args, "allow_live_provider", False)),
        )
        summary["registry_plan"] = {
            **summary["registry_plan"],
            "status": "materialized" if getattr(args, "run_canon", False) else "materialization_planned",
            "materialization_manifest": materialization.get("manifest_path", ""),
            "registry_builds": materialization.get("registry_builds", []),
        }

    _write_selected_observations(paths["selected_observations"], selected_observations)
    pack_args = _pack_args_from_plan(pack_plan)
    quiet_steps = not bool(getattr(args, "verbose", False))
    with _operator_step_output(quiet_steps):
        pack_rc = run_pack(pack_args)
    if pack_rc != ExitCode.SUCCESS:
        raise P009WorkflowError(f"pack failed with exit code {pack_rc}")
    summary["pack"] = _pack_completed_summary(pack_plan, paths["selected_observations"], paths["pack_dir"])

    verify_args = SimpleNamespace(
        pack=str(paths["pack_dir"]),
        validate_schema=True,
        quiet=True,
        verbose=False,
        check_only=False,
        fail_fast=False,
    )
    with _operator_step_output(quiet_steps):
        verify_rc = run_verify_pack(verify_args)
    if verify_rc != ExitCode.SUCCESS:
        raise P009WorkflowError(f"verify-pack failed with exit code {verify_rc}")
    summary["verify"] = {
        "status": "passed",
        "command": ["cmdrvl-xew", "verify-pack", "--pack", str(paths["pack_dir"]), "--validate-schema"],
    }
    summary["status"] = "completed"
    _write_summary(paths["summary"], summary)
    return summary


@contextmanager
def _operator_step_output(quiet: bool):
    if not quiet:
        yield
        return
    previous_disable = logging.root.manager.disable
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        logging.disable(logging.CRITICAL)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield
    finally:
        logging.disable(previous_disable)


def _workflow_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "scan_dir": out_dir / "scan",
        "seed_dir": out_dir / "registry_seeds",
        "selected_dir": out_dir / "selected",
        "selected_observations": out_dir / "selected" / "p009_selected_observations.v1.jsonl",
        "registry_work_dir": out_dir / "registry_materialization",
        "pack_dir": out_dir / "pack",
        "summary": out_dir / "p009_identity_fragility_summary.v1.json",
    }


def _registry_provider(path: Path | None) -> InstrumentRegistryP009Lookup | None:
    if path is None:
        return None
    try:
        return InstrumentRegistryP009Lookup(InstrumentRegistrySnapshot.load(path))
    except RegistrySnapshotError as exc:
        return InstrumentRegistryP009Lookup(snapshot_error=exc)


def _candidate_by_rank(candidates: tuple[P009ScanCandidate, ...], rank: int) -> P009ScanCandidate:
    if rank < 1:
        raise P009WorkflowError("--select-rank must be 1 or greater")
    for candidate in candidates:
        if candidate.rank == rank:
            return candidate
    raise P009WorkflowError(f"no P009 scan candidate at rank {rank}; candidates available: {len(candidates)}")


def _issue_counts(candidates: tuple[P009ScanCandidate, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for code in candidate.issue_codes:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _candidate_summary(candidate: P009ScanCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "rank": candidate.rank,
        "source_scope_key": candidate.source_scope_key,
        "issue_codes": list(candidate.issue_codes),
        "issue_code_counts": {code: candidate.issue_codes.count(code) for code in sorted(set(candidate.issue_codes))},
        "continuity_class": candidate.continuity_class,
        "registry_status": candidate.registry_status,
        "score": candidate.score,
        "source_ids": list(candidate.source_ids),
        "accessions": list(candidate.accessions),
        "report_periods": list(candidate.report_periods),
        "filed_dates": list(candidate.filed_dates),
        "event_count": len(candidate.event_ids),
        "seed_count": len(candidate.seed_identifiers),
    }


def _sources_for_candidate(
    sources: tuple[P009CorpusSource, ...],
    candidate: P009ScanCandidate,
) -> tuple[P009CorpusSource, ...]:
    source_ids = set(candidate.source_ids)
    selected = tuple(
        sorted(
            (source for source in sources if source.scope_key == candidate.source_scope_key and source.source_id in source_ids),
            key=lambda source: source.sort_key,
        )
    )
    if not selected:
        raise P009WorkflowError(f"selected candidate has no matching manifest sources: {candidate.candidate_id}")
    return selected


def _select_current_and_history(
    sources: tuple[P009CorpusSource, ...],
) -> tuple[P009CorpusSource, tuple[P009CorpusSource, ...]]:
    current = sorted(
        sources,
        key=lambda source: (
            source.filed_date,
            source.report_period,
            source.accession,
            source.source_record_id,
            source.artifact_ref,
        ),
    )[-1]
    history = tuple(source for source in sources if source != current)
    return current, tuple(sorted(history, key=lambda source: source.sort_key))


def _observations_for_candidate(
    observations: tuple[P009InstrumentObservation, ...],
    candidate: P009ScanCandidate,
) -> tuple[P009InstrumentObservation, ...]:
    selected_ids = set(candidate.observation_ids)
    selected = tuple(sorted((item for item in observations if item.observation_id in selected_ids), key=lambda item: item.sort_key))
    if len(selected) != len(selected_ids):
        missing = sorted(selected_ids - {item.observation_id for item in selected})
        raise P009WorkflowError(f"selected candidate observations are missing from corpus: {missing}")
    return selected


def _registry_seed_plan(
    candidate: P009ScanCandidate,
    *,
    seed_dir: Path,
    corpus_id: str,
    provider_configs: list[str],
    provider_source: str,
    registry_work_dir: Path,
    registry_version: str,
    canon_bin: str,
    incremental: bool,
    allow_live_provider: bool,
) -> dict[str, object]:
    seed_files = []
    unsupported = []
    for id_type, values in _group_seed_values(candidate).items():
        if id_type in _SUPPORTED_REGISTRY_SEED_TYPES:
            seed_files.append(
                {
                    "id_type": id_type,
                    "path": str(seed_dir / f"{id_type}.csv"),
                    "count": len(values),
                    "values": values,
                }
            )
        else:
            unsupported.append({"id_type": id_type, "values": values, "count": len(values)})

    command = [
        "cmdrvl-xew",
        "p008",
        "materialize-registry",
        "--corpus-id",
        corpus_id,
        "--out-dir",
        str(registry_work_dir),
        "--version",
        registry_version,
        "--provider-source",
        provider_source,
    ]
    for seed_file in seed_files:
        command.extend(["--seed-file", str(seed_file["path"])])
    if incremental:
        command.append("--incremental")
    if allow_live_provider:
        command.append("--allow-live-provider")
    for item in _sanitize_provider_config_args(provider_configs):
        command.extend(["--provider-config", item])
    return {
        "status": "planned",
        "corpus_id": corpus_id,
        "seed_files": seed_files,
        "unsupported_seed_identifiers": unsupported,
        "materialization_command": command,
        "run_canon_command": [*command, "--run-canon", "--canon-bin", canon_bin],
    }


def _group_seed_values(candidate: P009ScanCandidate) -> dict[str, list[str]]:
    grouped: dict[str, set[str]] = {}
    for seed in candidate.seed_identifiers:
        id_type = str(seed.get("id_type", "")).strip().lower()
        value = str(seed.get("value", "")).strip()
        if not id_type or not value:
            continue
        grouped.setdefault(id_type, set()).add(value)
    return {key: sorted(values) for key, values in sorted(grouped.items())}


def _sanitize_provider_config_args(items: list[str]) -> list[str]:
    sanitized = []
    for item in items:
        key, sep, value = item.partition("=")
        if not sep:
            sanitized.append(item)
            continue
        if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
            sanitized.append(f"{key}=[redacted]")
        else:
            sanitized.append(f"{key}={value}")
    return sanitized


def _pack_plan(
    args: argparse.Namespace,
    *,
    selected: P009ScanCandidate,
    current_source: P009CorpusSource,
    history_sources: tuple[P009CorpusSource, ...],
    selected_observations: tuple[P009InstrumentObservation, ...],
    selected_observations_path: Path,
    pack_dir: Path,
    registry_snapshot_path: Path | None,
    artifacts_root: Path,
) -> dict[str, object]:
    current_primary = _resolve_local_artifact(current_source, artifacts_root=artifacts_root)
    if not current_source.accession:
        raise P009WorkflowError("selected current source must have an SEC accession for Evidence Pack generation")
    cik = str(getattr(args, "cik", "") or current_source.accession.split("-", 1)[0]).zfill(10)
    form = str(getattr(args, "form", "") or current_source.form or "").upper()
    if not form:
        raise P009WorkflowError("selected current source must provide form, or pass --form")
    filed_date = str(getattr(args, "filed_date", "") or current_source.filed_date or "")
    if not filed_date:
        raise P009WorkflowError("selected current source must provide filed_date, or pass --filed-date")
    primary_url = str(getattr(args, "primary_document_url", "") or current_source.primary_document_url or "")
    if not primary_url:
        raise P009WorkflowError("selected current source must provide primary_document_url, or pass --primary-document-url")
    history_entries = []
    for source in history_sources:
        if not source.accession or not source.primary_document_url:
            continue
        history_entries.append(
            {
                "accession": source.accession,
                "primary_document_url": source.primary_document_url,
                "primary_artifact_path": str(_resolve_local_artifact(source, artifacts_root=artifacts_root)),
            }
        )

    pack_id = str(getattr(args, "pack_id", "") or f"XEW-P009-{selected.candidate_id[:12]}")
    command = [
        "cmdrvl-xew",
        "pack",
        "--pack-id",
        pack_id,
        "--out",
        str(pack_dir),
        "--primary",
        str(current_primary),
        "--cik",
        cik,
        "--accession",
        current_source.accession,
        "--form",
        form,
        "--filed-date",
        filed_date,
        "--primary-document-url",
        primary_url,
        "--p009-observations",
        str(selected_observations_path),
    ]
    period_end = str(getattr(args, "period_end", "") or current_source.report_period or "")
    if period_end:
        command.extend(["--period-end", period_end])
    if registry_snapshot_path is not None:
        command.extend(["--p008-registry-snapshot", str(registry_snapshot_path)])
    for entry in history_entries:
        command.extend(["--history-accession", entry["accession"]])
        command.extend(["--history-primary-document-url", entry["primary_document_url"]])
        command.extend(["--history-primary-artifact-path", entry["primary_artifact_path"]])
    if getattr(args, "retrieved_at", None):
        command.extend(["--retrieved-at", str(args.retrieved_at)])
    if getattr(args, "require_arelle", False):
        command.append("--require-arelle")
    else:
        command.append("--no-arelle")

    return {
        "status": "planned",
        "pack_id": pack_id,
        "pack_path": str(pack_dir),
        "command": command,
        "current_source": current_source.to_json(),
        "current_primary_artifact": str(current_primary),
        "history_entries": history_entries,
        "selected_observations_path": str(selected_observations_path),
        "selected_observation_count": len(selected_observations),
    }


def _safe_pack_plan(
    args: argparse.Namespace,
    *,
    selected: P009ScanCandidate,
    current_source: P009CorpusSource,
    history_sources: tuple[P009CorpusSource, ...],
    selected_observations: tuple[P009InstrumentObservation, ...],
    selected_observations_path: Path,
    pack_dir: Path,
    registry_snapshot_path: Path | None,
    artifacts_root: Path,
    allow_unavailable: bool,
) -> dict[str, object]:
    try:
        return _pack_plan(
            args,
            selected=selected,
            current_source=current_source,
            history_sources=history_sources,
            selected_observations=selected_observations,
            selected_observations_path=selected_observations_path,
            pack_dir=pack_dir,
            registry_snapshot_path=registry_snapshot_path,
            artifacts_root=artifacts_root,
        )
    except P009WorkflowError as exc:
        if not allow_unavailable:
            raise
        return {
            "status": "unavailable",
            "reason": str(exc),
            "pack_id": str(getattr(args, "pack_id", "") or f"XEW-P009-{selected.candidate_id[:12]}"),
            "pack_path": str(pack_dir),
            "command": [],
            "current_source": current_source.to_json(),
            "history_entries": [],
            "selected_observations_path": str(selected_observations_path),
            "selected_observation_count": len(selected_observations),
        }


def _resolve_local_artifact(source: P009CorpusSource, *, artifacts_root: Path) -> Path:
    if not source.local_path:
        raise P009WorkflowError(
            f"source {source.source_id} has no local_path; materialize cached artifacts before running pack"
        )
    raw = Path(source.local_path)
    candidates = [raw] if raw.is_absolute() else [artifacts_root / raw]
    manifest_path = Path(source.manifest_path)
    if not raw.is_absolute() and manifest_path:
        candidates.append(manifest_path.parent / raw)
    for path in candidates:
        resolved = path.resolve()
        if resolved.is_file():
            return resolved
    raise P009WorkflowError(f"local cached artifact missing for source {source.source_id}: {source.local_path}")


def _pack_args_from_plan(plan: dict[str, object]) -> SimpleNamespace:
    current = plan["current_source"]
    history_entries = plan["history_entries"]
    command = plan["command"]
    if not isinstance(current, dict):
        raise P009WorkflowError("pack plan current_source must be an object")
    if not isinstance(history_entries, list):
        raise P009WorkflowError("pack plan history_entries must be a list")
    if not isinstance(command, list):
        raise P009WorkflowError("pack plan command must be a list")

    def option(name: str, default: str = "") -> str:
        if name not in command:
            return default
        index = command.index(name)
        if index + 1 >= len(command):
            return default
        return str(command[index + 1])

    return SimpleNamespace(
        pack_id=str(plan["pack_id"]),
        out=str(plan["pack_path"]),
        primary=str(plan["current_primary_artifact"]),
        issuer_name=str(current.get("source_name", "") or current.get("source_scope_key", "") or current.get("scope_key", "")),
        cik=option("--cik"),
        accession=option("--accession"),
        form=option("--form"),
        filed_date=option("--filed-date"),
        period_end=option("--period-end") or None,
        primary_document_url=option("--primary-document-url"),
        comparator_accession=None,
        comparator_primary_document_url=None,
        comparator_primary_artifact_path=None,
        history_accession=None,
        history_primary_document_url=None,
        history_primary_artifact_path=None,
        history_entries=history_entries,
        retrieved_at=option("--retrieved-at") or None,
        arelle_version=None,
        resolution_mode="offline_preferred",
        require_arelle="--require-arelle" in command,
        no_arelle="--no-arelle" in command,
        arelle_xdg_config_home=None,
        derive_artifact_urls=False,
        p001_conflict_mode="rounded",
        p008_registry_snapshot=option("--p008-registry-snapshot") or None,
        p008_require_registry=False,
        p009_observations=[str(plan["selected_observations_path"])],
    )


def _write_seed_outputs(selected: P009ScanCandidate, seed_dir: Path, plan: dict[str, object]) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    rows_path = seed_dir / "p009_selected_registry_seeds.v1.jsonl"
    rows = []
    for seed in selected.seed_identifiers:
        rows.append(
            {
                "candidate_id": selected.candidate_id,
                "source_scope_key": selected.source_scope_key,
                "rank": selected.rank,
                "id_type": seed.get("id_type", ""),
                "value": seed.get("value", ""),
                "observation_ids": seed.get("observation_ids", []),
            }
        )
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda item: (str(item["id_type"]), str(item["value"]))):
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")

    for seed_file in plan["seed_files"]:
        path = Path(str(seed_file["path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow([seed_file["id_type"]])
            for value in seed_file["values"]:
                writer.writerow([value])


def _seed_file_metadata(seed_dir: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(seed_dir.glob("*.csv")):
        digest, size = sha256_file(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        rows.append(
            {
                "id_type": path.stem,
                "path": str(path),
                "sha256": digest,
                "bytes": size,
                "count": max(0, len(lines) - 1),
            }
        )
    return rows


def _write_selected_observations(path: Path, observations: tuple[P009InstrumentObservation, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for observation in sorted(observations, key=lambda item: item.sort_key):
            handle.write(json.dumps(_observation_row(observation), sort_keys=True, ensure_ascii=True) + "\n")


def _observation_row(observation: P009InstrumentObservation) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "p009_observations.v1",
        "source_family": observation.source_family,
        "source_adapter": observation.source_adapter,
        "scope_key": observation.source_scope.scope_key,
        "observation_ordinal": observation.observation_ordinal,
        "source_refs": [ref.to_json() for ref in observation.source_refs],
    }
    optional = {
        "accession": observation.accession,
        "source_record_id": observation.source_record_id,
        "filed_date": observation.filed_date,
        "report_period": observation.report_period,
    }
    for key, value in optional.items():
        if value:
            row[key] = value
    row.update(observation.identifiers.to_json())
    row.update(observation.weak_evidence.to_json())
    scope_extra = {
        key: value
        for key, value in observation.source_scope.to_json().items()
        if key not in {"scope_key", "source_family", "source_adapter"} and value
    }
    if scope_extra:
        row["source_scope"] = {"scope_key": observation.source_scope.scope_key, **scope_extra}
    return row


def _pack_completed_summary(plan: dict[str, object], observations_path: Path, pack_dir: Path) -> dict[str, object]:
    digest, size = sha256_file(observations_path)
    return {
        **plan,
        "status": "completed",
        "pack_path": str(pack_dir),
        "selected_observations_sha256": digest,
        "selected_observations_bytes": size,
    }


def _materialize_requested(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "materialize_registry", False) or getattr(args, "run_canon", False))


def _corpus_id(args: argparse.Namespace, candidate: P009ScanCandidate) -> str:
    explicit = str(getattr(args, "corpus_id", "") or "").strip()
    if explicit:
        return explicit
    return f"p009-{candidate.source_scope_key.replace(':', '-').replace('/', '-')}-{candidate.rank}"


def _ensure_output_paths_available(paths: dict[str, Path], *, stop_after: str, materialize: bool) -> None:
    keys = ["scan_dir", "summary"]
    if stop_after != "scan":
        keys.extend(["seed_dir"])
    if not stop_after:
        keys.extend(["selected_dir", "pack_dir"])
    if materialize and not stop_after:
        keys.append("registry_work_dir")
    for key in keys:
        path = paths[key]
        if path.is_dir() and any(path.iterdir()):
            raise P009WorkflowError(f"workflow output directory is not empty: {path}")
        if path.is_file():
            raise P009WorkflowError(f"workflow output path already exists as a file: {path}")


def _write_summary(path: Path, summary: dict[str, object]) -> None:
    write_json(path, summary)
