from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmdrvl_xew.registry_materialize import (
    RegistryMaterializationError,
    materialize_registry_from_corpus,
)


class TestRegistryMaterialize(unittest.TestCase):
    def test_writes_deterministic_seed_files_and_manifest_from_manifest_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "filings.jsonl"
            manifest.write_text(
                "\n".join(
                    [
                        json.dumps({"cik": "0001", "accession": "a", "cusip": "594918BR4", "isin": "US594918BR43"}),
                        json.dumps({"cik": "0001", "accession": "b", "cusip": "594918BR4", "sedol": "2588173"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = materialize_registry_from_corpus(
                corpus_id="msft-proof",
                out_dir=root / "registry-work",
                filing_manifest=manifest,
                seed_files=[],
                version="2026.06.09",
                provider_source="openfigi",
                provider_configs=["base_url=http://127.0.0.1:9000/v3/mapping", "api_key=secret"],
                canon_bin="canon",
                run_canon=False,
                incremental=False,
                allow_live_provider=False,
            )

            out_dir = root / "registry-work"
            self.assertEqual((out_dir / "seeds" / "cusip.csv").read_text(encoding="utf-8"), "cusip\n594918BR4\n")
            self.assertEqual((out_dir / "seeds" / "isin.csv").read_text(encoding="utf-8"), "isin\nUS594918BR43\n")
            self.assertEqual((out_dir / "seeds" / "sedol.csv").read_text(encoding="utf-8"), "sedol\n2588173\n")
            persisted = json.loads((out_dir / "registry_materialization_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result["corpus_id"], "msft-proof")
        self.assertEqual(len(result["registry_builds"]), 3)
        self.assertEqual(persisted["provider_options"]["api_key"], "[redacted]")
        self.assertIn("--provider-config", result["registry_builds"][0]["command"])
        self.assertNotIn("secret", json.dumps(result["registry_builds"], sort_keys=True))
        self.assertIn("api_key=[redacted]", result["registry_builds"][0]["command"])

    def test_run_canon_requires_local_twin_or_live_approval_for_openfigi(self):
        with tempfile.TemporaryDirectory() as td:
            seed = Path(td) / "seed.csv"
            seed.write_text("cusip\n594918BR4\n", encoding="utf-8")
            with self.assertRaises(RegistryMaterializationError):
                materialize_registry_from_corpus(
                    corpus_id="guard",
                    out_dir=Path(td) / "out",
                    filing_manifest=None,
                    seed_files=[seed],
                    version="2026.06.09",
                    provider_source="openfigi",
                    provider_configs=[],
                    canon_bin="canon",
                    run_canon=True,
                    incremental=False,
                    allow_live_provider=False,
                )

    def test_rejects_empty_seed_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "filings.csv"
            manifest.write_text("cik,accession,filed_date,form\n0001,a,2026-01-01,10-Q\n", encoding="utf-8")
            with self.assertRaises(RegistryMaterializationError):
                materialize_registry_from_corpus(
                    corpus_id="empty",
                    out_dir=Path(td) / "out",
                    filing_manifest=manifest,
                    seed_files=[],
                    version="2026.06.09",
                    provider_source="openfigi",
                    provider_configs=[],
                    canon_bin="canon",
                    run_canon=False,
                    incremental=False,
                    allow_live_provider=False,
                )

    def test_incremental_excludes_identifiers_already_in_local_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "registry-work"
            existing = out_dir / "registries" / "openfigi-cusip-2026.06.09"
            existing.mkdir(parents=True)
            (existing / "cusip-to-figi.json").write_text(
                json.dumps([{"input": "594918BR4", "canonical_id": "BBG000000001"}]),
                encoding="utf-8",
            )
            seed = root / "seed.csv"
            seed.write_text("cusip\n594918BR4\n95002UAZ4\n", encoding="utf-8")

            result = materialize_registry_from_corpus(
                corpus_id="incremental",
                out_dir=out_dir,
                filing_manifest=None,
                seed_files=[seed],
                version="2026.06.09",
                provider_source="openfigi",
                provider_configs=[],
                canon_bin="canon",
                run_canon=False,
                incremental=True,
                allow_live_provider=False,
            )

            seed_text = (out_dir / "seeds" / "cusip.csv").read_text(encoding="utf-8")

        self.assertEqual(seed_text, "cusip\n95002UAZ4\n")
        self.assertEqual(result["registry_builds"][0]["seed_count"], 1)
        self.assertEqual(result["registry_builds"][0]["discovered_seed_count"], 2)
        self.assertEqual(result["registry_builds"][0]["skipped_existing_count"], 1)

    def test_writes_figi_seed_files_for_p009_corpus_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "p009_rows.jsonl"
            manifest.write_text(
                json.dumps({"source_record_id": "row-1", "figi": "BBG000000001"}) + "\n",
                encoding="utf-8",
            )

            result = materialize_registry_from_corpus(
                corpus_id="p009-proof",
                out_dir=root / "registry-work",
                filing_manifest=manifest,
                seed_files=[],
                version="2026.06.09",
                provider_source="openfigi",
                provider_configs=[],
                canon_bin="canon",
                run_canon=False,
                incremental=False,
                allow_live_provider=False,
            )

            out_dir = root / "registry-work"
            seed_text = (out_dir / "seeds" / "figi.csv").read_text(encoding="utf-8")

        self.assertEqual(seed_text, "figi\nBBG000000001\n")
        figi_builds = [build for build in result["registry_builds"] if build["column"] == "figi"]
        self.assertEqual(figi_builds[0]["id_type"], "ID_BB_GLOBAL")

    def test_run_canon_with_twin_records_build_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed = root / "seed.csv"
            seed.write_text("cusip\n594918BR4\n", encoding="utf-8")

            def fake_run(command, check, text, capture_output, timeout):
                output_dir = Path(command[command.index("--output") + 1])
                output_dir.mkdir(parents=True)
                (output_dir / "_build.json").write_text(
                    json.dumps(
                        {
                            "summary": {
                                "resolved_count": 1,
                                "unresolved_count": 2,
                                "failure_count": 3,
                                "ambiguous_count": 4,
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

            with patch("cmdrvl_xew.registry_materialize.subprocess.run", side_effect=fake_run):
                result = materialize_registry_from_corpus(
                    corpus_id="twin",
                    out_dir=root / "out",
                    filing_manifest=None,
                    seed_files=[seed],
                    version="2026.06.09",
                    provider_source="openfigi",
                    provider_configs=["base_url=http://127.0.0.1:9000/v3/mapping"],
                    canon_bin="canon",
                    run_canon=True,
                    incremental=False,
                    allow_live_provider=False,
                )

        build = result["registry_builds"][0]
        self.assertEqual(build["status"], "completed")
        self.assertEqual(build["build_file"]["unresolved_count"], 2)
        self.assertEqual(build["build_file"]["failure_count"], 3)
        self.assertEqual(build["build_file"]["ambiguous_count"], 4)


if __name__ == "__main__":
    unittest.main()
