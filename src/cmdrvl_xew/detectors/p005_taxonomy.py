"""
XEW-P005: Taxonomy Inconsistency Checks

Detects inconsistent taxonomy references within iXBRL filings.
Focuses on mismatches between schema references and actual namespace usage in facts.
"""

from __future__ import annotations

from typing import Dict, List, Any, Set, Optional
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse, unquote

from ._base import BaseDetector, DetectorContext, DetectorFinding, DetectorInstance
from ..artifacts import extract_schema_refs
from ..util import (
    canonical_signature_p005,
    generate_finding_id,
    create_finding_summary,
    instance_id_from_signature
)

logger = logging.getLogger(__name__)


_VERSION_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})$")

_XML_SCHEMA_NS = "http://www.w3.org/2001/XMLSchema"
_XSD_IMPORT_TAG = f"{{{_XML_SCHEMA_NS}}}import"
_XSD_INCLUDE_TAG = f"{{{_XML_SCHEMA_NS}}}include"
_XSD_REDEFINE_TAG = f"{{{_XML_SCHEMA_NS}}}redefine"


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
            schema_ref_hrefs = self._extract_schema_ref_hrefs(context)
            fact_namespaces = self._extract_fact_namespaces(context.xbrl_model)
            declared_namespaces = self._extract_declared_namespaces(schema_ref_hrefs, context)
            inconsistencies = self._analyze_taxonomy_inconsistencies(
                schema_ref_hrefs=schema_ref_hrefs,
                declared_namespaces=declared_namespaces,
                fact_namespaces=fact_namespaces,
            )
            self.logger.debug(f"Detected {len(inconsistencies)} taxonomy inconsistencies")

            if not inconsistencies:
                self.logger.info("No taxonomy inconsistencies detected")
                return []

            # Create finding for inconsistencies
            finding = self._create_finding(inconsistencies, context)
            self.logger.info(f"Created finding with {len(finding.instances)} instances")

            return [finding]

        except Exception as e:
            self.logger.error(f"Error during P005 detection: {e}")
            raise

    def _extract_schema_ref_hrefs(self, context: DetectorContext) -> list[str]:
        """Extract link:schemaRef href values from the primary iXBRL document.

        Important: for reproducibility, we prefer the filing-authored href strings
        (typically relative filenames like "foo-20250101.xsd") over Arelle-resolved
        absolute paths (e.g., /tmp/.../foo-20250101.xsd).
        """
        primary_path = Path(context.primary_document_path)
        hrefs: list[str] = []
        try:
            hrefs = extract_schema_refs(primary_path)
        except Exception as e:
            self.logger.warning(f"Failed to extract schemaRef hrefs from primary document: {e}")

        normalized: list[str] = []
        seen: set[str] = set()
        for href in hrefs:
            value = str(href or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if normalized:
            return sorted(normalized)

        # Fallback: use Arelle modelDocument referencesDocument (keys are referenced docs).
        xbrl_model = getattr(context, "xbrl_model", None)
        model_doc = getattr(xbrl_model, "modelDocument", None) if xbrl_model is not None else None
        refs = getattr(model_doc, "referencesDocument", None) if model_doc is not None else None
        if isinstance(refs, dict):
            fallback: list[str] = []
            for ref_doc in refs.keys():
                uri = getattr(ref_doc, "uri", None) or getattr(ref_doc, "filepath", None)
                if not uri:
                    continue
                fallback.append(Path(str(uri)).name)
            fallback = sorted({h for h in fallback if h})
            if fallback:
                self.logger.warning("Falling back to Arelle referencesDocument for schema refs (may be less stable)")
                return fallback

        self.logger.warning("No schemaRef hrefs found; skipping schemaRef-based checks")
        return []

    def _extract_declared_namespaces(self, schema_ref_hrefs: list[str], context: DetectorContext) -> set[str]:
        """Extract declared namespaces from referenced extension schema(s).

        This method is deliberately artifact-driven (parsing local .xsd files)
        so it does not depend on network resolution of imported taxonomies.
        """
        if not schema_ref_hrefs:
            return set()

        artifacts_root = Path(context.artifacts_dir)
        base_dir = Path(context.primary_document_path).parent
        declared: set[str] = set()

        for href in schema_ref_hrefs:
            resolved = self._resolve_local_href(href, base_dir=base_dir, root_dir=artifacts_root)
            if resolved is None:
                continue
            if not resolved.is_file():
                self.logger.warning(f"schemaRef href resolves to missing local file: {href} -> {resolved}")
                continue
            declared |= self._extract_xsd_declared_namespaces(resolved, root_dir=artifacts_root)

        return declared

    def _resolve_local_href(self, href: str, *, base_dir: Path, root_dir: Path) -> Path | None:
        href = (href or "").strip()
        if not href:
            return None
        parsed = urlparse(href)
        if parsed.scheme or parsed.netloc:
            return None
        if not parsed.path:
            return None
        rel_path = Path(unquote(parsed.path))
        if rel_path.is_absolute():
            return None
        resolved = (base_dir / rel_path).resolve()
        try:
            resolved.relative_to(root_dir.resolve())
        except ValueError:
            # Don't allow resolving paths outside the artifact root.
            return None
        return resolved

    def _extract_xsd_declared_namespaces(self, schema_path: Path, *, root_dir: Path, max_files: int = 50) -> set[str]:
        """Return namespaces declared by an extension schema via targetNamespace + xs:import.

        Includes namespaces from xs:include / xs:redefine'd schemas when those
        schemaLocations resolve to local files under root_dir.
        """
        declared: set[str] = set()
        seen: set[Path] = set()
        stack: list[Path] = [schema_path]

        while stack:
            current = stack.pop()
            if current in seen:
                continue
            if len(seen) >= max_files:
                self.logger.warning(f"Reached max XSD include depth while parsing {schema_path.name}")
                break
            seen.add(current)

            try:
                tree = ET.parse(current)
            except Exception as e:
                self.logger.warning(f"Failed to parse XSD {current.name}: {e}")
                continue

            root = tree.getroot()
            target_namespace = root.get("targetNamespace")
            if target_namespace:
                declared.add(target_namespace.strip())

            for imp in root.iter(_XSD_IMPORT_TAG):
                ns = imp.get("namespace")
                if ns:
                    declared.add(ns.strip())

            for include_tag in (_XSD_INCLUDE_TAG, _XSD_REDEFINE_TAG):
                for inc in root.iter(include_tag):
                    loc = inc.get("schemaLocation")
                    if not loc:
                        continue
                    resolved = self._resolve_local_href(loc, base_dir=current.parent, root_dir=root_dir)
                    if resolved is None or not resolved.is_file():
                        continue
                    stack.append(resolved)

        return declared

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
        *,
        schema_ref_hrefs: list[str],
        declared_namespaces: set[str],
        fact_namespaces: Set[str],
    ) -> List[Dict[str, Any]]:
        """Analyze schema references vs fact namespaces for inconsistencies."""
        inconsistencies: List[Dict[str, Any]] = []

        schema_ref_hrefs_sorted = sorted({ref for ref in schema_ref_hrefs if ref})
        fact_namespaces_sorted = sorted(fact_namespaces)

        declared_namespaces_sorted = sorted({ns for ns in declared_namespaces if ns})
        missing: list[str] = []
        if declared_namespaces_sorted:
            missing = sorted(set(fact_namespaces_sorted) - set(declared_namespaces_sorted))
        if missing:
            details_parts = []
            details_parts.append(f"namespaces_in_facts_not_declared_in_schema_imports={missing}")
            inconsistencies.append(
                {
                    "issue_code": "namespace_schema_ref_mismatch",
                    "details": "; ".join(details_parts),
                    "schema_refs": schema_ref_hrefs_sorted,
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
                    "schema_refs": schema_ref_hrefs_sorted,
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

    def _create_finding(
        self,
        inconsistencies: List[Dict[str, Any]],
        context: DetectorContext,
    ) -> DetectorFinding:
        """Create a finding from taxonomy inconsistencies."""

        # Generate finding ID
        finding_id = generate_finding_id(context.accession, self.pattern_id)

        # Create instances for each inconsistency type
        instances = []
        for inconsistency in inconsistencies:
            instance = self._create_instance(inconsistency, context)
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
