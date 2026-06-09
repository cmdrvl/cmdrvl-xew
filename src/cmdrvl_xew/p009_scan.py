"""Deterministic P009 corpus scanner and candidate ranker."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from .exit_codes import ExitCode, exit_processing_error
from .instrument_registry import InstrumentRegistrySnapshot, RegistrySnapshotError
from .p009_corpus import P009CorpusLoadResult, P009CorpusSource, load_p009_corpus
from .p009_identity_ledger import (
    IdentityDriftEvent,
    IdentityObservationRef,
    InstrumentRegistryP009Lookup,
    P009LedgerConfig,
    P009RegistryLookupProvider,
    build_alias_graph,
    build_temporal_ledger,
    classify_identity_drift,
)
from .util import write_json


@dataclass(frozen=True)
class P009ScanCandidate:
    """One ranked P009 identity-fragility candidate."""

    candidate_id: str
    rank: int
    source_scope_key: str
    issue_codes: tuple[str, ...]
    continuity_class: str
    registry_status: str
    score: int
    score_components: dict[str, int]
    event_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    accessions: tuple[str, ...]
    report_periods: tuple[str, ...]
    filed_dates: tuple[str, ...]
    seed_identifiers: tuple[dict[str, object], ...]
    events: tuple[dict[str, object], ...]
    pack_input_plan: dict[str, object]

    @property
    def newest_filed_date(self) -> str:
        return self.filed_dates[-1] if self.filed_dates else ""

    @property
    def newest_report_period(self) -> str:
        return self.report_periods[-1] if self.report_periods else ""

    @property
    def sort_key(self) -> tuple[int, int, str, str, str]:
        return (
            -self.score,
            -len(self.report_periods),
            _reverse_date_key(self.newest_filed_date or self.newest_report_period),
            ",".join(self.issue_codes),
            self.candidate_id,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "rank": self.rank,
            "source_scope_key": self.source_scope_key,
            "issue_codes": list(self.issue_codes),
            "continuity_class": self.continuity_class,
            "registry_status": self.registry_status,
            "score": self.score,
            "score_components": dict(sorted(self.score_components.items())),
            "event_ids": list(self.event_ids),
            "observation_ids": list(self.observation_ids),
            "source_ids": list(self.source_ids),
            "accessions": list(self.accessions),
            "report_periods": list(self.report_periods),
            "filed_dates": list(self.filed_dates),
            "newest_filed_date": self.newest_filed_date,
            "newest_report_period": self.newest_report_period,
            "seed_identifiers": list(self.seed_identifiers),
            "events": list(self.events),
            "pack_input_plan": self.pack_input_plan,
        }


@dataclass(frozen=True)
class P009ScanResult:
    """Complete P009 scan result and output-ready artifacts."""

    candidates: tuple[P009ScanCandidate, ...]
    seed_rows: tuple[dict[str, object], ...]
    pack_inputs: tuple[dict[str, object], ...]
    diagnostics: tuple[dict[str, object], ...]
    manifest_input_sha256: str = ""
    observations_input_sha256: str = ""
    manifest_row_count: int = 0
    observation_row_count: int = 0
    source_count: int = 0
    observation_count: int = 0

    def to_json(self) -> dict[str, object]:
        return {
            "manifest_input_sha256": self.manifest_input_sha256,
            "observations_input_sha256": self.observations_input_sha256,
            "manifest_row_count": self.manifest_row_count,
            "observation_row_count": self.observation_row_count,
            "source_count": self.source_count,
            "observation_count": self.observation_count,
            "candidate_count": len(self.candidates),
            "seed_count": len(self.seed_rows),
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "seed_rows": list(self.seed_rows),
            "pack_inputs": list(self.pack_inputs),
            "diagnostics": list(self.diagnostics),
        }


def run_p009_scan_corpus(args: argparse.Namespace) -> int:
    """CLI entry point for P009 corpus scanning."""

    try:
        registry_provider = _registry_provider_from_path(getattr(args, "registry_snapshot", None))
        corpus = load_p009_corpus(
            Path(args.manifest),
            observations_path=Path(args.observations) if args.observations else None,
        )
        result = scan_p009_corpus(
            corpus,
            registry_snapshot=registry_provider,
            limit=args.limit,
        )
        paths = write_p009_scan_outputs(result, Path(args.out_dir))
    except (OSError, ValueError) as exc:
        exit_processing_error(str(exc))

    print(f"Wrote P009 corpus scan: {paths['candidates_jsonl']}")
    print(f"Candidates: {len(result.candidates)}")
    print(f"Registry seeds: {len(result.seed_rows)}")
    return ExitCode.SUCCESS


def scan_p009_corpus(
    corpus: P009CorpusLoadResult,
    *,
    registry_snapshot: P009RegistryLookupProvider | None = None,
    config: P009LedgerConfig | None = None,
    limit: int | None = None,
) -> P009ScanResult:
    """Scan a provider-neutral P009 corpus and rank fragile scopes."""

    config = config or P009LedgerConfig()
    ledger = build_temporal_ledger(
        corpus.observations,
        registry_snapshot=registry_snapshot,
        config=config,
    )
    graph = build_alias_graph(ledger)
    events = classify_identity_drift(ledger, graph, config=config)
    sources = tuple(sorted(corpus.sources, key=lambda source: source.sort_key))
    candidates = rank_p009_candidates(
        [_candidate_from_event(event, sources) for event in events if _is_scan_finding(event)]
    )
    if limit is not None:
        candidates = candidates[: max(0, limit)]
        candidates = rank_p009_candidates(candidates)
    seed_rows = tuple(_seed_rows_for_candidates(candidates))
    pack_inputs = tuple(candidate.pack_input_plan for candidate in candidates)
    diagnostics = tuple(
        sorted(
            [diagnostic.to_json() for diagnostic in corpus.diagnostics]
            + [diagnostic.to_json() for diagnostic in ledger.diagnostics],
            key=lambda item: (
                str(item.get("code", "")),
                str(item.get("source_path", "")),
                str(item.get("diagnostic_id", "")),
            ),
        )
    )
    return P009ScanResult(
        candidates=candidates,
        seed_rows=seed_rows,
        pack_inputs=pack_inputs,
        diagnostics=diagnostics,
        manifest_input_sha256=corpus.manifest_input_sha256,
        observations_input_sha256=corpus.observations_input_sha256,
        manifest_row_count=corpus.manifest_row_count,
        observation_row_count=corpus.observation_row_count,
        source_count=len(corpus.sources),
        observation_count=len(corpus.observations),
    )


def rank_p009_candidates(candidates: list[P009ScanCandidate] | tuple[P009ScanCandidate, ...]) -> tuple[P009ScanCandidate, ...]:
    """Rank candidates deterministically by actionability and stable ties."""

    ranked = sorted(candidates, key=lambda candidate: candidate.sort_key)
    return tuple(replace(candidate, rank=index) for index, candidate in enumerate(ranked, start=1))


def write_p009_scan_outputs(result: P009ScanResult, out_dir: Path) -> dict[str, str]:
    """Write stable P009 scan artifacts to a local directory."""

    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_jsonl = out_dir / "p009_scan_candidates.v1.jsonl"
    summary_csv = out_dir / "p009_scan_summary.v1.csv"
    seeds_jsonl = out_dir / "p009_registry_seeds.v1.jsonl"
    pack_inputs_json = out_dir / "p009_pack_inputs.v1.json"
    diagnostics_json = out_dir / "diagnostics.json"
    _write_jsonl(candidates_jsonl, [candidate.to_json() for candidate in result.candidates])
    _write_summary_csv(summary_csv, result.candidates)
    _write_jsonl(seeds_jsonl, result.seed_rows)
    write_json(pack_inputs_json, {"pack_inputs": list(result.pack_inputs)})
    write_json(
        diagnostics_json,
        {
            "manifest_input_sha256": result.manifest_input_sha256,
            "observations_input_sha256": result.observations_input_sha256,
            "manifest_row_count": result.manifest_row_count,
            "observation_row_count": result.observation_row_count,
            "source_count": result.source_count,
            "observation_count": result.observation_count,
            "candidate_count": len(result.candidates),
            "diagnostics": list(result.diagnostics),
        },
    )
    return {
        "candidates_jsonl": str(candidates_jsonl),
        "summary_csv": str(summary_csv),
        "seeds_jsonl": str(seeds_jsonl),
        "pack_inputs_json": str(pack_inputs_json),
        "diagnostics_json": str(diagnostics_json),
    }


def _candidate_from_event(
    event: IdentityDriftEvent,
    sources: tuple[P009CorpusSource, ...],
) -> P009ScanCandidate:
    refs = tuple(sorted(event.observation_refs, key=lambda ref: ref.sort_key))
    source_scope_key = event.source_scope_key
    observation_ids = _unique(ref.observation_id for ref in refs)
    source_ids = _unique(ref.source_id for ref in refs if ref.source_id)
    accessions = _unique(ref.accession for ref in refs if ref.accession)
    report_periods = _unique(ref.report_period for ref in refs if ref.report_period)
    filed_dates = _unique(ref.filed_date for ref in refs if ref.filed_date)
    seed_identifiers = _seed_identifiers(refs)
    pack_input_plan = _pack_input_plan(
        source_scope_key=source_scope_key,
        source_ids=source_ids,
        observation_ids=observation_ids,
        sources=sources,
        seed_identifiers=seed_identifiers,
    )
    score_components = _score_components(event, refs)
    candidate = P009ScanCandidate(
        candidate_id="",
        rank=0,
        source_scope_key=source_scope_key,
        issue_codes=event.issue_codes,
        continuity_class=event.continuity_class,
        registry_status=event.registry_status,
        score=sum(score_components.values()),
        score_components=score_components,
        event_ids=(event.event_id,),
        observation_ids=observation_ids,
        source_ids=source_ids,
        accessions=accessions,
        report_periods=report_periods,
        filed_dates=filed_dates,
        seed_identifiers=seed_identifiers,
        events=(event.to_json(),),
        pack_input_plan=pack_input_plan,
    )
    return replace(candidate, candidate_id=_candidate_id(candidate))


def _is_scan_finding(event: IdentityDriftEvent) -> bool:
    """Exclude pure registry proof when the reported identity basis did not drift."""

    return tuple(event.issue_codes) != ("registry_bridge_available",)


def _score_components(
    event: IdentityDriftEvent,
    refs: tuple[IdentityObservationRef, ...],
) -> dict[str, int]:
    issue_codes = set(event.issue_codes)
    components = {
        "registry_bridge_available": 1000 if "registry_bridge_available" in issue_codes else 0,
        "registry_bridge_ambiguous": 900 if "registry_bridge_ambiguous" in issue_codes else 0,
        "strong_identifier_removed": 800 if "strong_identifier_removed" in issue_codes else 0,
        "weak_key_temporal_collision": 700 if "weak_key_temporal_collision" in issue_codes else 0,
        "weak_continuity_only": 400 if "weak_continuity_only" in issue_codes else 0,
        "history_length": len({ref.report_period for ref in refs if ref.report_period}) * 10,
        "affected_value": _affected_value_score(refs),
    }
    return {key: value for key, value in components.items() if value}


def _affected_value_score(refs: tuple[IdentityObservationRef, ...]) -> int:
    values = []
    for ref in refs:
        value = ""
        for key, raw_value in ref.weak_key_fields:
            if key == "value":
                value = raw_value
                break
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            values.append(min(int(digits), 999_999_999))
    if not values:
        return 0
    return min(max(values) // 1_000_000, 99)


def _seed_identifiers(refs: tuple[IdentityObservationRef, ...]) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for ref in refs:
        for key in ref.strong_keys:
            if key.source != "reported":
                continue
            id_type = key.key_type
            value = key.value
            if id_type == "other_typed_identifier" and ":" in value:
                id_type, value = value.split(":", 1)
            grouped.setdefault((id_type, value), set()).add(ref.observation_id)
    return tuple(
        {
            "id_type": id_type,
            "value": value,
            "observation_ids": sorted(observation_ids),
        }
        for (id_type, value), observation_ids in sorted(grouped.items())
    )


def _seed_rows_for_candidates(candidates: tuple[P009ScanCandidate, ...]) -> list[dict[str, object]]:
    rows = []
    for candidate in candidates:
        for seed in candidate.seed_identifiers:
            rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "source_scope_key": candidate.source_scope_key,
                    "rank": candidate.rank,
                    "id_type": seed["id_type"],
                    "value": seed["value"],
                    "observation_ids": seed["observation_ids"],
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            int(row["rank"]),
            str(row["id_type"]),
            str(row["value"]),
            str(row["candidate_id"]),
        ),
    )


def _pack_input_plan(
    *,
    source_scope_key: str,
    source_ids: tuple[str, ...],
    observation_ids: tuple[str, ...],
    sources: tuple[P009CorpusSource, ...],
    seed_identifiers: tuple[dict[str, object], ...],
) -> dict[str, object]:
    source_id_set = set(source_ids)
    manifest_sources = [
        source.to_json()
        for source in sources
        if source.scope_key == source_scope_key and source.source_id in source_id_set
    ]
    return {
        "source_scope_key": source_scope_key,
        "source_ids": list(source_ids),
        "observation_ids": list(observation_ids),
        "manifest_sources": manifest_sources,
        "normalized_observation_evidence": {
            "observation_ids": list(observation_ids),
            "proof_mode": "hashed_normalized_observations",
        },
        "registry_seed_identifiers": list(seed_identifiers),
        "registry_seed_count": len(seed_identifiers),
    }


def _candidate_id(candidate: P009ScanCandidate) -> str:
    payload = {
        "source_scope_key": candidate.source_scope_key,
        "issue_codes": candidate.issue_codes,
        "continuity_class": candidate.continuity_class,
        "event_ids": candidate.event_ids,
        "observation_ids": candidate.observation_ids,
        "source_ids": candidate.source_ids,
        "seed_identifiers": candidate.seed_identifiers,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(f"v1|P009:scan-candidate|{encoded}".encode("ascii")).hexdigest()


def _registry_provider_from_path(path_value: str | None) -> InstrumentRegistryP009Lookup | None:
    if not path_value:
        return None
    try:
        return InstrumentRegistryP009Lookup(InstrumentRegistrySnapshot.load(path_value))
    except RegistrySnapshotError as exc:
        return InstrumentRegistryP009Lookup(snapshot_error=exc)


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...] | list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def _write_summary_csv(path: Path, candidates: tuple[P009ScanCandidate, ...]) -> None:
    fieldnames = [
        "rank",
        "candidate_id",
        "source_scope_key",
        "issue_codes",
        "continuity_class",
        "registry_status",
        "score",
        "observation_count",
        "source_ids",
        "report_periods",
        "seed_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "rank": candidate.rank,
                    "candidate_id": candidate.candidate_id,
                    "source_scope_key": candidate.source_scope_key,
                    "issue_codes": ",".join(candidate.issue_codes),
                    "continuity_class": candidate.continuity_class,
                    "registry_status": candidate.registry_status,
                    "score": candidate.score,
                    "observation_count": len(candidate.observation_ids),
                    "source_ids": ",".join(candidate.source_ids),
                    "report_periods": ",".join(candidate.report_periods),
                    "seed_count": len(candidate.seed_identifiers),
                }
            )


def _unique(values) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if str(value)}))


def _reverse_date_key(value: str) -> str:
    digits = value.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{99999999 - int(digits):08d}"
    return "99999999"
