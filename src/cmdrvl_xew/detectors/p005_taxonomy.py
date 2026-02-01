"""
XEW-P005: Taxonomy Inconsistency Checks

Detects inconsistent taxonomy references within iXBRL filings.
Focuses on mismatches between schema references and actual namespace usage in facts.
"""

from typing import Dict, List, Any, Set, Tuple, Optional
from collections import defaultdict
import logging
from urllib.parse import urlparse

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..util import (
    canonical_signature_p005,
    generate_finding_id,
    generate_instance_id,
    create_finding_summary,
    qname_to_clark,
    instance_id_from_signature
)

logger = logging.getLogger(__name__)


# Issue codes for P005 taxonomy inconsistency checks
P005_ISSUE_CODES = {
    'unreferenced_namespace': 'Namespace used in facts but not declared in schemaRef',
    'unused_schema_ref': 'SchemaRef declared but namespace not used in any facts',
    'schema_ref_mismatch': 'SchemaRef href points to different namespace than expected',
    'duplicate_schema_ref': 'Multiple schemaRef elements for same namespace',
    'missing_required_namespace': 'Expected standard namespace missing from schemaRef',
    'malformed_schema_ref': 'SchemaRef href format is malformed or invalid',
    'version_mismatch': 'SchemaRef version differs from namespace version in facts'
}


