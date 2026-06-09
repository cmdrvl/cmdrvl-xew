"""Corpus-scoped canon/OpenFIGI registry materialization for P008."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .instrument_identity import normalize_identifier
from .util import sha256_file, utc_now_iso, write_json


class RegistryMaterializationError(ValueError):
    """Raised when corpus registry materialization cannot proceed."""


_ID_COLUMNS = ("cusip", "isin", "sedol", "figi")
_OPENFIGI_ID_TYPES = {
    "cusip": "ID_CUSIP",
    "isin": "ID_ISIN",
    "sedol": "ID_SEDOL",
    "figi": "ID_BB_GLOBAL",
}


def run_p008_materialize_registry(args: argparse.Namespace) -> int:
    try:
        manifest = materialize_registry_from_corpus(
            corpus_id=args.corpus_id,
            out_dir=Path(args.out_dir),
            filing_manifest=Path(args.filing_manifest) if args.filing_manifest else None,
            seed_files=[Path(path) for path in args.seed_file or []],
            version=args.version,
            provider_source=args.provider_source,
            provider_configs=args.provider_config or [],
            canon_bin=args.canon_bin,
            run_canon=args.run_canon,
            incremental=args.incremental,
            allow_live_provider=args.allow_live_provider,
        )
    except RegistryMaterializationError as exc:
        exit_processing_error(str(exc))
    except OSError as exc:
        exit_invocation_error(str(exc))

    print(f"Wrote registry materialization manifest: {manifest['manifest_path']}")
    print(f"Corpus id: {manifest['corpus_id']}")
    print(f"Seed files: {len(manifest['seed_files'])}")
    print(f"Canon builds: {len(manifest['registry_builds'])}")
    return ExitCode.SUCCESS


def materialize_registry_from_corpus(
    *,
    corpus_id: str,
    out_dir: Path,
    filing_manifest: Path | None,
    seed_files: list[Path],
    version: str,
    provider_source: str,
    provider_configs: list[str],
    canon_bin: str,
    run_canon: bool,
    incremental: bool,
    allow_live_provider: bool,
) -> dict[str, Any]:
    corpus_id = _require_token(corpus_id, "corpus_id")
    version = _require_token(version, "version")
    provider_options = _parse_provider_configs(provider_configs)

    if run_canon and provider_source == "openfigi" and not allow_live_provider:
        base_url = provider_options.get("base_url", "")
        if not base_url:
            raise RegistryMaterializationError(
                "--run-canon with OpenFIGI requires --provider-config base_url=... for a local twin, "
                "or --allow-live-provider for an explicit maintenance-time live run"
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir = out_dir / "seeds"
    registries_dir = out_dir / "registries"
    seeds_dir.mkdir(parents=True, exist_ok=True)
    registries_dir.mkdir(parents=True, exist_ok=True)

    seed_values = {column: set() for column in _ID_COLUMNS}
    source_inputs: list[dict[str, Any]] = []

    if filing_manifest:
        extracted = _read_manifest_identifiers(filing_manifest)
        for column, values in extracted.items():
            seed_values[column].update(values)
        digest, size = sha256_file(filing_manifest)
        source_inputs.append(
            {
                "kind": "filing_manifest",
                "path": str(filing_manifest.resolve()),
                "sha256": digest,
                "bytes": size,
            }
        )

    for seed_file in seed_files:
        column, values = _read_seed_file(seed_file)
        seed_values[column].update(values)
        digest, size = sha256_file(seed_file)
        source_inputs.append(
            {
                "kind": "seed_file",
                "column": column,
                "path": str(seed_file.resolve()),
                "sha256": digest,
                "bytes": size,
            }
        )

    if not any(seed_values[column] for column in _ID_COLUMNS):
        raise RegistryMaterializationError("no usable CUSIP/ISIN/SEDOL seed identifiers found")

    written_seed_files = []
    registry_builds = []
    for column in _ID_COLUMNS:
        discovered_values = sorted(seed_values[column])
        if not discovered_values:
            continue
        registry_dir = registries_dir / f"{provider_source}-{column}-{version}"
        existing_values = _existing_registry_inputs(registry_dir, column) if incremental else set()
        values = [value for value in discovered_values if value not in existing_values]
        skipped_existing_count = len(discovered_values) - len(values)
        if not values:
            registry_builds.append(
                {
                    "column": column,
                    "id_type": _OPENFIGI_ID_TYPES[column],
                    "seed_count": 0,
                    "discovered_seed_count": len(discovered_values),
                    "skipped_existing_count": skipped_existing_count,
                    "registry_dir": str(registry_dir),
                    "status": "skipped_existing",
                }
            )
            continue
        seed_path = seeds_dir / f"{column}.csv"
        _write_seed_csv(seed_path, column, values)
        seed_sha, seed_bytes = sha256_file(seed_path)
        command = _canon_registry_build_command(
            canon_bin=canon_bin,
            provider_source=provider_source,
            seed_path=seed_path,
            seed_column=column,
            output_dir=registry_dir,
            version=version,
            incremental=incremental,
            provider_options={**provider_options, "id_type": _OPENFIGI_ID_TYPES[column]},
        )
        build_record = {
            "column": column,
            "id_type": _OPENFIGI_ID_TYPES[column],
            "seed_path": str(seed_path),
            "seed_sha256": seed_sha,
            "seed_bytes": seed_bytes,
            "seed_count": len(values),
            "discovered_seed_count": len(discovered_values),
            "skipped_existing_count": skipped_existing_count,
            "registry_dir": str(registry_dir),
            "command": command,
            "status": "planned",
        }
        if run_canon:
            proc = _run_canon(command)
            build_record["status"] = "completed"
            build_record["returncode"] = proc.returncode
            build_record["stdout_sha256"] = _text_sha256(proc.stdout)
            build_record["stderr_sha256"] = _text_sha256(proc.stderr)
            build_record.update(_canon_build_provenance(registry_dir))
        registry_builds.append(build_record)
        written_seed_files.append(
            {
                "column": column,
                "path": str(seed_path),
                "sha256": seed_sha,
                "bytes": seed_bytes,
                "count": len(values),
            }
        )

    manifest_path = out_dir / "registry_materialization_manifest.json"
    manifest = {
        "schema_id": "cmdrvl.xew.p008_registry_materialization",
        "schema_version": "1.0",
        "corpus_id": corpus_id,
        "created_at": utc_now_iso(),
        "provider_source": provider_source,
        "provider_options": _sanitize_provider_options(provider_options),
        "version": version,
        "incremental": incremental,
        "run_canon": run_canon,
        "allow_live_provider": allow_live_provider,
        "source_inputs": source_inputs,
        "seed_files": written_seed_files,
        "registry_builds": registry_builds,
    }
    write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _read_manifest_identifiers(path: Path) -> dict[str, set[str]]:
    if not path.is_file():
        raise RegistryMaterializationError(f"filing manifest not found: {path}")
    rows = _read_rows(path)
    extracted = {column: set() for column in _ID_COLUMNS}
    for row in rows:
        for column in _ID_COLUMNS:
            value = normalize_identifier(row.get(column, ""))
            if value:
                extracted[column].add(value)
    return extracted


def _read_seed_file(path: Path) -> tuple[str, set[str]]:
    if not path.is_file():
        raise RegistryMaterializationError(f"seed file not found: {path}")
    rows = _read_rows(path)
    if not rows:
        raise RegistryMaterializationError(f"seed file contains no rows: {path}")
    available = {key.lower() for key in rows[0].keys()}
    columns = [column for column in _ID_COLUMNS if column in available]
    if len(columns) != 1:
        raise RegistryMaterializationError(
            f"seed file must contain exactly one identifier column among {_ID_COLUMNS}: {path}"
        )
    column = columns[0]
    values = {normalize_identifier(row.get(column, "")) for row in rows}
    values.discard("")
    return column, values


def _existing_registry_inputs(registry_dir: Path, column: str) -> set[str]:
    if not registry_dir.is_dir():
        return set()
    inputs: set[str] = set()
    for path in sorted(registry_dir.glob(f"{column}-to-*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RegistryMaterializationError(f"existing registry mapping is not valid JSON: {path} ({exc})") from exc
        if not isinstance(raw, list):
            raise RegistryMaterializationError(f"existing registry mapping must be a JSON array: {path}")
        for index, row in enumerate(raw):
            if not isinstance(row, dict):
                raise RegistryMaterializationError(f"{path.name} entry {index} must be an object")
            value = normalize_identifier(row.get("input", ""))
            if value:
                inputs.add(value)
    return inputs


def _read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise RegistryMaterializationError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise RegistryMaterializationError(f"{path}:{line_number} must be a JSON object")
            rows.append({str(k).lower(): v for k, v in row.items()})
        return rows

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise RegistryMaterializationError(f"CSV has no header: {path}")
        return [{str(k).lower(): v for k, v in row.items()} for row in reader]


def _write_seed_csv(path: Path, column: str, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow([column])
        for value in values:
            writer.writerow([value])


def _canon_registry_build_command(
    *,
    canon_bin: str,
    provider_source: str,
    seed_path: Path,
    seed_column: str,
    output_dir: Path,
    version: str,
    incremental: bool,
    provider_options: dict[str, str],
) -> list[str]:
    command = [
        canon_bin,
        "registry",
        "build",
        "--source",
        provider_source,
        "--seed",
        str(seed_path),
        "--seed-column",
        seed_column,
        "--output",
        str(output_dir),
        "--version",
        version,
    ]
    if incremental:
        command.append("--incremental")
    for key in sorted(provider_options):
        value = provider_options[key]
        if value:
            command.extend(["--provider-config", f"{key}={value}"])
    return command


def _run_canon(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, check=True, text=True, capture_output=True, timeout=300)
    except FileNotFoundError as exc:
        raise RegistryMaterializationError(f"canon binary not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise RegistryMaterializationError(f"canon registry build failed{detail}") from exc


def _canon_build_provenance(registry_dir: Path) -> dict[str, Any]:
    build_path = registry_dir / "_build.json"
    if not build_path.is_file():
        return {"build_file": {"status": "missing"}}
    digest, size = sha256_file(build_path)
    try:
        raw = json.loads(build_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RegistryMaterializationError(f"canon _build.json is not valid JSON: {build_path} ({exc})") from exc
    if not isinstance(raw, dict):
        raise RegistryMaterializationError(f"canon _build.json must be an object: {build_path}")
    summary = raw.get("summary", {}) if isinstance(raw.get("summary"), dict) else {}
    return {
        "build_file": {
            "path": str(build_path),
            "sha256": digest,
            "bytes": size,
            "summary": summary,
            "unresolved_count": int(summary.get("unresolved_count", 0) or 0),
            "failure_count": int(summary.get("failure_count", 0) or 0),
            "ambiguous_count": int(summary.get("ambiguous_count", 0) or 0),
        }
    }


def _parse_provider_configs(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise RegistryMaterializationError(f"--provider-config must be key=value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise RegistryMaterializationError(f"--provider-config key is empty: {item}")
        parsed[key] = value.strip()
    return parsed


def _sanitize_provider_options(options: dict[str, str]) -> dict[str, str]:
    redacted = {}
    for key, value in sorted(options.items()):
        if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted


def _require_token(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise RegistryMaterializationError(f"{label} is required")
    return normalized


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
