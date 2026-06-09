"""Spec conformance tests for XEW-P009 identity drift contracts."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_P009_CODES = [
    "identifier_basis_transition",
    "strong_identifier_removed",
    "registry_bridge_available",
    "registry_bridge_missing",
    "registry_bridge_ambiguous",
    "weak_continuity_only",
    "weak_key_temporal_collision",
]


def _load_json(relative_path: str):
    path = ROOT / relative_path
    try:
        return json.JSONDecoder().decode(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Invalid JSON in {relative_path}: {exc}") from exc


class TestP009Spec(unittest.TestCase):
    def test_issue_code_catalog_contains_p009(self):
        catalog = _load_json("src/cmdrvl_xew/spec/xew_issue_codes.v1.json")

        self.assertEqual(catalog["patterns"]["XEW-P009"]["issue_codes"], EXPECTED_P009_CODES)

    def test_rule_basis_covers_every_p009_issue_code(self):
        rule_map = _load_json("src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json")
        rules = [rule for rule in rule_map["rules"] if rule.get("pattern_id") == "XEW-P009"]

        by_code = {rule["issue_code"]: rule for rule in rules}
        self.assertEqual(set(by_code), set(EXPECTED_P009_CODES))

        for issue_code in EXPECTED_P009_CODES:
            rule = by_code[issue_code]
            self.assertEqual(rule["source"], "OTHER")
            self.assertRegex(rule["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
            self.assertRegex(rule["sha256"], r"^[a-f0-9]{64}$")
            self.assertTrue(rule.get("url") or rule.get("title"))
            self.assertIn("P009", rule["citation"])
            self.assertGreater(len(rule["notes"]), 40)

        self.assertIn("must not call OpenFIGI", by_code["registry_bridge_available"]["notes"])
        self.assertIn("must not be replaced", by_code["registry_bridge_missing"]["notes"])

    def test_findings_schema_defines_p009_shape(self):
        schema = _load_json("src/cmdrvl_xew/schemas/xew_findings.schema.v1.json")

        finding_pattern_enum = schema["$defs"]["finding"]["properties"]["pattern_id"]["enum"]
        instance_kind_enum = schema["$defs"]["instance"]["properties"]["kind"]["enum"]
        p009_data = schema["$defs"]["p009_instrument_identity_drift"]
        p009_event = schema["$defs"]["p009_identity_drift_event"]

        self.assertIn("XEW-P009", finding_pattern_enum)
        self.assertIn("instrument_identity_drift", instance_kind_enum)
        self.assertNotIn("nport_identity_drift", instance_kind_enum)
        self.assertEqual(
            p009_data["properties"]["issue_codes"]["items"]["enum"],
            EXPECTED_P009_CODES,
        )
        self.assertEqual(
            p009_event["properties"]["issue_codes"]["items"]["enum"],
            EXPECTED_P009_CODES,
        )
        self.assertIn("continuity_class", p009_data["required"])
        self.assertIn("events", p009_data["required"])
        self.assertIn("source_scope", p009_data["required"])
        self.assertNotIn("series", p009_data["required"])

    def test_weak_p009_evidence_cannot_be_encoded_as_resolved_continuity(self):
        schema = _load_json("src/cmdrvl_xew/schemas/xew_findings.schema.v1.json")
        continuity_classes = set(
            schema["$defs"]["p009_instrument_identity_drift"]["properties"]["continuity_class"][
                "enum"
            ]
        )
        event_continuity_classes = set(
            schema["$defs"]["p009_identity_drift_event"]["properties"]["continuity_class"]["enum"]
        )

        self.assertIn("weak_unresolved", continuity_classes)
        self.assertIn("weak_collision", continuity_classes)
        self.assertNotIn("resolved", continuity_classes)
        self.assertEqual(continuity_classes, event_continuity_classes)

        contract_text = (ROOT / "docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            contract_text,
            re.compile(r"Weak .*cannot create a resolved canonical instrument identity", re.I),
        )
        self.assertIn("generated/instrument_identity_drift.v1.json", contract_text)
        self.assertNotIn("generated/nport_identity_drift.v1.json", contract_text)


if __name__ == "__main__":
    unittest.main()
