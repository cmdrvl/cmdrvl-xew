from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.canon_snapshot import CanonSnapshotAdapterError, build_p008_snapshot_from_canon
from cmdrvl_xew.instrument_identity import build_instrument_identity


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_canon_registry(root: Path, *, ambiguous: bool = False, failures_only: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "registry.json",
        {
            "id": "openfigi-cusip",
            "version": "2026.06.09",
            "source": "openfigi",
            "materialized_at": "2026-06-09T12:00:00Z",
            "seed_count": 1,
            "resolved_count": 0 if failures_only else 1,
            "entry_count": 0 if failures_only else 3,
        },
    )
    _write_json(
        root / "_build.json",
        {
            "version": "canon_registry_build.v0",
            "source": "openfigi",
            "seed": {"path": "seed.csv", "column": "cusip", "hash": "seed-sha", "count": 1},
            "provider": {"name": "openfigi", "options": {"id_type": "ID_CUSIP", "api_key": "secret"}},
            "summary": {"resolved_count": 0 if failures_only else 1, "failure_count": 1 if failures_only else 0},
        },
    )
    if failures_only:
        return
    figi_rows = [
        {
            "input": "594918BR4",
            "canonical_id": "BBG005NPW5Z2",
            "canonical_type": "figi",
            "rule_id": "OPENFIGI_CUSIP_TO_FIGI",
        }
    ]
    if ambiguous:
        figi_rows.append(
            {
                "input": "594918BR4",
                "canonical_id": "BBG005NPW5Z3",
                "canonical_type": "figi",
                "rule_id": "OPENFIGI_CUSIP_TO_FIGI",
            }
        )
    _write_json(root / "cusip-to-figi.json", figi_rows)
    _write_json(
        root / "cusip-to-ticker.json",
        [
            {
                "input": "594918BR4",
                "canonical_id": "MSFT",
                "canonical_type": "ticker",
                "rule_id": "OPENFIGI_CUSIP_TO_TICKER",
            }
        ],
    )
    _write_json(
        root / "cusip-to-name.json",
        [
            {
                "input": "594918BR4",
                "canonical_id": "MICROSOFT CORP",
                "canonical_type": "security_name",
                "rule_id": "OPENFIGI_CUSIP_TO_NAME",
            }
        ],
    )


class TestCanonSnapshotAdapter(unittest.TestCase):
    def test_converts_canon_registry_to_valid_p008_snapshot(self):
        instrument = build_instrument_identity(
            context_ref="note-2028",
            security_title="3.125% Notes due 2028",
            ticker="MSFT",
            exchange="Nasdaq",
            cusip="594918BR4",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "registry"
            _write_canon_registry(registry)
            overlay = root / "overlay.json"
            _write_json(
                overlay,
                {
                    "rows": [
                        {
                            "seed": "594918BR4",
                            "exchange": "Nasdaq",
                            "security_title": instrument.title.raw_title,
                            "normalized_title": instrument.title.normalized_title,
                            "canonical_signature": instrument.canonical_signature,
                            "security_type": "Corporate Bond",
                            "market_sector": "Corp",
                        }
                    ]
                },
            )
            out = root / "snapshot.json"

            snapshot = build_p008_snapshot_from_canon(
                registry_dir=registry,
                overlay_path=overlay,
                out_path=out,
                snapshot_id="p008-msft-canon",
                generated_at="2026-06-09T12:00:00Z",
            )

            lookup = snapshot.lookup(instrument)
            self.assertEqual(lookup.status, "resolved")
            self.assertEqual(lookup.row.figi, "BBG005NPW5Z2")
            self.assertEqual(lookup.row.cusip, "594918BR4")
            self.assertEqual(lookup.row.name, "MICROSOFT CORP")
            self.assertEqual(snapshot.metadata["source"]["build"]["provider_options"]["api_key"], "[redacted]")
            self.assertEqual(snapshot.metadata["source"]["build"]["id_type"], "ID_CUSIP")
            self.assertEqual(snapshot.metadata["source"]["build"]["failure_count"], 0)
            self.assertTrue(out.is_file())

    def test_preserves_multiple_figi_ambiguity(self):
        instrument = build_instrument_identity(
            context_ref="note-2028",
            security_title="3.125% Notes due 2028",
            ticker="MSFT",
            exchange="Nasdaq",
            cusip="594918BR4",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "registry"
            _write_canon_registry(registry, ambiguous=True)

            snapshot = build_p008_snapshot_from_canon(
                registry_dir=registry,
                out_path=root / "snapshot.json",
                generated_at="2026-06-09T12:00:00Z",
            )
            lookup = snapshot.lookup(instrument)

        self.assertEqual(lookup.status, "ambiguous")
        self.assertEqual({row.figi for row in lookup.candidates}, {"BBG005NPW5Z2", "BBG005NPW5Z3"})

    def test_rejects_failure_only_registry(self):
        with tempfile.TemporaryDirectory() as td:
            registry = Path(td) / "registry"
            _write_canon_registry(registry, failures_only=True)
            with self.assertRaises(CanonSnapshotAdapterError):
                build_p008_snapshot_from_canon(
                    registry_dir=registry,
                    out_path=Path(td) / "snapshot.json",
                    generated_at="2026-06-09T12:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
