"""
XEW-P001: Duplicate Facts With Equivalent Context/Unit

Detects facts that share the same concept, context signature, and unit but may have
conflicting values. This represents objective structural errors in XBRL filings.
"""

from __future__ import annotations

from typing import Dict, List, Any, Set, Tuple, Optional
from collections import defaultdict
from decimal import Decimal
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
    qname_object,
    instance_id_from_signature,
    canonicalize_typed_dimension_member,
    get_unit_measures_clark
)

logger = logging.getLogger(__name__)


def _attr_bool(value: object) -> bool:
    if value is None:
        return False
    if callable(value):
        try:
            return bool(value())
        except TypeError:
            return bool(value)
    return bool(value)


def _date_iso(value: object) -> str:
    if value is None:
        return ""
    date_value = getattr(value, "date", None)
    if callable(date_value):
        value = date_value()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


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

            # Create finding for duplicate facts only when there are value conflicts
            finding = self._create_finding(duplicate_groups, context)
            if finding is None:
                self.logger.info(
                    "Duplicate facts detected but no value conflicts under selected mode; skipping P001 finding"
                )
                return []

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
                unit = getattr(fact, 'unit', None)
                is_numeric = _attr_bool(getattr(fact, 'isNumeric', None)) or unit is not None
                fact_data = {
                    'concept': fact.concept,
                    'qname': fact.qname,
                    'value': fact.value,
                    'context': fact.context,
                    'unit': unit,
                    'is_numeric': bool(is_numeric),
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
            if fact_context is None:
                return None

            # Entity information
            entity_scheme, entity_identifier = self._extract_entity_identifier(fact_context)

            # Period signature
            if _attr_bool(getattr(fact_context, "isInstantPeriod", None)):
                instant = getattr(fact_context, "instantDate", None) or getattr(fact_context, "instantDatetime", None)
                period_sig = period_signature("instant", instant=_date_iso(instant))
            elif _attr_bool(getattr(fact_context, "isStartEndPeriod", None)):
                start = getattr(fact_context, "startDate", None) or getattr(fact_context, "startDatetime", None)
                end = getattr(fact_context, "endDate", None) or getattr(fact_context, "endDatetime", None)
                period_sig = period_signature("duration",
                                            start=_date_iso(start),
                                            end=_date_iso(end))
            else:
                self.logger.warning(f"Unknown period type for fact context: {fact_context}")
                return None

            # Dimension signature
            dimensions = []
            if hasattr(fact_context, 'qnameDims'):
                for dim_qname, member_obj in fact_context.qnameDims.items():
                    dim_clark = qname_to_clark(dim_qname)

                    # Handle explicit vs typed dimensions
                    if _attr_bool(getattr(member_obj, "isExplicit", None)):
                        member = getattr(member_obj, "member", None)
                        member_qname = getattr(member, "qname", None) if member is not None else None
                        if member_qname is None:
                            member_qname = getattr(member_obj, "memberQname", None)
                        if member_qname is None:
                            continue
                        dimensions.append((dim_clark, qname_to_clark(member_qname)))
                    elif _attr_bool(getattr(member_obj, "isTyped", None)):
                        # Use typed dimension canonicalization
                        typed_member = getattr(member_obj, "typedMember", None)
                        if typed_member is None:
                            continue
                        typed_value = str(typed_member)
                        member_canonical = canonicalize_typed_dimension_member(typed_value)
                        dimensions.append((dim_clark, member_canonical))

            dim_sig = dimension_signature(dimensions)

            # Unit normalization
            unit = None
            unit_obj = fact.get('unit')
            if unit_obj is not None and fact.get('is_numeric'):
                # Extract unit measures and normalize
                try:
                    unit_measures = get_unit_measures_clark(unit_obj)
                    unit = normalize_unit(measures=unit_measures)
                except Exception as e:
                    self.logger.warning(f"Failed to normalize unit: {e}")
                    # Fallback to unit ID
                    unit_id = getattr(unit_obj, 'id', None)
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

    def _extract_entity_identifier(self, fact_context) -> Tuple[str, str]:
        """Extract (scheme, identifier) from an Arelle context."""
        entity = getattr(fact_context, 'entityIdentifier', None)
        if entity is None:
            return "", ""

        if isinstance(entity, (tuple, list)) and len(entity) >= 2:
            return str(entity[0]), str(entity[1])

        if isinstance(entity, dict):
            scheme = entity.get('scheme') or entity.get('identifierScheme') or ''
            identifier = entity.get('value') or entity.get('identifier') or ''
            return str(scheme), str(identifier)

        scheme = getattr(entity, 'scheme', None)
        identifier = getattr(entity, 'value', None) or getattr(entity, 'identifier', None)
        return str(scheme or ""), str(identifier or "")

    def _p001_conflict_mode(self, context: DetectorContext) -> str:
        """Return P001 value conflict mode ('rounded' or 'strict')."""
        config = getattr(context, "config", None)
        if not isinstance(config, dict):
            return "rounded"
        raw = config.get("p001_conflict_mode")
        if raw is None:
            return "rounded"
        mode = str(raw).strip().lower()
        if mode == "strict":
            return "strict"
        return "rounded"

    def _parse_xbrl_int_attr(self, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, bool):
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.upper() in {"INF", "INFINITY"}:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def _numeric_rounding_interval(
        self,
        value: Decimal,
        *,
        decimals: object | None,
        precision: object | None,
    ) -> tuple[Decimal, Decimal]:
        decimals_int = self._parse_xbrl_int_attr(decimals)
        if decimals_int is not None:
            unit = Decimal(10) ** (-decimals_int)
            tol = Decimal("0.5") * unit
            return (value - tol, value + tol)

        precision_int = self._parse_xbrl_int_attr(precision)
        if precision_int is not None and precision_int > 0 and value != 0:
            unit = Decimal(10) ** (abs(value).adjusted() - precision_int + 1)
            tol = Decimal("0.5") * unit
            return (value - tol, value + tol)

        return (value, value)

    def _rounded_conflicts(self, facts: List[Dict[str, Any]]) -> bool:
        """Return True if values are inconsistent beyond XBRL rounding tolerance."""
        items: list[tuple[Decimal | None, object | None, object | None]] = []
        saw_non_nil = False
        saw_nil = False

        for fact in facts:
            raw_value = str(fact["value"]) if fact.get("value") is not None else None
            try:
                normalized = normalize_fact_value(raw_value, is_numeric=bool(fact.get("is_numeric")))
            except Exception:
                # Fall back to strict mode for unparsable numeric values.
                normalized = raw_value

            if not isinstance(normalized, Decimal) and normalized is not None:
                # Non-decimal (e.g., string) values are compared strictly.
                return self._strict_conflicts(facts)

            if normalized is None:
                saw_nil = True
            else:
                saw_non_nil = True

            arelle_fact = fact.get("arelle_fact")
            decimals = getattr(arelle_fact, "decimals", None) if arelle_fact is not None else None
            precision = getattr(arelle_fact, "precision", None) if arelle_fact is not None else None
            items.append((normalized, decimals, precision))

        # Nil vs non-nil is a conflict.
        if saw_nil and saw_non_nil:
            return True

        # All nil => no value conflict.
        if not saw_non_nil:
            return False

        intervals: list[tuple[Decimal, Decimal]] = []
        for value, decimals, precision in items:
            if value is None:
                continue
            intervals.append(self._numeric_rounding_interval(value, decimals=decimals, precision=precision))

        if not intervals:
            return False

        lo = max(interval[0] for interval in intervals)
        hi = min(interval[1] for interval in intervals)
        return lo > hi

    def _strict_conflicts(self, facts: List[Dict[str, Any]]) -> bool:
        normalized_values = []
        for fact in facts:
            raw_value = str(fact['value']) if fact['value'] is not None else None
            try:
                normalized_values.append(normalize_fact_value(raw_value, is_numeric=fact['is_numeric']))
            except Exception:
                normalized_values.append(raw_value)

        if len(normalized_values) < 2:
            return False
        base = normalized_values[0]
        return any(values_conflicting(base, v) for v in normalized_values[1:])

    def _fact_ref_from_fact(self, fact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build a schema-compatible fact_ref from an Arelle fact."""
        fact_context = fact.get('context')
        if fact_context is None:
            return None
        context_ref = getattr(fact_context, 'id', None) or getattr(fact_context, 'contextID', None)
        if not context_ref:
            return None

        ref: Dict[str, Any] = {
            'concept': qname_object(fact['qname']),
            'context_ref': str(context_ref),
        }

        unit = fact.get('unit')
        if unit is not None:
            unit_ref = getattr(unit, 'id', None)
            if unit_ref:
                ref['unit_ref'] = str(unit_ref)

        value = fact.get('value')
        if value is not None:
            ref['value'] = str(value)

        arelle_fact = fact.get('arelle_fact')
        if arelle_fact is not None:
            is_nil = getattr(arelle_fact, 'isNil', None)
            if is_nil is not None:
                ref['is_nil'] = bool(is_nil)
            decimals = getattr(arelle_fact, 'decimals', None)
            if decimals is not None:
                ref['decimals'] = str(decimals)
            precision = getattr(arelle_fact, 'precision', None)
            if precision is not None:
                ref['precision'] = str(precision)

        return ref

    def _create_finding(
        self, duplicate_groups: Dict[bytes, List[Dict[str, Any]]], context: DetectorContext
    ) -> DetectorFinding | None:
        """Create a finding from duplicate fact groups (conflicts only)."""

        # Generate finding ID
        finding_id = generate_finding_id(context.accession, self.pattern_id)

        # Create instances for each duplicate group
        instances = []
        for signature_bytes, facts in duplicate_groups.items():
            instance = self._create_instance(signature_bytes, facts, context)
            if instance:
                instances.append(instance)

        # Conflicts-only posture: if no value conflicts, do not emit a finding.
        if not instances:
            return None

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

    def _create_instance(self, signature_bytes: bytes, facts: List[Dict[str, Any]], context: DetectorContext) -> Optional[DetectorInstance]:
        """Create a detector instance from a group of duplicate facts."""
        try:
            # Generate instance ID from signature
            instance_id = instance_id_from_signature(signature_bytes)

            # Extract representative fact information
            first_fact = facts[0]

            conflict_mode = self._p001_conflict_mode(context)
            if conflict_mode == "strict":
                has_conflicts = self._strict_conflicts(facts)
            else:
                has_conflicts = self._rounded_conflicts(facts)

            # Conflicts-only posture: skip non-conflicting duplicates.
            if not has_conflicts:
                return None

            # Build fact refs (schema-compatible)
            fact_refs = []
            for fact in facts:
                ref = self._fact_ref_from_fact(fact)
                if ref:
                    fact_refs.append(ref)
            if len(fact_refs) < 2:
                return None

            # Build instance data
            issue_codes = ["duplicate_fact"]
            if has_conflicts:
                issue_codes.append("value_conflict")

            instance_data: Dict[str, Any] = {
                'concept': qname_object(first_fact['qname']),
                'context_ref': fact_refs[0]['context_ref'],
                'fact_count': len(fact_refs),
                'facts': fact_refs,
                'issue_codes': issue_codes,
                'value_conflict': has_conflicts,
            }
            unit_ref = fact_refs[0].get('unit_ref')
            if unit_ref:
                instance_data['unit_ref'] = unit_ref

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
                        'source': 'XBRL_SPEC',
                        'citation': 'Section 4.7.2 - Fact Uniqueness',
                        'url': 'https://www.xbrl.org/specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31+corrected-errata-2013-02-20.html',
                        'retrieved_at': '2026-01-31T15:38:00Z',
                        'sha256': 'placeholder_to_be_updated_with_real_hash',
                        'notes': 'Facts with identical concept QName, context, and unit (when applicable) represent duplicate assertions and create semantic ambiguity.'
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
