"""export-facts (xew.facts.v1).

Every expected value here is written from the source markup (tests/fixtures/facts_v1, or the real
filing and SEC's own extracted instance beside it), never from the exporter's output.

Needs the ``arelle`` and ``parquet`` extras. The real-filing tests also need the untracked sample
filing and a local taxonomy bundle; they skip, with the reason, when either is absent.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

try:
    import arelle  # type: ignore # noqa: F401
    import pyarrow  # type: ignore
    import pyarrow.parquet  # type: ignore

    HAVE_EXTRAS = True
except ImportError:
    HAVE_EXTRAS = False

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "facts_v1"
ACCESSION = "0000034903-25-000063"
SAMPLE = REPO / "sample" / ACCESSION
BUNDLE = Path(os.environ.get("XEW_TEST_ARELLE_HOME") or REPO / ".cache" / "xew-arelle-2018-2026")
IX = "http://www.xbrl.org/2013/inlineXBRL"
TABLE_FILES = (
    "facts.parquet",
    "contexts.parquet",
    "dimensions.parquet",
    "units.parquet",
    "filing.parquet",
    "documents.parquet",
)
DEAD_PROXY = "http://127.0.0.1:9"


def run_export(primary: Path, out: Path, xdg: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "XEW_USER_AGENT"}
    env.update(
        PYTHONPATH=str(REPO / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        HTTP_PROXY=DEAD_PROXY,
        HTTPS_PROXY=DEAD_PROXY,
        http_proxy=DEAD_PROXY,
        https_proxy=DEAD_PROXY,
    )
    command = [
        sys.executable, "-m", "cmdrvl_xew", "export-facts",
        "--primary", str(primary), "--out", str(out),
        "--cik", "34903", "--accession", ACCESSION, "--form", "10-Q",
        "--filed-date", "2025-10-31", "--period-end", "2025-09-30",
        "--primary-document-url", "https://example.com/primary.htm",
        "--arelle-xdg-config-home", str(xdg),
        *extra,
    ]
    return subprocess.run(command, cwd=out.parent, env=env, capture_output=True, text=True, timeout=600)


def read_rows(out: Path, name: str) -> list[dict]:
    return pyarrow.parquet.read_table(out / name).to_pylist()


def source_text_of(element: ET.Element) -> str:
    """Text content by the standard library's parser, independent of lxml and Arelle."""
    parts = [element.text or ""]
    for child in element:
        if child.tag != f"{{{IX}}}exclude":
            parts.append(source_text_of(child))
        parts.append(child.tail or "")
    return "".join(parts)


def element_at(root: ET.Element, path: str) -> ET.Element:
    node = root
    for step in path.strip("/").split("/")[1:]:
        node = list(node)[int(step[2:-1]) - 1]
    return node


class LocatorAssertions(unittest.TestCase):
    def assert_rows_resolve_to_source(self, rows: list[dict], source: Path) -> None:
        data = source.read_bytes()
        root = ET.fromstring(data[data.index(b"<?xml"):])
        by_id = {e.get("id"): e for e in root.iter() if e.get("id")}
        for row in rows:
            element = element_at(root, row["source_element_path"])
            self.assertIs(element, by_id[row["fact_id"]], row["fact_id"])
            self.assertEqual(element.get("contextRef"), row["context_id"], row["fact_id"])
            self.assertEqual(element.get("scale"), row["scale"], row["fact_id"])
            self.assertEqual(element.get("sign"), row["sign"], row["fact_id"])
            self.assertEqual(element.get("format"), row["format"], row["fact_id"])
            expected = source_text_of(element)
            follow = element.get("continuedAt")
            while follow:
                expected += source_text_of(by_id[follow])
                follow = by_id[follow].get("continuedAt")
            self.assertEqual(row["source_text"], expected, row["fact_id"])


