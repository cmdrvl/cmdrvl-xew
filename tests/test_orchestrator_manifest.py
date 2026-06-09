from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.orchestrator_manifest import manifest_from_orchestrator
from cmdrvl_xew.p008_scan import read_corpus_manifest


class TestOrchestratorManifest(unittest.TestCase):
    def test_normalizes_saved_orchestrator_response(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            response = root / "response.json"
            content = {
                "filings": [
                    {
                        "ticker": "MSFT",
                        "issuer": "Microsoft Corporation",
                        "cik": "789019",
                        "accession": "000119312526191507",
                        "filing_date": "20260429",
                        "form": "10-Q",
                    },
                    {
                        "ticker": "MSFT",
                        "issuer": "Microsoft Corporation",
                        "cik": "789019",
                        "accession": "0001193125-26-191508",
                        "filing_date": "2026-05-01",
                        "form": "10-Q",
                    },
                    {
                        "ticker": "BAD",
                        "cik": "1",
                        "accession": "",
                        "filing_date": "2026-04-29",
                        "form": "10-Q",
                    },
                ]
            }
            response.write_text(json.dumps({"data": {"content": json.dumps(content)}}), encoding="utf-8")
            out = root / "manifest.jsonl"

            result = manifest_from_orchestrator(
                query="recent MSFT filings",
                tenant="salt",
                out_path=out,
                response_json=response,
                cmdrvl_project=None,
            )
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            diagnostics = json.loads(Path(result["diagnostics_path"]).read_text(encoding="utf-8"))

        self.assertEqual(result["scan_ready_count"], 2)
        self.assertEqual(rows[0]["accession"], "0001193125-26-191508")
        self.assertEqual(rows[1]["accession"], "0001193125-26-191507")
        self.assertEqual(rows[1]["filed_date"], "2026-04-29")
        self.assertEqual(rows[1]["date_partition"], "20260429")
        self.assertEqual(rows[1]["cik"], "0000789019")
        self.assertEqual(rows[1]["issuer_name"], "Microsoft Corporation")
        self.assertEqual(diagnostics["invalid_count"], 1)

    def test_writes_csv_manifest_accepted_by_scanner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            response = root / "response.json"
            response.write_text(
                json.dumps(
                    {
                        "data": {
                            "content": json.dumps(
                                {
                                    "filings": [
                                        {
                                            "ticker": "MSFT",
                                            "issuer": "Microsoft Corporation",
                                            "cik": "789019",
                                            "accession": "000119312526191507",
                                            "filing_date": "20260429",
                                            "form": "10-Q",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ),
                encoding="utf-8",
            )
            out = root / "manifest.csv"

            manifest_from_orchestrator(
                query="recent MSFT filings",
                tenant="salt",
                out_path=out,
                response_json=response,
                cmdrvl_project=None,
            )
            rows = read_corpus_manifest(out)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].accession, "0001193125-26-191507")


if __name__ == "__main__":
    unittest.main()
