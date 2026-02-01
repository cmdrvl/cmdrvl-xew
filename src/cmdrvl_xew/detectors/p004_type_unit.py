"""
XEW-P004: Type/Unit/Numeric Checks

Detects objective violations in datatype, unit, or numeric attributes.
Focuses on clear rule-based correctness issues with pinned rule basis.
"""

from typing import Dict, List, Any, Set, Tuple, Optional
from decimal import Decimal, InvalidOperation
import logging
import re

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..util import (
    canonical_signature_p004,
    normalize_unit,
    normalize_numeric_value,
    get_unit_measures_clark,
    generate_finding_id,
    generate_instance_id,
    create_finding_summary,
    qname_to_clark,
    qname_object,
    instance_id_from_signature
)

logger = logging.getLogger(__name__)


# Issue codes for P004 type/unit/numeric violations
P004_ISSUE_CODES = {
    'decimals_precision_conflict': 'Both decimals and precision specified (discouraged)',
    'invalid_decimals': 'Decimals attribute invalid for numeric concept type',
    'invalid_precision': 'Precision attribute invalid for numeric concept type',
    'missing_unit': 'Numeric fact missing required unit attribute',
    'non_numeric_with_unit': 'Unit attribute present on non-numeric fact',
    'unit_incompatible': 'Unit type incompatible with concept data type',
}


