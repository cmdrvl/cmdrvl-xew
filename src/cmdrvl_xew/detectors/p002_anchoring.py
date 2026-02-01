"""
XEW-P002: Extension Concept Anchoring Defects

Detects objective anchoring defects in extension concepts without making semantic claims.
Focuses on structural issues like abstract targets and type/period mismatches.
"""

from typing import Dict, List, Any, Set, Tuple, Optional
from collections import defaultdict
import logging

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..util import (
    canonical_signature_p002,
    generate_finding_id,
    generate_instance_id,
    create_finding_summary,
    qname_to_clark,
    qname_object,
    instance_id_from_signature
)

logger = logging.getLogger(__name__)


# Issue codes for P002 anchoring defects (objective checks only)
P002_ISSUE_CODES = {
    'unanchored': 'Extension concept has no anchoring relationship',
    'anchor_target_abstract': 'Extension concept anchored to abstract concept',
    'period_type_mismatch': 'Extension period type differs from anchor period type',
    'type_mismatch': 'Extension data type differs from anchor data type',
    'anchor_to_extension': 'Extension concept anchored to another extension concept',
}


class AnchoringDefectsDetector(BaseDetector):
    """Detector for XEW-P002: Extension Concept Anchoring Defects."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P002"

    @property
    def pattern_name(self) -> str:
        return "Extension Concept Anchoring Defects"

    @property
    def alert_eligible(self) -> bool:
        return True  # P002 is v1 shipping set, alert-eligible

    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        """
        Detect anchoring defects in extension concepts.

        Args:
            context: Detection context with XBRL model and metadata

        Returns:
            List of findings (empty if no defects found)
        """
        self.logger.info("Running XEW-P002 extension anchoring defects detection")

        try:
            # Extract extension concepts and their anchoring relationships
            extension_concepts = self._extract_extension_concepts(context.xbrl_model)
            self.logger.debug(f"Found {len(extension_concepts)} extension concepts")

            anchoring_relationships = self._extract_anchoring_relationships(context.xbrl_model)
            self.logger.debug(f"Found {len(anchoring_relationships)} anchoring relationships")

            # Analyze anchoring defects
            defects = self._analyze_anchoring_defects(extension_concepts, anchoring_relationships, context)
            self.logger.debug(f"Detected {len(defects)} anchoring defects")

            if not defects:
                self.logger.info("No extension anchoring defects detected")
                return []

            # Create finding for anchoring defects
            finding = self._create_finding(defects, context)
            self.logger.info(f"Created finding with {len(finding.instances)} instances")

            return [finding]

        except Exception as e:
            self.logger.error(f"Error during P002 detection: {e}")
            raise

    def _extract_extension_concepts(self, xbrl_model) -> List[Dict[str, Any]]:
        """Extract extension concepts from XBRL model."""
        extension_concepts = []

        # Get the DTS (Discoverable Taxonomy Set) from Arelle model
        if not hasattr(xbrl_model, 'modelDocument') or not xbrl_model.modelDocument:
            self.logger.warning("No model document available for extension concept extraction")
            return extension_concepts

        # Extract concepts from extension taxonomy
        try:
            for concept in getattr(xbrl_model, 'qnameConcepts', {}).values():
                # Check if this is an extension concept (not from standard taxonomies)
                if self._is_extension_concept(concept):
                    concept_data = {
                        'concept': concept,
                        'qname': concept.qname,
                        'clark_notation': qname_to_clark(concept.qname),
                        'type': getattr(concept, 'type', None),
                        'period_type': getattr(concept, 'periodType', None),
                        'abstract': getattr(concept, 'abstract', False),
                        'substitution_group': getattr(concept, 'substitutionGroupQname', None),
                    }
                    extension_concepts.append(concept_data)

        except Exception as e:
            self.logger.error(f"Failed to extract extension concepts: {e}")

        return extension_concepts

    def _is_extension_concept(self, concept) -> bool:
        """Determine if a concept is an extension concept (not from standard taxonomies)."""
        if not concept or not hasattr(concept, 'qname'):
            return False

        # Common standard taxonomy namespaces (these are NOT extension concepts)
        standard_namespaces = {
            'http://fasb.org/us-gaap/',
            'http://xbrl.sec.gov/dei/',
            'http://xbrl.sec.gov/country/',
            'http://xbrl.sec.gov/currency/',
            'http://xbrl.ifrs.org/taxonomy/',
            'http://www.xbrl.org/2003/instance',
            'http://www.w3.org/2001/XMLSchema',
        }

        concept_ns = concept.qname.namespaceURI

        # Check if concept is from a standard taxonomy
        for std_ns in standard_namespaces:
            if concept_ns.startswith(std_ns):
                return False

        # If not from standard taxonomy, likely extension concept
        return True

    def _extract_anchoring_relationships(self, xbrl_model) -> List[Dict[str, Any]]:
        """Extract anchoring relationships from XBRL model."""
        anchoring_relationships = []

        try:
            # Look for anchoring relationships in the model
            # In XBRL, anchoring is typically expressed through definition linkbases
            if hasattr(xbrl_model, 'relationshipSet'):
                # Get anchoring arc roles
                anchoring_arcroles = [
                    'http://www.xbrl.org/2003/arcrole/concept-label',
                    'http://www.xbrl.org/2003/arcrole/concept-reference',
                    'http://xbrl.us/us-gaap/role/label/negated',
                    # Add more specific anchoring arc roles as needed
                ]

                for arcrole in anchoring_arcroles:
                    relationships = xbrl_model.relationshipSet(arcrole)
                    if relationships:
                        for rel in relationships.modelRelationships:
                            if hasattr(rel, 'fromModelObject') and hasattr(rel, 'toModelObject'):
                                rel_data = {
                                    'from_concept': rel.fromModelObject,
                                    'to_concept': rel.toModelObject,
                                    'from_qname': getattr(rel.fromModelObject, 'qname', None),
                                    'to_qname': getattr(rel.toModelObject, 'qname', None),
                                    'arcrole': arcrole,
                                    'relationship': rel
                                }
                                anchoring_relationships.append(rel_data)

        except Exception as e:
            self.logger.warning(f"Failed to extract anchoring relationships: {e}")

        return anchoring_relationships

    def _analyze_anchoring_defects(self,
                                 extension_concepts: List[Dict[str, Any]],
                                 anchoring_relationships: List[Dict[str, Any]],
                                 context: DetectorContext) -> List[Dict[str, Any]]:
        """Analyze extension concepts for anchoring defects."""
        defects = []

        # Build anchoring map for analysis
        anchoring_map = {}
        for rel in anchoring_relationships:
            from_qname = rel.get('from_qname')
            to_qname = rel.get('to_qname')
            if from_qname and to_qname:
                if from_qname not in anchoring_map:
                    anchoring_map[from_qname] = []
                anchoring_map[from_qname].append(rel)

        # Analyze each extension concept
        for ext_concept_data in extension_concepts:
            concept = ext_concept_data['concept']
            qname = ext_concept_data['qname']
            clark_notation = ext_concept_data['clark_notation']

            # Check for various anchoring defects
            concept_defects = []

            # 1. Check if concept is unanchored
            if qname not in anchoring_map:
                concept_defects.append('unanchored')

            # 2. Analyze existing anchoring relationships
            if qname in anchoring_map:
                for rel in anchoring_map[qname]:
                    anchor_concept = rel.get('to_concept')
                    if anchor_concept:
                        # Check if anchored to abstract concept
                        if getattr(anchor_concept, 'abstract', False):
                            concept_defects.append('anchor_target_abstract')

                        # Check period type mismatch
                        ext_period_type = ext_concept_data.get('period_type')
                        anchor_period_type = getattr(anchor_concept, 'periodType', None)
                        if (ext_period_type and anchor_period_type and
                            ext_period_type != anchor_period_type):
                            concept_defects.append('period_type_mismatch')

                        # Check data type mismatch (basic check)
                        ext_type = ext_concept_data.get('type')
                        anchor_type = getattr(anchor_concept, 'type', None)
                        if (ext_type and anchor_type and
                            str(ext_type) != str(anchor_type)):
                            concept_defects.append('type_mismatch')

                        # Check if anchored to another extension concept
                        if self._is_extension_concept(anchor_concept):
                            concept_defects.append('anchor_to_extension')

            # Record defects for this concept
            if concept_defects:
                # Filter to schema-supported issue codes
                allowed_codes = {
                    'unanchored',
                    'anchor_target_abstract',
                    'period_type_mismatch',
                    'type_mismatch',
                    'anchor_to_extension',
                }
                concept_defects = [code for code in concept_defects if code in allowed_codes]
                if not concept_defects:
                    continue
                defect_data = {
                    'extension_concept': concept,
                    'extension_qname': qname,
                    'clark_notation': clark_notation,
                    'issue_codes': list(set(concept_defects)),  # Remove duplicates
                    'anchoring_relationships': anchoring_map.get(qname, [])
                }
                defects.append(defect_data)

        return defects

    def _create_finding(self, defects: List[Dict[str, Any]], context: DetectorContext) -> DetectorFinding:
        """Create a finding from anchoring defects."""

        # Generate finding ID
        finding_id = generate_finding_id(context.accession, self.pattern_id)

        # Create instances for each defect
        instances = []
        for defect in defects:
            instance = self._create_instance(defect, context)
            if instance:
                instances.append(instance)

        # Apply deterministic ordering and truncation
        finding_summary = create_finding_summary(
            [inst.__dict__ for inst in instances],
            instance_limit=100,
            example_limit=10,
            include_examples=False  # Schema compliance
        )

        # Create finding with proper structure
        finding = DetectorFinding(
            finding_id=finding_id,
            pattern_id=self.pattern_id,
            pattern_name=self.pattern_name,
            alert_eligible=self.alert_eligible,
            status="detected",
            human_review_required=True,
            break_triggers=self.get_break_triggers(),
            rule_basis=self.load_rule_basis(),
            instances=[DetectorInstance(**inst) for inst in finding_summary['instances']],
            mechanism="Extension concepts with improper anchoring create validation ambiguity and may cause filing rejection when taxonomy or validation rules change",
            why_not_fatal_yet="Current validation may accept these patterns but tighter anchoring enforcement or taxonomy updates could surface them as errors"
        )

        return finding

    def _create_instance(self, defect_data: Dict[str, Any], context: DetectorContext) -> Optional[DetectorInstance]:
        """Create a detector instance from an anchoring defect."""
        try:
            issue_codes = defect_data['issue_codes']

            if not issue_codes:
                return None

            # Generate canonical signature for this defect
            signature_bytes = canonical_signature_p002(
                extension_concept_clark=defect_data['clark_notation'],
                issue_codes=issue_codes
            )

            # Generate instance ID from signature
            instance_id = instance_id_from_signature(signature_bytes)

            # Extract anchor information for evidence
            anchors = []
            for rel in defect_data.get('anchoring_relationships', []):
                anchor_concept = rel.get('to_concept')
                if anchor_concept and getattr(anchor_concept, 'qname', None):
                    anchors.append({
                        'arcrole': rel.get('arcrole', ''),
                        'target_concept': qname_object(anchor_concept.qname),
                    })
            anchors = sorted(anchors, key=lambda a: (a.get('arcrole', ''), a.get('target_concept', {}).get('clark', '')))

            # Find example facts using this extension concept
            used_fact_examples = self._fact_examples_for_concept(context.xbrl_model, defect_data['extension_qname'])
            if not used_fact_examples:
                return None

            # Build instance data
            instance_data: Dict[str, Any] = {
                'extension_concept': qname_object(defect_data['extension_qname']),
                'issue_codes': issue_codes,
                'used_fact_examples': used_fact_examples,
            }
            if anchors:
                instance_data['anchors'] = anchors

            return DetectorInstance(
                instance_id=instance_id,
                kind="extension_anchoring_issue",
                primary=True,
                data=instance_data
            )

        except Exception as e:
            self.logger.error(f"Failed to create P002 instance: {e}")
            return None

    def get_break_triggers(self) -> List[Dict[str, str]]:
        """Get break triggers for P002 pattern."""
        return [
            {
                'id': 'XEW-BT003',
                'summary': 'Taxonomy Refresh - Taxonomy updates trigger stricter validation rules'
            },
            {
                'id': 'XEW-BT002',
                'summary': 'Disclosure Reshaping - Table structure changes surface latent anchoring issues'
            },
            {
                'id': 'XEW-BT004',
                'summary': 'Validator Tightening - Rule enforcement changes surface tolerated anchoring errors'
            }
        ]

    def load_rule_basis(self) -> List[Dict[str, Any]]:
        """Load rule basis for P002 pattern from registry."""
        from .registry import get_registry

        try:
            registry = get_registry()
            rule_basis = registry.get_rule_basis(self.pattern_id)

            if rule_basis:
                # Flatten the citations from all rules for this pattern
                citations = []
                for rule in rule_basis:
                    citations.extend(rule.get('citations', []))
                return citations
            else:
                # Fallback to embedded rule basis if registry is not loaded
                return [
                    {
                        'source': 'SEC_EFM',
                        'citation': 'Section 6.14.3 - Extension Schema Requirements',
                        'url': 'https://www.sec.gov/structureddata/efm',
                        'retrieved_at': '2026-01-31T14:32:00Z',
                        'sha256': 'placeholder_to_be_updated_with_real_hash',
                        'notes': 'Extension concepts must be properly anchored to standard taxonomy concepts with appropriate type and period alignment.'
                    }
                ]

        except Exception as e:
            self.logger.warning(f"Failed to load rule basis from registry: {e}")
            return []

    def compute_canonical_signature(self, **kwargs) -> str:
        """Compute canonical signature for P002 instance ID generation."""
        # Extract required parameters for P002 signature
        extension_concept_clark = kwargs.get('extension_concept_clark')
        defect_code = kwargs.get('defect_code')
        anchor_concept_clark = kwargs.get('anchor_concept_clark')

        if not all(x is not None for x in [extension_concept_clark, defect_code]):
            raise ValueError("Missing required parameters for P002 canonical signature")

        # Generate canonical signature using util function
        signature_bytes = canonical_signature_p002(
            extension_concept_clark=extension_concept_clark,
            defect_code=defect_code,
            anchor_concept_clark=anchor_concept_clark
        )

        return signature_bytes.hex()

    def _fact_ref_from_fact(self, fact: Any) -> Optional[Dict[str, Any]]:
        """Build a schema-compatible fact_ref from an Arelle fact."""
        context = getattr(fact, 'context', None)
        if not context:
            return None
        context_ref = getattr(context, 'id', None) or getattr(context, 'contextID', None)
        if not context_ref:
            return None

        ref: Dict[str, Any] = {
            'concept': qname_object(fact.qname),
            'context_ref': str(context_ref),
        }

        unit = getattr(fact, 'unit', None)
        if unit is not None:
            unit_ref = getattr(unit, 'id', None)
            if unit_ref:
                ref['unit_ref'] = str(unit_ref)

        value = getattr(fact, 'value', None)
        if value is not None:
            ref['value'] = str(value)

        is_nil = getattr(fact, 'isNil', None)
        if is_nil is not None:
            ref['is_nil'] = bool(is_nil)

        decimals = getattr(fact, 'decimals', None)
        if decimals is not None:
            ref['decimals'] = str(decimals)

        precision = getattr(fact, 'precision', None)
        if precision is not None:
            ref['precision'] = str(precision)

        return ref

    def _fact_examples_for_concept(self, xbrl_model: Any, concept_qname: Any, limit: int = 3) -> List[Dict[str, Any]]:
        """Collect deterministic fact_ref examples for a given concept."""
        examples: List[Dict[str, Any]] = []
        for fact in getattr(xbrl_model, 'facts', []):
            if getattr(fact, 'qname', None) == concept_qname:
                ref = self._fact_ref_from_fact(fact)
                if ref:
                    examples.append(ref)

        examples.sort(key=lambda r: (r.get('context_ref', ''), r.get('value', '')))
        return examples[:limit]
