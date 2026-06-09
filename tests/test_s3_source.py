from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cmdrvl_xew.s3_source import S3SourceError, S3Uri, resolve_s3_source
from cmdrvl_xew.s3_source import _write_s3_provenance


class TestS3Source(unittest.TestCase):
    def test_parses_s3_uri(self):
        parsed = S3Uri.parse("s3://edgar-data-full/xbrl/20260429/0001193125-26-191507.nc")

        self.assertEqual(parsed.bucket, "edgar-data-full")
        self.assertEqual(parsed.key, "xbrl/20260429/0001193125-26-191507.nc")
        self.assertEqual(parsed.as_uri(), "s3://edgar-data-full/xbrl/20260429/0001193125-26-191507.nc")

    def test_resolves_extracted_uri_and_normalizes_prefix_slash(self):
        source = resolve_s3_source(
            SimpleNamespace(
                s3_uri="s3://edgar-data-full/extracted/20260429/0001193125-26-191507",
                source_layout="auto",
                bucket=None,
                date_partition=None,
                accession=None,
            )
        )

        self.assertEqual(source.layout, "extracted")
        self.assertEqual(source.uri.key, "extracted/20260429/0001193125-26-191507/")

    def test_resolves_bucket_date_accession_xbrl_object(self):
        source = resolve_s3_source(
            SimpleNamespace(
                s3_uri=None,
                source_layout="xbrl",
                bucket="edgar-data-full",
                date_partition="20260429",
                accession="0001193125-26-191507",
            )
        )

        self.assertEqual(source.layout, "xbrl")
        self.assertEqual(source.uri.as_uri(), "s3://edgar-data-full/xbrl/20260429/0001193125-26-191507.nc")

    def test_rejects_mismatched_layout(self):
        with self.assertRaises(S3SourceError):
            resolve_s3_source(
                SimpleNamespace(
                    s3_uri="s3://edgar-data-full/xbrl/20260429/0001193125-26-191507.nc",
                    source_layout="extracted",
                    bucket=None,
                    date_partition=None,
                    accession=None,
                )
            )

    def test_writes_stable_s3_provenance_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            doc = _write_s3_provenance(
                out_dir=out,
                source_layout="xbrl",
                source_uri=S3Uri("edgar-data-full", "xbrl/20260429/0001193125-26-191507.nc"),
                objects=[
                    {
                        "Key": "xbrl/20260429/0001193125-26-191507.nc",
                        "ETag": '"etag-value"',
                        "LastModified": "2026-04-30T06:26:35Z",
                        "ContentLength": 31304208,
                    }
                ],
            )
            path = out / "_xew_s3_provenance.json"
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(doc["selected_source_layout"], "xbrl")
        self.assertEqual(payload["objects"][0]["etag"], "etag-value")
        self.assertEqual(payload["objects"][0]["content_length"], 31304208)


if __name__ == "__main__":
    unittest.main()
