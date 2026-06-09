from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.detectors._base import DetectorContext
from cmdrvl_xew.detectors.p009_identity_drift import (
    InstrumentIdentityDriftDetector,
    generated_artifact_from_p009_findings,
)


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


def _row(
    accession: str,
    *,
    scope_key: str = "fund:alpha",
    report_period: str,
    filed_date: str,
    observation_ordinal: int = 0,
    **identity: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "p009_observations.v1",
        "source_family": "local_export",
        "source_adapter": "detector_fixture",
        "scope_key": scope_key,
        "accession": accession,
        "report_period": report_period,
        "filed_date": filed_date,
        "observation_ordinal": observation_ordinal,
        "source_path": f"{accession}.jsonl#row={observation_ordinal + 1}",
    }
    row.update(identity)
    return row


def _write_registry(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
                "schema_version": "1.0",
                "snapshot_id": "p009-detector-test",
                "generated_at": "2026-06-09T00:00:00Z",
                "source": {"producer": "canon", "dataset": "openfigi"},
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _context(observations: Path, *, registry: Path | None = None) -> DetectorContext:
    config: dict[str, object] = {"p009_observations": [str(observations)]}
    if registry is not None:
        config["p009_registry_snapshot"] = str(registry)
    return DetectorContext(
        primary_document_path=str(observations),
        artifacts_dir=str(observations.parent),
        cik="0000000001",
        accession="0000000001-26-000002",
        form="NPORT-P",
        filed_date="2026-03-02",
        xbrl_model=None,
        config=config,
    )


class TestP009Detector(unittest.TestCase):
    def test_exact_cusip_continuity_emits_no_drift_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            cusip="123456AB7",
                            issuer_name="Stable Issuer",
                            title_or_description="Stable Security",
                        ),
                        _row(
                            "0000000001-26-000002",
                            report_period="2026-02-28",
                            filed_date="2026-03-02",
                            cusip="123456AB7",
                            issuer_name="Stable Issuer",
                            title_or_description="Stable Security",
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            findings = InstrumentIdentityDriftDetector().detect(_context(observations))

        self.assertEqual(findings, [])

    def test_cusip_to_figi_bridge_emits_first_class_finding_and_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            cusip="123456AB7",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                            value="100000000",
                        ),
                        _row(
                            "0000000001-26-000002",
                            report_period="2026-02-28",
                            filed_date="2026-03-02",
                            figi="BBG000000001",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                            value="100000000",
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            _write_registry(registry, [{"figi": "BBG000000001", "cusip": "123456AB7"}])

            findings = InstrumentIdentityDriftDetector().detect(_context(observations, registry=registry))

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.pattern_id, "XEW-P009")
        instance = finding.instances[0]
        self.assertEqual(instance.kind, "instrument_identity_drift")
        self.assertEqual(
            set(instance.data["issue_codes"]),
            {"identifier_basis_transition", "registry_bridge_available"},
        )
        self.assertEqual(instance.data["continuity_class"], "registry_bridged")
        event = instance.data["events"][0]
        self.assertEqual(event["registry_status"], "resolved")
        self.assertEqual(event["basis_before"]["basis_type"], "cusip")
        self.assertEqual(event["basis_after"]["basis_type"], "figi")

        artifact = generated_artifact_from_p009_findings(findings, generated_at="2026-06-09T00:00:00Z")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["event_count"], 1)
        self.assertEqual(artifact["alias_graph"]["chain_count"], 1)
        self.assertEqual(artifact["unresolved_candidates"], [])

    def test_isin_to_cusip_registry_bridge_emits_transition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            isin="US123456AB78",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                        ),
                        _row(
                            "0000000001-26-000002",
                            report_period="2026-02-28",
                            filed_date="2026-03-02",
                            cusip="123456AB7",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            _write_registry(
                registry,
                [{"figi": "BBG000000001", "cusip": "123456AB7", "isin": "US123456AB78"}],
            )

            findings = InstrumentIdentityDriftDetector().detect(_context(observations, registry=registry))

        self.assertEqual(len(findings), 1)
        instance = findings[0].instances[0]
        self.assertEqual(instance.data["continuity_class"], "registry_bridged")
        self.assertEqual(
            set(instance.data["issue_codes"]),
            {"identifier_basis_transition", "registry_bridge_available"},
        )
        event = instance.data["events"][0]
        self.assertEqual(event["basis_before"]["basis_type"], "isin")
        self.assertEqual(event["basis_after"]["basis_type"], "cusip")
        self.assertEqual(event["registry_status"], "resolved")

    def test_cusip_removed_to_weak_only_stays_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            cusip="123456AB7",
                            ticker="WEAK",
                            issuer_name="Weak Issuer",
                            title_or_description="Weak Security",
                            value="25000000",
                        ),
                        _row(
                            "0000000001-26-000002",
                            report_period="2026-02-28",
                            filed_date="2026-03-02",
                            ticker="WEAK",
                            issuer_name="Weak Issuer",
                            title_or_description="Weak Security",
                            value="25000000",
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            findings = InstrumentIdentityDriftDetector().detect(_context(observations))

        self.assertEqual(len(findings), 1)
        issue_codes = set(findings[0].instances[0].data["issue_codes"])
        self.assertEqual(issue_codes, {"strong_identifier_removed", "weak_continuity_only"})
        self.assertEqual(findings[0].instances[0].data["continuity_class"], "weak_unresolved")

    def test_missing_registry_snapshot_does_not_guess_identifier_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            cusip="123456AB7",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                        ),
                        _row(
                            "0000000001-26-000002",
                            report_period="2026-02-28",
                            filed_date="2026-03-02",
                            figi="BBG000000001",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            findings = InstrumentIdentityDriftDetector().detect(_context(observations))

        self.assertEqual(len(findings), 1)
        instance = findings[0].instances[0]
        self.assertEqual(instance.data["issue_codes"], ["weak_key_temporal_collision"])
        self.assertEqual(instance.data["continuity_class"], "weak_collision")
        self.assertEqual(instance.data["registry_snapshot"]["status"], "absent")

    def test_ambiguous_registry_rows_emit_ambiguous_bridge_without_winner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            cusip="222222AB2",
                            issuer_name="Ambiguous Issuer",
                            title_or_description="Ambiguous Security",
                        )
                    ]
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            _write_registry(
                registry,
                [
                    {"figi": "BBG000000003", "cusip": "222222AB2"},
                    {"figi": "BBG000000004", "cusip": "222222AB2"},
                ],
            )

            findings = InstrumentIdentityDriftDetector().detect(_context(observations, registry=registry))

        self.assertEqual(len(findings), 1)
        instance = findings[0].instances[0]
        self.assertEqual(instance.data["issue_codes"], ["registry_bridge_ambiguous"])
        event = instance.data["events"][0]
        self.assertEqual(event["registry_status"], "ambiguous")
        self.assertEqual(
            [candidate["figi"] for candidate in event["registry_candidates"]],
            ["BBG000000003", "BBG000000004"],
        )

    def test_generated_artifact_is_byte_stable_for_same_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        _row(
                            "0000000001-26-000001",
                            report_period="2026-01-31",
                            filed_date="2026-02-02",
                            cusip="123456AB7",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                        ),
                        _row(
                            "0000000001-26-000002",
                            report_period="2026-02-28",
                            filed_date="2026-03-02",
                            figi="BBG000000001",
                            issuer_name="Bridge Issuer",
                            title_or_description="Bridge Security",
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            _write_registry(registry, [{"figi": "BBG000000001", "cusip": "123456AB7"}])
            detector = InstrumentIdentityDriftDetector()

            first = generated_artifact_from_p009_findings(
                detector.detect(_context(observations, registry=registry)),
                generated_at="2026-06-09T00:00:00Z",
            )
            second = generated_artifact_from_p009_findings(
                detector.detect(_context(observations, registry=registry)),
                generated_at="2026-06-09T00:00:00Z",
            )

        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=True),
            json.dumps(second, sort_keys=True, ensure_ascii=True),
        )


if __name__ == "__main__":
    unittest.main()
