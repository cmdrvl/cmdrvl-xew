from __future__ import annotations

import json
import unittest

from cmdrvl_xew.p009_identity_ledger import (
    P009RegistryCandidate,
    P009RegistryLookup,
    StaticP009RegistryLookup,
    build_alias_graph,
    build_temporal_ledger,
    classify_identity_drift,
)
from cmdrvl_xew.p009_observations import parse_p009_observation_rows


def _observations(rows: list[dict[str, object]]):
    prepared = []
    for index, row in enumerate(rows):
        base = {
            "source_family": "local_export",
            "source_adapter": "ledger_test",
            "scope_key": "scope:alpha",
            "source_record_id": f"row-{index + 1}",
            "observation_ordinal": index,
            "issuer_name": "Example Issuer",
            "title_or_description": "Example Security",
            "source_path": f"fixture.jsonl#row={index + 1}",
        }
        base.update(row)
        prepared.append(base)
    result = parse_p009_observation_rows(
        "\n".join(json.dumps(row, sort_keys=True) for row in prepared) + "\n"
    )
    if result.diagnostics:
        raise AssertionError([diagnostic.to_json() for diagnostic in result.diagnostics])
    return result.observations


def _graph(rows, registry=None):
    ledger = build_temporal_ledger(_observations(rows), registry_snapshot=registry)
    graph = build_alias_graph(ledger)
    events = classify_identity_drift(ledger, graph)
    return ledger, graph, events


