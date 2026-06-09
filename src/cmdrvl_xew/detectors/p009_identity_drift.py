"""XEW-P009: Temporal Instrument Identity Drift.

This detector consumes source-neutral P009 observation rows that have already
been staged as local Evidence Pack artifacts. It never parses a source-specific
filing format and never calls OpenFIGI, canon, HTTP, or model runtimes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..instrument_registry import InstrumentRegistrySnapshot, RegistrySnapshotError
from ..p009_identity_ledger import (
    AliasGraph,
    IdentityDriftEvent,
    IdentityObservationRef,
    InstrumentRegistryP009Lookup,
    P009LedgerConfig,
    P009RegistryLookupProvider,
    TemporalIdentityLedger,
    build_alias_graph,
    build_temporal_ledger,
    classify_identity_drift,
)
from ..p009_observations import P009InstrumentObservation, load_p009_observations
from ..util import sha256_file


class InstrumentIdentityDriftDetector(BaseDetector):
    """Detector for XEW-P009 temporal instrument identity drift."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P009"

    @property
    def pattern_name(self) -> str:
        return "Temporal Instrument Identity Drift"

    @property
    def alert_eligible(self) -> bool:
        return True

    def should_run(self, context: DetectorContext) -> bool:
        return bool(_p009_observation_paths(context))

    def detect(self, context: DetectorContext) -> list[DetectorFinding]:
        observations, input_metadata, diagnostics = self._load_observations(context)
        if not observations:
            return []

        registry_provider, registry_metadata = self._registry_provider(context)
        config = P009LedgerConfig()
        ledger = build_temporal_ledger(
            observations,
            registry_snapshot=registry_provider,
            config=config,
        )
        graph = build_alias_graph(ledger)
        events = tuple(
            event for event in classify_identity_drift(ledger, graph, config=config)
            if _is_detector_finding(event)
        )
        if not events:
            return []

        diagnostics.extend(_ledger_diagnostics(ledger))
        artifact = _generated_artifact_payload(
            config=config,
            ledger=ledger,
            graph=graph,
            events=events,
            input_metadata=input_metadata,
            registry_metadata=registry_metadata,
            diagnostics=diagnostics,
        )
        instances = self._instances_for_events(
            events,
            context=context,
            registry_metadata=registry_metadata,
            diagnostics=diagnostics,
            artifact=artifact,
        )
        if not instances:
            return []

        return [
            DetectorFinding(
                finding_id=self.generate_finding_id(context),
                pattern_id=self.pattern_id,
                pattern_name=self.pattern_name,
                alert_eligible=self.alert_eligible,
                status="detected",
                human_review_required=True,
                break_triggers=self.get_break_triggers(),
                instances=instances,
                mechanism=(
                    "P009 compares source-neutral instrument identity observations across a temporal "
                    "scope and reports identifier-basis drift, missing or ambiguous registry bridges, "
                    "and weak-key continuity that cannot deterministically resolve one instrument."
                ),
                why_not_fatal_yet=(
                    "A filing can be syntactically valid while its reported instrument identifiers are "
                    "too unstable for deterministic joins across time without preserving strong IDs or "
                    "a local registry bridge."
                ),
            )
        ]

    def compute_canonical_signature(self, **kwargs) -> str:
        scope_key = str(kwargs.get("source_scope_key", ""))
        event_ids = sorted(str(value) for value in kwargs.get("event_ids", []) if str(value))
        return "P009|identity_drift|" + scope_key + "|" + "|".join(event_ids)

    def get_break_triggers(self) -> list[dict[str, str]]:
        return [
            {
                "id": "XEW-BT009",
                "summary": "Instrument identity changes across reporting periods without a stable strong identifier path.",
            }
        ]

    def _load_observations(
        self,
        context: DetectorContext,
    ) -> tuple[tuple[P009InstrumentObservation, ...], list[dict[str, object]], list[dict[str, object]]]:
        observations: list[P009InstrumentObservation] = []
        input_metadata: list[dict[str, object]] = []
        diagnostics: list[dict[str, object]] = []
        for path_text in _p009_observation_paths(context):
            path = Path(path_text)
            path_label = _p009_observation_artifact_label(context, path)
            try:
                result = load_p009_observations(path)
                digest, size = sha256_file(path)
                input_metadata.append(
                    {
                        "path": path_label,
                        "sha256": digest,
                        "bytes": size,
                        "row_count": result.row_count,
                        "observation_count": len(result.observations),
                    }
                )
                observations.extend(result.observations)
                diagnostics.extend(_observation_diagnostics(result.diagnostics))
            except OSError as exc:
                diagnostics.append(
                    {
                        "issue_code": "p009_observation_input_unreadable",
                        "message": str(exc),
                        "path": path_label,
                    }
                )

        return (
            tuple(sorted(observations, key=lambda item: item.sort_key)),
            sorted(input_metadata, key=lambda item: str(item.get("path", ""))),
            sorted(diagnostics, key=_diagnostic_sort_key),
        )

    def _registry_provider(
        self,
        context: DetectorContext,
    ) -> tuple[P009RegistryLookupProvider | None, dict[str, object]]:
        path_text = str(
            context.config.get("p009_registry_snapshot")
            or context.config.get("p008_registry_snapshot")
            or ""
        )
        if not path_text:
            return None, {"status": "absent"}
        try:
            snapshot = InstrumentRegistrySnapshot.load(path_text)
            return InstrumentRegistryP009Lookup(snapshot), snapshot.metadata
        except RegistrySnapshotError as exc:
            return (
                InstrumentRegistryP009Lookup(snapshot_error=exc),
                {"status": "invalid", "diagnostic": str(exc), "path": path_text},
            )

    def _instances_for_events(
        self,
        events: tuple[IdentityDriftEvent, ...],
        *,
        context: DetectorContext,
        registry_metadata: dict[str, object],
        diagnostics: list[dict[str, object]],
        artifact: dict[str, object],
    ) -> list[DetectorInstance]:
        instances: list[DetectorInstance] = []
        for index, event in enumerate(sorted(events, key=lambda item: item.sort_key)):
            data = _event_instance_data(
                event,
                context=context,
                registry_metadata=registry_metadata,
                diagnostics=diagnostics,
            )
            if index == 0:
                data["_generated_artifact"] = artifact
            signature = self.compute_canonical_signature(
                source_scope_key=event.source_scope_key,
                event_ids=[event.event_id],
            )
            instances.append(
                DetectorInstance(
                    instance_id=_instance_id(signature),
                    kind="instrument_identity_drift",
                    primary=index == 0,
                    data=data,
                )
            )
        return instances


