"""SEC `ixt-sec` inline transforms in `pack` (bd-tz1).

Expected values and verdicts are written from the markup in tests/fixtures/sec_transforms. The
vendored file hashes below were computed from the upstream download of Arelle/EDGAR at the pinned
commit, not from the files in this repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import arelle  # type: ignore # noqa: F401

    HAVE_ARELLE = True
except ImportError:
    HAVE_ARELLE = False

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "sec_transforms"
VENDOR = REPO / "src" / "cmdrvl_xew" / "xew_edgar_ixt_sec"
DEAD_PROXY = "http://127.0.0.1:9"

COMMIT = "99e94b6c6f5ca2ef06a9c2f29b0a4290a7f959db"
UPSTREAM_SHA256 = {
    "__init__.py": "2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1",
    "text2num.py": "6c9b26354320a2fb34fe380cdc71ff7f8d1cc712811e6b10c661e512f0383409",
}
# `shasum -a 256 __init__.py text2num.py | shasum -a 256` on the upstream files.
IDENTITY = (
    "Arelle/EDGAR transform 99e94b6c6f5c "
    "sha256:9d2c3154229397b1bfcf5065314be7317dd8d6fd9a5cc61fb4921f2637f3dd9e"
)

# id -> value as the markup states it; None = cannot be produced from the filing.
EXPECTED_VALUES = {
    "m1": "MD", "m2": "DE", "n1": "2", "n2": "2",
    "x1": None, "x2": None, "u1": None, "u2": None, "s1": None, "s2": None,
    "p1": None, "p2": "5", "p3": "7", "q1": None, "q2": "9",
}
# (concept, context) -> reported values of each conflict, in any order.
EXPECTED_CONFLICTS = {("Note", "y2025"): ["DE", "MD"], ("Amount", "now"): ["5", "7"]}
# (concept, context) -> (facts in the set, [(source text, format) of the unavailable ones])
EXPECTED_UNEVALUATED = {
    ("Note", "y2024"): (2, [("Gondor", "ixt-sec:stateprovnameen"), ("Narnia", "ixt-sec:stateprovnameen")]),
    ("Note", "y2023"): (2, [("alpha", "zz:mystery"), ("beta", "zz:mystery")]),
    ("Note", "y2022"): (2, [("same", "zz:mystery"), ("same", "zz:mystery")]),
    ("Amount", "now"): (3, [("unreadable", "zz:mystery")]),
    ("Amount", "prior"): (2, [("unreadable", "zz:mystery")]),
}


def offline_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "XEW_USER_AGENT"}
    env.update(
        PYTHONPATH=str(REPO / "src"), PYTHONDONTWRITEBYTECODE="1",
        HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
    )
    return env


def run_pack(primary: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "-m", "cmdrvl_xew", "pack", "--pack-id", "XEW-EP-SEC", "--out", str(out),
            "--primary", str(primary), "--cik", "0000000001", "--accession", "0000000001-25-000001",
            "--form", "10-Q", "--filed-date", "2025-11-01",
            "--primary-document-url", "https://example.com/f.htm",
            "--retrieved-at", "2026-01-15T10:30:00Z", "--resolution-mode", "offline_only",
            "--arelle-xdg-config-home", str(out.parent / "xdg"), *extra,
        ],
        cwd=out.parent, env=offline_env(), capture_output=True, text=True, timeout=600,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def instances(findings: dict, pattern_id: str) -> list[dict]:
    return [
        instance
        for finding in findings["findings"]
        if finding["pattern_id"] == pattern_id
        for instance in finding["observed"]["instances"]
    ]


class TestVendoredFiles(unittest.TestCase):
    def test_vendored_files_are_the_upstream_bytes(self):
        found = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in VENDOR.glob("*.py")}
        self.assertEqual(found, UPSTREAM_SHA256)

    def test_notice_records_the_source_and_every_license_statement(self):
        notice = (VENDOR / "NOTICE.md").read_text(encoding="utf-8")
        for text in (
            COMMIT, "https://github.com/Arelle/EDGAR", *UPSTREAM_SHA256.values(),
            "CC0 1.0 Universal", "17 U.S.C. 105", "'license': 'Apache-2'", "MIT License",
            "Copyright (c) 2008 Greg Hewgill", "The above copyright notice and this permission notice",
        ):
            self.assertIn(text, notice)
        self.assertIn("CC0 1.0 Universal", (VENDOR / "LICENSE.EDGAR").read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_ARELLE, "needs the arelle extra")
class TestPackWithSecTransforms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.packs = {}
        for mode in ("rounded", "strict"):
            out = cls.work / mode
            result = run_pack(FIXTURES / "dups.htm", out, "--require-arelle", "--p001-conflict-mode", mode)
            if result.returncode != 0:
                raise AssertionError(result.stderr)
            cls.packs[mode] = out

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_conflicts_are_exactly_those_the_markup_states(self):
        for mode, out in self.packs.items():
            with self.subTest(mode=mode):
                got = {
                    (i["data"]["concept"]["local_name"], i["data"]["context_ref"]):
                        sorted(f["value"] for f in i["data"]["facts"] if "value" in f)
                    for i in instances(read_json(out / "xew_findings.json"), "XEW-P001")
                }
                self.assertEqual(got, EXPECTED_CONFLICTS)

    def test_every_set_that_could_not_be_fully_evaluated_is_listed_in_ext(self):
        for mode, out in self.packs.items():
            with self.subTest(mode=mode):
                listing = read_json(out / "xew_findings.json")["ext"]["p001_unevaluated_duplicate_sets"]
                self.assertEqual((listing["total"], listing["included"], listing["truncated"]), (5, 5, False))
                got = {
                    (s["concept"]["local_name"], s["context_ref"]): (
                        s["fact_count"],
                        sorted(
                            (f["source"]["source_text"], f["source"]["format"])
                            for f in s["facts"] if "value" not in f
                        ),
                    )
                    for s in listing["sets"]
                }
                self.assertEqual(got, EXPECTED_UNEVALUATED)
                ids = [s["instance_id"] for s in listing["sets"]]
                self.assertEqual(ids, sorted(ids))
                for entry in listing["sets"]:
                    unavailable = [f for f in entry["facts"] if "value" not in f]
                    self.assertEqual(entry["unavailable_count"], len(unavailable))
                    for fact in unavailable:
                        self.assertEqual(fact["source"]["value_status"], "unavailable")

    def test_unavailable_values_are_marked_in_all_evidence_and_the_placeholder_never_appears(self):
        out = self.packs["rounded"]
        for path in out.rglob("*.json"):
            self.assertNotIn("ixTransformValueError", path.read_text(encoding="utf-8"), path.name)
        document = read_json(out / "xew_findings.json")
        p004 = [i["data"]["fact"] for i in instances(document, "XEW-P004")]
        marked = [f for f in p004 if "value" not in f]
        self.assertEqual(len(marked), 2)  # p1 and q1
        for fact in marked:
            self.assertEqual(
                fact["source"],
                {"value_status": "unavailable", "source_text": "unreadable", "format": "zz:mystery"},
            )
        self.assertEqual(sorted(f["value"] for f in p004 if "value" in f), ["5", "7", "9"])

    def test_packs_validate_and_record_the_transform_identity(self):
        for out in self.packs.values():
            verify = subprocess.run(
                [sys.executable, "-m", "cmdrvl_xew", "verify-pack", "--pack", str(out), "--validate-schema"],
                env=offline_env(), capture_output=True, text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            self.assertEqual(read_json(out / "toolchain" / "toolchain.json")["arelle_sec_plugin_version"], IDENTITY)
            findings = read_json(out / "xew_findings.json")
            self.assertEqual(findings["toolchain"]["arelle_sec_plugin_version"], IDENTITY)
            manifest = {f["path"]: f["sha256"] for f in read_json(out / "pack_manifest.json")["files"]}
            self.assertEqual(
                manifest["toolchain/toolchain.json"],
                hashlib.sha256((out / "toolchain" / "toolchain.json").read_bytes()).hexdigest(),
            )

    def test_a_pack_that_did_not_use_arelle_does_not_claim_the_transforms(self):
        out = self.work / "no-arelle"
        result = run_pack(FIXTURES / "dups.htm", out, "--no-arelle")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_json(out / "toolchain" / "toolchain.json")["arelle_sec_plugin_version"], "not_loaded")
        self.assertEqual(read_json(out / "xew_findings.json")["toolchain"]["arelle_sec_plugin_version"], "not_loaded")

    def test_ext_listing_is_capped_at_100_sets_and_says_so(self):
        source = self.work / "many-source"
        source.mkdir()
        shutil.copyfile(FIXTURES / "sec.xsd", source / "sec.xsd")
        template = (FIXTURES / "dups.htm").read_text(encoding="utf-8")
        head = template[: template.index('<xbrli:context id="now">')]
        contexts, facts = [], []
        for number in range(101):  # 101 sets of two unreadable facts, one context each
            contexts.append(
                f'<xbrli:context id="c{number}"><xbrli:entity><xbrli:identifier scheme="http://example.com/id">'
                f"E{number}</xbrli:identifier></xbrli:entity><xbrli:period>"
                "<xbrli:instant>2025-09-30</xbrli:instant></xbrli:period></xbrli:context>"
            )
            facts += [
                f'<p><ix:nonFraction id="f{number}-{copy}" name="s:Ratio" contextRef="c{number}" unitRef="pure" '
                'decimals="INF" format="zz:mystery">?</ix:nonFraction></p>'
                for copy in (1, 2)
            ]
        unit = '<xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>'
        (source / "many.htm").write_text(
            head + "".join(contexts) + unit + "</ix:resources></ix:header></div>" + "".join(facts) + "</body></html>",
            encoding="utf-8",
        )
        out = self.work / "many"
        result = run_pack(source / "many.htm", out, "--require-arelle")
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = read_json(out / "xew_findings.json")["ext"]["p001_unevaluated_duplicate_sets"]
        self.assertEqual(
            (listing["total"], listing["included"], listing["truncated"], len(listing["sets"])),
            (101, 100, True, 100),
        )
        ids = [s["instance_id"] for s in listing["sets"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(instances(read_json(out / "xew_findings.json"), "XEW-P001"), [])

    def test_ext_listing_is_absent_when_every_set_was_evaluated(self):
        out = self.work / "wide"
        result = run_pack(REPO / "tests" / "fixtures" / "pack_precision" / "wide.htm", out, "--require-arelle")
        self.assertEqual(result.returncode, 0, result.stderr)
        document = read_json(out / "xew_findings.json")
        self.assertNotIn("p001_unevaluated_duplicate_sets", document.get("ext", {}))
        self.assertTrue(instances(document, "XEW-P001"))


@unittest.skipUnless(HAVE_ARELLE, "needs the arelle extra")
class TestP008StillSeesTheDisplayedText(unittest.TestCase):
    """The exchange names below have SEC codes that XEW-P008 would key differently."""

    DISPLAYED = {
        "stock": "NYSE American", "note": "NYSE American", "arca": "NYSE Arca",
        "national": "NYSE National", "bzx": "Cboe BZX Exchange",
        "chicago": "Chicago Stock Exchange", "iex": "Investors Exchange",
    }
    CODES = {
        "stock": "NYSEAMER", "note": "NYSEAMER", "arca": "NYSEArca", "national": "NYSENAT",
        "bzx": "CboeBZX", "chicago": "CHX", "iex": "IEX",
    }

    def test_arelle_values_are_codes_and_p008_reads_the_displayed_text(self):
        from cmdrvl_xew.detectors.p008_identity_collapse import InstrumentIdentityCollapseDetector
        from cmdrvl_xew.pack import _load_xbrl_model_with_arelle

        with tempfile.TemporaryDirectory() as xdg:
            model = _load_xbrl_model_with_arelle(
                FIXTURES / "p008.htm", resolution_mode="offline_only", require_arelle=True,
                disable_arelle=False, arelle_xdg_config_home=xdg,
            )
            try:
                facts = [f for f in model.facts if f.qname.localName == "SecurityExchangeName"]
                self.assertEqual({f.contextID: str(f.value) for f in facts}, self.CODES)
                detector = InstrumentIdentityCollapseDetector()
                self.assertEqual({f.contextID: detector._arelle_fact_value(f) for f in facts}, self.DISPLAYED)
            finally:
                model.close()

    def test_p008_end_to_end_matches_a_registry_keyed_by_the_displayed_name(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            registry = work / "registry.json"
            registry.write_text(json.dumps({
                "schema_id": "cmdrvl.canon.openfigi_registry_snapshot", "schema_version": "1.0",
                "snapshot_id": "xew-test", "generated_at": "2026-01-01T00:00:00Z",
                "source": {"provider": "canon", "dataset": "openfigi"},
                "rows": [
                    {"figi": "BBG000000001", "ticker": "XEWT", "exchange": "NYSE American",
                     "normalized_title": "COMMON STOCK PAR 0.01"},
                    {"figi": "BBG000000002", "ticker": "XEWT", "exchange": "NYSE American",
                     "normalized_title": "NOTE 3.125% DUE 2028"},
                ],
            }), encoding="utf-8")
            out = work / "pack"
            result = run_pack(FIXTURES / "p008.htm", out, "--require-arelle",
                              "--p008-registry-snapshot", str(registry))
            self.assertEqual(result.returncode, 0, result.stderr)
            (instance,) = instances(read_json(out / "xew_findings.json"), "XEW-P008")
            members = instance["data"]["members"]
            self.assertEqual(
                sorted(m["registry"]["row"]["figi"] for m in members), ["BBG000000001", "BBG000000002"]
            )
            exchange_values = {
                f["value"] for m in members for f in m["facts"]
                if f["concept"]["local_name"] == "SecurityExchangeName"
            }
            self.assertEqual(exchange_values, {"NYSE American"})
            self.assertNotIn("NYSEAMER", json.dumps(instance))


@unittest.skipUnless(HAVE_ARELLE, "needs the arelle extra")
class TestLoaderRefusalAndIsolation(unittest.TestCase):
    """Arelle's plugin registry is one per process."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def load_values(self, xdg: Path | None = None) -> dict:
        from arelle.ModelValue import INVALIDixVALUE
        from cmdrvl_xew.pack import _load_xbrl_model_with_arelle

        model = _load_xbrl_model_with_arelle(
            FIXTURES / "dups.htm", resolution_mode="offline_only", require_arelle=False,
            disable_arelle=False, arelle_xdg_config_home=str(xdg or self.work / "xdg"),
        )
        self.assertIsNotNone(model)
        try:
            return {f.id: None if f.value is INVALIDixVALUE else str(f.value) for f in model.factsInInstance}
        finally:
            model.close()

    def registered_plugins(self) -> list[str]:
        from arelle import PluginManager

        return sorted((PluginManager.getInstance().pluginConfig or {}).get("modules", {}))

    def hostile_plugin(self) -> Path:
        """A plugin that rewrites a SEC transform and notes every controller it sees."""
        directory = self.work / "xew_test_hostile_plugin"
        directory.mkdir()
        (directory / "__init__.py").write_text(textwrap.dedent('''
            from pathlib import Path
            from arelle.ModelValue import qname

            def mark(name):
                (Path(__file__).parent / name).write_text("ran")

            def transforms(custom, *args, **kwargs):
                mark("transforms-called")
                custom[qname("http://www.sec.gov/inlineXBRL/transformation/2015-08-31",
                             "ixt-sec:stateprovnameen")] = lambda text: "XX"

            def cntlr_init(cntlr, *args, **kwargs):
                mark("cntlr-init-called")

            __pluginInfo__ = {
                "name": "Hostile test plugin", "version": "1",
                "ModelManager.LoadCustomTransforms": transforms,
                "Cntlr.Init": cntlr_init,
            }
        '''), encoding="utf-8")
        return directory

    def test_repeated_loads_in_one_process_are_identical_and_leave_nothing_registered(self):
        for _ in range(3):
            self.assertEqual(self.load_values(), EXPECTED_VALUES)
            self.assertEqual(self.registered_plugins(), [])

    def test_a_plugin_already_registered_in_the_process_cannot_change_results(self):
        from arelle import Cntlr, PluginManager

        hostile = self.hostile_plugin()
        controller = Cntlr.Cntlr(logFileName="logToBuffer")
        PluginManager.init(controller, loadPluginConfig=False)
        self.assertIsNotNone(PluginManager.addPluginModule(str(hostile / "__init__.py")))
        self.addCleanup(PluginManager.close)
        self.assertIn("Hostile test plugin", self.registered_plugins())

        self.assertEqual(self.load_values(), EXPECTED_VALUES)
        self.assertFalse((hostile / "transforms-called").exists())
        self.assertFalse((hostile / "cntlr-init-called").exists())

    def test_a_users_installed_plugin_config_cannot_change_results(self):
        hostile = self.hostile_plugin()
        xdg = self.work / "user-xdg"
        (xdg / "arelle").mkdir(parents=True)
        (xdg / "arelle" / "plugins.json").write_text(json.dumps({
            "modules": {"Hostile test plugin": {
                "name": "Hostile test plugin", "status": "enabled", "version": "1",
                "moduleURL": str(hostile), "path": str(hostile / "__init__.py"),
                "fileDate": "2000-01-01T00:00:00 UTC",
                "classMethods": ["ModelManager.LoadCustomTransforms", "Cntlr.Init"],
            }},
            "classes": {
                "ModelManager.LoadCustomTransforms": ["Hostile test plugin"],
                "Cntlr.Init": ["Hostile test plugin"],
            },
        }), encoding="utf-8")

        self.assertEqual(self.load_values(xdg), EXPECTED_VALUES)
        self.assertFalse((hostile / "transforms-called").exists())
        self.assertFalse((hostile / "cntlr-init-called").exists())

    def test_installed_entry_point_plugins_are_never_discovered(self):
        from arelle.plugin_system.entry_point_ref import EntryPointRef

        with patch.object(EntryPointRef, "discoverAll", side_effect=AssertionError("discovery ran")), \
                patch.object(EntryPointRef, "_discoverInstalled", side_effect=AssertionError("discovery ran")):
            self.assertEqual(self.load_values(), EXPECTED_VALUES)

    def assert_load_refused(self, directory: Path, *patches) -> None:
        from cmdrvl_xew import sec_transforms

        with patch.object(sec_transforms, "TRANSFORM_DIR", directory):
            for extra in patches:
                extra.start()
                self.addCleanup(extra.stop)
            with self.assertRaises(SystemExit) as caught:
                self.load_values()  # require_arelle=False: it must refuse all the same
        self.assertEqual(caught.exception.code, 3)
        self.assertEqual(self.registered_plugins(), [])

    def copy_of_vendor(self) -> Path:
        directory = self.work / "xew_edgar_ixt_sec"
        shutil.copytree(VENDOR, directory, ignore=shutil.ignore_patterns("__pycache__"))
        return directory

    def test_a_changed_vendored_file_is_refused(self):
        directory = self.copy_of_vendor()
        with (directory / "text2num.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# changed\n")
        self.assert_load_refused(directory)

    def test_missing_vendored_files_are_refused(self):
        self.assert_load_refused(self.work / "does-not-exist")

    def test_a_module_that_registers_no_transforms_is_refused(self):
        from cmdrvl_xew import sec_transforms

        directory = self.copy_of_vendor()
        source = (directory / "__init__.py").read_text(encoding="utf-8")
        changed = source.replace("'ModelManager.LoadCustomTransforms': loadSECtransforms,", "")
        self.assertNotEqual(changed, source)
        (directory / "__init__.py").write_text(changed, encoding="utf-8")
        # Even if the hash pin were updated to match, registration must still be checked.
        pins = {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in UPSTREAM_SHA256
        }
        self.assert_load_refused(directory, patch.object(sec_transforms, "PINNED_SHA256", pins))


if __name__ == "__main__":
    unittest.main()
