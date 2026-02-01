"""Unit tests for XEW-P002 anchoring defects detector."""

import unittest
from unittest.mock import Mock

from cmdrvl_xew.detectors.p002_anchoring import AnchoringDefectsDetector
from cmdrvl_xew.detectors._base import DetectorContext


ARCROLE = "http://www.xbrl.org/2003/arcrole/concept-label"


class TestP002AnchoringDetector(unittest.TestCase):
    """Test cases for P002 anchoring defects detector."""

    def setUp(self):
        self.detector = AnchoringDefectsDetector()

    def test_no_model_document_returns_empty(self):
        xbrl_model = Mock()
        xbrl_model.modelDocument = None
        xbrl_model.qnameConcepts = {}
        xbrl_model.facts = []
        xbrl_model.relationshipSet = Mock(return_value=None)

        context = self._make_context(xbrl_model)
        findings = self.detector.detect(context)
        self.assertEqual(findings, [])

    def test_unanchored_extension_detected(self):
        ext_concept, ext_qname = self._make_concept(
            namespace="http://example.com/ext",
            local_name="ExtItem",
            type_name="stringItemType",
            period_type="instant",
            abstract=False,
        )
        fact = self._make_fact(ext_qname)
        xbrl_model = self._make_model([ext_concept], [], [fact])

        findings = self.detector.detect(self._make_context(xbrl_model))
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("unanchored", issue_codes)

    def test_anchor_abstract_and_mismatches(self):
        ext_concept, ext_qname = self._make_concept(
            namespace="http://example.com/ext",
            local_name="ExtItem",
            type_name="monetaryItemType",
            period_type="instant",
            abstract=False,
        )
        anchor_concept, _anchor_qname = self._make_concept(
            namespace="http://fasb.org/us-gaap/2023-01-31",
            local_name="Anchor",
            type_name="stringItemType",
            period_type="duration",
            abstract=True,
        )
        rel = self._make_relationship(ext_concept, anchor_concept)
        fact = self._make_fact(ext_qname)
        xbrl_model = self._make_model([ext_concept], [rel], [fact])

        findings = self.detector.detect(self._make_context(xbrl_model))
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("anchor_target_abstract", issue_codes)
        self.assertIn("period_type_mismatch", issue_codes)
        self.assertIn("type_mismatch", issue_codes)

    def test_anchor_to_extension_detected(self):
        ext_concept, ext_qname = self._make_concept(
            namespace="http://example.com/ext",
            local_name="ExtItem",
            type_name="stringItemType",
            period_type="instant",
            abstract=False,
        )
        anchor_concept, _anchor_qname = self._make_concept(
            namespace="http://example.com/ext",
            local_name="OtherExt",
            type_name="stringItemType",
            period_type="instant",
            abstract=False,
        )
        rel = self._make_relationship(ext_concept, anchor_concept)
        fact = self._make_fact(ext_qname)
        xbrl_model = self._make_model([ext_concept], [rel], [fact])

        findings = self.detector.detect(self._make_context(xbrl_model))
        self.assertEqual(len(findings), 1)
        issue_codes = self._extract_issue_codes(findings[0])
        self.assertIn("anchor_to_extension", issue_codes)

    def _extract_issue_codes(self, finding):
        return {code for instance in finding.instances for code in instance.data.get("issue_codes", [])}

    def _make_context(self, xbrl_model):
        return DetectorContext(
            primary_document_path="/tmp/primary.htm",
            artifacts_dir="/tmp",
            cik="0001234567",
            accession="0001234567-25-000001",
            form="10-Q",
            filed_date="2025-01-31",
            xbrl_model=xbrl_model,
            config={},
        )

    def _make_model(self, concepts, relationships, facts):
        xbrl_model = Mock()
        xbrl_model.modelDocument = object()
        xbrl_model.qnameConcepts = {concept.qname: concept for concept in concepts}
        xbrl_model.facts = facts

        def relationship_set(arcrole):
            if arcrole != ARCROLE or not relationships:
                return None
            relset = Mock()
            relset.modelRelationships = relationships
            return relset

        xbrl_model.relationshipSet = Mock(side_effect=relationship_set)
        return xbrl_model

    def _make_relationship(self, from_concept, to_concept):
        rel = Mock()
        rel.fromModelObject = from_concept
        rel.toModelObject = to_concept
        return rel

    def _make_fact(self, qname):
        fact = Mock()
        fact.qname = qname
        fact.context = Mock()
        fact.context.id = "ctx-1"
        fact.value = "100"
        return fact

    def _make_concept(self, *, namespace, local_name, type_name, period_type, abstract):
        qname = self._make_qname(namespace, local_name)
        concept = Mock()
        concept.qname = qname
        concept.type = type_name
        concept.periodType = period_type
        concept.abstract = abstract
        return concept, qname

    def _make_qname(self, namespace, local_name):
        qname = Mock()
        qname.namespaceURI = namespace
        qname.localName = local_name
        qname.prefix = None
        return qname


if __name__ == '__main__':
    unittest.main()
