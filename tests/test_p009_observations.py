from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.p009_observations import (
    adapter_for_source_family,
    load_p009_observations,
    normalize_p009_identifier,
    observation_identity_evidence,
    parse_p009_observation_rows,
)


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


class TestP009Observations(unittest.TestCase):
    def test_jsonl_adapter_parses_normalizes_and_sorts_observations(self):
        rows = [
            {
                "schema_version": "p009_observations.v1",
                "source_family": "sec_filing",
                "source_adapter": "test_export",
                "scope_key": "fund:alpha",
                "accession": "0000000001-26-000002",
                "filed_date": "2026-03-01",
                "report_period": "2026-02-28",
                "observation_ordinal": 2,
                "issuer_name": "  Example   Issuer  ",
                "title_or_description": "Example Notes",
                "cusip": " 123 456 ab7 ",
                "isin": "us123456ab78",
                "ticker": " exm ",
                "source_path": "s3://bucket/source-b.xml",
                "source_pointer": "/root/holding[2]",
            },
            {
                "schema_version": "p009_observations.v1",
                "source_family": "sec_filing",
                "source_adapter": "test_export",
                "source_scope": {"scope_key": "fund:alpha", "cik": "0000123456"},
                "accession": "0000000001-26-000001",
                "filed_date": "2026-02-01",
                "report_period": "2026-01-31",
                "observation_ordinal": 1,
                "issuer_name": "Example Issuer",
                "title": "Example Notes",
                "figi": "bbg000000001",
                "source_refs": [
                    {
                        "path": "s3://bucket/source-a.xml",
                        "pointer": "/root/holding[1]",
                        "row_number": 17,
                    }
                ],
            },
        ]

        result = parse_p009_observation_rows(_jsonl(rows))
        repeated = parse_p009_observation_rows(_jsonl(rows))

        self.assertEqual(result.diagnostics, ())
        self.assertEqual([obs.report_period for obs in result.observations], ["2026-01-31", "2026-02-28"])
        self.assertEqual(result.observations[0].identifiers.figi, "BBG000000001")
        self.assertEqual(result.observations[1].identifiers.cusip, "123456AB7")
        self.assertEqual(result.observations[1].identifiers.isin, "US123456AB78")
        self.assertEqual(result.observations[1].identifiers.ticker, "EXM")
        self.assertEqual(result.observations[0].source_scope.cik, "0000123456")
        self.assertEqual(
            [obs.observation_id for obs in result.observations],
            [obs.observation_id for obs in repeated.observations],
        )

        evidence = observation_identity_evidence(result.observations[0])
        self.assertEqual(evidence["basis_type"], "figi")
        self.assertEqual(evidence["scope_key"], "fund:alpha")

    def test_csv_loader_accepts_source_record_id_and_other_identifier(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.csv"
            path.write_text(
                "source_family,source_adapter,scope_key,source_record_id,report_period,"
                "observation_ordinal,issuer_name,title_or_description,other_id_type,"
                "other_id_value,source_path\n"
                "local_export,csv_test,portfolio:1,row-1,2026-01-31,0,"
                "Issuer,Security,internal_id, abc-123 ,export.csv#row=2\n",
                encoding="utf-8",
            )

            result = load_p009_observations(path)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(len(result.observations), 1)
        observation = result.observations[0]
        self.assertEqual(observation.source_record_id, "row-1")
        self.assertEqual(observation.identifiers.other_identifiers, (("INTERNAL_ID", "ABC-123"),))
        self.assertEqual(observation.source_refs[0].path, "export.csv#row=2")

    def test_invalid_identifier_shape_is_diagnostic_and_weak_evidence_remains(self):
        result = parse_p009_observation_rows(
            _jsonl(
                [
                    {
                        "source_family": "local_export",
                        "scope_key": "scope:weak",
                        "source_record_id": "row-1",
                        "report_period": "2026-01-31",
                        "issuer_name": "Weak Issuer",
                        "title_or_description": "Weak Security",
                        "cusip": "bad!",
                    }
                ]
            )
        )

        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].identifiers.cusip, "")
        self.assertTrue(result.observations[0].weak_evidence.has_weak_evidence)
        self.assertIn("P009-OBS-E006", {diagnostic.code for diagnostic in result.diagnostics})

    def test_missing_scope_and_missing_identity_fail_closed(self):
        result = parse_p009_observation_rows(
            _jsonl(
                [
                    {
                        "source_family": "local_export",
                        "source_record_id": "row-1",
                        "report_period": "2026-01-31",
                        "issuer_name": "Issuer",
                    },
                    {
                        "source_family": "local_export",
                        "scope_key": "scope:no-identity",
                        "source_record_id": "row-2",
                        "report_period": "2026-01-31",
                    },
                ]
            )
        )

        self.assertEqual(result.observations, ())
        codes = [diagnostic.code for diagnostic in result.diagnostics]
        self.assertIn("P009-OBS-E003", codes)
        self.assertIn("P009-OBS-E004", codes)

    def test_malformed_rows_and_unsupported_sources_are_diagnostics(self):
        malformed = '{"source_family":"local_export"\n'
        result = parse_p009_observation_rows(
            malformed
            + json.dumps(
                {
                    "source_family": "mystery",
                    "scope_key": "scope:1",
                    "source_record_id": "row-1",
                    "report_period": "2026-01-31",
                    "ticker": "TICK",
                }
            )
            + "\n"
        )

        self.assertEqual(result.observations, ())
        self.assertIn("P009-OBS-E001", {diagnostic.code for diagnostic in result.diagnostics})
        self.assertIn("P009-OBS-E002", {diagnostic.code for diagnostic in result.diagnostics})

        unsupported = adapter_for_source_family("unsupported_family").parse("{}")
        self.assertEqual(unsupported.observations, ())
        self.assertEqual(unsupported.diagnostics[0].code, "P009-OBS-E009")

    def test_identifier_normalization_aliases(self):
        self.assertEqual(normalize_p009_identifier("ID_CUSIP", " 123 456 AB7 "), "123456AB7")
        self.assertEqual(normalize_p009_identifier("ID_ISIN", " us123456ab78 "), "US123456AB78")
        self.assertEqual(normalize_p009_identifier("ticker", " brk.b "), "BRK.B")


if __name__ == "__main__":
    unittest.main()