def _p009_observation_paths(context: DetectorContext) -> tuple[str, ...]:
    raw = context.config.get("p009_observations")
    if raw is None:
        raw = context.config.get("p009_observation_paths")
    if raw is None:
        return ()
    if isinstance(raw, (str, Path)):
        raw_items = [raw]
    elif isinstance(raw, (list, tuple)):
        raw_items = list(raw)
    else:
        raw_items = []
    return tuple(sorted({str(Path(item)) for item in raw_items if str(item)}))


def _p009_observation_artifact_label(context: DetectorContext, path: Path) -> str:
    mapping = context.config.get("p009_observation_artifacts")
    if isinstance(mapping, dict):
        label = mapping.get(str(path)) or mapping.get(str(path.resolve()))
        if label:
            return str(label)
    return path.name


def _is_detector_finding(event: IdentityDriftEvent) -> bool:
    return tuple(event.issue_codes) != ("registry_bridge_available",)


def _event_instance_data(
    event: IdentityDriftEvent,
    *,
    context: DetectorContext,
    registry_metadata: dict[str, object],
    diagnostics: list[dict[str, object]],
) -> dict[str, object]:
    refs = tuple(sorted(event.observation_refs, key=lambda ref: ref.sort_key))
    event_json = _event_json(event, context=context)
    issue_codes = sorted({code for code in event.issue_codes})
    return {
        "issue_codes": issue_codes,
        "continuity_class": event.continuity_class,
        "source_scope": _source_scope(refs, context=context),
        "event_count": 1,
        "events": [event_json],
        "registry_snapshot": registry_metadata,
        "deterministic_repair": _deterministic_repair(issue_codes),
        "diagnostics": sorted(diagnostics, key=_diagnostic_sort_key),
    }


