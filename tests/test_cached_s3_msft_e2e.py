from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from cmdrvl_xew.identity_fragility import run_p008_identity_fragility


class TestCachedS3MsftE2E(unittest.TestCase):
    def test_cached_s3_msft_identity_fragility_path(self):
        if os.environ.get("XEW_RUN_REAL_S3_E2E") != "1":
            self.skipTest("set XEW_RUN_REAL_S3_E2E=1 to run the real cached-S3 MSFT path")
        taxonomy_home = os.environ.get("XEW_ARELLE_XDG_CONFIG_HOME")
        if not taxonomy_home:
            self.skipTest("set XEW_ARELLE_XDG_CONFIG_HOME to a taxonomy package config home")

        with tempfile.TemporaryDirectory() as td:
            rc = run_p008_identity_fragility(
                SimpleNamespace(
                    work_dir=td,
                    bucket=os.environ.get("XEW_EDGAR_S3_BUCKET", "edgar-data-full"),
                    source_layout=os.environ.get("XEW_EDGAR_S3_LAYOUT", "extracted"),
                    aws_profile=os.environ.get("AWS_PROFILE") or "salt_profile",
                    taxonomy_home=taxonomy_home,
                    pack_id="XEW-P008-MSFT-20260429",
                    retrieved_at="2026-06-09T00:00:00Z",
                    p008_registry_snapshot=os.environ.get("XEW_P008_REGISTRY_SNAPSHOT") or None,
                    p008_require_registry=bool(os.environ.get("XEW_P008_REGISTRY_SNAPSHOT")),
                    dry_run=False,
                    force=False,
                )
            )

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