@unittest.skipUnless(HAVE_EXTRAS, "needs the arelle and parquet extras")
class TestSyntheticExport(LocatorAssertions):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.xdg = cls.work / "xdg"
        cls.out = cls.work / "out"
        cls.result = run_export(FIXTURE / "tiny.htm", cls.out, cls.xdg)
        if cls.result.returncode != 0:
            raise AssertionError(cls.result.stderr)
        cls.rows = {row["fact_id"]: row for row in read_rows(cls.out, "facts.parquet")}
        cls.manifest = json.loads((cls.out / "export_manifest.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def assert_value(self, fact_id, status, text, number, number_status):
        row = self.rows[fact_id]
        self.assertEqual(
            (row["value_status"], row["value_text"], row["value_decimal"], row["decimal_status"]),
            (status, text, None if number is None else Decimal(number), number_status),
            fact_id,
        )

    def test_every_fact_in_the_source_is_a_row_in_document_order(self):
        in_source = [
            "hidden-note", "scaled", "negative", "percent", "dash", "nil-amount", "empty-note",
            "huge-integer", "long-fraction", "huge-scaled", "widest", "scaled-again", "section",
            "nested", "escaped", "sec-transform",
        ]
        self.assertEqual(list(self.rows), in_source)
        self.assertEqual([self.rows[i]["fact_ordinal"] for i in in_source], list(range(1, 17)))
        self.assertEqual(self.manifest["facts_loaded"], 16)
        self.assertEqual(self.manifest["facts_exported"], 16)
        self.assertEqual(self.manifest["facts_excluded"], [])

    def test_escaped_markup_keeps_relative_links(self):
        value = self.rows["escaped"]["value_text"]
        self.assertIn('href="exhibit.htm"', value)
        self.assertIn('src="logo.png"', value)
        self.assertNotIn("file:", value)
        self.assertEqual(self.rows["escaped"]["source_text"], "See the exhibit")

    def test_scale_sign_and_formats(self):
        self.assert_value("scaled", "reported", "1247000", "1247000", "exact")
        self.assert_value("negative", "reported", "-2500000", "-2500000", "exact")
        self.assert_value("percent", "reported", "0.0085", "0.0085", "exact")
        self.assert_value("dash", "reported", "0", "0", "exact")
        negative = self.rows["negative"]
        self.assertEqual(
            (negative["source_text"], negative["sign"], negative["scale"], negative["decimals"]),
            ("2.5", "-", "6", "-5"),
        )
        self.assertEqual(self.rows["dash"]["source_text"], "—")
        self.assertEqual(self.rows["percent"]["decimals"], "INF")

    def test_nil_and_empty_are_distinct(self):
        self.assert_value("nil-amount", "nil", None, None, "no_value")
        self.assert_value("empty-note", "empty", "", None, "not_numeric")
        self.assertTrue(self.rows["nil-amount"]["is_nil"])
        self.assertFalse(self.rows["empty-note"]["is_nil"])

    def test_wide_values_are_never_rounded(self):
        # More digits than Python's default 28-digit decimal context.
        self.assert_value("huge-integer", "reported", "123456789012345678901234567890", None, "out_of_range")
        self.assert_value("long-fraction", "reported", "0.123456789012345678901234567890123", None, "out_of_range")
        self.assert_value("huge-scaled", "reported", "1234567890123456789012345678901", None, "out_of_range")
        self.assert_value(
            "widest", "reported", "12345678901234567890.123456789012345678",
            "12345678901234567890.123456789012345678", "exact",
        )

    def test_duplicates_are_kept_and_keyed(self):
        first, second = self.rows["scaled"], self.rows["scaled-again"]
        self.assertEqual(first["aspect_key"], second["aspect_key"])
        self.assertEqual((first["duplicate_ordinal"], second["duplicate_ordinal"]), (1, 2))
        self.assertEqual((first["duplicate_count"], second["duplicate_count"]), (2, 2))
        self.assertEqual(second["fact_key"], f"{second['aspect_key']}:2")
        self.assertEqual(len({row["fact_key"] for row in self.rows.values()}), 16)
        others = [r for i, r in self.rows.items() if i not in ("scaled", "scaled-again")]
        self.assertEqual({r["duplicate_count"] for r in others}, {1})

    def test_text_continuation_exclude_nested_and_hidden(self):
        section = self.rows["section"]
        self.assertEqual(section["source_text"], "Alpha bold 42 units omega end. Continued here.")
        self.assertEqual(section["continuation_ids"], "section-more")
        for fragment in ("Alpha ", "bold ", "42", " units", " omega", " Continued ", "here"):
            self.assertIn(fragment, section["value_text"])
        self.assertNotIn("PAGE 3", section["value_text"])
        self.assertNotIn("between, not part", section["value_text"])
        self.assert_value("nested", "reported", "42", "42", "exact")
        self.assertTrue(self.rows["hidden-note"]["in_ix_hidden"])
        self.assertFalse(section["in_ix_hidden"])

    def test_unshipped_transform_has_no_value_but_keeps_the_source(self):
        self.assert_value("sec-transform", "transform_unavailable", None, None, "not_numeric")
        row = self.rows["sec-transform"]
        self.assertEqual((row["source_text"], row["format"]), ("Maryland", "ixt-sec:stateprovnameen"))
        self.assertEqual(self.manifest["value_status_counts"]["transform_unavailable"], 1)
        for table in TABLE_FILES:
            self.assertNotIn("ixTransformValueError", str(read_rows(self.out, table)))

    def test_contexts_dimensions_and_units(self):
        negative = self.rows["negative"]
        self.assertEqual(
            (negative["entity_scheme"], negative["entity_identifier"], negative["period_type"],
             negative["period_instant"], negative["period_start"], negative["period_end"]),
            ("http://example.com/id", "E1", "instant", "2025-09-30", None, None),
        )
        scaled_year = self.rows["dash"]
        self.assertEqual(
            (scaled_year["period_type"], scaled_year["period_start"], scaled_year["period_end"]),
            ("duration", "2025-01-01", "2025-12-31"),
        )
        self.assertEqual(scaled_year["unit"], "iso4217:USD/xbrli:shares")
        self.assertEqual(scaled_year["dimensions"], "[]")

        dimensions = read_rows(self.out, "dimensions.parquet")
        self.assertEqual(
            [(d["context_id"], d["axis"], d["member_kind"], d["member"], d["container"]) for d in dimensions],
            [
                ("now-dims", "t:LoanAxis", "typed", None, "segment"),
                ("now-dims", "t:SegmentAxis", "explicit", "t:RetailMember", "segment"),
            ],
        )
        self.assertEqual(
            json.loads(dimensions[0]["typed_member_json"]),
            {"name": "{http://example.com/tiny}LoanNumber", "text": "0007"},
        )
        self.assertIn("0007", negative["dimensions"])
        units = {u["unit_id"]: u for u in read_rows(self.out, "units.parquet")}
        self.assertEqual(
            (units["usd-per-share"]["numerator"], units["usd-per-share"]["denominator"]),
            ("iso4217:USD", "xbrli:shares"),
        )
        self.assertEqual([c["context_id"] for c in read_rows(self.out, "contexts.parquet")],
                         ["now", "now-dims", "older-year", "prior-year", "year"])

    def test_filing_ancestry_and_documents(self):
        digest = hashlib.sha256((FIXTURE / "tiny.htm").read_bytes()).hexdigest()
        (filing,) = read_rows(self.out, "filing.parquet")
        self.assertEqual(
            filing,
            {
                "accession": ACCESSION, "cik": "0000034903", "form": "10-Q", "filed_date": "2025-10-31",
                "period_end": "2025-09-30", "primary_document_url": "https://example.com/primary.htm",
                "amends_accession": None, "amendment_flag": None, "primary_document": "tiny.htm",
                "primary_document_sha256": digest, "schema_id": "xew.facts.v1",
            },
        )
        local = {d["uri"]: d["sha256"] for d in read_rows(self.out, "documents.parquet") if d["role"] == "local"}
        self.assertEqual(
            local,
            {name: hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() for name in ("tiny.htm", "tiny.xsd")},
        )

    def test_rows_resolve_to_the_source(self):
        self.assert_rows_resolve_to_source(list(self.rows.values()), FIXTURE / "tiny.htm")

    def test_schema_and_manifest_hashes(self):
        schema = pyarrow.parquet.read_schema(self.out / "facts.parquet")
        self.assertEqual(schema.field("value_text").type, pyarrow.string())
        self.assertEqual(schema.field("value_decimal").type, pyarrow.decimal128(38, 18))
        for name in schema.names:
            self.assertFalse(pyarrow.types.is_floating(schema.field(name).type), name)
        self.assertEqual(sorted(self.manifest["files"]), sorted(TABLE_FILES))
        for name, entry in self.manifest["files"].items():
            data = (self.out / name).read_bytes()
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest(), name)
            self.assertEqual(entry["rows"], len(read_rows(self.out, name)), name)
            self.assertNotIn(str(self.work).encode(), data, name)

    def test_two_runs_from_two_directories_are_byte_identical(self):
        copy = self.work / "another" / "place"
        copy.mkdir(parents=True)
        for name in ("tiny.htm", "tiny.xsd"):
            shutil.copyfile(FIXTURE / name, copy / name)
        second = self.work / "second"
        result = run_export(copy / "tiny.htm", second, self.xdg)
        self.assertEqual(result.returncode, 0, result.stderr)
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(sorted(p.name for p in second.iterdir()), names)
        for name in names:
            self.assertEqual((second / name).read_bytes(), (self.out / name).read_bytes(), name)

    def test_amends_accession_is_recorded_only_when_given(self):
        out = self.work / "amendment"
        result = run_export(FIXTURE / "tiny.htm", out, self.xdg, "--amends-accession", "0000034903-25-000001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_rows(out, "filing.parquet")[0]["amends_accession"], "0000034903-25-000001")

    def test_incomplete_taxonomy_is_refused_and_nothing_is_written(self):
        broken = self.work / "broken"
        broken.mkdir()
        shutil.copyfile(FIXTURE / "tiny.htm", broken / "tiny.htm")
        schema = (FIXTURE / "tiny.xsd").read_text(encoding="utf-8").replace(
            '<xsd:element name="Amount"',
            '<xsd:import namespace="http://example.com/absent" '
            'schemaLocation="https://example.com/absent-2025.xsd"/>\n  <xsd:element name="Amount"',
        )
        (broken / "tiny.xsd").write_text(schema, encoding="utf-8")
        out = self.work / "refused"
        result = run_export(broken / "tiny.htm", out, self.xdg)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("export refused, nothing written", result.stderr)
        self.assertIn("IOerror", result.stderr)
        self.assertFalse(out.exists())

    def test_non_empty_output_directory_is_left_alone(self):
        out = self.work / "occupied"
        out.mkdir()
        (out / "keep.txt").write_text("mine", encoding="utf-8")
        result = run_export(FIXTURE / "tiny.htm", out, self.xdg)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual([p.name for p in out.iterdir()], ["keep.txt"])
        self.assertEqual((out / "keep.txt").read_text(encoding="utf-8"), "mine")

    def test_bad_accession_is_a_config_error(self):
        out = self.work / "bad-args"
        result = run_export(FIXTURE / "tiny.htm", out, self.xdg, "--amends-accession", "nope")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(out.exists())


@unittest.skipUnless(HAVE_EXTRAS, "needs the arelle and parquet extras")
class TestTypedDecimal(unittest.TestCase):
    def test_bounds_are_exact_and_nothing_is_rounded(self):
        from cmdrvl_xew.facts_export import typed_decimal

        fits = ["0", "-0.000", "99999999999999999999.999999999999999999", "-12.50",
                "100000000000000000000e-1", "1.0000000000000000000000000000000000000000"]
        for text in fits:
            value, status = typed_decimal(text)
            self.assertEqual(status, "exact", text)
            self.assertEqual(value, Decimal(text), text)
        too_wide = ["100000000000000000000", "0.0000000000000000001", "1.0000000000000000001",
                    "-123456789012345678901", "INF", "-INF", "NaN", "text"]
        for text in too_wide:
            self.assertEqual(typed_decimal(text), (None, "out_of_range"), text)


@unittest.skipUnless(HAVE_EXTRAS, "needs the arelle and parquet extras")
@unittest.skipUnless(SAMPLE.is_dir(), f"untracked sample filing not present: {SAMPLE}")
@unittest.skipUnless((BUNDLE / "arelle" / "taxonomyPackages.json").is_file(), f"no taxonomy bundle at {BUNDLE}")
class TestRealFilingExport(LocatorAssertions):
    PRIMARY = SAMPLE / "frt-20250930.htm"

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.xdg = cls.work / "xdg"
        # Arelle may write to its config home, so give it a copy of the registry and cache.
        (cls.xdg / "arelle").mkdir(parents=True)
        shutil.copyfile(BUNDLE / "arelle" / "taxonomyPackages.json", cls.xdg / "arelle" / "taxonomyPackages.json")
        shutil.copytree(BUNDLE / "arelle" / "cache", cls.xdg / "arelle" / "cache")
        cls.out = cls.work / "out"
        cls.result = run_export(cls.PRIMARY, cls.out, cls.xdg)
        if cls.result.returncode != 0:
            raise AssertionError(cls.result.stderr)
        cls.rows = read_rows(cls.out, "facts.parquet")
        cls.by_id = {row["fact_id"]: row for row in cls.rows}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def source_root(self) -> ET.Element:
        data = self.PRIMARY.read_bytes()
        return ET.fromstring(data[data.index(b"<?xml"):])

    def test_every_source_fact_is_exported_once_in_document_order(self):
        tags = {f"{{{IX}}}{name}" for name in ("nonFraction", "nonNumeric", "fraction", "tuple")}
        in_source = [e.get("id") for e in self.source_root().iter() if e.tag in tags]
        self.assertEqual(len(in_source), 1336)
        self.assertEqual([row["fact_id"] for row in self.rows], in_source)
        manifest = json.loads((self.out / "export_manifest.json").read_text())
        self.assertEqual((manifest["facts_loaded"], manifest["facts_exported"]), (1336, 1336))

    def test_every_row_resolves_to_the_source(self):
        self.assert_rows_resolve_to_source(self.rows, self.PRIMARY)

    def test_edge_rows_read_from_the_filing(self):
        # Displayed text, scale and sign as they appear in the filing.
        expected = {
            "f-189": ("—", "3", None, "0"),
            "f-897": ("1,247", "3", "-", "-1247000"),
            "f-1085": ("1.0", "9", None, "1000000000"),
            "f-1336": ("85", "-4", None, "0.0085"),
        }
        for fact_id, (text, scale, sign, value) in expected.items():
            row = self.by_id[fact_id]
            self.assertEqual((row["source_text"], row["scale"], row["sign"]), (text, scale, sign), fact_id)
            self.assertEqual((row["value_text"], row["value_decimal"]), (value, Decimal(value)), fact_id)

    def test_values_agree_with_the_sec_extracted_instance(self):
        """SEC's own XBRL instance for this accession, produced by EDGAR and not by this code."""
        data = (SAMPLE / "XML" / "frt-20250930_htm.xml").read_bytes()
        data = data[data.index(b"<?xml"):].rstrip()
        if data.endswith(b"</XBRL>"):
            data = data[: -len(b"</XBRL>")]
        theirs = {e.get("id"): e for e in ET.fromstring(data) if e.get("contextRef")}
        self.assertEqual(sorted(theirs), sorted(self.by_id))
        numeric = text = 0
        for fact_id, element in theirs.items():
            row = self.by_id[fact_id]
            namespace, local = element.tag[1:].split("}")
            self.assertEqual(
                (row["concept_namespace"], row["concept_local_name"], row["context_id"], row["unit_id"],
                 row["decimals"], row["is_nil"]),
                (namespace, local, element.get("contextRef"), element.get("unitRef"), element.get("decimals"),
                 element.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true"),
                fact_id,
            )
            if row["value_status"] != "reported":
                continue
            instance_text = "".join(element.itertext())
            if row["fact_kind"] == "numeric":
                self.assertEqual(Decimal(row["value_text"]), Decimal(instance_text.strip()), fact_id)
                self.assertEqual(row["value_decimal"], Decimal(instance_text.strip()), fact_id)
                numeric += 1
            elif not instance_text.lstrip().startswith("<"):
                # Escaped HTML blocks are serialized differently there and are not compared.
                self.assertEqual(row["value_text"].strip(), instance_text.strip(), fact_id)
                text += 1
        self.assertEqual((numeric, text), (1264, 46))

    def test_dimensions_agree_with_the_sec_extracted_instance(self):
        data = (SAMPLE / "XML" / "frt-20250930_htm.xml").read_bytes()
        data = data[data.index(b"<?xml"):].rstrip()
        if data.endswith(b"</XBRL>"):
            data = data[: -len(b"</XBRL>")]
        # Prefix to namespace, to expand the QName-valued attributes and text.
        namespaces = dict(item for _, item in ET.iterparse(io.BytesIO(data), events=["start-ns"]))

        def expand(qname: str) -> str:
            prefix, local = qname.strip().split(":")
            return f"{{{namespaces[prefix]}}}{local}"

        expected = []
        for context in ET.fromstring(data).iter("{http://www.xbrl.org/2003/instance}context"):
            for member in context.iter("{http://xbrl.org/2006/xbrldi}explicitMember"):
                expected.append((context.get("id"), expand(member.get("dimension")), expand(member.text)))
        got = [
            (
                d["context_id"],
                f"{{{d['axis_namespace']}}}{d['axis_local_name']}",
                f"{{{d['member_namespace']}}}{d['member_local_name']}",
            )
            for d in read_rows(self.out, "dimensions.parquet")
        ]
        self.assertEqual(len(expected), 409)
        self.assertEqual(sorted(got), sorted(expected))
        by_context: dict[str, list] = {}
        for context_id, axis, member in expected:
            by_context.setdefault(context_id, []).append((axis, member))
        for row in self.rows:
            self.assertEqual(
                sorted((d["axis"], d["member"]) for d in json.loads(row["dimensions"])),
                sorted(by_context.get(row["context_id"], [])),
                row["fact_id"],
            )

    def test_transform_gaps_are_the_sec_transform_facts(self):
        unavailable = {r["fact_id"] for r in self.rows if r["value_status"] == "transform_unavailable"}
        in_source = {e.get("id") for e in self.source_root().iter() if (e.get("format") or "").startswith("ixt-sec:")}
        self.assertEqual(unavailable, in_source)
        self.assertEqual(len(unavailable), 10)
        self.assertEqual(sum(r["value_status"] == "nil" for r in self.rows), 4)


if __name__ == "__main__":
    unittest.main()
