from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmdrvl_xew.cli import main
from cmdrvl_xew.exit_codes import ExitCode
from cmdrvl_xew.instrument_registry import InstrumentRegistrySnapshot
from cmdrvl_xew.p009_corpus import load_p009_corpus
from cmdrvl_xew.p009_identity_ledger import InstrumentRegistryP009Lookup
from cmdrvl_xew.p009_scan import scan_p009_corpus, write_p009_scan_outputs


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


def _manifest_row(
    source_id: str,
    *,
    scope_key: str,
    report_period: str,
    filed_date: str,
) -> dict[str, object]:
    return {
        "schema_version": "p009_corpus_manifest.v1",
        "source_family": "local_export",
        "source_adapter": "scan_fixture",
        "scope_key": scope_key,
        "source_record_id": source_id,
        "report_period": report_period,
        "filed_date": filed_date,
        "local_path": f"{source_id}.jsonl",
    }


def _observation_row(
    source_id: str,
    *,
    scope_key: str,
    report_period: str,
    filed_date: str,
    observation_ordinal: int,
    **identity: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "p009_observations.v1",
        "source_family": "local_export",
        "source_adapter": "scan_fixture",
        "scope_key": scope_key,
        "source_record_id": source_id,
        "report_period": report_period,
        "filed_date": filed_date,
        "observation_ordinal": observation_ordinal,
        "source_path": f"{source_id}.jsonl#row=1",
    }
    row.update(identity)
    return row


