"""`pack` must read and compare inline numeric values without rounding them (bd-0ql).

Python's default decimal context keeps 28 digits. Arelle applies ``ix:scale`` in the caller's
context, and P001 compares values with decimal arithmetic. Every expected value and verdict here is
written from the markup of tests/fixtures/pack_precision/wide.htm.
"""

from __future__ import annotations

import decimal
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cmdrvl_xew.detectors.p001_duplicates import DuplicateFactsDetector

try:
    import arelle  # type: ignore # noqa: F401

    HAVE_ARELLE = True
except ImportError:
    HAVE_ARELLE = False

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "pack_precision" / "wide.htm"
DEAD_PROXY = "http://127.0.0.1:9"

# concept -> the two values as the filing states them (after scale).
CONFLICTS = {
    "LongFraction": ["0.1234567890123456789012345678901", "0.1234567890123456789012345678902"],
    "WideInteger": ["123456789012345678901234567890", "123456789012345678901234567891"],
    "ScaledWide": ["1234567890123456789012345678901", "1234567890123456789012345678902"],
    "Reported": ["5.1234567890123456789012345678901", "7"],
    "OutsideTolerance": ["1.000000000000000000000000001", "1.000000000000000000000000002"],
}
CONSISTENT = {"InsideTolerance", "Ordinary"}


@unittest.skipUnless(HAVE_ARELLE, "needs the arelle extra")
class TestPackKeepsEveryDigit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.conflicts = {mode: cls.pack_conflicts(mode) for mode in ("rounded", "strict")}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def pack_conflicts(cls, mode: str) -> dict[str, list[str]]:
        """Run the real `pack` command, offline; return each P001 conflict's reported values."""
        out = cls.work / mode
        env = {k: v for k, v in os.environ.items() if k != "XEW_USER_AGENT"}
        env.update(
            PYTHONPATH=str(REPO / "src"),
            PYTHONDONTWRITEBYTECODE="1",
            HTTP_PROXY=DEAD_PROXY,
            HTTPS_PROXY=DEAD_PROXY,
            http_proxy=DEAD_PROXY,
            https_proxy=DEAD_PROXY,
        )
        result = subprocess.run(
            [
                sys.executable, "-m", "cmdrvl_xew", "pack", "--pack-id", "XEW-EP-PRECISION",
                "--out", str(out), "--primary", str(FIXTURE), "--cik", "0000000001",
                "--accession", "0000000001-25-000001", "--form", "10-Q", "--filed-date", "2025-11-01",
                "--primary-document-url", "https://example.com/wide.htm",
                "--retrieved-at", "2026-01-15T10:30:00Z", "--resolution-mode", "offline_only",
                "--require-arelle", "--p001-conflict-mode", mode,
                "--arelle-xdg-config-home", str(cls.work / "xdg"),
            ],
            cwd=cls.work, env=env, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        document = json.loads((out / "xew_findings.json").read_text())
        found: dict[str, list[str]] = {}
        for finding in document["findings"]:
            if finding["pattern_id"] != "XEW-P001":
                continue
            for instance in finding["observed"]["instances"]:
                data = instance["data"]
                found[data["concept"]["local_name"]] = sorted(fact["value"] for fact in data["facts"])
        return found

    def test_rounded_mode_reports_each_conflict_with_the_filed_values(self):
        for concept, values in CONFLICTS.items():
            with self.subTest(concept=concept):
                self.assertEqual(self.conflicts["rounded"].get(concept), sorted(values))

    def test_rounded_mode_reports_nothing_for_consistent_pairs(self):
        self.assertEqual(set(self.conflicts["rounded"]) & CONSISTENT, set())

    def test_strict_mode_reports_every_difference_with_the_filed_values(self):
        for concept, values in CONFLICTS.items():
            with self.subTest(concept=concept):
                self.assertEqual(self.conflicts["strict"].get(concept), sorted(values))
        # Strict mode compares exact values, so these differing pairs are conflicts too.
        self.assertEqual(
            self.conflicts["strict"].get("InsideTolerance"),
            ["2.000000000000000000000000000000", "2.0000000000000000000000000000004"],
        )
        self.assertEqual(self.conflicts["strict"].get("Ordinary"), ["1247000", "1247400"])


@unittest.skipUnless(HAVE_ARELLE, "needs the arelle extra")
class TestLoaderScopesPrecision(unittest.TestCase):
    def test_values_are_exact_after_loading_and_no_context_leaks(self):
        from cmdrvl_xew.pack import _load_xbrl_model_with_arelle

        default_precision = decimal.DefaultContext.prec
        with tempfile.TemporaryDirectory() as xdg, decimal.localcontext() as callers:
            callers.prec = 7  # whatever the caller uses must be what it gets back
            model = _load_xbrl_model_with_arelle(
                FIXTURE, resolution_mode="offline_only", require_arelle=True,
                disable_arelle=False, arelle_xdg_config_home=xdg,
            )
            try:
                self.assertEqual(decimal.getcontext().prec, 7)
                # Read outside the loader, in the caller's 7-digit context: already computed.
                values = {fact.id: fact.value for fact in model.factsInInstance}
            finally:
                model.close()
        self.assertEqual(decimal.DefaultContext.prec, default_precision)
        self.assertEqual(values["rp1"], "5.1234567890123456789012345678901")
        self.assertEqual(values["wi2"], "123456789012345678901234567891")
        self.assertEqual(values["sw1"], "1234567890123456789012345678901")


class TestP001ComparisonArithmetic(unittest.TestCase):
    """The rounding-interval arithmetic itself, including the `precision` attribute path."""

    @staticmethod
    def fact(value: str, **attributes) -> dict:
        return {"value": value, "is_numeric": True, "arelle_fact": SimpleNamespace(**attributes)}

    def conflicts(self, *facts: dict) -> bool:
        return DuplicateFactsDetector()._rounded_conflicts(list(facts))

    def test_precision_attribute_uses_the_unrounded_magnitude(self):
        # 9.99999999999999999999999999999 to 3 significant figures is within 0.005 of itself, so
        # 10.04 is outside. Rounding abs(value) to 28 digits gives 10 and a tolerance of 0.05.
        self.assertTrue(
            self.conflicts(self.fact("9.99999999999999999999999999999", precision="3"), self.fact("10.04"))
        )
        self.assertFalse(
            self.conflicts(self.fact("9.99999999999999999999999999999", precision="3"), self.fact("10.004"))
        )

    def test_comparison_leaves_the_callers_context_alone(self):
        with decimal.localcontext() as callers:
            callers.prec = 7
            self.conflicts(self.fact("1.5", decimals="1"), self.fact("1.52"))
            self.assertEqual(decimal.getcontext().prec, 7)


if __name__ == "__main__":
    unittest.main()
