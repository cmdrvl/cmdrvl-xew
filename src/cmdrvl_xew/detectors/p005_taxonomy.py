"""
XEW-P005: Taxonomy Inconsistency Checks

Detects inconsistent taxonomy references within iXBRL filings.
Focuses on mismatches between schema references and actual namespace usage in facts.
"""

from typing import Dict, List, Any, Set, Optional
import logging
import re

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..util import (
    canonical_signature_p005,
    generate_finding_id,
    create_finding_summary,
    instance_id_from_signature
)

logger = logging.getLogger(__name__)


_VERSION_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})$")


class TaxonomyInconsistencyDetector(BaseDetector):
    """Detector for XEW-P005: Taxonomy Inconsistency Checks."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P005"

    @property
    def pattern_name(self) -> str:
        return "Inconsistent Taxonomy References"

    @property
    def alert_eligible(self) -> bool:
        return True  # P005 is v1 shipping set, alert-eligible

    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        """
        Detect taxonomy inconsistencies in iXBRL filing.

        Args:
            context: Detection context with XBRL model and metadata

        Returns:
            List of findings (empty if no inconsistencies found)
        """
        self.logger.info("Running XEW-P005 taxonomy inconsistency detection")

        try:
            schema_refs = self._extract_schema_references(context.xbrl_model)
            fact_namespaces = self._extract_fact_namespaces(context.xbrl_model)
            inconsistencies = self._analyze_taxonomy_inconsistencies(schema_refs, fact_namespaces)
            self.logger.debug(f"Detected {len(inconsistencies)} taxonomy inconsistencies")

            if not inconsistencies:
                self.logger.info("No taxonomy inconsistencies detected")
                return []

            # Create finding for inconsistencies
            finding = self._create_finding(inconsistencies, schema_refs, fact_namespaces, context)
            self.logger.info(f"Created finding with {len(finding.instances)} instances")

            return [finding]

        except Exception as e:
            self.logger.error(f"Error during P005 detection: {e}")
            raise

    def _extract_schema_references(self, xbrl_model) -> List[Dict[str, Any]]:
        """Extract schema references from XBRL model."""
        schema_refs = []

        try:
            # In Arelle, schema references are typically in the modelDocument
            if not hasattr(xbrl_model, 'modelDocument') or not xbrl_model.modelDocument:
                self.logger.warning("No model document available for schema reference extraction")
                return schema_refs

            # Extract from referencesDocument or schemaLocation
            if hasattr(xbrl_model.modelDocument, 'referencesDocument'):
                for ref_doc in xbrl_model.modelDocument.referencesDocument.values():
                    if hasattr(ref_doc, 'schemaLocation'):
                        href = ref_doc.schemaLocation
                        # Extract namespace from href or ref_doc properties
                        namespace = getattr(ref_doc, 'targetNamespace', None)

                        schema_ref_data = {
                            'href': href,
                            'namespace': namespace,
                            'document': ref_doc
                        }
                        schema_refs.append(schema_ref_data)

            # Also check direct schema references in the instance document
            if hasattr(xbrl_model.modelDocument, 'schemaLocationElements'):
                for schema_loc in xbrl_model.modelDocument.schemaLocationElements.values():
                    namespace_uri = getattr(schema_loc, 'namespaceURI', None)
                    location_uri = getattr(schema_loc, 'schemaLocation', None)

                    if namespace_uri and location_uri:
                        schema_ref_data = {
                            'href': location_uri,
                            'namespace': namespace_uri,
                            'element': schema_loc
                        }
                        schema_refs.append(schema_ref_data)

        except Exception as e:
            self.logger.warning(f"Failed to extract schema references: {e}")

        return schema_refs

    def _extract_fact_namespaces(self, xbrl_model) -> Set[str]:
        """Extract unique namespaces used in facts."""
        fact_namespaces = set()

        try:
            for fact in getattr(xbrl_model, 'facts', []):
                if hasattr(fact, 'qname') and fact.qname:
                    namespace = fact.qname.namespaceURI
                    if namespace:
                        fact_namespaces.add(namespace)

        except Exception as e:
            self.logger.warning(f"Failed to extract fact namespaces: {e}")

        return fact_namespaces

    def _analyze_taxonomy_inconsistencies(
        self,
        schema_refs: List[Dict[str, Any]],
        fact_namespaces: Set[str]
    ) -> List[Dict[str, Any]]:
        """Analyze schema references vs fact namespaces for inconsistencies."""
        inconsistencies: List[Dict[str, Any]] = []

        schema_ref_hrefs = sorted({ref.get('href') for ref in schema_refs if ref.get('href')})
        declared_namespaces = sorted({ref.get('namespace') for ref in schema_refs if ref.get('namespace')})
        fact_namespaces_sorted = sorted(fact_namespaces)

        missing = sorted(set(fact_namespaces_sorted) - set(declared_namespaces))
        unused = sorted(set(declared_namespaces) - set(fact_namespaces_sorted))
        if missing or unused:
            details_parts = []
            if missing:
                details_parts.append(f"namespaces_in_facts_not_in_schema_refs={missing}")
            if unused:
                details_parts.append(f"schema_ref_namespaces_not_in_facts={unused}")
            inconsistencies.append(
                {
                    "issue_code": "namespace_schema_ref_mismatch",
                    "details": "; ".join(details_parts),
                    "schema_refs": schema_ref_hrefs,
                    "namespaces_in_facts": fact_namespaces_sorted,
                }
            )

        mixed_versions = self._detect_mixed_taxonomy_versions(fact_namespaces_sorted)
        if mixed_versions:
            details = "; ".join(
                f"{base} versions={sorted(list(versions))}"
                for base, versions in mixed_versions.items()
            )
            inconsistencies.append(
                {
                    "issue_code": "mixed_taxonomy_versions",
                    "details": details,
                    "schema_refs": schema_ref_hrefs,
                    "namespaces_in_facts": fact_namespaces_sorted,
                }
            )

        return inconsistencies

    def _detect_mixed_taxonomy_versions(self, namespaces: List[str]) -> Dict[str, Set[str]]:
        versions_by_base: Dict[str, Set[str]] = {}
        for ns in namespaces:
            match = _VERSION_RE.search(ns)
            if not match:
                continue
            version = match.group(1)
            base = ns[:match.start()]
            versions_by_base.setdefault(base, set()).add(version)
        return {base: versions for base, versions in versions_by_base.items() if len(versions) > 1}

    def _create_finding(self, inconsistencies: List[Dict[str, Any]],
                       schema_refs: List[Dict[str, Any]],
                       fact_namespaces: Set[str],
                       context: DetectorContext) -> DetectorFinding:
        """Create a finding from taxonomy inconsistencies."""

        # Generate finding ID
        finding_id = generate_finding_id(context.accession, self.pattern_id)

        # Create instances for each inconsistency type
        instances = []
        for inconsistency in inconsistencies:
            instance = self._create_instance(inconsistency, schema_refs, fact_namespaces, context)
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
            mechanism="Taxonomy reference inconsistencies can cause filing rejection when validators enforce stricter schema validation or when referenced taxonomies change",
            why_not_fatal_yet="Current validation may tolerate minor inconsistencies, but stricter taxonomy validation or schema updates could surface these as blocking errors"
        )

        return finding

    def _create_instance(
        self,
        inconsistency: Dict[str, Any],
        schema_refs: List[Dict[str, Any]],
        fact_namespaces: Set[str],
        context: DetectorContext
    ) -> Optional[DetectorInstance]:
        """Create a detector instance from a taxonomy inconsistency."""
        try:
            issue_code = inconsistency['issue_code']
            details = inconsistency['details']
            schema_ref_hrefs = inconsistency.get('schema_refs', [])
            namespaces_in_facts = inconsistency.get('namespaces_in_facts', [])

            # Generate canonical signature
            signature_bytes = canonical_signature_p005(
                issue_code=issue_code,
                schema_refs=schema_ref_hrefs,
                namespaces=namespaces_in_facts
            )

            # Generate instance ID from signature
            instance_id = instance_id_from_signature(signature_bytes)

            # Build instance data
            instance_data = {
                "issue_code": issue_code,
                "schema_refs": schema_ref_hrefs,
                "namespaces_in_facts": namespaces_in_facts,
                "details": details,
            }

            return DetectorInstance(
                instance_id=instance_id,
                kind="taxonomy_reference_issue",
                primary=True,
                data=instance_data
            )

        except Exception as e:
            self.logger.error(f"Failed to create P005 instance: {e}")
            return None

    def get_break_triggers(self) -> List[Dict[str, str]]:
        """Get break triggers for P005 pattern."""
        return [
            {
                'id': 'XEW-BT003',
                'summary': 'Taxonomy Refresh - Taxonomy updates trigger stricter validation rules'
            },
            {
                'id': 'XEW-BT004',
                'summary': 'Validator Tightening - Rule enforcement changes surface tolerated taxonomy errors'
            },
        ]

    def load_rule_basis(self) -> List[Dict[str, Any]]:
        """Load rule basis for P005 pattern from registry."""
        from .registry import get_registry

        try:
            registry = get_registry()
            rule_basis = registry.get_rule_basis(self.pattern_id)
            if rule_basis:
                citations = []
                for rule in rule_basis:
                    citations.extend(rule.get('citations', []))
                return citations
        except Exception as e:
            self.logger.warning(f"Failed to load rule basis from registry: {e}")
        return []

    def compute_canonical_signature(self, **kwargs) -> str:
        """Compute canonical signature for instance ID generation."""
        # This would extract parameters and call canonical_signature_p005
        raise NotImplementedError("Use _create_instance for P005 detection")
