from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.flatten import run_flatten
from cmdrvl_xew.sgml import SgmlExtractionError, extract_complete_submission_sgml


def _synthetic_submission() -> bytes:
    return b"""<SUBMISSION>
<ACCESSION-NUMBER>0000123456-26-000001
<TYPE>10-Q
<PUBLIC-DOCUMENT-COUNT>3
<FILING-DATE>20260131
<DOCUMENT>
<TYPE>10-Q
<SEQUENCE>1
<FILENAME>issuer-20251231.htm
<DESCRIPTION>Primary iXBRL
<TEXT>
<XBRL>
<html xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
<head><title>Issuer</title></head>
<body>
<link:schemaRef xlink:href="issuer-20251231.xsd"/>
</body>
</html>
</XBRL>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-101.SCH
<SEQUENCE>2
<FILENAME>issuer-20251231.xsd
<DESCRIPTION>Schema
<TEXT>
<schema xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
<link:linkbaseRef xlink:href="issuer-20251231_lab.xml"/>
</schema>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-101.LAB
<SEQUENCE>3
<FILENAME>issuer-20251231_lab.xml
<DESCRIPTION>Labels
<TEXT>
<linkbase/>
</TEXT>
</DOCUMENT>
</SUBMISSION>
"""


class TestSgmlExtractor(unittest.TestCase):
    def test_extracts_complete_submission_to_typed_layout_and_flattens(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            nc = root / "0000123456-26-000001.nc"
            nc.write_bytes(_synthetic_submission())
            extracted = root / "typed"

            result = extract_complete_submission_sgml(nc, extracted, accession="0000123456-26-000001")

            self.assertEqual(result.accession, "0000123456-26-000001")
            self.assertEqual(result.primary_document, "10-Q/issuer-20251231.htm")
            self.assertTrue((extracted / "10-Q" / "issuer-20251231.htm").is_file())
            self.assertTrue((extracted / "EX-101.SCH" / "issuer-20251231.xsd").is_file())
            self.assertTrue((extracted / "EX-101.LAB" / "issuer-20251231_lab.xml").is_file())
            self.assertTrue((extracted / "_xew_sgml_extraction.json").is_file())

            flat = root / "flat"
            rc = run_flatten(type("Args", (), {"edgar_dir": str(extracted), "out": str(flat), "force": False})())
            self.assertEqual(rc, 0)
            self.assertTrue((flat / "issuer-20251231.htm").is_file())
            self.assertTrue((flat / "issuer-20251231.xsd").is_file())
            self.assertTrue((flat / "issuer-20251231_lab.xml").is_file())

    def test_rejects_duplicate_output_paths(self):
        payload = _synthetic_submission().replace(b"<TYPE>EX-101.LAB", b"<TYPE>EX-101.SCH")
        payload = payload.replace(b"<FILENAME>issuer-20251231_lab.xml", b"<FILENAME>issuer-20251231.xsd")
        with tempfile.TemporaryDirectory() as td:
            nc = Path(td) / "dup.nc"
            nc.write_bytes(payload)
            with self.assertRaises(SgmlExtractionError):
                extract_complete_submission_sgml(nc, Path(td) / "out")

    def test_rejects_accession_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            nc = Path(td) / "sample.nc"
            nc.write_bytes(_synthetic_submission())
            with self.assertRaises(SgmlExtractionError):
                extract_complete_submission_sgml(nc, Path(td) / "out", accession="0000123456-26-999999")


if __name__ == "__main__":
    unittest.main()
