from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmdrvl_xew.exit_codes import ExitCode
from cmdrvl_xew.p008_scan import rank_scan_results, scan_p008_corpus


def _write_pack(path: Path, *, title_count: int, status: str) -> None:
    generated = path / "generated"
    generated.mkdir(parents=True)
    members = []
    for index in range(title_count):
        members.append(
            {
                "security_title": f"{index + 1}.000% Notes due 203{index}",
                "instrument_kind": "debt_note" if index else "common_stock",
                "canonical_signature": f"sig-{index}",
                "ticker": "MSFT",
                "exchange": "NASDAQ",
                "registry": {"status": status},
                "facts": [{"source": {"extraction": "arelle"}}],
            }
        )
    (generated / "instrument_identity_collapse.v1.json").write_text(
        json.dumps(
            {
                "collapse_group_count": 1,
                "collapse_groups": [{"members": members}],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class TestP008Scan(unittest.TestCase):
    def test_reads_manifest_and_ranks_existing_packs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_a = root / "pack-a"
            pack_b = root / "pack-b"
            _write_pack(pack_a, title_count=2, status="snapshot_absent")
            _write_pack(pack_b, title_count=3, status="resolved")
            manifest = root / "manifest.jsonl"
            manifest.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "ticker": "MSFT",
                                "issuer_name": "Microsoft",
                                "cik": "0000789019",
                                "accession": "0001193125-26-191507",
                                "filed_date": "2026-04-29",
                                "form": "10-Q",
                                "pack_path": str(pack_a),
                            }
                        ),
                        json.dumps(
                            {
                                "ticker": "MSFT",
                                "issuer_name": "Microsoft",
                                "cik": "0000789019",
                                "accession": "0001193125-26-191508",
                                "filed_date": "2026-05-01",
                                "form": "10-Q",
                                "pack_path": str(pack_b),
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = scan_p008_corpus(
                manifest_path=manifest,
                out_dir=root / "scan",
                run_packs=False,
                aws_profile=None,
                bucket="edgar-data-full",
                taxonomy_home=None,
                p008_registry_snapshot=None,
                max_filings=None,
                keep_packs=False,
                continue_on_error=True,
                fail_fast=False,
            )
            self.assertTrue(Path(result["jsonl_path"]).exists())
            self.assertTrue(Path(result["csv_path"]).exists())

        self.assertEqual(result["rows"][0]["accession"], "0001193125-26-191508")
        self.assertEqual(result["rows"][0]["resolved_or_ambiguous_member_count"], 3)

    def test_missing_pack_path_skips_without_run_packs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "ticker,cik,accession,filed_date,form\nMSFT,0000789019,0001193125-26-191507,2026-04-29,10-Q\n",
                encoding="utf-8",
            )

            result = scan_p008_corpus(
                manifest_path=manifest,
                out_dir=root / "scan",
                run_packs=False,
                aws_profile=None,
                bucket="edgar-data-full",
                taxonomy_home=None,
                p008_registry_snapshot=None,
                max_filings=None,
                keep_packs=False,
                continue_on_error=True,
                fail_fast=False,
            )

        self.assertEqual(result["rows"][0]["status"], "skipped")

    def test_rank_scan_results_is_stable_for_ties(self):
        ranked = rank_scan_results(
            [
                {"status": "scanned", "resolved_or_ambiguous_member_count": 1, "distinct_instrument_kind_count": 1, "filed_date": "2026-01-02", "accession": "b"},
                {"status": "scanned", "resolved_or_ambiguous_member_count": 1, "distinct_instrument_kind_count": 1, "filed_date": "2026-01-01", "accession": "a"},
            ]
        )
        self.assertEqual([row["accession"] for row in ranked], ["b", "a"])

    def test_rank_scan_results_uses_max_members_before_date(self):
        ranked = rank_scan_results(
            [
                {"status": "scanned", "resolved_or_ambiguous_member_count": 0, "max_member_count": 2, "distinct_instrument_kind_count": 1, "filed_date": "2026-06-01", "accession": "newer"},
                {"status": "scanned", "resolved_or_ambiguous_member_count": 0, "max_member_count": 4, "distinct_instrument_kind_count": 1, "filed_date": "2026-01-01", "accession": "stronger"},
            ]
        )
        self.assertEqual([row["accession"] for row in ranked], ["stronger", "newer"])

    def test_run_packs_path_uses_cached_s3_and_pack_without_aws_in_unit_test(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "ticker,issuer_name,cik,accession,filed_date,form,source_layout\n"
                "MSFT,Microsoft,0000789019,0001193125-26-191507,2026-04-29,10-Q,xbrl\n",
                encoding="utf-8",
            )

            def fake_fetch(args):
                flat = Path(args.out)
                flat.mkdir(parents=True, exist_ok=True)
                (flat / "msft-20260331.htm").write_text("<html></html>", encoding="utf-8")
                return ExitCode.SUCCESS

            def fake_pack(args):
                _write_pack(Path(args.out), title_count=3, status="resolved")
                return ExitCode.SUCCESS

            with patch("cmdrvl_xew.p008_scan.run_fetch_s3", side_effect=fake_fetch) as fetch, patch(
                "cmdrvl_xew.p008_scan.run_pack", side_effect=fake_pack
            ) as pack:
                result = scan_p008_corpus(
                    manifest_path=manifest,
                    out_dir=root / "scan",
                    run_packs=True,
                    aws_profile="salt_profile",
                    bucket="edgar-data-full",
                    taxonomy_home=str(root / "taxonomy"),
                    p008_registry_snapshot=None,
                    max_filings=None,
                    keep_packs=False,
                    continue_on_error=True,
                    fail_fast=False,
                )
                pack_path_exists = Path(result["rows"][0]["pack_path"]).exists()

        self.assertEqual(result["rows"][0]["status"], "scanned")
        self.assertEqual(result["rows"][0]["max_member_count"], 3)
        self.assertEqual(fetch.call_args.args[0].source_layout, "xbrl")
        self.assertEqual(pack.call_args.args[0].resolution_mode, "offline_only")
        self.assertTrue(pack_path_exists)


if __name__ == "__main__":
    unittest.main()
