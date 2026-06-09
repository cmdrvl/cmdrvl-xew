"""Convert local canon OpenFIGI registry output into a P008 snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .instrument_identity import normalize_exchange_key, normalize_identifier, normalize_text, normalize_ticker
from .instrument_registry import InstrumentRegistrySnapshot, RegistrySnapshotError
from .util import sha256_file, utc_now_iso, write_json


class CanonSnapshotAdapterError(ValueError):
    """Raised when canon registry output cannot be converted safely."""


def run_p008_snapshot_from_canon(args: argparse.Namespace) -> int:
    try:
        snapshot = build_p008_snapshot_from_canon(
            registry_dir=Path(args.registry_dir),
            out_path=Path(args.out),
            overlay_path=Path(args.overlay) if args.overlay else None,
            snapshot_id=args.snapshot_id,
            generated_at=args.generated_at,
        )
    except CanonSnapshotAdapterError as exc:
        exit_processing_error(str(exc))
    except OSError as exc:
        exit_invocation_error(str(exc))

    print(f"Wrote P008 snapshot: {args.out}")
    print(f"Rows: {len(snapshot.rows)}")
    print(f"Snapshot id: {snapshot.snapshot_id}")
    return ExitCode.SUCCESS


def build_p008_snapshot_from_canon(
    *,
    registry_dir: Path,
    out_path: Path,
    overlay_path: Path | None = None,
    snapshot_id: str | None = None,
    generated_at: str | None = None,
) -> InstrumentRegistrySnapshot:
    registry_dir = registry_dir.resolve()
    if not registry_dir.is_dir():
        raise CanonSnapshotAdapterError(f"canon registry directory not found: {registry_dir}")

    registry_json = _read_json_object(registry_dir / "registry.json", "registry.json")
    build_json = _read_optional_json_object(registry_dir / "_build.json")
    overlay = _read_overlay(overlay_path) if overlay_path else {}

    mapping_files = _mapping_files(registry_dir)
    if not mapping_files:
        raise CanonSnapshotAdapterError(f"No canon mapping files found in {registry_dir}")

    grouped: dict[str, dict[str, list[dict[str, str]]]] = {}
    seed_column = _seed_column(build_json, mapping_files)
    for path in mapping_files:
        target = _mapping_target(path.name)
        entries = _read_json_array(path, path.name)
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise CanonSnapshotAdapterError(f"{path.name} entry {index} must be an object")
            raw_input = normalize_identifier(entry.get("input", ""))
            canonical_id = normalize_text(entry.get("canonical_id", ""))
            canonical_type = normalize_text(entry.get("canonical_type", ""))
            rule_id = normalize_text(entry.get("rule_id", ""))
            if not raw_input or not canonical_id:
                continue
            grouped.setdefault(raw_input, {}).setdefault(target, []).append(
                {
                    "canonical_id": canonical_id,
                    "canonical_type": canonical_type,
                    "rule_id": rule_id,
                }
            )

    rows: list[dict[str, str]] = []
    for seed in sorted(grouped):
        targets = grouped[seed]
        figi_mappings = targets.get("figi", [])
        if not figi_mappings:
            continue
        overlay_row = overlay.get(seed, {})
        for mapping in sorted(figi_mappings, key=lambda item: (item["canonical_id"], item["canonical_type"])):
            row = _base_row_for_seed(seed, seed_column)
            figi = normalize_identifier(mapping["canonical_id"])
            row["figi"] = figi
            if mapping["canonical_type"] == "composite_figi":
                row["composite_figi"] = figi
            row.update(_first_target_values(targets))
            row.update(overlay_row)
            row = {key: value for key, value in sorted(row.items()) if value}
            rows.append(row)

    if not rows:
        raise CanonSnapshotAdapterError(
            "canon registry contains no usable FIGI mappings; provider failures/unresolved rows may be the only output"
        )

    source = _source_metadata(
        registry_dir=registry_dir,
        registry_json=registry_json,
        build_json=build_json,
        seed_column=seed_column,
        overlay_path=overlay_path,
    )
    document = {
        "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
        "schema_version": "1.0",
        "snapshot_id": snapshot_id or _default_snapshot_id(registry_json, seed_column),
        "generated_at": generated_at or utc_now_iso(),
        "source": source,
        "rows": sorted(rows, key=lambda item: (item.get("canonical_signature", ""), item.get("cusip", ""), item.get("isin", ""), item.get("sedol", ""), item.get("figi", ""))),
    }

    write_json(out_path, document)
    try:
        return InstrumentRegistrySnapshot.load(out_path)
    except RegistrySnapshotError as exc:
        raise CanonSnapshotAdapterError(f"adapter produced invalid P008 snapshot: {exc}") from exc


def _mapping_files(registry_dir: Path) -> list[Path]:
    return sorted(
        path for path in registry_dir.glob("*.json")
        if path.name not in {"registry.json", "_build.json"} and "-to-" in path.name
    )


def _mapping_target(filename: str) -> str:
    stem = filename[:-5] if filename.endswith(".json") else filename
    _seed, sep, target = stem.partition("-to-")
    if not sep or not target:
        raise CanonSnapshotAdapterError(f"Unsupported canon mapping filename: {filename}")
    return target.replace("-", "_")


def _seed_column(build_json: dict[str, Any], mapping_files: list[Path]) -> str:
    seed = build_json.get("seed")
    if isinstance(seed, dict):
        column = normalize_text(seed.get("column", "")).lower()
        if column:
            return column
    first = mapping_files[0].name
    return first.split("-to-", 1)[0].replace("-", "_").lower()


def _base_row_for_seed(seed: str, seed_column: str) -> dict[str, str]:
    if seed_column == "cusip":
        return {"cusip": seed}
    if seed_column == "isin":
        return {"isin": seed}
    if seed_column == "sedol":
        return {"sedol": seed}
    if seed_column == "figi":
        return {"figi": seed}
    return {}


def _first_target_values(targets: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    values: dict[str, str] = {}
    if targets.get("ticker"):
        values["ticker"] = normalize_ticker(targets["ticker"][0]["canonical_id"])
    if targets.get("name"):
        values["name"] = normalize_text(targets["name"][0]["canonical_id"])
    if targets.get("exchange"):
        values["exchange"] = normalize_exchange_key(targets["exchange"][0]["canonical_id"])
    if targets.get("security_type"):
        values["security_type"] = normalize_text(targets["security_type"][0]["canonical_id"])
    if targets.get("market_sector"):
        values["market_sector"] = normalize_text(targets["market_sector"][0]["canonical_id"])
    if targets.get("composite_figi"):
        values["composite_figi"] = normalize_identifier(targets["composite_figi"][0]["canonical_id"])
    if targets.get("share_class_figi"):
        values["share_class_figi"] = normalize_identifier(targets["share_class_figi"][0]["canonical_id"])
    return values


def _read_overlay(path: Path) -> dict[str, dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CanonSnapshotAdapterError(f"overlay is not valid JSON: {path} ({exc})") from exc
    if isinstance(raw, dict):
        rows = raw.get("rows", [])
    else:
        rows = raw
    if not isinstance(rows, list):
        raise CanonSnapshotAdapterError("overlay must be an array or an object with rows[]")
    overlay: dict[str, dict[str, str]] = {}
    allowed = {
        "ticker",
        "exchange",
        "security_title",
        "normalized_title",
        "canonical_signature",
        "cusip",
        "isin",
        "sedol",
        "composite_figi",
        "share_class_figi",
        "market_sector",
        "security_type",
        "name",
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CanonSnapshotAdapterError(f"overlay row {index} must be an object")
        seed = normalize_identifier(row.get("seed") or row.get("cusip") or row.get("isin") or row.get("sedol") or "")
        if not seed:
            raise CanonSnapshotAdapterError(f"overlay row {index} missing seed/cusip/isin/sedol")
        normalized: dict[str, str] = {}
        for key in allowed:
            value = row.get(key)
            if value is None:
                continue
            if key in {"cusip", "isin", "sedol", "composite_figi", "share_class_figi"}:
                normalized[key] = normalize_identifier(value)
            elif key == "ticker":
                normalized[key] = normalize_ticker(value)
            elif key == "exchange":
                normalized[key] = normalize_exchange_key(value)
            else:
                normalized[key] = normalize_text(value)
        overlay[seed] = normalized
    return overlay


def _source_metadata(
    *,
    registry_dir: Path,
    registry_json: dict[str, Any],
    build_json: dict[str, Any],
    seed_column: str,
    overlay_path: Path | None,
) -> dict[str, Any]:
    source = {
        "producer": "canon",
        "dataset": "openfigi",
        "registry_id": normalize_text(registry_json.get("id", "")),
        "registry_version": normalize_text(registry_json.get("version", "")),
        "registry_source": normalize_text(registry_json.get("source", "")),
        "registry_dir": str(registry_dir),
        "registry_dir_sha256": _hash_registry_dir(registry_dir),
        "seed_column": seed_column,
    }
    if build_json:
        source["build"] = {
            "version": normalize_text(build_json.get("version", "")),
            "source": normalize_text(build_json.get("source", "")),
            "seed_hash": normalize_text((build_json.get("seed") or {}).get("hash", "")) if isinstance(build_json.get("seed"), dict) else "",
            "id_type": normalize_text(((build_json.get("provider") or {}).get("options") or {}).get("id_type", "")) if isinstance(build_json.get("provider"), dict) else "",
            "provider_options": _redacted_provider_options(build_json),
            "summary": build_json.get("summary", {}) if isinstance(build_json.get("summary"), dict) else {},
        }
        if isinstance(build_json.get("seed"), dict):
            source["build"]["seed"] = {
                "path": normalize_text(build_json["seed"].get("path", "")),
                "column": normalize_text(build_json["seed"].get("column", "")),
                "hash": normalize_text(build_json["seed"].get("hash", "")),
                "count": int(build_json["seed"].get("count", 0) or 0),
            }
        for key in ("corpus_id", "manifest_sha256", "seed_sha256", "canon_version"):
            value = normalize_text(build_json.get(key, ""))
            if value:
                source["build"][key] = value
        summary = source["build"]["summary"]
        if isinstance(summary, dict):
            source["build"]["unresolved_count"] = int(summary.get("unresolved_count", 0) or 0)
            source["build"]["failure_count"] = int(summary.get("failure_count", 0) or 0)
            source["build"]["ambiguous_count"] = int(summary.get("ambiguous_count", 0) or 0)
        build_path = registry_dir / "_build.json"
        if build_path.is_file():
            source["build"]["sha256"], source["build"]["bytes"] = sha256_file(build_path)
    if overlay_path:
        source["overlay"] = {"path": str(overlay_path.resolve())}
        source["overlay"]["sha256"], source["overlay"]["bytes"] = sha256_file(overlay_path)
    return source


def _hash_registry_dir(registry_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(registry_dir.glob("*.json"), key=lambda item: item.name):
        digest, size = sha256_file(path)
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\0")
        h.update(str(size).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def _redacted_provider_options(build_json: dict[str, Any]) -> dict[str, str]:
    provider = build_json.get("provider")
    if not isinstance(provider, dict):
        return {}
    options = provider.get("options")
    if not isinstance(options, dict):
        return {}
    redacted = {}
    for key, value in sorted(options.items()):
        normalized_key = normalize_text(key)
        if "key" in normalized_key.lower() or "token" in normalized_key.lower() or "secret" in normalized_key.lower():
            redacted[normalized_key] = "[redacted]"
        else:
            redacted[normalized_key] = normalize_text(value)
    return redacted


def _default_snapshot_id(registry_json: dict[str, Any], seed_column: str) -> str:
    registry_id = normalize_text(registry_json.get("id", "")) or f"openfigi-{seed_column}"
    version = normalize_text(registry_json.get("version", "")) or "unversioned"
    return f"{registry_id}@{version}"


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise CanonSnapshotAdapterError(f"Missing {label}: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CanonSnapshotAdapterError(f"{label} is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise CanonSnapshotAdapterError(f"{label} must be a JSON object")
    return data


def _read_optional_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _read_json_object(path, path.name)


def _read_json_array(path: Path, label: str) -> list[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CanonSnapshotAdapterError(f"{label} is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, list):
        raise CanonSnapshotAdapterError(f"{label} must be a JSON array")
    return data