def _event_json(event: IdentityDriftEvent, *, context: DetectorContext) -> dict[str, object]:
    data: dict[str, object] = {
        "event_id": event.event_id,
        "issue_codes": list(event.issue_codes),
        "continuity_class": event.continuity_class,
        "basis_before": event.basis_before.to_json(),
        "basis_after": event.basis_after.to_json(),
        "observations": [
            _observation_ref_json(ref, context=context)
            for ref in sorted(event.observation_refs, key=lambda item: item.sort_key)
        ],
    }
    if event.registry_status:
        data["registry_status"] = event.registry_status
    if event.registry_candidates:
        data["registry_candidates"] = [
            candidate.to_json()
            for candidate in sorted(event.registry_candidates, key=lambda item: item.sort_key)
        ]
    return data


def _observation_ref_json(ref: IdentityObservationRef, *, context: DetectorContext) -> dict[str, object]:
    weak_fields = dict(ref.weak_key_fields)
    accession = ref.accession or context.accession
    data: dict[str, object] = {
        "accession": accession,
        "observation_ordinal": ref.observation_ordinal,
        "identity_basis": ref.reported_basis.to_json(),
        "source_paths": list(ref.source_paths) or [ref.observation_id],
    }
    optional = {
        "report_period": ref.report_period,
        "source_family": ref.source_family,
        "source_adapter": ref.source_adapter,
        "issuer_name": weak_fields.get("issuer_name", ""),
        "title_or_description": weak_fields.get("title_or_description", ""),
    }
    for key, value in sorted(optional.items()):
        if value:
            data[key] = value
    return data


def _source_scope(refs: tuple[IdentityObservationRef, ...], *, context: DetectorContext) -> dict[str, object]:
    first = refs[0] if refs else None
    accessions = sorted({ref.accession for ref in refs if ref.accession})
    if not accessions:
        accessions = [context.accession]
    data: dict[str, object] = {
        "scope_key": first.source_scope_key if first else context.accession,
        "accessions": accessions,
        "cik": context.cik,
    }
    if first is not None:
        if first.source_family:
            data["source_family"] = first.source_family
        if first.source_adapter:
            data["source_adapter"] = first.source_adapter
    return data


def _generated_artifact_payload(
    *,
    config: P009LedgerConfig,
    ledger: TemporalIdentityLedger,
    graph: AliasGraph,
    events: tuple[IdentityDriftEvent, ...],
    input_metadata: list[dict[str, object]],
    registry_metadata: dict[str, object],
    diagnostics: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_id": "cmdrvl.xew.instrument_identity_drift",
        "schema_version": "1.0",
        "detector_version": "XEW-P009.v1",
        "observation_inputs": input_metadata,
        "registry_snapshot": registry_metadata,
        "event_count": len(events),
        "events": [_artifact_event_json(event) for event in sorted(events, key=lambda item: item.sort_key)],
        "timelines": _timelines(ledger),
        "alias_graph": _alias_graph_summary(graph),
        "unresolved_candidates": [
            _artifact_event_json(event)
            for event in sorted(events, key=lambda item: item.sort_key)
            if event.continuity_class in {"registry_missing", "registry_ambiguous", "weak_unresolved", "weak_collision"}
        ],
        "caps": {
            "max_observations_per_scope": config.max_observations_per_scope,
            "max_events_per_issue_code": config.max_events_per_issue_code,
            "max_registry_candidates_per_event": config.max_registry_candidates_per_event,
            "max_source_refs_per_event": config.max_source_refs_per_event,
        },
        "diagnostics": sorted(diagnostics, key=_diagnostic_sort_key),
    }


def _artifact_event_json(event: IdentityDriftEvent) -> dict[str, object]:
    data = event.to_json()
    data["observation_refs"] = [
        ref.to_json()
        for ref in sorted(event.observation_refs, key=lambda item: item.sort_key)
    ]
    return data


