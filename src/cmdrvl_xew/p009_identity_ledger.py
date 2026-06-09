"""Temporal identity ledger and alias graph for XEW-P009.

This module is pure data/model logic. It does not read files, call providers,
or materialize registry data. Registry evidence is supplied by the caller as a
local lookup provider and is treated as deterministic input.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from .instrument_identity import normalize_text, normalize_ticker
from .p009_observations import P009InstrumentObservation


_REGISTRY_RESOLVED_STATUSES = {"resolved", "duplicate_identical"}
_REGISTRY_EVENT_STATUSES = {"resolved", "duplicate_identical", "missing", "ambiguous"}


@dataclass(frozen=True)
class IdentityBasis:
    """Strongest identity basis for one observation at one point in time."""

    basis_type: str
    basis_value: str = ""
    id_type: str = ""
    registry_status: str = ""

    @property
    def signature(self) -> str:
        return _signature_fields(
            (
                ("basis_type", self.basis_type),
                ("basis_value", self.basis_value),
                ("id_type", self.id_type),
                ("registry_status", self.registry_status),
            )
        )

    def to_json(self) -> dict[str, str]:
        data = {"basis_type": self.basis_type}
        if self.basis_value:
            data["basis_value"] = self.basis_value
        if self.id_type:
            data["id_type"] = self.id_type
        if self.registry_status:
            data["registry_status"] = self.registry_status
        return data


@dataclass(frozen=True, order=True)
class IdentityKey:
    """Canonical graph node for a strong identifier."""

    key_type: str
    value: str
    source: str = "reported"

    @property
    def signature(self) -> str:
        return _signature_fields(
            (
                ("source", self.source),
                ("key_type", self.key_type),
                ("value", self.value),
            )
        )

    def to_json(self) -> dict[str, str]:
        return {"key_type": self.key_type, "value": self.value, "source": self.source}


@dataclass(frozen=True)
class P009RegistryCandidate:
    """Local registry candidate supplied to the ledger."""

    figi: str
    id_type: str = ""
    id_value: str = ""
    row_hash: str = ""
    name: str = ""

    @property
    def stable_id(self) -> str:
        if self.row_hash:
            return self.row_hash
        payload = _signature_fields(
            (
                ("figi", self.figi),
                ("id_type", self.id_type),
                ("id_value", self.id_value),
                ("name", self.name),
            )
        )
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @property
    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (self.figi, self.id_type, self.id_value, self.stable_id, self.name)

    def to_json(self) -> dict[str, str]:
        data = {"figi": self.figi, "candidate_id": self.stable_id}
        optional = {
            "id_type": self.id_type,
            "id_value": self.id_value,
            "row_hash": self.row_hash,
            "name": self.name,
        }
        for key in sorted(optional):
            if optional[key]:
                data[key] = optional[key]
        return data


@dataclass(frozen=True)
class P009RegistryLookup:
    """Local registry lookup result for one observation."""

    status: str
    candidates: tuple[P009RegistryCandidate, ...] = ()
    diagnostic: str = ""

    @property
    def resolved_figi(self) -> str:
        if self.status in _REGISTRY_RESOLVED_STATUSES and self.candidates:
            return self.candidates[0].figi
        return ""

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {"status": self.status}
        if self.candidates:
            data["candidates"] = [candidate.to_json() for candidate in self.candidates]
        if self.diagnostic:
            data["diagnostic"] = self.diagnostic
        return data


class P009RegistryLookupProvider(Protocol):
    """Read-only local registry lookup provider."""

    def lookup_observation(self, observation: P009InstrumentObservation) -> P009RegistryLookup:
        """Return local registry evidence for an observation."""


@dataclass(frozen=True)
class StaticP009RegistryLookup:
    """Small deterministic lookup provider for tests and local fixtures."""

    lookups: dict[tuple[str, str], P009RegistryLookup]

    def lookup_observation(self, observation: P009InstrumentObservation) -> P009RegistryLookup:
        for key in _reported_identity_keys(observation):
            lookup = self.lookups.get((key.key_type, key.value))
            if lookup is not None:
                return _sort_lookup(lookup)
        return P009RegistryLookup(status="missing")


@dataclass(frozen=True)
class IdentityObservationRef:
    """Ledger reference to one normalized P009 observation."""

    observation_id: str
    source_scope_key: str
    source_family: str
    source_adapter: str
    source_id: str
    accession: str
    source_record_id: str
    report_period: str
    filed_date: str
    observation_ordinal: int
    source_paths: tuple[str, ...]
    reported_basis: IdentityBasis
    resolved_basis: IdentityBasis
    strong_keys: tuple[IdentityKey, ...]
    weak_key: str
    registry_lookup: P009RegistryLookup

    @property
    def sort_key(self) -> tuple[str, str, str, str, int, str]:
        return (
            self.report_period,
            self.source_id,
            self.source_scope_key,
            self.source_paths[0] if self.source_paths else "",
            self.observation_ordinal,
            self.observation_id,
        )

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "observation_id": self.observation_id,
            "source_scope_key": self.source_scope_key,
            "source_family": self.source_family,
            "source_adapter": self.source_adapter,
            "source_id": self.source_id,
            "report_period": self.report_period,
            "observation_ordinal": self.observation_ordinal,
            "source_paths": list(self.source_paths),
            "reported_basis": self.reported_basis.to_json(),
            "resolved_basis": self.resolved_basis.to_json(),
            "strong_keys": [key.to_json() for key in self.strong_keys],
            "weak_key": self.weak_key,
            "registry_lookup": self.registry_lookup.to_json(),
        }
        if self.accession:
            data["accession"] = self.accession
        if self.source_record_id:
            data["source_record_id"] = self.source_record_id
        if self.filed_date:
            data["filed_date"] = self.filed_date
        return data


@dataclass(frozen=True)
class AliasEdge:
    """Allowed strong-identity edge in the P009 alias graph."""

    left: IdentityKey
    right: IdentityKey
    edge_type: str
    observation_ids: tuple[str, ...] = ()
    registry_status: str = ""

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        left, right = _ordered_key_pair(self.left, self.right)
        return (self.edge_type, left.signature, right.signature, ",".join(self.observation_ids))

    @property
    def signature(self) -> str:
        left, right = _ordered_key_pair(self.left, self.right)
        return _signature_fields(
            (
                ("edge_type", self.edge_type),
                ("left", left.signature),
                ("right", right.signature),
                ("observation_ids", ",".join(self.observation_ids)),
                ("registry_status", self.registry_status),
            )
        )

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "edge_type": self.edge_type,
            "left": self.left.to_json(),
            "right": self.right.to_json(),
        }
        if self.observation_ids:
            data["observation_ids"] = list(self.observation_ids)
        if self.registry_status:
            data["registry_status"] = self.registry_status
        return data


@dataclass(frozen=True)
class IdentityChain:
    """Connected component of strong identity keys."""

    chain_id: str
    identity_keys: tuple[IdentityKey, ...]
    observation_refs: tuple[IdentityObservationRef, ...]
    continuity_class: str
    edge_types: tuple[str, ...] = ()

    @property
    def sort_key(self) -> tuple[str, str, str, str, int, str, str]:
        first_ref = self.observation_refs[0].sort_key if self.observation_refs else ("", "", "", "", 0, "")
        return (*first_ref, self.chain_id)

    def to_json(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "identity_keys": [key.to_json() for key in self.identity_keys],
            "observation_ids": [ref.observation_id for ref in self.observation_refs],
            "continuity_class": self.continuity_class,
            "edge_types": list(self.edge_types),
        }


@dataclass(frozen=True)
class WeakContinuityGroup:
    """Weak evidence group that cannot create a canonical chain by itself."""

    weak_key: str
    observation_refs: tuple[IdentityObservationRef, ...]
    strong_chain_ids: tuple[str, ...]
    strong_key_signatures: tuple[str, ...]

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.weak_key, ",".join(ref.observation_id for ref in self.observation_refs))

    def to_json(self) -> dict[str, object]:
        return {
            "weak_key": self.weak_key,
            "observation_ids": [ref.observation_id for ref in self.observation_refs],
            "strong_chain_ids": list(self.strong_chain_ids),
            "strong_key_signatures": list(self.strong_key_signatures),
        }


@dataclass(frozen=True)
class P009LedgerDiagnostic:
    """Deterministic diagnostic from ledger/graph/classifier stages."""

    code: str
    message: str
    source_scope_key: str = ""
    observation_id: str = ""

    @property
    def diagnostic_id(self) -> str:
        payload = json.dumps(self.to_json(include_id=False), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.code, self.source_scope_key, self.observation_id, self.message)

    def to_json(self, *, include_id: bool = True) -> dict[str, str]:
        data = {"code": self.code, "message": self.message}
        if include_id:
            data["diagnostic_id"] = self.diagnostic_id
        if self.source_scope_key:
            data["source_scope_key"] = self.source_scope_key
        if self.observation_id:
            data["observation_id"] = self.observation_id
        return data


@dataclass(frozen=True)
class P009LedgerConfig:
    """Deterministic caps for P009 temporal identity processing."""

    max_observations_per_scope: int = 10_000
    max_events_per_issue_code: int = 1_000
    max_registry_candidates_per_event: int = 20
    max_source_refs_per_event: int = 20


@dataclass(frozen=True)
class TemporalIdentityLedger:
    """Sorted P009 temporal observations plus lookup metadata."""

    observations: tuple[IdentityObservationRef, ...]
    diagnostics: tuple[P009LedgerDiagnostic, ...] = ()

    def observations_by_scope(self) -> dict[str, tuple[IdentityObservationRef, ...]]:
        grouped: dict[str, list[IdentityObservationRef]] = {}
        for observation in self.observations:
            grouped.setdefault(observation.source_scope_key, []).append(observation)
        return {
            scope: tuple(sorted(items, key=lambda item: item.sort_key))
            for scope, items in sorted(grouped.items())
        }

    def to_json(self) -> dict[str, object]:
        return {
            "observations": [observation.to_json() for observation in self.observations],
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True)
class AliasGraph:
    """Strong identity alias graph and weak continuity groups."""

    nodes: tuple[IdentityKey, ...]
    edges: tuple[AliasEdge, ...]
    chains: tuple[IdentityChain, ...]
    weak_groups: tuple[WeakContinuityGroup, ...]

    def chain_for_observation(self, observation_id: str) -> IdentityChain | None:
        for chain in self.chains:
            if any(ref.observation_id == observation_id for ref in chain.observation_refs):
                return chain
        return None

    def to_json(self) -> dict[str, object]:
        return {
            "nodes": [node.to_json() for node in self.nodes],
            "edges": [edge.to_json() for edge in self.edges],
            "chains": [chain.to_json() for chain in self.chains],
            "weak_groups": [group.to_json() for group in self.weak_groups],
        }


@dataclass(frozen=True)
class IdentityDriftEvent:
    """Classified P009 identity drift or unresolved fragility event."""

    event_id: str
    issue_codes: tuple[str, ...]
    continuity_class: str
    source_scope_key: str
    observation_refs: tuple[IdentityObservationRef, ...]
    basis_before: IdentityBasis
    basis_after: IdentityBasis
    registry_status: str = ""
    registry_candidates: tuple[P009RegistryCandidate, ...] = ()
    identity_keys: tuple[IdentityKey, ...] = ()
    weak_key: str = ""
    chain_id: str = ""

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        priority = {
            "registry_bridged": 0,
            "registry_ambiguous": 1,
            "proven_transition": 2,
            "registry_missing": 3,
            "weak_collision": 4,
            "weak_unresolved": 5,
        }.get(self.continuity_class, 9)
        newest = max((ref.report_period for ref in self.observation_refs), default="")
        return (priority, ",".join(self.issue_codes), _reverse_date_key(newest), self.event_id)

    @property
    def signature(self) -> str:
        return _signature_fields(
            (
                ("issue_codes", ",".join(self.issue_codes)),
                ("continuity_class", self.continuity_class),
                ("source_scope_key", self.source_scope_key),
                ("observation_ids", ",".join(ref.observation_id for ref in self.observation_refs)),
                ("basis_before", self.basis_before.signature),
                ("basis_after", self.basis_after.signature),
                ("registry_status", self.registry_status),
                ("registry_candidate_ids", ",".join(candidate.stable_id for candidate in self.registry_candidates)),
                ("identity_keys", ",".join(key.signature for key in self.identity_keys)),
                ("weak_key", self.weak_key),
                ("chain_id", self.chain_id),
            )
        )

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "event_id": self.event_id,
            "issue_codes": list(self.issue_codes),
            "continuity_class": self.continuity_class,
            "source_scope_key": self.source_scope_key,
            "observation_ids": [ref.observation_id for ref in self.observation_refs],
            "basis_before": self.basis_before.to_json(),
            "basis_after": self.basis_after.to_json(),
        }
        if self.registry_status:
            data["registry_status"] = self.registry_status
        if self.registry_candidates:
            data["registry_candidates"] = [candidate.to_json() for candidate in self.registry_candidates]
        if self.identity_keys:
            data["identity_keys"] = [key.to_json() for key in self.identity_keys]
        if self.weak_key:
            data["weak_key"] = self.weak_key
        if self.chain_id:
            data["chain_id"] = self.chain_id
        return data


def build_temporal_ledger(
    observations: tuple[P009InstrumentObservation, ...] | list[P009InstrumentObservation],
    registry_snapshot: P009RegistryLookupProvider | None = None,
    config: P009LedgerConfig | None = None,
) -> TemporalIdentityLedger:
    """Build a sorted temporal ledger from normalized P009 observations."""

    config = config or P009LedgerConfig()
    refs: list[IdentityObservationRef] = []
    diagnostics: list[P009LedgerDiagnostic] = []
    scoped_counts: dict[str, int] = {}
    for observation in sorted(observations, key=lambda item: item.sort_key):
        scope_key = observation.source_scope.scope_key
        scoped_counts[scope_key] = scoped_counts.get(scope_key, 0) + 1
        if scoped_counts[scope_key] > config.max_observations_per_scope:
            diagnostics.append(
                P009LedgerDiagnostic(
                    code="P009-LEDGER-E001",
                    message="max observations per source scope exceeded; observation omitted",
                    source_scope_key=scope_key,
                    observation_id=observation.observation_id,
                )
            )
            continue
        registry_lookup = _lookup_registry(registry_snapshot, observation)
        refs.append(_observation_ref(observation, registry_lookup))
    return TemporalIdentityLedger(
        observations=tuple(sorted(refs, key=lambda ref: ref.sort_key)),
        diagnostics=tuple(sorted(diagnostics, key=lambda diagnostic: diagnostic.sort_key)),
    )


def build_alias_graph(ledger: TemporalIdentityLedger) -> AliasGraph:
    """Build strong alias graph and weak continuity groups from a ledger."""

    nodes = sorted({key for ref in ledger.observations for key in ref.strong_keys})
    edges = _alias_edges(ledger.observations)
    chains = _identity_chains(nodes, edges, ledger.observations)
    weak_groups = _weak_groups(ledger.observations, chains)
    return AliasGraph(
        nodes=tuple(nodes),
        edges=tuple(sorted(edges, key=lambda edge: edge.sort_key)),
        chains=tuple(sorted(chains, key=lambda chain: chain.sort_key)),
        weak_groups=tuple(sorted(weak_groups, key=lambda group: group.sort_key)),
    )


def classify_identity_drift(
    ledger: TemporalIdentityLedger,
    graph: AliasGraph,
    config: P009LedgerConfig | None = None,
) -> tuple[IdentityDriftEvent, ...]:
    """Classify P009 drift/fragility events deterministically."""

    config = config or P009LedgerConfig()
    events: list[IdentityDriftEvent] = []
    for chain in graph.chains:
        events.extend(_chain_events(chain))
    for group in graph.weak_groups:
        events.extend(_weak_group_events(group, graph))
    events.extend(_registry_ambiguity_events(ledger))
    return _cap_events(events, config)


def stable_event_id(event: IdentityDriftEvent) -> str:
    """Return deterministic sha256 over the event signature."""

    return hashlib.sha256(f"v1|P009:event|{event.signature}".encode("ascii")).hexdigest()


def _observation_ref(
    observation: P009InstrumentObservation,
    registry_lookup: P009RegistryLookup,
) -> IdentityObservationRef:
    reported_basis = _reported_basis(observation)
    resolved_basis = _resolved_basis(reported_basis, registry_lookup)
    strong_keys = _strong_keys(observation, registry_lookup)
    source_paths = tuple(sorted(ref.signature_path for ref in observation.source_refs))
    return IdentityObservationRef(
        observation_id=observation.observation_id,
        source_scope_key=observation.source_scope.scope_key,
        source_family=observation.source_family,
        source_adapter=observation.source_adapter,
        source_id=observation.source_id,
        accession=observation.accession,
        source_record_id=observation.source_record_id,
        report_period=observation.report_period,
        filed_date=observation.filed_date,
        observation_ordinal=observation.observation_ordinal,
        source_paths=source_paths,
        reported_basis=reported_basis,
        resolved_basis=resolved_basis,
        strong_keys=strong_keys,
        weak_key=_weak_key(observation),
        registry_lookup=registry_lookup,
    )


def _reported_basis(observation: P009InstrumentObservation) -> IdentityBasis:
    basis_type, basis_value = observation.identifiers.strongest_basis
    if basis_type == "absent" and observation.weak_evidence.has_weak_evidence:
        return IdentityBasis("weak_descriptive", _weak_key(observation))
    if basis_type == "other_typed_identifier" and ":" in basis_value:
        id_type, value = basis_value.split(":", 1)
        return IdentityBasis(basis_type, value, id_type=id_type)
    return IdentityBasis(basis_type, basis_value)


def _resolved_basis(reported_basis: IdentityBasis, registry_lookup: P009RegistryLookup) -> IdentityBasis:
    figi = registry_lookup.resolved_figi
    if figi:
        return IdentityBasis("figi_from_registry", figi, registry_status=registry_lookup.status)
    if registry_lookup.status in {"missing", "ambiguous", "snapshot_invalid"}:
        return IdentityBasis(
            reported_basis.basis_type,
            reported_basis.basis_value,
            id_type=reported_basis.id_type,
            registry_status=registry_lookup.status,
        )
    return reported_basis


def _strong_keys(
    observation: P009InstrumentObservation,
    registry_lookup: P009RegistryLookup,
) -> tuple[IdentityKey, ...]:
    keys = list(_reported_identity_keys(observation))
    if registry_lookup.resolved_figi:
        keys.append(IdentityKey("figi", registry_lookup.resolved_figi, source="registry"))
    return tuple(sorted(set(keys)))


def _reported_identity_keys(observation: P009InstrumentObservation) -> tuple[IdentityKey, ...]:
    ids = observation.identifiers
    keys: list[IdentityKey] = []
    for key_type, value in (
        ("figi", ids.figi),
        ("cusip", ids.cusip),
        ("isin", ids.isin),
        ("sedol", ids.sedol),
    ):
        if value:
            keys.append(IdentityKey(key_type, value))
    for id_type, value in ids.other_identifiers:
        keys.append(IdentityKey("other_typed_identifier", f"{id_type}:{value}"))
    return tuple(sorted(set(keys)))


def _lookup_registry(
    registry_snapshot: P009RegistryLookupProvider | None,
    observation: P009InstrumentObservation,
) -> P009RegistryLookup:
    if registry_snapshot is None:
        return P009RegistryLookup(status="snapshot_absent")
    return _sort_lookup(registry_snapshot.lookup_observation(observation))


def _sort_lookup(lookup: P009RegistryLookup) -> P009RegistryLookup:
    return P009RegistryLookup(
        status=lookup.status,
        candidates=tuple(sorted(lookup.candidates, key=lambda candidate: candidate.sort_key)),
        diagnostic=lookup.diagnostic,
    )


def _alias_edges(observation_refs: tuple[IdentityObservationRef, ...]) -> set[AliasEdge]:
    edges: set[AliasEdge] = set()
    for ref in observation_refs:
        reported_keys = tuple(key for key in ref.strong_keys if key.source == "reported")
        for left, right in _pairwise(reported_keys):
            edges.add(
                AliasEdge(
                    left=left,
                    right=right,
                    edge_type="same_observation",
                    observation_ids=(ref.observation_id,),
                )
            )
        registry_keys = tuple(key for key in ref.strong_keys if key.source == "registry")
        if ref.registry_lookup.status in _REGISTRY_RESOLVED_STATUSES:
            for reported in reported_keys:
                for registry in registry_keys:
                    edges.add(
                        AliasEdge(
                            left=reported,
                            right=registry,
                            edge_type="registry_bridge",
                            observation_ids=(ref.observation_id,),
                            registry_status=ref.registry_lookup.status,
                        )
                    )
    keys_by_value: dict[tuple[str, str], set[IdentityKey]] = {}
    observations_by_value: dict[tuple[str, str], set[str]] = {}
    for ref in observation_refs:
        for key in ref.strong_keys:
            value_key = (key.key_type, key.value)
            keys_by_value.setdefault(value_key, set()).add(key)
            observations_by_value.setdefault(value_key, set()).add(ref.observation_id)
    for value_key, keys in keys_by_value.items():
        for left, right in _pairwise(tuple(sorted(keys))):
            edges.add(
                AliasEdge(
                    left=left,
                    right=right,
                    edge_type="exact_identifier",
                    observation_ids=tuple(sorted(observations_by_value[value_key])),
                )
            )
    return edges


def _identity_chains(
    nodes: list[IdentityKey],
    edges: set[AliasEdge],
    observation_refs: tuple[IdentityObservationRef, ...],
) -> list[IdentityChain]:
    adjacency: dict[IdentityKey, set[IdentityKey]] = {node: set() for node in nodes}
    for edge in edges:
        adjacency.setdefault(edge.left, set()).add(edge.right)
        adjacency.setdefault(edge.right, set()).add(edge.left)
    seen: set[IdentityKey] = set()
    edge_types_by_component: dict[tuple[IdentityKey, ...], set[str]] = {}
    components: list[tuple[IdentityKey, ...]] = []
    for node in nodes:
        if node in seen:
            continue
        stack = [node]
        component: set[IdentityKey] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.add(current)
            stack.extend(sorted(adjacency.get(current, ()), reverse=True))
        ordered = tuple(sorted(component))
        components.append(ordered)
        edge_types_by_component[ordered] = {
            edge.edge_type
            for edge in edges
            if edge.left in component and edge.right in component
        }

    chains: list[IdentityChain] = []
    for component in components:
        component_set = set(component)
        refs = tuple(
            ref for ref in observation_refs if component_set.intersection(ref.strong_keys)
        )
        if not refs:
            continue
        chain_id = _chain_id(component)
        edge_types = tuple(sorted(edge_types_by_component[component]))
        chains.append(
            IdentityChain(
                chain_id=chain_id,
                identity_keys=component,
                observation_refs=tuple(sorted(refs, key=lambda ref: ref.sort_key)),
                continuity_class="registry_bridged" if "registry_bridge" in edge_types else "proven",
                edge_types=edge_types,
            )
        )
    return chains


def _weak_groups(
    observation_refs: tuple[IdentityObservationRef, ...],
    chains: list[IdentityChain],
) -> list[WeakContinuityGroup]:
    chain_by_observation: dict[str, str] = {}
    for chain in chains:
        for ref in chain.observation_refs:
            chain_by_observation[ref.observation_id] = chain.chain_id
    grouped: dict[str, list[IdentityObservationRef]] = {}
    for ref in observation_refs:
        if ref.weak_key:
            grouped.setdefault(ref.weak_key, []).append(ref)
    weak_groups: list[WeakContinuityGroup] = []
    for weak_key, refs in grouped.items():
        if len(refs) < 2:
            continue
        strong_chain_ids = tuple(
            sorted({chain_by_observation[ref.observation_id] for ref in refs if ref.observation_id in chain_by_observation})
        )
        strong_key_signatures = tuple(
            sorted({key.signature for ref in refs for key in ref.strong_keys})
        )
        weak_groups.append(
            WeakContinuityGroup(
                weak_key=weak_key,
                observation_refs=tuple(sorted(refs, key=lambda ref: ref.sort_key)),
                strong_chain_ids=strong_chain_ids,
                strong_key_signatures=strong_key_signatures,
            )
        )
    return weak_groups


def _chain_events(chain: IdentityChain) -> list[IdentityDriftEvent]:
    refs = tuple(sorted(chain.observation_refs, key=lambda ref: ref.sort_key))
    if len(refs) < 2:
        return []
    first = refs[0]
    last = refs[-1]
    issue_codes: list[str] = []
    if first.reported_basis != last.reported_basis:
        issue_codes.append("identifier_basis_transition")
    if any(ref.registry_lookup.status in _REGISTRY_RESOLVED_STATUSES for ref in refs):
        issue_codes.append("registry_bridge_available")
    if not issue_codes:
        return []
    continuity_class = "registry_bridged" if "registry_bridge_available" in issue_codes else "proven_transition"
    event = IdentityDriftEvent(
        event_id="",
        issue_codes=tuple(sorted(set(issue_codes))),
        continuity_class=continuity_class,
        source_scope_key=first.source_scope_key,
        observation_refs=refs,
        basis_before=first.reported_basis,
        basis_after=last.reported_basis,
        registry_status=_dominant_registry_status(refs),
        registry_candidates=_registry_candidates(refs),
        identity_keys=chain.identity_keys,
        chain_id=chain.chain_id,
    )
    return [_with_event_id(event)]


def _weak_group_events(group: WeakContinuityGroup, graph: AliasGraph) -> list[IdentityDriftEvent]:
    events: list[IdentityDriftEvent] = []
    refs = group.observation_refs
    first = refs[0]
    last = refs[-1]
    chain_count = len(group.strong_chain_ids)
    has_unresolved_ref = any(not ref.strong_keys for ref in refs)
    if chain_count > 1:
        event = IdentityDriftEvent(
            event_id="",
            issue_codes=("weak_key_temporal_collision",),
            continuity_class="weak_collision",
            source_scope_key=first.source_scope_key,
            observation_refs=refs,
            basis_before=first.reported_basis,
            basis_after=last.reported_basis,
            identity_keys=_keys_for_chain_ids(graph, group.strong_chain_ids),
            weak_key=group.weak_key,
        )
        events.append(_with_event_id(event))
    if chain_count == 0 or has_unresolved_ref:
        issue_codes = ["weak_continuity_only"]
        if _has_strong_removed(refs):
            issue_codes.append("strong_identifier_removed")
        if any(ref.registry_lookup.status == "missing" for ref in refs):
            issue_codes.append("registry_bridge_missing")
        continuity_class = "registry_missing" if "registry_bridge_missing" in issue_codes else "weak_unresolved"
        event = IdentityDriftEvent(
            event_id="",
            issue_codes=tuple(sorted(issue_codes)),
            continuity_class=continuity_class,
            source_scope_key=first.source_scope_key,
            observation_refs=refs,
            basis_before=first.reported_basis,
            basis_after=last.reported_basis,
            registry_status=_dominant_registry_status(refs),
            registry_candidates=_registry_candidates(refs),
            weak_key=group.weak_key,
        )
        events.append(_with_event_id(event))
    return events


def _registry_ambiguity_events(ledger: TemporalIdentityLedger) -> list[IdentityDriftEvent]:
    events: list[IdentityDriftEvent] = []
    for ref in ledger.observations:
        if ref.registry_lookup.status != "ambiguous":
            continue
        event = IdentityDriftEvent(
            event_id="",
            issue_codes=("registry_bridge_ambiguous",),
            continuity_class="registry_ambiguous",
            source_scope_key=ref.source_scope_key,
            observation_refs=(ref,),
            basis_before=ref.reported_basis,
            basis_after=ref.reported_basis,
            registry_status=ref.registry_lookup.status,
            registry_candidates=ref.registry_lookup.candidates,
            identity_keys=ref.strong_keys,
            weak_key=ref.weak_key,
        )
        events.append(_with_event_id(event))
    return events


def _cap_events(
    events: list[IdentityDriftEvent],
    config: P009LedgerConfig,
) -> tuple[IdentityDriftEvent, ...]:
    sorted_events = sorted(events, key=lambda event: event.sort_key)
    counts: dict[str, int] = {}
    capped: list[IdentityDriftEvent] = []
    for event in sorted_events:
        primary_code = event.issue_codes[0]
        counts[primary_code] = counts.get(primary_code, 0) + 1
        if counts[primary_code] > config.max_events_per_issue_code:
            continue
        candidates = event.registry_candidates[: config.max_registry_candidates_per_event]
        refs = tuple(_cap_ref_source_paths(ref, config.max_source_refs_per_event) for ref in event.observation_refs)
        if candidates != event.registry_candidates or refs != event.observation_refs:
            event = IdentityDriftEvent(
                event_id="",
                issue_codes=event.issue_codes,
                continuity_class=event.continuity_class,
                source_scope_key=event.source_scope_key,
                observation_refs=refs,
                basis_before=event.basis_before,
                basis_after=event.basis_after,
                registry_status=event.registry_status,
                registry_candidates=candidates,
                identity_keys=event.identity_keys,
                weak_key=event.weak_key,
                chain_id=event.chain_id,
            )
            event = _with_event_id(event)
        capped.append(event)
    return tuple(capped)


def _cap_ref_source_paths(ref: IdentityObservationRef, limit: int) -> IdentityObservationRef:
    if len(ref.source_paths) <= limit:
        return ref
    return IdentityObservationRef(
        observation_id=ref.observation_id,
        source_scope_key=ref.source_scope_key,
        source_family=ref.source_family,
        source_adapter=ref.source_adapter,
        source_id=ref.source_id,
        accession=ref.accession,
        source_record_id=ref.source_record_id,
        report_period=ref.report_period,
        filed_date=ref.filed_date,
        observation_ordinal=ref.observation_ordinal,
        source_paths=ref.source_paths[:limit],
        reported_basis=ref.reported_basis,
        resolved_basis=ref.resolved_basis,
        strong_keys=ref.strong_keys,
        weak_key=ref.weak_key,
        registry_lookup=ref.registry_lookup,
    )


def _with_event_id(event: IdentityDriftEvent) -> IdentityDriftEvent:
    return IdentityDriftEvent(
        event_id=stable_event_id(event),
        issue_codes=event.issue_codes,
        continuity_class=event.continuity_class,
        source_scope_key=event.source_scope_key,
        observation_refs=event.observation_refs,
        basis_before=event.basis_before,
        basis_after=event.basis_after,
        registry_status=event.registry_status,
        registry_candidates=event.registry_candidates,
        identity_keys=event.identity_keys,
        weak_key=event.weak_key,
        chain_id=event.chain_id,
    )


def _weak_key(observation: P009InstrumentObservation) -> str:
    fields = list(observation.weak_evidence.signature_fields)
    ticker = normalize_ticker(observation.identifiers.ticker)
    if ticker:
        fields.append(("ticker", ticker))
    if not fields:
        return ""
    return f"P009:weak|{_signature_fields(tuple(fields))}"


def _has_strong_removed(refs: tuple[IdentityObservationRef, ...]) -> bool:
    saw_strong = False
    for ref in sorted(refs, key=lambda item: item.sort_key):
        if ref.strong_keys:
            saw_strong = True
        elif saw_strong:
            return True
    return False


def _dominant_registry_status(refs: tuple[IdentityObservationRef, ...]) -> str:
    priority = ("ambiguous", "resolved", "duplicate_identical", "missing", "snapshot_invalid", "snapshot_absent")
    statuses = {ref.registry_lookup.status for ref in refs if ref.registry_lookup.status in _REGISTRY_EVENT_STATUSES or ref.registry_lookup.status == "snapshot_absent"}
    for status in priority:
        if status in statuses:
            return status
    return ""


def _registry_candidates(refs: tuple[IdentityObservationRef, ...]) -> tuple[P009RegistryCandidate, ...]:
    candidates = {
        candidate.stable_id: candidate
        for ref in refs
        for candidate in ref.registry_lookup.candidates
    }
    return tuple(sorted(candidates.values(), key=lambda candidate: candidate.sort_key))


def _keys_for_chain_ids(graph: AliasGraph, chain_ids: tuple[str, ...]) -> tuple[IdentityKey, ...]:
    keys: set[IdentityKey] = set()
    target = set(chain_ids)
    for chain in graph.chains:
        if chain.chain_id in target:
            keys.update(chain.identity_keys)
    return tuple(sorted(keys))


def _chain_id(keys: tuple[IdentityKey, ...]) -> str:
    signature = ",".join(key.signature for key in keys)
    return hashlib.sha256(f"v1|P009:chain|{signature}".encode("ascii")).hexdigest()


def _ordered_key_pair(left: IdentityKey, right: IdentityKey) -> tuple[IdentityKey, IdentityKey]:
    return (left, right) if left <= right else (right, left)


def _pairwise(keys: tuple[IdentityKey, ...]) -> list[tuple[IdentityKey, IdentityKey]]:
    pairs: list[tuple[IdentityKey, IdentityKey]] = []
    ordered = tuple(sorted(keys))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            pairs.append((left, right))
    return pairs


def _signature_fields(fields: tuple[tuple[str, str], ...]) -> str:
    parts = []
    for key, value in sorted((key, value) for key, value in fields if value):
        parts.append(f"{_safe_token(key)}={_safe_token(value)}")
    return ";".join(parts)


def _safe_token(value: object) -> str:
    text = normalize_text(value)
    encoded = json.dumps(text, ensure_ascii=True, separators=(",", ":"))
    return encoded[1:-1].replace("|", "%7C").replace("=", "%3D")


def _reverse_date_key(value: str) -> str:
    digits = value.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{99999999 - int(digits):08d}"
    return "99999999"