class TypeUnitNumericDetector(BaseDetector):
    """Detector for XEW-P004: Type/Unit/Numeric Checks."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P004"

    @property
    def pattern_name(self) -> str:
        return "Type/Unit/Numeric Attribute Violations"

    @property
    def alert_eligible(self) -> bool:
        return True  # P004 is v1 shipping set, alert-eligible

    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        """
        Detect type, unit, and numeric attribute violations.

        Args:
            context: Detection context with XBRL model and metadata

        Returns:
            List of findings (empty if no violations found)
        """
        self.logger.info("Running XEW-P004 type/unit/numeric checks detection")

        try:
            # Extract facts with their type and unit information
            facts = self._extract_facts_with_attributes(context.xbrl_model)
            self.logger.debug(f"Extracted {len(facts)} facts for P004 analysis")

            # Analyze each fact for type/unit/numeric violations
            violations = []
            for fact in facts:
                fact_violations = self._analyze_fact_violations(fact)
                if fact_violations:
                    violations.extend(fact_violations)

            self.logger.debug(f"Detected {len(violations)} type/unit/numeric violations")

            if not violations:
                self.logger.info("No type/unit/numeric violations detected")
                return []

            # Create finding for violations
            finding = self._create_finding(violations, context)
            self.logger.info(f"Created finding with {len(finding.instances)} instances")

            return [finding]

        except Exception as e:
            self.logger.error(f"Error during P004 detection: {e}")
            raise

    def _extract_facts_with_attributes(self, xbrl_model) -> List[Dict[str, Any]]:
        """Extract facts with their type, unit, and numeric attributes."""
        facts = []

        try:
            for fact in getattr(xbrl_model, 'facts', []):
                fact_data = {
                    'fact': fact,
                    'qname': fact.qname,
                    'clark_notation': qname_to_clark(fact.qname),
                    'value': fact.value,
                    'concept': fact.concept,
                    'context': fact.context,
                    'unit': getattr(fact, 'unit', None),
                    'is_numeric': getattr(fact, 'isNumeric', False),

                    # Numeric attributes
                    'decimals': getattr(fact, 'decimals', None),
                    'precision': getattr(fact, 'precision', None),

                    # Type information
                    'type_qname': getattr(fact.concept, 'type', None) if fact.concept else None,
                    'period_type': getattr(fact.concept, 'periodType', None) if fact.concept else None,

                    # Context and unit references
                    'context_ref': getattr(fact.context, 'id', None) if fact.context else None,
                    'unit_ref': getattr(fact.unit, 'id', None) if fact.unit else None,
                }
                facts.append(fact_data)

        except Exception as e:
            self.logger.warning(f"Failed to extract facts with attributes: {e}")

        return facts

    def _analyze_fact_violations(self, fact_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze a single fact for type/unit/numeric violations."""
        violations = []

        qname = fact_data['qname']
        clark_notation = fact_data['clark_notation']
        is_numeric = fact_data['is_numeric']
        decimals = fact_data['decimals']
        precision = fact_data['precision']
        unit = fact_data['unit']
        concept = fact_data['concept']
        value = fact_data['value']

        # Check numeric attribute violations
        if is_numeric:
            # Check for missing unit on numeric fact
            if not unit:
                violations.append({
                    'fact_data': fact_data,
                    'issue_code': 'missing_unit_numeric',
                    'description': f"Numeric fact {clark_notation} missing unit attribute"
                })

            # Check decimals attribute issues
            if decimals is not None:
                try:
                    decimals_val = int(decimals)
                    if decimals_val < 0:
                        violations.append({
                            'fact_data': fact_data,
                            'issue_code': 'negative_decimals',
                            'description': f"Negative decimals attribute: {decimals_val}"
                        })
                except (ValueError, TypeError):
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'invalid_decimals',
                        'description': f"Invalid decimals attribute: {decimals}"
                    })

            # Check precision attribute issues
            if precision is not None:
                try:
                    precision_val = int(precision)
                    if precision_val > 20:  # Excessive precision threshold
                        violations.append({
                            'fact_data': fact_data,
                            'issue_code': 'excessive_precision',
                            'description': f"Excessively high precision: {precision_val}"
                        })
                except (ValueError, TypeError):
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'invalid_precision',
                        'description': f"Invalid precision attribute: {precision}"
                    })

            # Check for both decimals and precision (discouraged)
            if decimals is not None and precision is not None:
                violations.append({
                    'fact_data': fact_data,
                    'issue_code': 'decimals_precision_conflict',
                    'description': f"Both decimals ({decimals}) and precision ({precision}) specified"
                })

            # Check unit type compatibility
            if unit and concept:
                unit_violations = self._check_unit_type_compatibility(fact_data)
                violations.extend(unit_violations)

        else:
            # Non-numeric fact with unit attribute (discouraged)
            if unit:
                violations.append({
                    'fact_data': fact_data,
                    'issue_code': 'unit_on_non_numeric',
                    'description': f"Non-numeric fact {clark_notation} has unit attribute"
                })

        # Check data type constraint violations
        if concept and value is not None:
            type_violations = self._check_type_constraints(fact_data)
            violations.extend(type_violations)

        # Map internal issue codes to v1 catalog codes (drop unsupported)
        issue_code_map = {
            'missing_unit_numeric': 'missing_unit',
            'negative_decimals': 'invalid_decimals',
            'invalid_decimals': 'invalid_decimals',
            'excessive_precision': 'invalid_precision',
            'invalid_precision': 'invalid_precision',
            'decimals_precision_conflict': 'decimals_precision_conflict',
            'unit_on_non_numeric': 'non_numeric_with_unit',
            'unit_type_mismatch': 'unit_incompatible',
            'type_constraint_violation': None,
        }

        mapped: List[Dict[str, Any]] = []
        for violation in violations:
            code = issue_code_map.get(violation.get('issue_code'))
            if not code:
                continue
            mapped_violation = dict(violation)
            mapped_violation['issue_code'] = code
            mapped.append(mapped_violation)

        return mapped

    def _check_unit_type_compatibility(self, fact_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check if unit type is compatible with concept data type."""
        violations = []

        unit = fact_data['unit']
        concept = fact_data['concept']
        clark_notation = fact_data['clark_notation']

        try:
            # Extract unit measures
            unit_measures = get_unit_measures_clark(unit)

            # Get concept type information
            concept_type = getattr(concept, 'type', None)
            type_name = str(concept_type) if concept_type else ''

            # Basic unit type compatibility checks
            # (This would be expanded with more sophisticated type analysis)

            # Check for monetary amounts with non-currency units
            if 'monetary' in type_name.lower() or 'money' in type_name.lower():
                has_currency_unit = any('iso4217' in measure.lower() or
                                      'currency' in measure.lower()
                                      for measure in unit_measures)
                if not has_currency_unit:
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'unit_type_mismatch',
                        'description': f"Monetary concept {clark_notation} has non-currency unit measures: {unit_measures}"
                    })

            # Check for pure numeric types with units (should be pure)
            if ('decimal' in type_name.lower() or 'integer' in type_name.lower() or
                'pure' in type_name.lower()):
                if len(unit_measures) > 1 or (unit_measures and 'pure' not in unit_measures[0].lower()):
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'unit_type_mismatch',
                        'description': f"Pure numeric concept {clark_notation} has complex unit: {unit_measures}"
                    })

        except Exception as e:
            self.logger.warning(f"Failed to check unit type compatibility: {e}")

        return violations

    def _check_type_constraints(self, fact_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check if fact value violates concept data type constraints."""
        violations = []

        concept = fact_data['concept']
        value = fact_data['value']
        clark_notation = fact_data['clark_notation']

        try:
            concept_type = getattr(concept, 'type', None)
            if not concept_type:
                return violations

            type_name = str(concept_type).lower()
            value_str = str(value) if value is not None else ''

            # Check decimal/numeric constraints
            if 'decimal' in type_name or 'float' in type_name:
                try:
                    normalize_numeric_value(value_str)
                except ValueError:
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'type_constraint_violation',
                        'description': f"Value '{value_str}' invalid for decimal type"
                    })

            # Check integer constraints
            elif 'integer' in type_name:
                try:
                    int_val = int(float(value_str))  # Allow "1.0" format
                    if str(int_val) != value_str.strip():
                        violations.append({
                            'fact_data': fact_data,
                            'issue_code': 'type_constraint_violation',
                            'description': f"Value '{value_str}' invalid for integer type"
                        })
                except (ValueError, TypeError):
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'type_constraint_violation',
                        'description': f"Value '{value_str}' invalid for integer type"
                    })

            # Check boolean constraints
            elif 'boolean' in type_name:
                if value_str.lower() not in ('true', 'false', '1', '0'):
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'type_constraint_violation',
                        'description': f"Value '{value_str}' invalid for boolean type"
                    })

            # Check date constraints
            elif 'date' in type_name:
                date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
                if not date_pattern.match(value_str.strip()):
                    violations.append({
                        'fact_data': fact_data,
                        'issue_code': 'type_constraint_violation',
                        'description': f"Value '{value_str}' invalid for date type"
                    })

        except Exception as e:
            self.logger.warning(f"Failed to check type constraints: {e}")

        return violations

    def _create_finding(self, violations: List[Dict[str, Any]], context: DetectorContext) -> DetectorFinding:
        """Create a finding from type/unit/numeric violations."""

        # Generate finding ID
        finding_id = generate_finding_id(context.accession, self.pattern_id)

        # Create instances for each violation
        instances = []
        for violation in violations:
            instance = self._create_instance(violation, context)
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
            mechanism="Facts with invalid type, unit, or numeric attributes may cause parsing errors or validation failures when XBRL processors enforce stricter type checking",
            why_not_fatal_yet="Current validation may be lenient on attribute violations, but stricter type enforcement or updated validation rules could surface these as blocking errors"
        )

        return finding

    def _create_instance(self, violation: Dict[str, Any], context: DetectorContext) -> Optional[DetectorInstance]:
        """Create a detector instance from a type/unit/numeric violation."""
        try:
            fact_data = violation['fact_data']
            issue_code = violation['issue_code']
            description = violation['description']

            # Extract key identifiers
            clark_notation = fact_data['clark_notation']
            context_ref = fact_data['context_ref'] or ''
            unit_ref = fact_data['unit_ref']

            # Normalize unit for signature
            unit = None
            if fact_data['unit']:
                try:
                    unit_measures = get_unit_measures_clark(fact_data['unit'])
                    unit = normalize_unit(measures=unit_measures)
                except Exception:
                    unit = normalize_unit(unit_ref=unit_ref) if unit_ref else None

            # Generate canonical signature
            signature_bytes = canonical_signature_p004(
                concept_clark=clark_notation,
                context_id=context_ref,
                unit=unit,
                issue_code=issue_code
            )

            # Generate instance ID from signature
            instance_id = instance_id_from_signature(signature_bytes)

            # Build fact_ref (schema-compatible)
            if not context_ref:
                return None
            fact_ref: Dict[str, Any] = {
                'concept': qname_object(fact_data['qname']),
                'context_ref': context_ref,
            }
            if unit_ref:
                fact_ref['unit_ref'] = unit_ref
            if fact_data.get('value') is not None:
                fact_ref['value'] = str(fact_data['value'])
            if fact_data.get('decimals') is not None:
                fact_ref['decimals'] = str(fact_data['decimals'])
            if fact_data.get('precision') is not None:
                fact_ref['precision'] = str(fact_data['precision'])
            arelle_fact = fact_data.get('fact')
            if arelle_fact is not None:
                is_nil = getattr(arelle_fact, 'isNil', None)
                if is_nil is not None:
                    fact_ref['is_nil'] = bool(is_nil)

            instance_data: Dict[str, Any] = {
                'issue_code': issue_code,
                'fact': fact_ref,
            }
            if fact_data.get('type_qname') is not None:
                instance_data['concept_type'] = str(fact_data['type_qname'])
            if fact_data.get('unit') is not None:
                try:
                    unit_measures = get_unit_measures_clark(fact_data['unit'])
                    instance_data['unit_measures'] = [qname_object(m) for m in unit_measures]
                except Exception:
                    pass

            return DetectorInstance(
                instance_id=instance_id,
                kind="fact_numeric_typing_issue",
                primary=True,
                data=instance_data
            )

        except Exception as e:
            self.logger.error(f"Failed to create P004 instance: {e}")
            return None

    def get_break_triggers(self) -> List[Dict[str, str]]:
        """Get break triggers for P004 pattern."""
        return [
            {
                'id': 'XEW-BT004',
                'summary': 'Validator Tightening - Stricter type/unit validation enforcement'
            },
            {
                'id': 'XEW-BT003',
                'summary': 'Taxonomy Refresh - Updated type definitions trigger validation changes'
            }
        ]

    def load_rule_basis(self) -> List[Dict[str, Any]]:
        """Load rule basis for P004 pattern from registry."""
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
                        'citation': 'Section 4.6 - Data Types',
                        'url': 'http://www.xbrl.org/Specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31+corrected-errata-2013-02-20.html#_4.6',
                        'retrieved_at': '2026-01-31T00:00:00Z',
                        'sha256': 'placeholder_hash_for_xbrl_21_types',
                        'notes': 'XBRL facts must use appropriate data types and units as defined by their concepts.'
                    }
                ]

        except Exception as e:
            self.logger.warning(f"Failed to load rule basis from registry: {e}")
            return []

    def compute_canonical_signature(self, **kwargs) -> str:
        """Compute canonical signature for P004 instance ID generation."""
        # Extract required parameters for P004 signature
        concept_clark = kwargs.get('concept_clark')
        context_ref = kwargs.get('context_ref')
        unit_ref = kwargs.get('unit_ref')
        violation_code = kwargs.get('violation_code')

        if not all(x is not None for x in [concept_clark, violation_code]):
            raise ValueError("Missing required parameters for P004 canonical signature")

        # Generate canonical signature using util function
        signature_bytes = canonical_signature_p004(
            concept_clark=concept_clark,
            context_ref=context_ref,
            unit_ref=unit_ref,
            violation_code=violation_code
        )

        return signature_bytes.hex()
