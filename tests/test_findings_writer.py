"""Unit tests for findings writer behavior."""

import json
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.findings import FindingsWriter
from cmdrvl_xew.detectors._base import DetectorContext, DetectorFinding, DetectorInstance


class TestFindingsWriterSuppressed(unittest.TestCase):
    """Validate suppressed findings are preserved in output."""

    def test_suppressed_findings_included(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "xew_findings.json"
            writer = FindingsWriter(output_path)

            context = DetectorContext(
                primary_document_path="primary.html",
                artifacts_dir=str(tmp_dir),
                cik="0000000000",
                accession="0000000000-00-000000",
                form="10-Q",
                filed_date="2025-01-01",
                xbrl_model=None,
                config={},
            )

            suppressed = DetectorFinding(
                finding_id="XEW-F-0000000000-00-000000-XEW-P001",
                pattern_id="XEW-P001",
                pattern_name="Duplicate Facts",
                alert_eligible=False,
                status="suppressed",
                suppression_reason="Missing or invalid rule basis citation",
                human_review_required=True,
                break_triggers=[{"id": "XEW-BT001", "summary": "test"}],
                instances=[
                    DetectorInstance(
                        instance_id="instance-1",
                        kind="duplicate_fact_set",
                        primary=True,
                        data={},
                    )
                ],
                mechanism="test",
                why_not_fatal_yet="test",
            )

            detected = DetectorFinding(
                finding_id="XEW-F-0000000000-00-000000-XEW-P004",
                pattern_id="XEW-P004",
                pattern_name="Type/Unit",
                alert_eligible=True,
                status="detected",
                human_review_required=True,
                break_triggers=[{"id": "XEW-BT001", "summary": "test"}],
                instances=[],
                mechanism="test",
                why_not_fatal_yet="test",
            )

            toolchain = {
                "cmdrvl_xew_version": "dev",
                "arelle_version": "dev",
                "config": {},
            }

            input_metadata = {
                "cik": "0000000000",
                "accession": "0000000000-00-000000",
                "form": "10-Q",
                "filed_date": "2025-01-01",
                "primary_document_url": "https://example.com/primary.html",
                "primary_artifact_path": "artifacts/primary.html",
            }

            writer.write_findings(
                findings=[suppressed, detected],
                context=context,
                artifacts=[],
                toolchain=toolchain,
                input_metadata=input_metadata,
                generated_at="2025-01-01T00:00:00Z",
            )

            data = json.loads(output_path.read_text(encoding="utf-8"))
            findings = {item["pattern_id"]: item for item in data["findings"]}

            self.assertIn("XEW-P001", findings)
            self.assertIn("XEW-P004", findings)
            self.assertEqual(findings["XEW-P001"]["status"], "suppressed")
            self.assertEqual(
                findings["XEW-P001"]["suppression_reason"],
                "Missing or invalid rule basis citation",
            )


if __name__ == "__main__":
    unittest.main()
