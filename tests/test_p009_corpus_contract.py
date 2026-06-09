from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.p009_corpus import (
    load_p009_corpus,
    load_p009_manifest,
    load_p009_observations,
    stable_p009_row_id,
    validate_p009_corpus,
)


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


class TestP009CorpusContract(unittest.TestCase):
    def test_manifest_loads_local_and_s3_sources_with_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.xml"
            artifact.write_text("<root>identity</root>\n", encoding="utf-8")
            artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = root / "p009_corpus_manifest.v1.jsonl"
            manifest.write_text(
                _jsonl(
                    [
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "sec_filing",
                            "source_adapter": "fixture_xml",
                            "scope_key": "fund:alpha",
                            "accession": "0000000001-26-000001",
                            "filed_date": "2026-02-01",
                            "form": "NPORT-P",
                            "report_period": "2026-01-31",
                            "primary_document_url": "https://www.sec.gov/example",
                            "local_path": "source.xml",
                            "source_artifact_sha256": artifact_sha,
                        },
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "external_observation",
                            "scope_key": "portfolio:beta",
                            "source_record_id": "export-row-1",
                            "report_period": "2026-01-31",
                            "s3_uri": "s3://cache/p009/beta.jsonl",
                            "source_name": "upstream-export",
                            "source_export_id": "export-20260609",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = load_p009_manifest(manifest)

        self.assertEqual(result.diagnostics, ())
        self.assertRegex(result.manifest_input_sha256, r"^[a-f0-9]{64}$")
        self.assertEqual(result.manifest_row_count, 2)
        self.assertEqual(len(result.sources), 2)
        local = next(source for source in result.sources if source.local_path)
        self.assertEqual(local.artifact_sha256, artifact_sha)
        self.assertEqual(local.artifact_bytes, len("<root>identity</root>\n"))
        self.assertEqual(local.source_id, "0000000001-26-000001")
        s3 = next(source for source in result.sources if source.s3_uri)
        self.assertEqual(s3.artifact_ref, "s3://cache/p009/beta.jsonl")
        self.assertEqual(s3.source_export_id, "export-20260609")

    def test_manifest_reports_required_invalid_and_missing_artifact_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "p009_corpus_manifest.v1.jsonl"
            manifest.write_text(
                _jsonl(
                    [
                        {"schema_version": "p009_corpus_manifest.v1", "source_family": "local_export"},
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "warehouse_private",
                            "scope_key": "scope:bad-family",
                            "source_record_id": "row-1",
                            "local_path": "missing.xml",
                        },
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "sec_filing",
                            "scope_key": "scope:bad-date",
                            "accession": "bad-accession",
                            "source_record_id": "bad source id",
                            "filed_date": "20260609",
                            "local_path": "missing.xml",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = load_p009_manifest(manifest)

        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("P009-CORPUS-E002", codes)
        self.assertIn("P009-CORPUS-E003", codes)
        self.assertIn("P009-CORPUS-E004", codes)
        self.assertIn("P009-CORPUS-E005", codes)
        self.assertIn("P009-CORPUS-E006", codes)
        self.assertEqual(result.sources, ())

    def test_corpus_combines_manifest_and_observations_with_source_linkage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "observations.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = root / "p009_corpus_manifest.v1.jsonl"
            manifest.write_text(
                _jsonl(
                    [
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "local_export",
                            "source_adapter": "rows",
                            "scope_key": "scope:alpha",
                            "source_record_id": "row-set-1",
                            "report_period": "2026-01-31",
                            "local_path": "observations.jsonl",
                            "source_artifact_sha256": artifact_sha,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            observations = root / "p009_observations.v1.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        {
                            "schema_version": "p009_observations.v1",
                            "source_family": "local_export",
                            "source_adapter": "rows",
                            "scope_key": "scope:alpha",
                            "source_record_id": "row-set-1",
                            "report_period": "2026-01-31",
                            "observation_ordinal": 0,
                            "cusip": "123456AB7",
                            "issuer_name": "Issuer",
                            "title_or_description": "Security",
                            "source_path": "observations.jsonl#row=1",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = load_p009_corpus(manifest, observations_path=observations)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.manifest_row_count, 1)
        self.assertEqual(result.observation_row_count, 1)
        self.assertEqual(result.observations[0].identifiers.cusip, "123456AB7")
        self.assertRegex(result.observations_input_sha256, r"^[a-f0-9]{64}$")

    def test_observation_without_manifest_source_and_no_identity_are_corpus_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "p009_corpus_manifest.v1.jsonl"
            manifest.write_text(
                _jsonl(
                    [
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "local_export",
                            "scope_key": "scope:alpha",
                            "source_record_id": "row-set-1",
                            "local_path": "source.jsonl",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            observations = root / "p009_observations.v1.jsonl"
            observations.write_text(
                _jsonl(
                    [
                        {
                            "schema_version": "p009_observations.v1",
                            "source_family": "local_export",
                            "scope_key": "scope:beta",
                            "source_record_id": "row-set-2",
                            "report_period": "2026-01-31",
                            "cusip": "123456AB7",
                        },
                        {
                            "schema_version": "p009_observations.v1",
                            "source_family": "local_export",
                            "scope_key": "scope:alpha",
                            "source_record_id": "row-set-1",
                            "report_period": "2026-01-31",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = load_p009_corpus(manifest, observations_path=observations)

        codes = [diagnostic.code for diagnostic in result.diagnostics]
        self.assertIn("P009-CORPUS-E007", codes)
        self.assertIn("P009-CORPUS-E008", codes)
        self.assertEqual(len(result.observations), 1)

    def test_load_p009_observations_accepts_csv_and_stable_row_id_is_order_independent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.csv"
            path.write_text(
                "source_family,scope_key,source_record_id,report_period,cusip,issuer_name\n"
                "local_export,scope:alpha,row-1,2026-01-31,123456AB7,Issuer\n",
                encoding="utf-8",
            )

            result = load_p009_observations(path)

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.observation_row_count, 1)
        self.assertEqual(result.observations[0].identifiers.cusip, "123456AB7")
        left = {"scope_key": "scope:alpha", "source_record_id": "row-1", "row_number": 1}
        right = {"row_number": 99, "source_record_id": "row-1", "scope_key": "scope:alpha"}
        self.assertEqual(stable_p009_row_id(left), stable_p009_row_id(right))

    def test_validate_p009_corpus_is_empty_for_manifest_only_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.xml"
            artifact.write_text("<root />\n", encoding="utf-8")
            manifest = root / "p009_corpus_manifest.v1.jsonl"
            manifest.write_text(
                _jsonl(
                    [
                        {
                            "schema_version": "p009_corpus_manifest.v1",
                            "source_family": "sec_filing",
                            "scope_key": "scope:alpha",
                            "accession": "0000000001-26-000001",
                            "local_path": "source.xml",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = load_p009_manifest(manifest)

        self.assertEqual(validate_p009_corpus(result), ())


if __name__ == "__main__":
    unittest.main()