def _write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
                "schema_version": "1.0",
                "snapshot_id": "p009-scan-test",
                "generated_at": "2026-06-09T00:00:00Z",
                "source": {"producer": "canon", "dataset": "openfigi"},
                "rows": [
                    {"figi": "BBG000000001", "cusip": "123456AB7", "name": "Bridge Security"},
                    {"figi": "BBG000000002", "cusip": "999999AB9", "name": "Clean Security"},
                    {"figi": "BBG000000003", "cusip": "222222AB2", "name": "Ambiguous A"},
                    {"figi": "BBG000000004", "cusip": "222222AB2", "name": "Ambiguous B"},
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_scan_fixture(root: Path) -> tuple[Path, Path, Path]:
    manifest = root / "p009_corpus_manifest.v1.jsonl"
    observations = root / "p009_observations.v1.jsonl"
    registry = root / "registry.json"
    rows = [
        _manifest_row("bridge-jan", scope_key="fund:bridge", report_period="2026-01-31", filed_date="2026-02-02"),
        _manifest_row("bridge-feb", scope_key="fund:bridge", report_period="2026-02-28", filed_date="2026-03-02"),
        _manifest_row("ambiguous-jan", scope_key="fund:ambiguous", report_period="2026-01-31", filed_date="2026-02-05"),
        _manifest_row("weak-jan", scope_key="fund:weak", report_period="2026-01-31", filed_date="2026-02-04"),
        _manifest_row("weak-feb", scope_key="fund:weak", report_period="2026-02-28", filed_date="2026-03-04"),
        _manifest_row("clean-jan", scope_key="fund:clean", report_period="2026-01-31", filed_date="2026-02-03"),
        _manifest_row("clean-feb", scope_key="fund:clean", report_period="2026-02-28", filed_date="2026-03-03"),
    ]
    manifest.write_text(_jsonl(rows), encoding="utf-8")
    for row in rows:
        (root / str(row["local_path"])).write_text("{}\n", encoding="utf-8")
    observations.write_text(
        _jsonl(
            [
                _observation_row(
                    "bridge-jan",
                    scope_key="fund:bridge",
                    report_period="2026-01-31",
                    filed_date="2026-02-02",
                    observation_ordinal=0,
                    cusip="123456AB7",
                    issuer_name="Bridge Issuer",
                    title_or_description="Bridge Security",
                    value="100000000",
                ),
                _observation_row(
                    "bridge-feb",
                    scope_key="fund:bridge",
                    report_period="2026-02-28",
                    filed_date="2026-03-02",
                    observation_ordinal=0,
                    figi="BBG000000001",
                    issuer_name="Bridge Issuer",
                    title_or_description="Bridge Security",
                    value="100000000",
                ),
                _observation_row(
                    "ambiguous-jan",
                    scope_key="fund:ambiguous",
                    report_period="2026-01-31",
                    filed_date="2026-02-05",
                    observation_ordinal=0,
                    cusip="222222AB2",
                    issuer_name="Ambiguous Issuer",
                    title_or_description="Ambiguous Security",
                    value="50000000",
                ),
                _observation_row(
                    "weak-jan",
                    scope_key="fund:weak",
                    report_period="2026-01-31",
                    filed_date="2026-02-04",
                    observation_ordinal=0,
                    ticker="WEAK",
                    issuer_name="Weak Issuer",
                    title_or_description="Weak Security",
                    value="25000000",
                ),
                _observation_row(
                    "weak-feb",
                    scope_key="fund:weak",
                    report_period="2026-02-28",
                    filed_date="2026-03-04",
                    observation_ordinal=0,
                    ticker="WEAK",
                    issuer_name="Weak Issuer",
                    title_or_description="Weak Security",
                    value="25000000",
                ),
                _observation_row(
                    "clean-jan",
                    scope_key="fund:clean",
                    report_period="2026-01-31",
                    filed_date="2026-02-03",
                    observation_ordinal=0,
                    cusip="999999AB9",
                    issuer_name="Clean Issuer",
                    title_or_description="Clean Security",
                    value="75000000",
                ),
                _observation_row(
                    "clean-feb",
                    scope_key="fund:clean",
                    report_period="2026-02-28",
                    filed_date="2026-03-03",
                    observation_ordinal=0,
                    cusip="999999AB9",
                    issuer_name="Clean Issuer",
                    title_or_description="Clean Security",
                    value="75000000",
                ),
            ]
        ),
        encoding="utf-8",
    )
    _write_registry(registry)
    return manifest, observations, registry


def _write_single_fragile_scan_fixture(root: Path) -> tuple[Path, Path, Path]:
    manifest = root / "p009_single_fragile_manifest.v1.jsonl"
    observations = root / "p009_single_fragile_observations.v1.jsonl"
    registry = root / "single-fragile-registry.json"
    rows = [
        _manifest_row("fragile-jan", scope_key="fund:fragile", report_period="2026-01-31", filed_date="2026-02-02"),
        _manifest_row("fragile-feb", scope_key="fund:fragile", report_period="2026-02-28", filed_date="2026-03-02"),
        _manifest_row("clean-a-jan", scope_key="fund:clean-a", report_period="2026-01-31", filed_date="2026-02-03"),
        _manifest_row("clean-a-feb", scope_key="fund:clean-a", report_period="2026-02-28", filed_date="2026-03-03"),
        _manifest_row("clean-b-jan", scope_key="fund:clean-b", report_period="2026-01-31", filed_date="2026-02-04"),
        _manifest_row("clean-b-feb", scope_key="fund:clean-b", report_period="2026-02-28", filed_date="2026-03-04"),
    ]
    manifest.write_text(_jsonl(rows), encoding="utf-8")
    for row in rows:
        (root / str(row["local_path"])).write_text("{}\n", encoding="utf-8")
    observations.write_text(
        _jsonl(
            [
                _observation_row(
                    "fragile-jan",
                    scope_key="fund:fragile",
                    report_period="2026-01-31",
                    filed_date="2026-02-02",
                    observation_ordinal=0,
                    cusip="123456AB7",
                    issuer_name="Fragile Issuer",
                    title_or_description="Fragile Security",
                    value="100000000",
                ),
                _observation_row(
                    "fragile-feb",
                    scope_key="fund:fragile",
                    report_period="2026-02-28",
                    filed_date="2026-03-02",
                    observation_ordinal=0,
                    figi="BBG000000001",
                    issuer_name="Fragile Issuer",
                    title_or_description="Fragile Security",
                    value="100000000",
                ),
                _observation_row(
                    "clean-a-jan",
                    scope_key="fund:clean-a",
                    report_period="2026-01-31",
                    filed_date="2026-02-03",
                    observation_ordinal=0,
                    cusip="999999AB9",
                    issuer_name="Clean A Issuer",
                    title_or_description="Clean A Security",
                    value="75000000",
                ),
                _observation_row(
                    "clean-a-feb",
                    scope_key="fund:clean-a",
                    report_period="2026-02-28",
                    filed_date="2026-03-03",
                    observation_ordinal=0,
                    cusip="999999AB9",
                    issuer_name="Clean A Issuer",
                    title_or_description="Clean A Security",
                    value="75000000",
                ),
                _observation_row(
                    "clean-b-jan",
                    scope_key="fund:clean-b",
                    report_period="2026-01-31",
                    filed_date="2026-02-04",
                    observation_ordinal=0,
                    isin="US111111AB18",
                    issuer_name="Clean B Issuer",
                    title_or_description="Clean B Security",
                    value="50000000",
                ),
                _observation_row(
                    "clean-b-feb",
                    scope_key="fund:clean-b",
                    report_period="2026-02-28",
                    filed_date="2026-03-04",
                    observation_ordinal=0,
                    isin="US111111AB18",
                    issuer_name="Clean B Issuer",
                    title_or_description="Clean B Security",
                    value="50000000",
                ),
            ]
        ),
        encoding="utf-8",
    )
    registry.write_text(
        json.dumps(
            {
                "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
                "schema_version": "1.0",
                "snapshot_id": "p009-single-fragile-scan-test",
                "generated_at": "2026-06-09T00:00:00Z",
                "source": {"producer": "canon", "dataset": "openfigi"},
                "rows": [{"figi": "BBG000000001", "cusip": "123456AB7", "name": "Fragile Security"}],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest, observations, registry


class TestP009Scan(unittest.TestCase):
    def test_scan_discovers_and_ranks_fragile_scopes_from_broad_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest, observations, registry = _write_scan_fixture(root)
            corpus = load_p009_corpus(manifest, observations_path=observations)
            provider = InstrumentRegistryP009Lookup(InstrumentRegistrySnapshot.load(registry))
            result = scan_p009_corpus(corpus, registry_snapshot=provider)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual([candidate.source_scope_key for candidate in result.candidates], [
            "fund:bridge",
            "fund:ambiguous",
            "fund:weak",
        ])
        top = result.candidates[0]
        self.assertEqual(top.continuity_class, "registry_bridged")
        self.assertEqual(set(top.issue_codes), {"identifier_basis_transition", "registry_bridge_available"})
        self.assertEqual(top.registry_status, "resolved")
        self.assertEqual(top.source_ids, ("bridge-feb", "bridge-jan"))
        self.assertEqual(
            {(seed["id_type"], seed["value"]) for seed in top.seed_identifiers},
            {("cusip", "123456AB7"), ("figi", "BBG000000001")},
        )
        self.assertEqual(len(top.pack_input_plan["manifest_sources"]), 2)
        self.assertNotIn("fund:clean", {candidate.source_scope_key for candidate in result.candidates})

    def test_scan_discovers_one_fragile_scope_among_clean_histories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest, observations, registry = _write_single_fragile_scan_fixture(root)
            corpus = load_p009_corpus(manifest, observations_path=observations)
            provider = InstrumentRegistryP009Lookup(InstrumentRegistrySnapshot.load(registry))
            result = scan_p009_corpus(corpus, registry_snapshot=provider)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual([candidate.source_scope_key for candidate in result.candidates], ["fund:fragile"])
        candidate = result.candidates[0]
        self.assertEqual(candidate.rank, 1)
        self.assertEqual(candidate.continuity_class, "registry_bridged")
        self.assertEqual(candidate.registry_status, "resolved")
        self.assertEqual(set(candidate.issue_codes), {"identifier_basis_transition", "registry_bridge_available"})
        self.assertEqual(candidate.source_ids, ("fragile-feb", "fragile-jan"))
        self.assertEqual({item["scope_key"] for item in candidate.pack_input_plan["manifest_sources"]}, {"fund:fragile"})
        self.assertEqual(
            {(seed["id_type"], seed["value"]) for seed in candidate.seed_identifiers},
            {("cusip", "123456AB7"), ("figi", "BBG000000001")},
        )

    def test_scan_without_registry_reports_unresolved_collision_not_live_lookup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest, observations, _registry = _write_scan_fixture(root)
            corpus = load_p009_corpus(manifest, observations_path=observations)
            result = scan_p009_corpus(corpus)

        bridge = next(candidate for candidate in result.candidates if candidate.source_scope_key == "fund:bridge")
        self.assertEqual(bridge.issue_codes, ("weak_key_temporal_collision",))
        self.assertEqual(bridge.continuity_class, "weak_collision")
        self.assertNotIn("registry_bridge_available", bridge.issue_codes)

    def test_write_outputs_are_stable_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest, observations, registry = _write_scan_fixture(root)
            corpus = load_p009_corpus(manifest, observations_path=observations)
            provider = InstrumentRegistryP009Lookup(InstrumentRegistrySnapshot.load(registry))
            result = scan_p009_corpus(corpus, registry_snapshot=provider)
            repeated = scan_p009_corpus(corpus, registry_snapshot=provider)
            paths = write_p009_scan_outputs(result, root / "scan")

            candidates = [
                json.loads(line)
                for line in Path(paths["candidates_jsonl"]).read_text(encoding="utf-8").splitlines()
            ]
            summary_rows = list(
                csv.DictReader(io.StringIO(Path(paths["summary_csv"]).read_text(encoding="utf-8")))
            )
            seeds = [
                json.loads(line)
                for line in Path(paths["seeds_jsonl"]).read_text(encoding="utf-8").splitlines()
            ]
            pack_inputs = json.loads(Path(paths["pack_inputs_json"]).read_text(encoding="utf-8"))
            diagnostics = json.loads(Path(paths["diagnostics_json"]).read_text(encoding="utf-8"))

        self.assertEqual([candidate.candidate_id for candidate in result.candidates], [
            candidate.candidate_id for candidate in repeated.candidates
        ])
        self.assertEqual(candidates[0]["candidate_id"], result.candidates[0].candidate_id)
        self.assertEqual(summary_rows[0]["source_scope_key"], "fund:bridge")
        self.assertGreaterEqual(len(seeds), 3)
        self.assertEqual(pack_inputs["pack_inputs"][0]["source_scope_key"], "fund:bridge")
        self.assertEqual(diagnostics["candidate_count"], 3)

    def test_cli_scan_corpus_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest, observations, registry = _write_scan_fixture(root)
            out_dir = root / "scan"
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                rc = main(
                    [
                        "p009",
                        "scan-corpus",
                        "--manifest",
                        str(manifest),
                        "--observations",
                        str(observations),
                        "--registry-snapshot",
                        str(registry),
                        "--out-dir",
                        str(out_dir),
                        "--limit",
                        "1",
                    ]
                )
            candidates = (out_dir / "p009_scan_candidates.v1.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(rc, ExitCode.SUCCESS)
        self.assertEqual(len(candidates), 1)
        self.assertIn("Candidates: 1", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