class TaxonomyInconsistencyDetector(BaseDetector):
    """Detector for XEW-P005: Taxonomy Inconsistency Checks."""

    @property
    def pattern_id(self) -> str:
        return "XEW-P005"

    @property
    def pattern_name(self) -> str:
        return "Taxonomy Inconsistency Checks"

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
            # Extract schema references from the filing
            schema_refs = self._extract_schema_references(context.xbrl_model)
            self.logger.debug(f"Extracted {len(schema_refs)} schema references")

            # Extract namespaces used in facts
            fact_namespaces = self._extract_fact_namespaces(context.xbrl_model)
            self.logger.debug(f"Found {len(fact_namespaces)} unique namespaces in facts")

            # Analyze inconsistencies
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

    def _analyze_taxonomy_inconsistencies(self,
                                        schema_refs: List[Dict[str, Any]],
                                        fact_namespaces: Set[str]) -> List[Dict[str, Any]]:
        """Analyze schema references vs fact namespaces for inconsistencies."""
        inconsistencies = []

        # Build mapping of declared namespaces
        declared_namespaces = set()
        schema_ref_by_namespace = {}

        for ref in schema_refs:
            namespace = ref.get('namespace')
            if namespace:
                declared_namespaces.add(namespace)
                if namespace in schema_ref_by_namespace:
                    # Duplicate schema reference
                    inconsistencies.append({
                        'issue_code': 'duplicate_schema_ref',
                        'description': f"Multiple schemaRef elements for namespace: {namespace}",
                        'namespace': namespace,
                        'schema_refs': [schema_ref_by_namespace[namespace], ref]
                    })
                else:
                    schema_ref_by_namespace[namespace] = ref

        # Check for unreferenced namespaces (used in facts but not declared)
        unreferenced = fact_namespaces - declared_namespaces
        for namespace in unreferenced:
            inconsistencies.append({
                'issue_code': 'unreferenced_namespace',
                'description': f"Namespace used in facts but not declared in schemaRef: {namespace}",
                'namespace': namespace,
                'schema_refs': [],
                'fact_usage': True
            })

        # Check for unused schema references (declared but not used in facts)
        unused = declared_namespaces - fact_namespaces
        for namespace in unused:
            ref = schema_ref_by_namespace.get(namespace)
            inconsistencies.append({
                'issue_code': 'unused_schema_ref',
                'description': f"SchemaRef declared but namespace not used in facts: {namespace}",
                'namespace': namespace,
                'schema_refs': [ref] if ref else [],
                'fact_usage': False
            })

        # Validate schema reference formats
        for ref in schema_refs:
            href = ref.get('href', '')
            namespace = ref.get('namespace', '')

            # Check for malformed href
            if href and not self._is_valid_schema_ref_href(href):
                inconsistencies.append({
                    'issue_code': 'malformed_schema_ref',
                    'description': f"SchemaRef href format is malformed: {href}",
                    'namespace': namespace,
                    'schema_refs': [ref],
                    'href': href
                })

            # Check for href/namespace mismatches (basic heuristics)
            if href and namespace and self._detect_href_namespace_mismatch(href, namespace):
                inconsistencies.append({
                    'issue_code': 'schema_ref_mismatch',
                    'description': f"SchemaRef href may not match declared namespace",
                    'namespace': namespace,
                    'schema_refs': [ref],
                    'href': href
                })

        return inconsistencies

    def _is_valid_schema_ref_href(self, href: str) -> bool:
        """Basic validation of schema reference href format."""
        if not href:
            return False

        # Check if it's a valid URL or relative path
        try:
            parsed = urlparse(href)
            # Must have some path component
            return bool(parsed.path)
        except Exception:
            return False

    def _detect_href_namespace_mismatch(self, href: str, namespace: str) -> bool:
        """Detect potential href/namespace mismatches using heuristics."""
        try:
            # Basic heuristic: check if namespace domain appears in href
            namespace_parts = namespace.replace('http://', '').replace('https://', '').split('/')
            href_parts = href.replace('http://', '').replace('https://', '')

            # If namespace has domain and href doesn't contain it, potential mismatch
            if len(namespace_parts) > 0 and namespace_parts[0]:
                domain = namespace_parts[0]
                if domain not in href_parts:
                    return True

            return False
        except Exception:
            # If parsing fails, assume no mismatch to avoid false positives
            return False

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

    def _create_instance(self, inconsistency: Dict[str, Any],
                        schema_refs: List[Dict[str, Any]],
                        fact_namespaces: Set[str],
                        context: DetectorContext) -> DetectorInstance | None:
        """Create a detector instance from a taxonomy inconsistency."""
        try:
            issue_code = inconsistency['issue_code']
            namespace = inconsistency.get('namespace', '')
            description = inconsistency['description']

            # Collect schema ref hrefs and fact namespaces for signature
            schema_ref_hrefs = [ref.get('href', '') for ref in schema_refs]
            schema_ref_hrefs = [href for href in schema_ref_hrefs if href]  # Filter empty

            # Generate canonical signature
            signature_bytes = canonical_signature_p005(
                issue_code=issue_code,
                schema_refs=schema_ref_hrefs,
                namespaces=sorted(fact_namespaces)  # Sort for determinism
            )

            # Generate instance ID from signature
            instance_id = instance_id_from_signature(signature_bytes)

            # Build instance data
            instance_data = {
                'issue_code': issue_code,
                'description': description,
                'namespace': namespace,
                'schema_refs_count': len(schema_refs),
                'fact_namespaces_count': len(fact_namespaces),
                'affected_schema_refs': [ref.get('href', '') for ref in inconsistency.get('schema_refs', [])],
                'fact_usage': inconsistency.get('fact_usage'),
                'signature_debug': signature_bytes.hex()
            }

            # Add specific data based on issue type
            if 'href' in inconsistency:
                instance_data['problematic_href'] = inconsistency['href']

            return DetectorInstance(
                instance_id=instance_id,
                kind="taxonomy_inconsistency",
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
            {
                'id': 'XEW-BT005',
                'summary': 'Schema Validation Enhancement - Stricter schema reference validation'
            }
        ]

    def load_rule_basis(self) -> List[Dict[str, Any]]:
        """Load rule basis for P005 pattern."""
        return [
            {
                'source': 'XBRL_21',
                'citation': '4.2',
                'url': 'http://www.xbrl.org/Specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31+corrected-errata-2013-02-20.html#_4.2',
                'retrieved_at': '2026-01-31T00:00:00Z',
                'sha256': 'placeholder_hash_for_xbrl_21_schema_refs'
            },
            {
                'source': 'EFM',
                'citation': '6.3.2',
                'url': 'https://www.sec.gov/info/edgar/edgartaxonomies.htm',
                'retrieved_at': '2026-01-31T00:00:00Z',
                'sha256': 'placeholder_hash_for_efm_taxonomy_rules'
            }
        ]

    def compute_canonical_signature(self, **kwargs) -> str:
        """Compute canonical signature for instance ID generation."""
        # This would extract parameters and call canonical_signature_p005
        raise NotImplementedError("Use _create_instance for P005 detection")