"""
XEW-P001: Duplicate Facts With Equivalent Context/Unit

Detects facts that share the same concept, context signature, and unit but may have
conflicting values. This represents objective structural errors in XBRL filings.
"""

from typing import Dict, List, Any, Set, Tuple, Optional
from collections import defaultdict
import logging

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..util import (
    canonical_signature_p001,
    normalize_unit,
    normalize_fact_value,
    values_conflicting,
    period_signature,
    dimension_signature,
    generate_finding_id,
    generate_instance_id,
    create_finding_summary,
    qname_to_clark,
    instance_id_from_signature,
    canonicalize_typed_dimension_member,
    get_unit_measures_clark
)

logger = logging.getLogger(__name__)


class DuplicateFactsDetector(BaseDetector):
    """Detector for XEW-P001: Duplicate Facts With Equivalent Context/Unit."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P001"

    @property
    def pattern_name(self) -> str:
        return "Duplicate Facts With Equivalent Context/Unit"

    @property
    def alert_eligible(self) -> bool:
        return True  # P001 is highest priority, always alert-eligible

    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        """
        Detect duplicate facts with equivalent context and unit.

        Args:
            context: Detection context with XBRL model and metadata

        Returns:
            List of findings (empty if no duplicates found)
        """
        self.logger.info("Running XEW-P001 duplicate facts detection")

        try:
            # Extract facts from XBRL model
            facts = self._extract_facts(context.xbrl_model)
            self.logger.debug(f"Extracted {len(facts)} facts for analysis")

            # Group facts by canonical signature
            fact_groups = self._group_facts_by_signature(facts, context)
            self.logger.debug(f"Grouped facts into {len(fact_groups)} signature groups")

            # Identify duplicate groups (more than one fact per signature)
            duplicate_groups = {sig: facts for sig, facts in fact_groups.items() if len(facts) > 1}
            self.logger.debug(f"Found {len(duplicate_groups)} groups with duplicates")

            if not duplicate_groups:
                self.logger.info("No duplicate facts detected")
                return []

            # Create finding for duplicate facts
            finding = self._create_finding(duplicate_groups, context)
            self.logger.info(f"Created finding with {len(finding.instances)} instances")

            return [finding]

        except Exception as e:
            self.logger.error(f"Error during P001 detection: {e}")
            raise

    def _extract_facts(self, xbrl_model) -> List[Dict[str, Any]]:
        """Extract relevant facts from XBRL model for duplicate analysis."""
        facts = []

        # Extract facts from Arelle model
        # Note: This is a simplified extraction - production would use full Arelle API
        for fact in getattr(xbrl_model, 'facts', []):
            try:
                fact_data = {
                    'concept': fact.concept,
                    'qname': fact.qname,
                    'value': fact.value,
                    'context': fact.context,
                    'unit': getattr(fact, 'unit', None),
                    'is_numeric': getattr(fact, 'isNumeric', False),
                    'arelle_fact': fact  # Keep reference for additional analysis
                }
                facts.append(fact_data)
            except Exception as e:
                self.logger.warning(f"Failed to extract fact data: {e}")
                continue

        return facts

    def _group_facts_by_signature(self, facts: List[Dict[str, Any]], context: DetectorContext) -> Dict[bytes, List[Dict[str, Any]]]:
        """Group facts by their canonical signature for duplicate detection."""
        fact_groups = defaultdict(list)

        for fact in facts:
            try:
                signature = self._compute_fact_signature(fact, context)
                if signature:
                    fact_groups[signature].append(fact)
            except Exception as e:
                self.logger.warning(f"Failed to compute signature for fact: {e}")
                continue

        return dict(fact_groups)

    def _compute_fact_signature(self, fact: Dict[str, Any], context: DetectorContext) -> Optional[bytes]:
        """Compute canonical signature for a fact."""
        try:
            # Extract QName (concept)
            qname = fact['qname']
            concept_clark = qname_to_clark(qname)

            # Extract context information
            fact_context = fact['context']
            if not fact_context:
                return None

            # Entity information
            entity_scheme = getattr(fact_context.entityIdentifier, 'scheme', '')
            entity_identifier = getattr(fact_context.entityIdentifier, 'value', '')

            # Period signature
            if hasattr(fact_context, 'isInstantPeriod') and fact_context.isInstantPeriod:
                period_sig = period_signature("instant", instant=str(fact_context.instantDate))
            elif hasattr(fact_context, 'isStartEndPeriod') and fact_context.isStartEndPeriod:
                period_sig = period_signature("duration",
                                            start=str(fact_context.startDate),
                                            end=str(fact_context.endDate))
            else:
                self.logger.warning(f"Unknown period type for fact context: {fact_context}")
                return None

            # Dimension signature
            dimensions = []
            if hasattr(fact_context, 'qnameDims'):
                for dim_qname, member_obj in fact_context.qnameDims.items():
                    dim_clark = qname_to_clark(dim_qname)

                    # Handle explicit vs typed dimensions
                    if hasattr(member_obj, 'isExplicit') and member_obj.isExplicit:
                        member_clark = qname_to_clark(member_obj.member)
                        dimensions.append((dim_clark, member_clark))
                    elif hasattr(member_obj, 'isTyped') and member_obj.isTyped:
                        # Use typed dimension canonicalization
                        typed_value = str(member_obj.typedMember)
                        member_canonical = canonicalize_typed_dimension_member(typed_value)
                        dimensions.append((dim_clark, member_canonical))

            dim_sig = dimension_signature(dimensions)

            # Unit normalization
            unit = None
            if fact['unit'] and fact['is_numeric']:
                # Extract unit measures and normalize
                try:
                    unit_measures = get_unit_measures_clark(fact['unit'])
                    unit = normalize_unit(measures=unit_measures)
                except Exception as e:
                    self.logger.warning(f"Failed to normalize unit: {e}")
                    # Fallback to unit ID
                    unit_id = getattr(fact['unit'], 'id', None)
                    unit = normalize_unit(unit_ref=unit_id) if unit_id else None

            # Generate canonical signature
            signature_bytes = canonical_signature_p001(
                concept_clark=concept_clark,
                entity_scheme=entity_scheme,
                entity_identifier=entity_identifier,
                period_sig=period_sig,
                dim_sig=dim_sig,
                unit=unit
            )

            return signature_bytes

        except Exception as e:
            self.logger.error(f"Failed to compute fact signature: {e}")
            return None

    def _create_finding(self, duplicate_groups: Dict[bytes, List[Dict[str, Any]]], context: DetectorContext) -> DetectorFinding:
        """Create a finding from duplicate fact groups."""

        # Generate finding ID
        finding_id = generate_finding_id(context.accession, self.pattern_id)

        # Create instances for each duplicate group
        instances = []
        for signature_bytes, facts in duplicate_groups.items():
            instance = self._create_instance(signature_bytes, facts)
            if instance:
                instances.append(instance)

        # Apply deterministic ordering and truncation
        finding_summary = create_finding_summary(
            [inst.__dict__ for inst in instances],
            instance_limit=100,  # Configurable limit
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
            mechanism="Facts with identical concept, context signature, and unit but potentially different values indicate data inconsistency or submission errors",
            why_not_fatal_yet="EDGAR validation may not catch context-equivalent duplicates if they use different context IDs or have subtle unit variations"
        )

        return finding

    def _create_instance(self, signature_bytes: bytes, facts: List[Dict[str, Any]]) -> Optional[DetectorInstance]:
        """Create a detector instance from a group of duplicate facts."""
        try:
            # Generate instance ID from signature
            instance_id = instance_id_from_signature(signature_bytes)

            # Extract representative fact information
            first_fact = facts[0]
            concept_clark = qname_to_clark(first_fact['qname'])

            # Normalize fact values and detect conflicts
            normalized_values = []
            raw_values = []
            for fact in facts:
                raw_value = str(fact['value']) if fact['value'] is not None else None
                normalized_value = normalize_fact_value(raw_value, is_numeric=fact['is_numeric'])

                normalized_values.append(normalized_value)
                raw_values.append(raw_value)

            # Check for value conflicts
            has_conflicts = False
            if len(set(str(v) for v in normalized_values if v is not None)) > 1:
                has_conflicts = True

            # Build instance data
            instance_data = {
                'concept_clark': concept_clark,
                'duplicate_count': len(facts),
                'raw_values': raw_values,
                'normalized_values': [str(v) for v in normalized_values],
                'has_value_conflicts': has_conflicts,
                'context_signature': signature_bytes.hex(),  # For debugging/analysis
                'unit_signature': '',  # Could add normalized unit info here
            }

            return DetectorInstance(
                instance_id=instance_id,
                kind="duplicate_fact_set",
                primary=True,  # All P001 instances are primary
                data=instance_data
            )

        except Exception as e:
            self.logger.error(f"Failed to create instance: {e}")
            return None

    def get_break_triggers(self) -> List[Dict[str, str]]:
        """Get break triggers for P001 pattern."""
        return [
            {
                'id': 'XEW-BT001',
                'summary': 'Period Coincidence - Period changes expose hidden duplicates'
            },
            {
                'id': 'XEW-BT004',
                'summary': 'Validator Tightening - Rule enforcement changes surface tolerated errors'
            }
        ]

    def load_rule_basis(self) -> List[Dict[str, Any]]:
        """Load rule basis for P001 pattern from registry."""
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
                        'source': 'XBRL Specification 2.1',
                        'title': 'Section 4.7.2 - Fact Uniqueness',
                        'url': 'https://www.xbrl.org/specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31+corrected-errata-2013-02-20.html',
                        'retrieved_at': '2026-01-31T15:38:00Z',
                        'sha256': 'placeholder_to_be_updated_with_real_hash',
                        'summary': 'Facts with identical concept QName, context, and unit (when applicable) represent duplicate assertions and create semantic ambiguity.'
                    }
                ]

        except Exception as e:
            self.logger.warning(f"Failed to load rule basis from registry: {e}")
            return []

    def compute_canonical_signature(self, **kwargs) -> str:
        """Compute canonical signature for P001 instance ID generation."""
        # Extract required parameters for P001 signature
        concept_clark = kwargs.get('concept_clark')
        entity_scheme = kwargs.get('entity_scheme')
        entity_identifier = kwargs.get('entity_identifier')
        period_sig = kwargs.get('period_sig')
        dim_sig = kwargs.get('dim_sig', b'')
        unit = kwargs.get('unit')

        if not all(x is not None for x in [concept_clark, entity_scheme, entity_identifier, period_sig]):
            raise ValueError("Missing required parameters for P001 canonical signature")

        # Generate canonical signature using util function
        signature_bytes = canonical_signature_p001(
            concept_clark=concept_clark,
            entity_scheme=entity_scheme,
            entity_identifier=entity_identifier,
            period_sig=period_sig,
            dim_sig=dim_sig,
            unit=unit
        )

        return signature_bytes.hex()