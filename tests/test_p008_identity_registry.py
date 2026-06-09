"""Conformance tests for XEW-P008 identity and registry primitives."""

from __future__ import annotations

import json
import string
import tempfile
import unittest
from pathlib import Path

from cmdrvl_xew.instrument_identity import (
    InstrumentIdentityError,
    build_instrument_identity,
    parse_instrument_title,
)
from cmdrvl_xew.instrument_registry import InstrumentRegistrySnapshot


def _snapshot(rows):
    return {
        "schema_id": "cmdrvl.canon.openfigi_registry_snapshot",
        "schema_version": "1.0",
        "snapshot_id": "p008-msft-demo",
        "generated_at": "2026-06-09T00:00:00Z",
        "source": {
            "provider": "canon",
            "dataset": "openfigi",
        },
        "rows": rows,
    }


def _write_snapshot(path: Path, rows) -> InstrumentRegistrySnapshot:
    path.write_text(json.dumps(_snapshot(rows), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return InstrumentRegistrySnapshot.load(path)


class TestP008IdentityRegistry(unittest.TestCase):
    def test_p008_u001_common_stock_title(self):
        title = parse_instrument_title("Common stock, $0.00000625 par value per share")

        self.assertEqual(title.instrument_kind, "common_stock")
        self.assertEqual(title.par_value, "0.00000625")
        self.assertEqual(title.normalized_title, "COMMON STOCK PAR 0.00000625")
        self.assertEqual(title.coupon_percent, "")
        self.assertEqual(title.maturity_year, "")

    def test_p008_u002_u003_note_titles(self):
        note_2028 = parse_instrument_title("3.125% Notes due 2028")
        note_2033 = parse_instrument_title("2.625% Notes due 2033")

        self.assertEqual(note_2028.instrument_kind, "debt_note")
        self.assertEqual(note_2028.coupon_percent, "3.125")
        self.assertEqual(note_2028.maturity_year, "2028")
        self.assertEqual(note_2028.normalized_title, "NOTE 3.125% DUE 2028")
        self.assertEqual(note_2033.coupon_percent, "2.625")
        self.assertEqual(note_2033.maturity_year, "2033")

    def test_p008_u004_u005_weak_key_collapse_distinct_signatures(self):
        instruments = [
            build_instrument_identity(
                context_ref="stock",
                security_title="Common stock, $0.00000625 par value per share",
                ticker="MSFT",
                exchange="Nasdaq",
            ),
            build_instrument_identity(
                context_ref="note-2028",
                security_title="3.125% Notes due 2028",
                ticker="MSFT",
                exchange="Nasdaq",
            ),
            build_instrument_identity(
                context_ref="note-2033",
                security_title="2.625% Notes due 2033",
                ticker="MSFT",
                exchange="Nasdaq",
            ),
        ]

        weak_keys = {instrument.weak_key for instrument in instruments}
        signatures = {instrument.canonical_signature for instrument in instruments}

        self.assertEqual(len(weak_keys), 1)
        self.assertEqual(len(signatures), 3)
        self.assertIn("ticker=MSFT", next(iter(weak_keys)))
        self.assertIn("exchange=NASDAQ", next(iter(weak_keys)))

    def test_p008_u007_u008_u009_registry_resolves_three_msft_rows(self):
        common = build_instrument_identity(
            context_ref="stock",
            security_title="Common stock, $0.00000625 par value per share",
            ticker="MSFT",
            exchange="Nasdaq",
        )
        note_2028 = build_instrument_identity(
            context_ref="note-2028",
            security_title="3.125% Notes due 2028",
            ticker="MSFT",
            exchange="Nasdaq",
        )
        note_2033 = build_instrument_identity(
            context_ref="note-2033",
            security_title="2.625% Notes due 2033",
            ticker="MSFT",
            exchange="Nasdaq",
        )

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _write_snapshot(
                Path(tmp) / "registry.json",
                [
                    {
                        "figi": "BBG000BPH459",
                        "ticker": "MSFT",
                        "exchange": "Nasdaq",
                        "normalized_title": common.title.normalized_title,
                        "composite_figi": "BBG000BPH459",
                        "share_class_figi": "BBG001S5TD05",
                        "market_sector": "Equity",
                    },
                    {
                        "figi": "BBG005NPW5Z2",
                        "ticker": "MSFT",
                        "exchange": "Nasdaq",
                        "normalized_title": note_2028.title.normalized_title,
                        "market_sector": "Corp",
                    },
                    {
                        "figi": "BBG004HDR2M6",
                        "ticker": "MSFT",
                        "exchange": "Nasdaq",
                        "normalized_title": note_2033.title.normalized_title,
                        "market_sector": "Corp",
                    },
                ],
            )

            self.assertEqual(snapshot.lookup(common).row.figi, "BBG000BPH459")
            self.assertEqual(snapshot.lookup(note_2028).row.figi, "BBG005NPW5Z2")
            self.assertEqual(snapshot.lookup(note_2033).row.figi, "BBG004HDR2M6")

    def test_p008_u010_duplicate_identical_rows_are_deduped(self):
        instrument = build_instrument_identity(
            context_ref="stock",
            security_title="Common stock, $0.00000625 par value per share",
            ticker="MSFT",
            exchange="Nasdaq",
        )
        row = {
            "figi": "BBG000BPH459",
            "ticker": "MSFT",
            "exchange": "Nasdaq",
            "normalized_title": instrument.title.normalized_title,
        }
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _write_snapshot(Path(tmp) / "registry.json", [row, row])
            lookup = snapshot.lookup(instrument)

        self.assertEqual(lookup.status, "duplicate_identical")
        self.assertEqual(lookup.row.figi, "BBG000BPH459")
        self.assertEqual(lookup.duplicate_count, 1)

    def test_p008_u011_ambiguous_rows_never_select_figi(self):
        instrument = build_instrument_identity(
            context_ref="stock",
            security_title="Common stock, $0.00000625 par value per share",
            ticker="MSFT",
            exchange="Nasdaq",
        )
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _write_snapshot(
                Path(tmp) / "registry.json",
                [
                    {
                        "figi": "BBG000BPH459",
                        "ticker": "MSFT",
                        "exchange": "Nasdaq",
                        "normalized_title": instrument.title.normalized_title,
                    },
                    {
                        "figi": "BBG000BPH450",
                        "ticker": "MSFT",
                        "exchange": "Nasdaq",
                        "normalized_title": instrument.title.normalized_title,
                    },
                ],
            )
            lookup = snapshot.lookup(instrument)

        self.assertEqual(lookup.status, "ambiguous")
        self.assertIsNone(lookup.row)
        self.assertEqual({row.figi for row in lookup.candidates}, {"BBG000BPH459", "BBG000BPH450"})

    def test_p008_u012_missing_registry_row_never_invents_figi(self):
        instrument = build_instrument_identity(
            context_ref="note-2028",
            security_title="3.125% Notes due 2028",
            ticker="MSFT",
            exchange="Nasdaq",
        )
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _write_snapshot(Path(tmp) / "registry.json", [])
            lookup = snapshot.lookup(instrument)

        self.assertEqual(lookup.status, "missing")
        self.assertIsNone(lookup.row)
        self.assertEqual(lookup.candidates, ())

    def test_p008_u013_cusip_precedence_over_noisy_weak_fields(self):
        instrument = build_instrument_identity(
            context_ref="note-2028",
            security_title="3.125% Notes due 2028",
            ticker="WRONG",
            exchange="NYSE",
            cusip="594918BR4",
        )
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _write_snapshot(
                Path(tmp) / "registry.json",
                [
                    {
                        "figi": "BBG005NPW5Z2",
                        "ticker": "MSFT",
                        "exchange": "Nasdaq",
                        "cusip": "594918BR4",
                        "normalized_title": instrument.title.normalized_title,
                    }
                ],
            )
            lookup = snapshot.lookup(instrument)

        self.assertEqual(lookup.status, "resolved")
        self.assertEqual(lookup.row.figi, "BBG005NPW5Z2")

    def test_p008_u014_unsupported_titles_refuse_to_guess(self):
        with self.assertRaises(InstrumentIdentityError):
            parse_instrument_title("Debt Securities")
        with self.assertRaises(InstrumentIdentityError):
            parse_instrument_title("Notes")

    def test_p008_u015_determinism_for_permuted_input_order(self):
        instruments = [
            build_instrument_identity(
                context_ref="stock",
                security_title="Common stock, $0.00000625 par value per share",
                ticker="MSFT",
                exchange="Nasdaq",
            ),
            build_instrument_identity(
                context_ref="note-2028",
                security_title="3.125% Notes due 2028",
                ticker="MSFT",
                exchange="Nasdaq",
            ),
            build_instrument_identity(
                context_ref="note-2033",
                security_title="2.625% Notes due 2033",
                ticker="MSFT",
                exchange="Nasdaq",
            ),
        ]
        expected = sorted(instrument.canonical_signature for instrument in instruments)
        permutations = [
            instruments,
            [instruments[1], instruments[2], instruments[0]],
            [instruments[2], instruments[0], instruments[1]],
            [instruments[2], instruments[1], instruments[0]],
        ]

        for ordering in permutations:
            self.assertEqual(sorted(instrument.canonical_signature for instrument in ordering), expected)

    def test_p008_u016_structure_fuzz_parser_never_guesses_or_crashes(self):
        alphabet = string.ascii_letters + string.digits + " %$/.,-"
        for index in range(250):
            length = (index * 17) % 80
            value = "".join(alphabet[(index * 31 + offset * 7) % len(alphabet)] for offset in range(length))
            try:
                parsed = parse_instrument_title(value)
            except InstrumentIdentityError:
                continue
            self.assertIn(parsed.instrument_kind, {"common_stock", "debt_note"})
            self.assertTrue(parsed.normalized_title)


if __name__ == "__main__":
    unittest.main()
