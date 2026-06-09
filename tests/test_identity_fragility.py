from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from cmdrvl_xew.identity_fragility import run_p008_identity_fragility
from cmdrvl_xew.identity_fragility import _assert_msft_titles, _summarize_p008


class TestIdentityFragilityProof(unittest.TestCase):
    def test_dry_run_emits_no_live_provider_plan(self):
        args = SimpleNamespace(
            work_dir=str(Path(tempfile.gettempdir()) / "xew-msft-proof"),
            bucket="edgar-data-full",
            source_layout="extracted",
            aws_profile="salt_profile",
            taxonomy_home=str(Path(tempfile.gettempdir()) / "taxonomy"),
            pack_id="XEW-P008-MSFT-20260429",
            retrieved_at="2026-06-09T00:00:00Z",
            p008_registry_snapshot=None,
            p008_require_registry=False,
            dry_run=True,
            force=False,
        )
        out = io.StringIO()
        with redirect_stdout(out):
            rc = run_p008_identity_fragility(args)
        payload = json.loads(out.getvalue())

        self.assertEqual(rc, 0)
        self.assertTrue(payload["no_live_sec"])
        self.assertTrue(payload["no_live_openfigi"])
        self.assertEqual(payload["case"]["accession"], "0001193125-26-191507")
        self.assertEqual(payload["commands"][0][1], "fetch-s3")

    def test_summary_requires_three_expected_msft_titles(self):
        with tempfile.TemporaryDirectory() as td:
            pack = Path(td)
            generated = pack / "generated"
            generated.mkdir()
            (generated / "instrument_identity_collapse.v1.json").write_text(
                json.dumps(
                    {
                        "collapse_group_count": 1,
                        "collapse_groups": [
                            {
                                "members": [
                                    {
                                        "security_title": "Common stock, $0.00000625 par value per share",
                                        "canonical_signature": "a",
                                        "ticker": "MSFT",
                                        "exchange": "NASDAQ",
                                        "registry": {"status": "snapshot_absent"},
                                        "facts": [{"source": {"extraction": "arelle"}}],
                                    },
                                    {
                                        "security_title": "3.125% Notes due 2028",
                                        "canonical_signature": "b",
                                        "ticker": "MSFT",
                                        "exchange": "NASDAQ",
                                        "registry": {"status": "snapshot_absent"},
                                        "facts": [{"source": {"extraction": "arelle"}}],
                                    },
                                    {
                                        "security_title": "2.625% Notes due 2033",
                                        "canonical_signature": "c",
                                        "ticker": "MSFT",
                                        "exchange": "NASDAQ",
                                        "registry": {"status": "snapshot_absent"},
                                        "facts": [{"source": {"extraction": "arelle"}}],
                                    },
                                ]
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            summary = _summarize_p008(pack)

        _assert_msft_titles(summary)
        self.assertEqual(summary["collapse_group_count"], 1)
        self.assertEqual(summary["registry_status_counts"], {"snapshot_absent": 3})
        self.assertEqual({member["source_extraction"] for member in summary["members"]}, {"arelle"})


if __name__ == "__main__":
    unittest.main()