class TestP009IdentityLedger(unittest.TestCase):
    def test_exact_cusip_continuity_creates_proven_chain_without_drift_event(self):
        ledger, graph, events = _graph(
            [
                {"report_period": "2026-01-31", "cusip": "123456AB7"},
                {"report_period": "2026-02-28", "cusip": "123456AB7"},
            ]
        )

        self.assertEqual(len(ledger.observations), 2)
        self.assertEqual(len(graph.chains), 1)
        self.assertEqual(graph.chains[0].continuity_class, "proven")
        self.assertEqual(len(graph.chains[0].observation_refs), 2)
        self.assertEqual(events, ())

    def test_same_observation_alias_supports_identifier_basis_transition(self):
        _ledger, graph, events = _graph(
            [
                {"report_period": "2026-01-31", "isin": "US123456AB78"},
                {"report_period": "2026-02-28", "cusip": "123456AB7", "isin": "US123456AB78"},
            ]
        )

        self.assertEqual(len(graph.chains), 1)
        self.assertIn("same_observation", graph.chains[0].edge_types)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].issue_codes, ("identifier_basis_transition",))
        self.assertEqual(events[0].continuity_class, "proven_transition")
        self.assertEqual(events[0].basis_before.basis_type, "isin")
        self.assertEqual(events[0].basis_after.basis_type, "cusip")

    def test_registry_bridge_connects_cusip_to_later_reported_figi(self):
        registry = StaticP009RegistryLookup(
            {
                ("cusip", "123456AB7"): P009RegistryLookup(
                    status="resolved",
                    candidates=(
                        P009RegistryCandidate(
                            figi="BBG000000001",
                            id_type="cusip",
                            id_value="123456AB7",
                            row_hash="registry-row-1",
                        ),
                    ),
                )
            }
        )
        _ledger, graph, events = _graph(
            [
                {"report_period": "2026-01-31", "cusip": "123456AB7"},
                {"report_period": "2026-02-28", "figi": "BBG000000001"},
            ],
            registry=registry,
        )

        self.assertEqual(len(graph.chains), 1)
        self.assertIn("registry_bridge", graph.chains[0].edge_types)
        self.assertIn("exact_identifier", graph.chains[0].edge_types)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].continuity_class, "registry_bridged")
        self.assertEqual(
            set(events[0].issue_codes),
            {"identifier_basis_transition", "registry_bridge_available"},
        )
        self.assertEqual(events[0].registry_candidates[0].figi, "BBG000000001")

    def test_weak_continuity_only_never_creates_resolved_chain(self):
        _ledger, graph, events = _graph(
            [
                {
                    "report_period": "2026-01-31",
                    "ticker": "EXM",
                    "value": "100",
                },
                {
                    "report_period": "2026-02-28",
                    "ticker": "EXM",
                    "value": "100",
                },
            ]
        )

        self.assertEqual(graph.chains, ())
        self.assertEqual(len(graph.weak_groups), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].issue_codes, ("weak_continuity_only",))
        self.assertEqual(events[0].continuity_class, "weak_unresolved")

    def test_same_weak_key_mapping_to_two_strong_ids_is_collision(self):
        _ledger, graph, events = _graph(
            [
                {
                    "report_period": "2026-01-31",
                    "ticker": "EXM",
                    "value": "100",
                    "cusip": "111111111",
                },
                {
                    "report_period": "2026-02-28",
                    "ticker": "EXM",
                    "value": "100",
                    "cusip": "222222222",
                },
            ]
        )

        self.assertEqual(len(graph.chains), 2)
        self.assertEqual(len(graph.weak_groups), 1)
        self.assertEqual(graph.weak_groups[0].strong_chain_ids, tuple(sorted(graph.weak_groups[0].strong_chain_ids)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].issue_codes, ("weak_key_temporal_collision",))
        self.assertEqual(events[0].continuity_class, "weak_collision")

    def test_ambiguous_registry_rows_are_preserved_without_winner(self):
        registry = StaticP009RegistryLookup(
            {
                ("cusip", "123456AB7"): P009RegistryLookup(
                    status="ambiguous",
                    candidates=(
                        P009RegistryCandidate(figi="BBG000000002", row_hash="row-b"),
                        P009RegistryCandidate(figi="BBG000000001", row_hash="row-a"),
                    ),
                )
            }
        )
        ledger, graph, events = _graph(
            [{"report_period": "2026-01-31", "cusip": "123456AB7"}],
            registry=registry,
        )

        self.assertEqual(len(graph.chains), 1)
        self.assertNotIn("registry_bridge", graph.chains[0].edge_types)
        self.assertEqual(ledger.observations[0].resolved_basis.registry_status, "ambiguous")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].issue_codes, ("registry_bridge_ambiguous",))
        self.assertEqual(events[0].continuity_class, "registry_ambiguous")
        self.assertEqual([candidate.figi for candidate in events[0].registry_candidates], ["BBG000000001", "BBG000000002"])

    def test_ledger_graph_and_events_are_byte_stable(self):
        rows = [
            {
                "source_record_id": "stable-row-3",
                "source_path": "fixture.jsonl#stable-row-3",
                "row_number": 3,
                "observation_ordinal": 3,
                "report_period": "2026-03-31",
                "cusip": "333333333",
            },
            {
                "source_record_id": "stable-row-1",
                "source_path": "fixture.jsonl#stable-row-1",
                "row_number": 1,
                "observation_ordinal": 1,
                "report_period": "2026-01-31",
                "cusip": "111111111",
            },
            {
                "source_record_id": "stable-row-2",
                "source_path": "fixture.jsonl#stable-row-2",
                "row_number": 2,
                "observation_ordinal": 2,
                "report_period": "2026-02-28",
                "cusip": "111111111",
                "figi": "BBG000000003",
            },
        ]

        first = _graph(rows)
        second = _graph(list(reversed(rows)))

        first_json = json.dumps(
            {
                "ledger": first[0].to_json(),
                "graph": first[1].to_json(),
                "events": [event.to_json() for event in first[2]],
            },
            sort_keys=True,
        )
        second_json = json.dumps(
            {
                "ledger": second[0].to_json(),
                "graph": second[1].to_json(),
                "events": [event.to_json() for event in second[2]],
            },
            sort_keys=True,
        )

        self.assertEqual(first_json, second_json)


if __name__ == "__main__":
    unittest.main()