def _timelines(ledger: TemporalIdentityLedger) -> list[dict[str, object]]:
    timelines = []
    for scope_key, refs in ledger.observations_by_scope().items():
        timelines.append(
            {
                "scope_key": scope_key,
                "observation_count": len(refs),
                "observations": [ref.to_json() for ref in refs],
            }
        )
    return sorted(timelines, key=lambda item: str(item.get("scope_key", "")))


def _alias_graph_summary(graph: AliasGraph) -> dict[str, object]:
    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "chain_count": len(graph.chains),
        "weak_group_count": len(graph.weak_groups),
        "chains": [chain.to_json() for chain in graph.chains],
        "weak_groups": [group.to_json() for group in graph.weak_groups],
    }


def _deterministic_repair(issue_codes: list[str]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    issue_set = set(issue_codes)
    if "registry_bridge_available" in issue_set:
        actions.append(
            {
                "target": "reported_identifier_fields",
                "action": "Preserve the reported strong identifier and the local registry FIGI bridge in downstream joins.",
            }
        )
    if "registry_bridge_missing" in issue_set or "weak_continuity_only" in issue_set:
        actions.append(
            {
                "target": "registry_seed_file",
                "action": "Materialize local registry rows for each reported CUSIP, ISIN, SEDOL, FIGI, or typed identifier before joining history.",
            }
        )
    if "registry_bridge_ambiguous" in issue_set:
        actions.append(
            {
                "target": "registry_candidate_review",
                "action": "Keep the chain unresolved until a deterministic local registry row selects exactly one instrument.",
            }
        )
    if "weak_key_temporal_collision" in issue_set:
        actions.append(
            {
                "target": "weak_key_join",
                "action": "Do not collapse records by ticker, name, title, value, or other weak descriptive evidence alone.",
            }
        )
    if "strong_identifier_removed" in issue_set or "identifier_basis_transition" in issue_set:
        actions.append(
            {
                "target": "source_reporting_fields",
                "action": "Retain the prior strong identifier field alongside any new identifier basis across reporting periods.",
            }
        )
    if not actions:
        actions.append(
            {
                "target": "instrument_identity_policy",
                "action": "Treat the temporal chain as unresolved unless strong identifier or local registry evidence proves continuity.",
            }
        )
    return sorted(actions, key=lambda item: (item["target"], item["action"]))


def _observation_diagnostics(diagnostics) -> list[dict[str, object]]:
    rows = []
    for diagnostic in diagnostics:
        data = diagnostic.to_json()
        rows.append(
            {
                "issue_code": str(data.get("code", "")),
                "message": str(data.get("message", "")),
                "source_path": str(data.get("source_path", "")),
            }
        )
    return rows


def _ledger_diagnostics(ledger: TemporalIdentityLedger) -> list[dict[str, object]]:
    rows = []
    for diagnostic in ledger.diagnostics:
        data = diagnostic.to_json()
        rows.append(
            {
                "issue_code": str(data.get("code", "")),
                "message": str(data.get("message", "")),
                "source_scope_key": str(data.get("source_scope_key", "")),
                "observation_id": str(data.get("observation_id", "")),
            }
        )
    return rows


def _diagnostic_sort_key(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(item.get("issue_code", "")),
        str(item.get("source_path", "")),
        str(item.get("source_scope_key", "")),
        str(item.get("message", "")),
    )


def _instance_id(signature: str) -> str:
    return hashlib.sha256(f"v1|{signature}".encode("ascii")).hexdigest()


def generated_artifact_from_p009_findings(
    findings: list[DetectorFinding],
    *,
    generated_at: str,
) -> dict[str, object] | None:
    for finding in sorted(findings, key=lambda item: getattr(item, "finding_id", "")):
        if getattr(finding, "pattern_id", "") != "XEW-P009":
            continue
        for instance in sorted(getattr(finding, "instances", []) or [], key=lambda item: getattr(item, "instance_id", "")):
            data = getattr(instance, "data", {}) or {}
            artifact = data.get("_generated_artifact")
            if isinstance(artifact, dict):
                return {
                    **artifact,
                    "generated_at": generated_at,
                }
    return None
