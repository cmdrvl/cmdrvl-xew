"""Behaviour that changed with arelle-release 2.47.5 (contract output revision R3), and the
version statements that must agree with the pin.

Expected values and verdicts come from the markup. Each refused document is
tests/fixtures/arelle_behaviour/values.htm (which exports with either Arelle) with one value, or the
root element, made invalid.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

try:
    import arelle  # type: ignore # noqa: F401
    import pyarrow.parquet  # type: ignore

    HAVE_EXTRAS = True
except ImportError:
    HAVE_EXTRAS = False

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "arelle_behaviour"
DEAD_PROXY = "http://127.0.0.1:9"

REQUIRED_PYTHON = ">=3.11"
ARELLE_REQUIREMENT = "arelle-release==2.47.5"


def cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "XEW_USER_AGENT"}
    env.update(
        PYTHONPATH=str(REPO / "src"), PYTHONDONTWRITEBYTECODE="1",
        HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
    )
    return subprocess.run(
        [sys.executable, "-m", "cmdrvl_xew", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=600
    )


COMMON = (
    "--cik", "0000000001", "--accession", "0000000001-25-000001", "--form", "10-Q",
    "--filed-date", "2025-11-01", "--primary-document-url", "https://example.com/f.htm",
)


def export(primary: Path, work: Path, name: str) -> tuple[subprocess.CompletedProcess, Path]:
    out = work / name
    result = cli("export-facts", "--primary", str(primary), "--out", str(out), *COMMON,
                 "--arelle-xdg-config-home", str(work / "xdg"), cwd=work)
    return result, out


def pack(primary: Path, work: Path, name: str, *extra: str) -> tuple[subprocess.CompletedProcess, Path]:
    out = work / name
    result = cli("pack", "--pack-id", "XEW-EP-ARELLE", "--out", str(out), "--primary", str(primary), *COMMON,
                 "--retrieved-at", "2026-01-15T10:30:00Z", "--resolution-mode", "offline_only",
                 "--arelle-xdg-config-home", str(work / "xdg"), *extra, cwd=work)
    return result, out


def rows_by_id(out: Path) -> dict:
    return {r["fact_id"]: r for r in pyarrow.parquet.read_table(out / "facts.parquet").to_pylist()}


class TestStatedVersionsAgree(unittest.TestCase):
    """One requirement, stated in several places: they must not drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    def test_package_metadata_pins(self):
        extras = self.project["optional-dependencies"]
        self.assertEqual(self.project["requires-python"], REQUIRED_PYTHON)
        self.assertEqual(extras["arelle"], [ARELLE_REQUIREMENT])
        self.assertEqual([r for r in extras["prod"] if r.startswith("arelle")], [ARELLE_REQUIREMENT])

    def test_the_constants_pack_writes_match_the_metadata(self):
        from cmdrvl_xew import ARELLE_REQUIREMENT as written_arelle, REQUIRES_PYTHON as written_python

        self.assertEqual(written_python, self.project["requires-python"])
        self.assertEqual([written_arelle], self.project["optional-dependencies"]["arelle"])

    def test_the_lock_resolves_the_pinned_arelle(self):
        lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
        self.assertEqual(lock["requires-python"], REQUIRED_PYTHON)
        versions = [p["version"] for p in lock["package"] if p["name"] == "arelle-release"]
        self.assertEqual(versions, [ARELLE_REQUIREMENT.split("==")[1]])

    def test_readme_states_the_same_minimum(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("Python 3.11 or later", readme)
        self.assertIn(ARELLE_REQUIREMENT, readme)

    @unittest.skipUnless(HAVE_EXTRAS, "needs the arelle and parquet extras")
    def test_the_installed_arelle_is_the_pinned_one(self):
        from arelle import Version  # type: ignore

        self.assertEqual(Version.__version__, ARELLE_REQUIREMENT.split("==")[1])

    def test_reproduction_steps_state_the_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            result, out = pack(FIXTURES / "blocks.htm", work, "pack", "--no-arelle")
            self.assertEqual(result.returncode, 0, result.stderr)
            steps = json.loads((out / "reproduction_steps.json").read_text())
            self.assertEqual(
                steps["verification"]["requirements"],
                {
                    "os": "Linux, macOS, or Windows with Python 3.11+",
                    "python": ">=3.11",
                    "dependencies": ["cmdrvl-xew==0.1.0", "arelle-release==2.47.5"],
                },
            )


@unittest.skipUnless(HAVE_EXTRAS, "needs the arelle and parquet extras")
class TestEscapedBlocks(unittest.TestCase):
    """R3 change A."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        result, cls.exported = export(FIXTURES / "blocks.htm", cls.work, "export")
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        result, cls.packed = pack(FIXTURES / "blocks.htm", cls.work, "pack", "--require-arelle")
        if result.returncode != 0:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_link_attributes_keep_the_filed_text(self):
        value = rows_by_id(self.exported)["links"]["value_text"]
        for attribute in ('href="my exhibit.htm"', 'src="data:image/png;base64,iVBO Rw0K"',
                          'codebase="base/"', 'data="movie.bin"'):
            self.assertIn(attribute, value)
        self.assertNotIn("%20", value)
        self.assertNotIn('data="base/movie.bin"', value)

    def test_space_against_percent20_is_one_p001_conflict_and_identical_blocks_are_none(self):
        document = json.loads((self.packed / "xew_findings.json").read_text())
        conflicts = {
            instance["data"]["context_ref"]: sorted(fact["value"] for fact in instance["data"]["facts"])
            for finding in document["findings"] if finding["pattern_id"] == "XEW-P001"
            for instance in finding["observed"]["instances"]
        }
        self.assertEqual(
            conflicts,
            {"y2025": ['<a href="my exhibit.htm">e</a>', '<a href="my%20exhibit.htm">e</a>']},
        )


@unittest.skipUnless(HAVE_EXTRAS, "needs the arelle and parquet extras")
class TestValueValidation(unittest.TestCase):
    """R3 changes B, C and D, as export-facts shows them."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def variant(self, old: str, new: str) -> Path:
        source = self.work / "source"
        source.mkdir()
        shutil.copyfile(FIXTURES / "types.xsd", source / "types.xsd")
        text = (FIXTURES / "values.htm").read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, old)
        (source / "variant.htm").write_text(text.replace(old, new), encoding="utf-8")
        return source / "variant.htm"

    def assert_refused(self, primary: Path, code: str) -> None:
        result, out = export(primary, self.work, "refused")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("export refused, nothing written", result.stderr)
        self.assertIn(f"{code} x1", result.stderr)
        self.assertFalse(out.exists())

    def assert_exports(self, fixture: str, expected: dict) -> None:
        result, out = export(FIXTURES / fixture, self.work, "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = rows_by_id(out)
        self.assertEqual({i: (rows[i]["value_status"], rows[i]["value_text"]) for i in rows}, expected)

    def test_b_value_space_enumerations_and_the_colon_name_export(self):
        self.assert_exports(
            "widened.htm",
            {"choice-1": ("reported", "1.0"), "choice-2": ("reported", "2.50"), "name": ("reported", ":a")},
        )

    def test_the_control_values_for_c_and_d_export(self):
        self.assert_exports(
            "values.htm",
            {
                "bytes": ("reported", "aGVsbG8="), "day": ("reported", "2025-01-31+14:00"),
                "since": ("reported", "2025-01-01"),
            },
        )

    def test_c_invalid_base64_is_refused(self):
        self.assert_refused(self.variant(">aGVsbG8=<", ">not*base64<"), "xmlSchema:valueError")

    def test_c_time_zone_beyond_14_hours_is_refused(self):
        self.assert_refused(self.variant(">2025-01-31+14:00<", ">2025-01-31+15:00<"), "xmlSchema:valueError")

    def test_c_date_below_min_inclusive_is_refused(self):
        self.assert_refused(
            self.variant('contextRef="y2025">2025-01-01</ix:nonNumeric>',
                         'contextRef="y2025">2024-12-31</ix:nonNumeric>'),
            "xmlSchema:valueError",
        )

    def test_d_inline_root_outside_xhtml_is_refused(self):
        primary = self.variant('<html xmlns="http://www.w3.org/1999/xhtml"\n', "<html\n")
        self.assert_refused(primary, "ix11.3.3.1:rootElement")


if __name__ == "__main__":
    unittest.main()
