from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmdrvl_xew.cli import main
from cmdrvl_xew.exit_codes import ExitCode


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


def _minimal_ixbrl(title: str) -> str:
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink">
<head><title>{title}</title></head>
<body>
  <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="entity">Example Trust</ix:nonNumeric>
  <ix:references>
    <link:schemaRef xlink:href="http://xbrl.sec.gov/dei/2025/dei-2025.xsd"/>
  </ix:references>
</body>
</html>"""


def _manifest_row(
    accession: str,
    *,
    scope_key: str,
    report_period: str,
    filed_date: str,
    local_path: str,
) -> dict[str, object]:
    return {
        "schema_version": "p009_corpus_manifest.v1",
        "source_family": "sec_filing",
        "source_adapter": "workflow_fixture",
        "scope_key": scope_key,
        "accession": accession,
        "report_period": report_period,
        "filed_date": filed_date,
        "form": "10-Q",
        "primary_document_url": (
            "https://www.sec.gov/Archives/edgar/data/1/"
            f"{accession.replace('-', '')}/{Path(local_path).name}"
        ),
        "local_path": local_path,
    }


def _observation_row(
    accession: str,
    *,
    scope_key: str,
    report_period: str,
    filed_date: str,
    source_path: str,
    **identity: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "p009_observations.v1",
        "source_family": "sec_filing",
        "source_adapter": "workflow_fixture",
        "scope_key": scope_key,
        "accession": accession,
        "report_period": report_period,
        "filed_date": filed_date,
        "observation_ordinal": 0,
        "source_path": source_path,
    }
    row.update(identity)
    return row


def _write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
                "schema_version": "1.0",
                "snapshot_id": "p009-workflow-test",
                "generated_at": "2026-06-09T00:00:00Z",
                "source": {"producer": "canon", "dataset": "openfigi"},
                "rows": [{"figi": "BBG000000001", "cusip": "123456AB7", "name": "Bridge Security"}],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_workflow_fixture(root: Path) -> tuple[Path, Path, Path]:
    for name in ("bridge-jan.htm", "bridge-feb.htm", "weak-jan.htm", "weak-feb.htm"):
        (root / name).write_text(_minimal_ixbrl(name), encoding="utf-8")

    manifest = root / "p009_corpus_manifest.v1.jsonl"
    observations = root / "p009_observations.v1.jsonl"
    registry = root / "registry.json"
    manifest.write_text(
        _jsonl(
            [
                _manifest_row(
                    "0000000001-26-000001",
                    scope_key="fund:bridge",
                    report_period="2026-01-31",
                    filed_date="2026-02-02",
                    local_path="bridge-jan.htm",
                ),
                _manifest_row(
                    "0000000001-26-000002",
                    scope_key="fund:bridge",
                    report_period="2026-02-28",
                    filed_date="2026-03-02",
                    local_path="bridge-feb.htm",
                ),
                _manifest_row(
                    "0000000001-26-000003",
                    scope_key="fund:weak",
                    report_period="2026-01-31",
                    filed_date="2026-02-03",
                    local_path="weak-jan.htm",
                ),
                _manifest_row(
                    "0000000001-26-000004",
                    scope_key="fund:weak",
                    report_period="2026-02-28",
                    filed_date="2026-03-03",
                    local_path="weak-feb.htm",
                ),
            ]
        ),
        encoding="utf-8",
    )
    observations.write_text(
        _jsonl(
            [
                _observation_row(
                    "0000000001-26-000001",
                    scope_key="fund:bridge",
                    report_period="2026-01-31",
                    filed_date="2026-02-02",
                    source_path="bridge-jan.htm#holding=1",
                    cusip="123456AB7",
                    issuer_name="Bridge Issuer",
                    title_or_description="Bridge Security",
                    value="100000000",
                ),
                _observation_row(
                    "0000000001-26-000002",
                    scope_key="fund:bridge",
                    report_period="2026-02-28",
                    filed_date="2026-03-02",
                    source_path="bridge-feb.htm#holding=1",
                    figi="BBG000000001",
                    issuer_name="Bridge Issuer",
                    title_or_description="Bridge Security",
                    value="100000000",
                ),
                _observation_row(
                    "0000000001-26-000003",
                    scope_key="fund:weak",
                    report_period="2026-01-31",
                    filed_date="2026-02-03",
                    source_path="weak-jan.htm#holding=1",
                    ticker="WEAK",
                    issuer_name="Weak Issuer",
                    title_or_description="Weak Security",
                    value="25000000",
                ),
                _observation_row(
                    "0000000001-26-000004",
                    scope_key="fund:weak",
                    report_period="2026-02-28",
                    filed_date="2026-03-03",
                    source_path="weak-feb.htm#holding=1",
                    ticker="WEAK",
                    issuer_name="Weak Issuer",
                    title_or_description="Weak Security",
                    value="25000000",
                ),
            ]
        ),
        encoding="utf-8",
    )
    _write_registry(registry)
    return manifest, observations, registry


def _workflow_args(root: Path, out_dir: Path) -> list[str]:
    manifest, observations, registry = _write_workflow_fixture(root)
    return [
        "p009",
        "prove-identity-drift",
        "--manifest",
        str(manifest),
        "--observations",
        str(observations),
        "--registry-snapshot",
        str(registry),
        "--artifacts-root",
        str(root),
        "--out",
        str(out_dir),
        "--retrieved-at",
        "2026-06-09T00:00:00Z",
    ]


class TestP009Workflow(unittest.TestCase):
    def test_dry_run_prints_plan_without_writing_outputs_or_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "workflow"
            args = _workflow_args(root, out_dir) + [
                "--dry-run",
                "--provider-config",
                "api_key=secret-value",
                "--provider-config",
                "base_url=http://127.0.0.1:9000/v3/mapping",
            ]

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                rc = main(args)
            summary = json.loads(stdout.getvalue())

        self.assertEqual(rc, ExitCode.SUCCESS)
        self.assertEqual(summary["mode"], "dry_run")
        self.assertEqual(summary["selected_candidate"]["source_scope_key"], "fund:bridge")
        self.assertIn("materialization_command", summary["registry_plan"])
        self.assertIn("command", summary["pack"])
        self.assertIn("command", summary["verify"])
        self.assertFalse(out_dir.exists())
        self.assertNotIn("secret-value", json.dumps(summary, sort_keys=True))

    def test_stop_after_seeds_writes_scan_and_seed_files_without_pack(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "workflow"

            with patch("sys.stdout", new_callable=io.StringIO):
                rc = main(_workflow_args(root, out_dir) + ["--stop-after", "seeds"])
            summary = json.loads((out_dir / "p009_identity_fragility_summary.v1.json").read_text(encoding="utf-8"))
            scan_written = (out_dir / "scan" / "p009_scan_candidates.v1.jsonl").is_file()
            cusip_seed_written = (out_dir / "registry_seeds" / "cusip.csv").is_file()
            figi_seed_written = (out_dir / "registry_seeds" / "figi.csv").is_file()
            pack_written = (out_dir / "pack" / "pack_manifest.json").exists()

        self.assertEqual(rc, ExitCode.SUCCESS)
        self.assertEqual(summary["status"], "stopped_after_seeds")
        self.assertTrue(scan_written)
        self.assertTrue(cusip_seed_written)
        self.assertTrue(figi_seed_written)
        self.assertFalse(pack_written)

    def test_stop_after_scan_writes_only_scan_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "workflow"

            with patch("sys.stdout", new_callable=io.StringIO):
                rc = main(_workflow_args(root, out_dir) + ["--stop-after", "scan"])
            summary = json.loads((out_dir / "p009_identity_fragility_summary.v1.json").read_text(encoding="utf-8"))
            scan_written = (out_dir / "scan" / "p009_scan_candidates.v1.jsonl").is_file()
            seed_dir_exists = (out_dir / "registry_seeds").exists()
            pack_written = (out_dir / "pack" / "pack_manifest.json").exists()

        self.assertEqual(rc, ExitCode.SUCCESS)
        self.assertEqual(summary["status"], "stopped_after_scan")
        self.assertTrue(scan_written)
        self.assertFalse(seed_dir_exists)
        self.assertFalse(pack_written)

    def test_full_workflow_runs_scan_pack_verify_and_emits_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "workflow"

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                rc = main(_workflow_args(root, out_dir))
            printed = json.loads(stdout.getvalue())
            summary = json.loads((out_dir / "p009_identity_fragility_summary.v1.json").read_text(encoding="utf-8"))
            findings = json.loads((out_dir / "pack" / "xew_findings.json").read_text(encoding="utf-8"))
            generated_written = (out_dir / "pack" / "generated" / "instrument_identity_drift.v1.json").is_file()

        self.assertEqual(rc, ExitCode.SUCCESS)
        self.assertEqual(printed["status"], "completed")
        self.assertEqual(summary["pack"]["status"], "completed")
        self.assertEqual(summary["verify"]["status"], "passed")
        self.assertEqual(summary["selected_candidate"]["rank"], 1)
        self.assertEqual(summary["selected_candidate"]["continuity_class"], "registry_bridged")
        self.assertEqual(summary["selected_candidate"]["registry_status"], "resolved")
        self.assertEqual(
            set(summary["selected_candidate"]["issue_codes"]),
            {"identifier_basis_transition", "registry_bridge_available"},
        )
        self.assertEqual(summary["pack"]["selected_observation_count"], 2)
        self.assertTrue(generated_written)
        self.assertIn("identifier_basis_transition", summary["scan"]["issue_code_counts"])
        self.assertEqual(
            [item["pattern_id"] for item in findings["findings"] if item["pattern_id"] == "XEW-P009"],
            ["XEW-P009"],
        )

    def test_missing_selected_artifact_refuses_full_pack_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "workflow"
            args = _workflow_args(root, out_dir)
            manifest = Path(args[args.index("--manifest") + 1])
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace("bridge-feb.htm", "missing-bridge-feb.htm"),
                encoding="utf-8",
            )

            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as raised:
                    main(args)

        self.assertEqual(raised.exception.code, ExitCode.PROCESSING_ERROR)


if __name__ == "__main__":
    unittest.main()
