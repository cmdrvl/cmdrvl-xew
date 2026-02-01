from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    """UTC timestamp in ISO 8601 format with 'Z' suffix and no fractional seconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            n += len(chunk)
            h.update(chunk)
    return h.hexdigest(), n


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic-ish formatting for diffs and reproducibility.
    data = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(data + "\n", encoding="utf-8")


CANONICAL_SIGNATURE_VERSION = "v1"


def canonical_signature_bytes(sig_body: str, *, version: str = CANONICAL_SIGNATURE_VERSION) -> bytes:
    """Build version-tagged canonical signature bytes."""
    version = _ensure_ascii(version, "signature version")
    if "|" in version:
        raise ValueError("signature version must not contain '|'")
    sig = f"{version}|{sig_body}"
    _ensure_ascii(sig, "canonical signature")
    return sig.encode("ascii")


def period_signature(period_type: str, *, instant: str | None = None, start: str | None = None, end: str | None = None) -> str:
    if period_type == "instant":
        if not instant:
            raise ValueError("instant period requires instant date")
        sig = f"instant:{instant}"
    elif period_type == "duration":
        if not start or not end:
            raise ValueError("duration period requires start and end dates")
        sig = f"duration:{start}..{end}"
    else:
        raise ValueError(f"unknown period_type: {period_type}")
    return _ensure_ascii(sig, "period signature")


def dimension_signature(dimensions: Iterable[tuple[str, str]] | None) -> str:
    if not dimensions:
        return ""
    items = [(dim, member) for dim, member in dimensions]
    for dim, member in items:
        _ensure_ascii(dim, "dimension")
        _ensure_ascii(member, "dimension member")
    items.sort(key=lambda item: (item[0], item[1]))
    sig = ";".join(f"{dim}={member}" for dim, member in items)
    return _ensure_ascii(sig, "dimension signature")


def clark_notation(namespace_uri: str, local_name: str, *, enforce_ascii: bool = True) -> str:
    clark = f"{{{namespace_uri}}}{local_name}"
    if enforce_ascii:
        _ensure_ascii(clark, "clark notation")
    return clark


def qname_to_clark(qname: Any, *, enforce_ascii: bool = True) -> str:
    namespace, local_name, _prefixed = qname_to_parts(qname)
    return clark_notation(namespace, local_name, enforce_ascii=enforce_ascii)


def qname_object(qname: Any, *, include_prefixed: bool = True, enforce_ascii: bool = True) -> dict[str, str]:
    namespace, local_name, prefixed = qname_to_parts(qname)
    if enforce_ascii:
        _ensure_ascii(namespace, "namespace")
        _ensure_ascii(local_name, "local name")
        if prefixed:
            _ensure_ascii(prefixed, "prefixed qname")
    obj = {
        "clark": clark_notation(namespace, local_name, enforce_ascii=enforce_ascii),
        "namespace": namespace,
        "local_name": local_name,
    }
    if include_prefixed and prefixed:
        obj["prefixed"] = prefixed
    return obj


def canonical_signature_p001(
    concept_clark: str,
    entity_scheme: str,
    entity_identifier: str,
    period_sig: str,
    dim_sig: str,
    unit: NormalizedUnit | None,
    *,
    version: str = CANONICAL_SIGNATURE_VERSION,
) -> bytes:
    """Generate canonical signature for P001 duplicate facts detection.

    Args:
        concept_clark: Concept in Clark notation
        entity_scheme: Entity identifier scheme
        entity_identifier: Entity identifier value
        period_sig: Period signature string
        dim_sig: Dimension signature string
        unit: Normalized unit or None for non-numeric facts
        version: Signature version

    Returns:
        Canonical signature bytes
    """
    unit_sig = unit_signature(unit)
    sig_body = f"P001|{concept_clark}|{entity_scheme}|{entity_identifier}|{period_sig}|{dim_sig}|{unit_sig}"
    return canonical_signature_bytes(_ensure_ascii(sig_body, "P001 signature"), version=version)


def canonical_signature_p002(
    extension_concept_clark: str,
    issue_codes: Iterable[str],
    *,
    version: str = CANONICAL_SIGNATURE_VERSION,
) -> bytes:
    codes = _sorted_csv(issue_codes, "issue_codes")
    sig_body = f"P002|{extension_concept_clark}|{codes}"
    return canonical_signature_bytes(_ensure_ascii(sig_body, "P002 signature"), version=version)


def canonical_signature_p004(
    concept_clark: str,
    context_id: str,
    unit: NormalizedUnit | None,
    issue_code: str,
    *,
    version: str = CANONICAL_SIGNATURE_VERSION,
) -> bytes:
    """Generate canonical signature for P004 numeric/unit/type issues.

    Args:
        concept_clark: Concept in Clark notation
        context_id: Context reference ID
        unit: Normalized unit or None for non-numeric facts
        issue_code: Specific P004 issue code
        version: Signature version

    Returns:
        Canonical signature bytes
    """
    unit_sig = unit_signature(unit)
    sig_body = f"P004|{concept_clark}|{context_id}|{unit_sig}|{issue_code}"
    return canonical_signature_bytes(_ensure_ascii(sig_body, "P004 signature"), version=version)


def canonical_signature_p005(
    issue_code: str,
    schema_refs: Iterable[str],
    namespaces: Iterable[str],
    *,
    version: str = CANONICAL_SIGNATURE_VERSION,
) -> bytes:
    schema_ref_sha = _sha256_joined_sorted(schema_refs, "schema_refs")
    ns_sha = _sha256_joined_sorted(namespaces, "namespaces")
    sig_body = f"P005|{issue_code}|schemaRefSha256={schema_ref_sha}|nsSha256={ns_sha}"
    return canonical_signature_bytes(_ensure_ascii(sig_body, "P005 signature"), version=version)


def canonical_signature_p007(
    entity_scheme: str,
    entity_identifier: str,
    period_sig: str,
    dim_sig: str,
    *,
    version: str = CANONICAL_SIGNATURE_VERSION,
) -> bytes:
    sig_body = f"P007|{entity_scheme}|{entity_identifier}|{period_sig}|{dim_sig}"
    return canonical_signature_bytes(_ensure_ascii(sig_body, "P007 signature"), version=version)


def instance_id_from_signature(signature_bytes: bytes) -> str:
    return hashlib.sha256(signature_bytes).hexdigest()


def _sorted_csv(values: Iterable[str], field: str) -> str:
    items = _ensure_ascii_list(values, field)
    items.sort()
    return ",".join(items)


def _sha256_joined_sorted(values: Iterable[str], field: str) -> str:
    items = _ensure_ascii_list(values, field)
    items.sort()
    joined = "\n".join(items)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def normalize_typed_dimension_value(typed_value: str) -> str:
    """Normalize typed dimension value for stable hashing.

    Args:
        typed_value: Raw typed dimension value

    Returns:
        Normalized value with stable newline/whitespace handling

    Normalization rules:
    - Normalize newlines to \n
    - Strip leading/trailing whitespace
    - Preserve internal whitespace and structure
    - Preserve UTF-8 content (no ASCII restriction)
    """
    if not typed_value:
        return ""

    # Normalize newlines (Windows \r\n -> \n, Mac \r -> \n)
    normalized = typed_value.replace('\r\n', '\n').replace('\r', '\n')

    # Strip only leading/trailing whitespace (preserve internal structure)
    normalized = normalized.strip()

    return normalized


def typed_dimension_value_hash(typed_value: str) -> str:
    """Generate SHA256 hash for typed dimension values with stable normalization."""
    normalized = normalize_typed_dimension_value(typed_value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonicalize_typed_dimension_member(typed_value: str) -> str:
    """Create canonical typed dimension member in typed:sha256(value) format.

    Args:
        typed_value: Raw typed dimension value

    Returns:
        Canonical member in format "typed:sha256(normalized_value)"

    Example:
        canonicalize_typed_dimension_member("Some text\r\n  value  ")
        -> "typed:a1b2c3d4...64chars..."
    """
    value_hash = typed_dimension_value_hash(typed_value)
    return f"typed:{value_hash}"


def _ensure_ascii_list(values: Iterable[str], field: str) -> list[str]:
    items = list(values)
    for item in items:
        _ensure_ascii(item, field)
    return items


def _ensure_ascii(value: str, field: str) -> str:
    if not value.isascii():
        raise ValueError(f"{field} must be ASCII")
    return value


def _parse_clark(clark: str) -> tuple[str, str]:
    if not clark.startswith("{") or "}" not in clark:
        raise ValueError("clark notation must be '{namespace}localName'")
    namespace, local_name = clark[1:].split("}", 1)
    if not namespace or not local_name:
        raise ValueError("clark notation must include namespace and local name")
    return namespace, local_name


def qname_to_parts(qname: Any) -> tuple[str, str, str | None]:
    if qname is None:
        raise TypeError("qname is required")

    if isinstance(qname, dict):
        if "clark" in qname:
            namespace, local_name = _parse_clark(str(qname["clark"]))
            prefixed = qname.get("prefixed")
            return namespace, local_name, prefixed if prefixed else None
        if "namespace" in qname and ("local_name" in qname or "localName" in qname):
            namespace = str(qname["namespace"])
            local_name = str(qname.get("local_name") or qname.get("localName"))
            prefixed = qname.get("prefixed")
            return namespace, local_name, prefixed if prefixed else None

    if isinstance(qname, str):
        namespace, local_name = _parse_clark(qname)
        return namespace, local_name, None

    if isinstance(qname, tuple) and len(qname) == 2:
        namespace, local_name = qname
        return str(namespace), str(local_name), None

    namespace = getattr(qname, "namespaceURI", None) or getattr(qname, "namespace", None)
    local_name = getattr(qname, "localName", None) or getattr(qname, "localname", None) or getattr(qname, "local", None)
    if namespace is None or local_name is None:
        raise TypeError(f"unsupported QName type: {type(qname)!r}")

    prefix = getattr(qname, "prefix", None)
    if prefix:
        prefixed = f"{prefix}:{local_name}"
    else:
        prefixed = getattr(qname, "prefixedName", None) or getattr(qname, "prefixed_name", None)
    return str(namespace), str(local_name), prefixed if prefixed else None


# Unit normalization and equivalence for XEW detectors
# Based on XBRL 2.1 spec: units are equivalent if they have the same measures (regardless of order)

@dataclass(frozen=True)
class NormalizedUnit:
    """Normalized unit representation for deterministic comparison and hashing."""
    measures: tuple[str, ...]  # Sorted measures in Clark notation
    is_numeric: bool  # Whether this represents a numeric unit

    def __post_init__(self):
        # Validate measures are sorted for determinism
        if self.measures != tuple(sorted(self.measures)):
            raise ValueError("NormalizedUnit measures must be pre-sorted")


def normalize_unit_measures(measures: Iterable[str]) -> tuple[str, ...]:
    """Normalize unit measures to sorted Clark notation tuple.

    Args:
        measures: Iterable of measure Clark notations (e.g., ['{http://www.xbrl.org/2003/iso4217}USD'])

    Returns:
        Sorted tuple of measures for deterministic comparison
    """
    normalized = []
    for measure in measures:
        _ensure_ascii(measure, "unit measure")
        # Validate Clark notation format
        if not (measure.startswith("{") and "}" in measure):
            raise ValueError(f"unit measure must be in Clark notation: {measure}")
        normalized.append(measure)

    # Sort for deterministic ordering
    normalized.sort()
    return tuple(normalized)


def normalize_unit(unit_ref: str | None = None, *, measures: Iterable[str] | None = None) -> NormalizedUnit | None:
    """Normalize a unit for equivalence comparison and canonical signatures.

    Args:
        unit_ref: Unit reference ID (for signatures when actual measures aren't available)
        measures: Unit measures in Clark notation (preferred for equivalence)

    Returns:
        NormalizedUnit or None for non-numeric facts
    """
    if measures is not None:
        # Prefer actual measures for semantic equivalence
        norm_measures = normalize_unit_measures(measures)
        return NormalizedUnit(measures=norm_measures, is_numeric=True)
    elif unit_ref is not None:
        # Fall back to unit_ref for signature generation (when measures unavailable)
        _ensure_ascii(unit_ref, "unit_ref")
        # Treat unit_ref as a single "synthetic" measure for determinism
        return NormalizedUnit(measures=(unit_ref,), is_numeric=True)
    else:
        # Non-numeric fact (no unit)
        return None


def unit_signature(unit: NormalizedUnit | None) -> str:
    """Generate canonical signature component for a unit.

    Args:
        unit: Normalized unit or None for non-numeric facts

    Returns:
        Unit signature string (empty for non-numeric facts)
    """
    if unit is None:
        return ""

    # Join measures with semicolon for multi-measure units (e.g., ratios)
    return ";".join(unit.measures)


def units_equivalent(unit1: NormalizedUnit | None, unit2: NormalizedUnit | None) -> bool:
    """Check if two normalized units are semantically equivalent.

    Args:
        unit1, unit2: Normalized units to compare

    Returns:
        True if units are equivalent (same measures, ignoring order)
    """
    if unit1 is None and unit2 is None:
        return True  # Both non-numeric
    if unit1 is None or unit2 is None:
        return False  # One numeric, one non-numeric

    # Units are equivalent if they have the same measures (already sorted)
    return unit1.measures == unit2.measures


def unit_from_ref(unit_ref: str) -> NormalizedUnit:
    """Create a normalized unit from a unit reference ID (backward compatibility).

    Use this when you only have unitRef but not the actual measures.
    For proper semantic equivalence, use normalize_unit() with measures.

    Args:
        unit_ref: Unit reference ID from XBRL fact

    Returns:
        NormalizedUnit using unit_ref as synthetic measure
    """
    _ensure_ascii(unit_ref, "unit_ref")
    return NormalizedUnit(measures=(unit_ref,), is_numeric=True)


def get_unit_measures_clark(unit_element: Any) -> list[str]:
    """Extract measures from a unit element and convert to Clark notation.

    Args:
        unit_element: Arelle unit object or similar

    Returns:
        List of measures in Clark notation format
    """
    measures = []

    # Handle different unit element types/interfaces
    if hasattr(unit_element, 'measures'):
        # Arelle unit object
        for measure in unit_element.measures:
            if hasattr(measure, 'qname'):
                measures.append(qname_to_clark(measure.qname))
            else:
                # Assume it's already a QName we can convert
                measures.append(qname_to_clark(measure))
    elif hasattr(unit_element, 'measure'):
        # Single measure case
        measure = unit_element.measure
        if hasattr(measure, 'qname'):
            measures.append(qname_to_clark(measure.qname))
        else:
            measures.append(qname_to_clark(measure))
    else:
        raise TypeError(f"unsupported unit element type: {type(unit_element)}")

    return measures


# Value normalization for P001 duplicate conflict detection
# Normalizes fact values for comparison while preserving raw values in evidence

from decimal import Decimal, InvalidOperation
import re
from typing import Union

NormalizedValue = Union[Decimal, str, None]


def normalize_fact_value(raw_value: str | None, *, is_numeric: bool = False) -> NormalizedValue:
    """Normalize a fact value for duplicate conflict detection.

    Args:
        raw_value: Raw fact value from XBRL
        is_numeric: True if this is a numeric fact (use decimal normalization)

    Returns:
        Normalized value (Decimal for numeric, str for non-numeric, None for nil)

    Note:
        Raw values are preserved in findings; normalization is for comparison only.
    """
    if raw_value is None:
        return None

    if is_numeric:
        return normalize_numeric_value(raw_value)
    else:
        return normalize_string_value(raw_value)


def normalize_numeric_value(raw_value: str | None) -> Decimal | None:
    """Normalize numeric fact value using decimal arithmetic.

    Args:
        raw_value: Raw numeric value string from XBRL fact

    Returns:
        Normalized Decimal value or None for nil

    Raises:
        ValueError: If value cannot be parsed as a valid number

    Examples:
        "1000" -> Decimal('1000')
        "1000.00" -> Decimal('1000.00') (preserves precision)
        "1.23E+3" -> Decimal('1230')
        " 42 " -> Decimal('42') (strips whitespace)
    """
    if raw_value is None:
        return None

    # Strip whitespace but preserve the numeric representation
    cleaned = raw_value.strip()
    if not cleaned:
        return None

    try:
        # Use Decimal for exact numeric representation (avoid float precision issues)
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"invalid numeric value: {raw_value!r}") from e


def normalize_string_value(raw_value: str | None) -> str | None:
    """Normalize string fact value for comparison.

    Args:
        raw_value: Raw string value from XBRL fact

    Returns:
        Normalized string or None for nil

    Normalization rules:
    - Strips leading/trailing whitespace
    - Normalizes internal whitespace to single spaces
    - Preserves case (XBRL text facts are case-sensitive)
    - Preserves UTF-8 content (no ASCII restriction)
    """
    if raw_value is None:
        return None

    # Strip leading/trailing whitespace
    cleaned = raw_value.strip()
    if not cleaned:
        return ""

    # Normalize internal whitespace (collapse multiple spaces/newlines to single space)
    normalized = re.sub(r'\s+', ' ', cleaned)

    return normalized


def values_equivalent(value1: NormalizedValue, value2: NormalizedValue) -> bool:
    """Check if two normalized fact values are equivalent.

    Args:
        value1, value2: Normalized values to compare

    Returns:
        True if values are equivalent for duplicate detection purposes
    """
    if value1 is None and value2 is None:
        return True  # Both nil
    if value1 is None or value2 is None:
        return False  # One nil, one non-nil

    # Direct equality for normalized values (Decimal or str)
    return value1 == value2


def values_conflicting(value1: NormalizedValue, value2: NormalizedValue) -> bool:
    """Check if two normalized fact values represent a conflict.

    Args:
        value1, value2: Normalized values to compare

    Returns:
        True if values are different and represent a potential data conflict

    Note:
        This is the inverse of values_equivalent() - used for P001 conflict detection.
    """
    return not values_equivalent(value1, value2)


def numeric_precision_info(decimal_value: Decimal) -> dict[str, int]:
    """Extract precision information from a normalized numeric value.

    Args:
        decimal_value: Normalized decimal value

    Returns:
        Dict with 'scale' (decimal places) and 'precision' (total digits) info

    Examples:
        Decimal('1000') -> {'scale': 0, 'precision': 4}
        Decimal('1000.00') -> {'scale': 2, 'precision': 6}
        Decimal('0.001') -> {'scale': 3, 'precision': 1}
    """
    sign, digits, exponent = decimal_value.as_tuple()

    # Scale is decimal places (negative exponent, clamped to 0)
    scale = max(0, -exponent)

    # Precision is total significant digits
    precision = len(digits)

    return {
        'scale': scale,
        'precision': precision
    }


@dataclass(frozen=True)
class NormalizedFact:
    """Normalized fact representation for P001 duplicate conflict detection."""
    signature_bytes: bytes  # Canonical signature from canonical_signature_p001()
    raw_value: str | None   # Original raw value (preserved in evidence)
    normalized_value: NormalizedValue  # Normalized value for comparison
    unit: NormalizedUnit | None  # Normalized unit
    is_numeric: bool  # Whether this represents a numeric fact

    @property
    def instance_id(self) -> str:
        """Generate deterministic instance ID from signature."""
        return instance_id_from_signature(self.signature_bytes)

    def conflicts_with(self, other: 'NormalizedFact') -> bool:
        """Check if this fact conflicts with another fact with the same signature."""
        if self.signature_bytes != other.signature_bytes:
            raise ValueError("can only check conflicts between facts with identical signatures")

        # Same signature but different values = conflict
        return values_conflicting(self.normalized_value, other.normalized_value)

    def equivalent_to(self, other: 'NormalizedFact') -> bool:
        """Check if this fact is equivalent to another (same signature + same value)."""
        return (
            self.signature_bytes == other.signature_bytes and
            values_equivalent(self.normalized_value, other.normalized_value)
        )


# Deterministic ordering and truncation for reproducible findings output
# Ensures same inputs produce byte-identical outputs regardless of list size

import re
from typing import Any, TypeVar, Callable, Union

T = TypeVar('T')

# Default truncation limits for different finding types
DEFAULT_INSTANCE_LIMIT = 100  # Max instances per finding
DEFAULT_EXAMPLE_LIMIT = 10    # Max example instances for illustration
DEFAULT_CONTEXT_LIMIT = 50    # Max contexts to include
DEFAULT_NAMESPACE_LIMIT = 25  # Max namespace references


@dataclass(frozen=True)
class TruncationInfo:
    """Metadata about list truncation for findings transparency."""
    total_count: int      # Total items before truncation
    included_count: int   # Items actually included
    truncated: bool       # Whether truncation occurred
    limit: int           # Truncation limit applied

    @property
    def truncated_count(self) -> int:
        """Number of items that were truncated."""
        return max(0, self.total_count - self.included_count)


def deterministic_sort(
    items: list[T],
    *,
    key_func: Callable[[T], Any] | None = None,
    reverse: bool = False
) -> list[T]:
    """Sort items with deterministic, reproducible ordering.

    Args:
        items: List of items to sort
        key_func: Function to extract sort key (default: str() conversion)
        reverse: Whether to reverse the sort order

    Returns:
        Sorted list with stable, deterministic ordering

    Note:
        Uses locale-independent sorting to ensure reproducibility across environments.
    """
    if not items:
        return items.copy()

    # Default key function converts to string for consistent ordering
    if key_func is None:
        key_func = lambda x: str(x)

    # Sort with stable algorithm (Python's sort is stable)
    # Add secondary sort key on string representation for determinism
    def stable_key(item):
        primary_key = key_func(item)
        # Ensure primary key is comparable
        if not isinstance(primary_key, (str, int, float, tuple)):
            primary_key = str(primary_key)
        # Add string representation as tiebreaker for full determinism
        return (primary_key, str(item))

    return sorted(items, key=stable_key, reverse=reverse)


def deterministic_sort_instances(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort finding instances by instance_id for deterministic output.

    Args:
        instances: List of finding instance dicts

    Returns:
        Sorted instances by instance_id (ascending)
    """
    return deterministic_sort(instances, key_func=lambda x: x.get('instance_id', ''))


def deterministic_sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort findings by finding_id for deterministic output.

    Args:
        findings: List of finding dicts

    Returns:
        Sorted findings by finding_id (ascending)
    """
    return deterministic_sort(findings, key_func=lambda x: x.get('finding_id', ''))


def truncate_with_metadata(
    items: list[T],
    limit: int,
    *,
    sort_key: Callable[[T], Any] | None = None
) -> tuple[list[T], TruncationInfo]:
    """Truncate a list with deterministic ordering and metadata.

    Args:
        items: List of items to potentially truncate
        limit: Maximum number of items to include
        sort_key: Function to extract sort key for deterministic ordering

    Returns:
        Tuple of (truncated_items, truncation_metadata)
    """
    total_count = len(items)

    # Sort deterministically first
    sorted_items = deterministic_sort(items, key_func=sort_key)

    # Truncate if needed
    if total_count <= limit:
        truncated_items = sorted_items
        included_count = total_count
        truncated = False
    else:
        truncated_items = sorted_items[:limit]
        included_count = limit
        truncated = True

    metadata = TruncationInfo(
        total_count=total_count,
        included_count=included_count,
        truncated=truncated,
        limit=limit
    )

    return truncated_items, metadata


def truncate_instances(
    instances: list[dict[str, Any]],
    limit: int = DEFAULT_INSTANCE_LIMIT
) -> tuple[list[dict[str, Any]], TruncationInfo]:
    """Truncate finding instances with deterministic ordering.

    Args:
        instances: List of instance dicts
        limit: Maximum instances to include

    Returns:
        Tuple of (truncated_instances, truncation_info)
    """
    return truncate_with_metadata(
        instances,
        limit,
        sort_key=lambda x: x.get('instance_id', '')
    )


def truncate_examples(
    instances: list[dict[str, Any]],
    limit: int = DEFAULT_EXAMPLE_LIMIT
) -> tuple[list[dict[str, Any]], TruncationInfo]:
    """Truncate to example instances for illustration purposes.

    Args:
        instances: List of instance dicts
        limit: Maximum examples to include

    Returns:
        Tuple of (example_instances, truncation_info)
    """
    return truncate_with_metadata(
        instances,
        limit,
        sort_key=lambda x: x.get('instance_id', '')
    )


def create_finding_summary(
    instances: list[dict[str, Any]],
    instance_limit: int = DEFAULT_INSTANCE_LIMIT,
    example_limit: int = DEFAULT_EXAMPLE_LIMIT,
    include_examples: bool = False,
) -> dict[str, Any]:
    """Create finding summary with proper instance truncation and metadata.

    Args:
        instances: All instances for this finding
        instance_limit: Limit for detailed instances
        example_limit: Limit for example instances
        include_examples: Include non-schema `examples` list when True

    Returns:
        Dict with 'observed' section containing truncated instances and metadata
    """
    # Truncate full instances
    truncated_instances, instance_info = truncate_instances(instances, instance_limit)

    summary = {
        'instance_count_total': instance_info.total_count,
        'instance_count_included': instance_info.included_count,
        'truncated': instance_info.truncated,
        'instances': truncated_instances,
    }

    if include_examples:
        # Examples are for debugging/illustration and are not part of the v1/v2 schema.
        example_instances, _example_info = truncate_examples(instances, example_limit)
        summary['examples'] = example_instances

    return summary


def sort_qnames_deterministically(qnames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort QName objects deterministically by Clark notation.

    Args:
        qnames: List of QName dicts (with 'clark' field)

    Returns:
        Sorted QNames by Clark notation (ascending)
    """
    return deterministic_sort(qnames, key_func=lambda x: x.get('clark', ''))


def sort_namespaces_deterministically(namespaces: list[str]) -> list[str]:
    """Sort namespace URIs deterministically.

    Args:
        namespaces: List of namespace URI strings

    Returns:
        Sorted namespaces (ascending, case-sensitive)
    """
    return deterministic_sort(namespaces)


def sort_schema_refs_deterministically(schema_refs: list[str]) -> list[str]:
    """Sort schema reference hrefs deterministically.

    Args:
        schema_refs: List of schema reference href strings

    Returns:
        Sorted schema refs (ascending, case-sensitive)
    """
    return deterministic_sort(schema_refs)


def apply_deterministic_ordering(finding: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic ordering to all lists in a finding.

    Args:
        finding: Finding dict that may contain lists

    Returns:
        Finding with all lists sorted deterministically

    Note:
        This is applied to findings before serialization to ensure reproducible output.
    """
    if not isinstance(finding, dict):
        return finding

    result = finding.copy()

    # Sort instances if present
    if 'observed' in result and isinstance(result['observed'], dict):
        observed = result['observed']

        if 'instances' in observed and isinstance(observed['instances'], list):
            observed = observed.copy()
            observed['instances'] = deterministic_sort_instances(observed['instances'])
            result['observed'] = observed

        if 'examples' in observed and isinstance(observed['examples'], list):
            observed = observed.copy()
            observed['examples'] = deterministic_sort_instances(observed['examples'])
            result['observed'] = observed

    # Sort rule_basis if present
    if 'rule_basis' in result and isinstance(result['rule_basis'], list):
        result['rule_basis'] = deterministic_sort(
            result['rule_basis'],
            key_func=lambda x: (x.get('source', ''), x.get('citation', ''))
        )

    # Sort break_triggers if present
    if 'break_triggers' in result and isinstance(result['break_triggers'], list):
        result['break_triggers'] = deterministic_sort(
            result['break_triggers'],
            key_func=lambda x: x.get('id', '')
        )

    return result


# Deterministic ID generation for XEW findings and instances
# Implements stable, reproducible IDs per Evidence Pack contract

import re

# XEW ID format constants
XEW_FINDING_PREFIX = "XEW-F"
XEW_ACCESSION_PATTERN = re.compile(r'^\d{10}-\d{2}-\d{6}$')  # XXXXXXXXXX-XX-XXXXXX
XEW_PATTERN_FORMATS = {
    "P001", "P002", "P004", "P005", "P007",  # Current patterns
    "M001", "M002", "M003", "M004", "M005"   # Markers (future)
}


def validate_accession_number(accession: str) -> str:
    """Validate EDGAR accession number format.

    Args:
        accession: Accession number string (e.g., "0000123456-26-000005")

    Returns:
        Validated accession number

    Raises:
        ValueError: If accession format is invalid
    """
    _ensure_ascii(accession, "accession")

    if not XEW_ACCESSION_PATTERN.match(accession):
        raise ValueError(
            f"accession must match format XXXXXXXXXX-XX-XXXXXX: {accession!r}"
        )

    return accession


def validate_pattern_id(pattern_id: str) -> str:
    """Validate XEW pattern ID format.

    Args:
        pattern_id: Pattern ID (e.g., "XEW-P001", "XEW-M001")

    Returns:
        Validated pattern ID

    Raises:
        ValueError: If pattern ID format is invalid
    """
    _ensure_ascii(pattern_id, "pattern_id")

    # Accept both "P001" and "XEW-P001" formats
    if pattern_id.startswith("XEW-"):
        core_pattern = pattern_id[4:]  # Remove "XEW-" prefix
    else:
        core_pattern = pattern_id

    if core_pattern not in XEW_PATTERN_FORMATS:
        valid_patterns = ", ".join(sorted(XEW_PATTERN_FORMATS))
        raise ValueError(
            f"pattern_id must be a valid XEW pattern: {pattern_id!r}. "
            f"Valid patterns: {valid_patterns}"
        )

    # Ensure consistent format with XEW- prefix
    return f"XEW-{core_pattern}"


def generate_finding_id(accession: str, pattern_id: str) -> str:
    """Generate deterministic finding ID per Evidence Pack contract.

    Args:
        accession: EDGAR accession number (e.g., "0000123456-26-000005")
        pattern_id: XEW pattern ID (e.g., "XEW-P001" or "P001")

    Returns:
        Finding ID in format: "XEW-F-<accession>-<pattern>"

    Examples:
        generate_finding_id("0000123456-26-000005", "P001")
        -> "XEW-F-0000123456-26-000005-XEW-P001"

        generate_finding_id("0000789123-25-000010", "XEW-P004")
        -> "XEW-F-0000789123-25-000010-XEW-P004"
    """
    validated_accession = validate_accession_number(accession)
    validated_pattern = validate_pattern_id(pattern_id)

    finding_id = f"{XEW_FINDING_PREFIX}-{validated_accession}-{validated_pattern}"

    # Ensure ASCII for deterministic behavior
    _ensure_ascii(finding_id, "finding_id")

    return finding_id


def generate_instance_id(signature_bytes: bytes) -> str:
    """Generate deterministic instance ID from canonical signature.

    Args:
        signature_bytes: Canonical signature bytes from canonical_signature_*() functions

    Returns:
        Instance ID as SHA256 hex digest (64 characters)

    Note:
        This is an alias for instance_id_from_signature() for consistency.
        Instance IDs are globally unique within a pattern based on signature content.
    """
    return instance_id_from_signature(signature_bytes)


def parse_finding_id(finding_id: str) -> dict[str, str]:
    """Parse finding ID back into components.

    Args:
        finding_id: Finding ID (e.g., "XEW-F-0000123456-26-000005-XEW-P001")

    Returns:
        Dict with 'accession' and 'pattern_id' keys

    Raises:
        ValueError: If finding ID format is invalid
    """
    _ensure_ascii(finding_id, "finding_id")

    # Expected format: XEW-F-XXXXXXXXXX-XX-XXXXXX-XEW-PXXX
    if not finding_id.startswith(f"{XEW_FINDING_PREFIX}-"):
        raise ValueError(f"finding_id must start with '{XEW_FINDING_PREFIX}-': {finding_id!r}")

    # Remove XEW-F- prefix and split
    remainder = finding_id[len(XEW_FINDING_PREFIX) + 1:]

    # Split on XEW- to separate accession from pattern
    if "-XEW-" not in remainder:
        raise ValueError(f"finding_id must contain pattern with XEW- prefix: {finding_id!r}")

    accession_part, pattern_part = remainder.rsplit("-XEW-", 1)

    # Validate components
    accession = validate_accession_number(accession_part)
    pattern_id = validate_pattern_id(f"XEW-{pattern_part}")

    return {
        'accession': accession,
        'pattern_id': pattern_id
    }


def create_finding_metadata(
    accession: str,
    pattern_id: str,
    signature_bytes: bytes | None = None
) -> dict[str, str]:
    """Create standard finding metadata with deterministic IDs.

    Args:
        accession: EDGAR accession number
        pattern_id: XEW pattern ID
        signature_bytes: Optional signature for instance ID generation

    Returns:
        Dict with 'finding_id' and optionally 'instance_id'
    """
    finding_id = generate_finding_id(accession, pattern_id)

    metadata = {
        'finding_id': finding_id,
        'pattern_id': validate_pattern_id(pattern_id),
        'accession': validate_accession_number(accession)
    }

    if signature_bytes is not None:
        metadata['instance_id'] = generate_instance_id(signature_bytes)

    return metadata


@dataclass(frozen=True)
class XEWIdentifiers:
    """Container for XEW finding and instance identifiers."""
    finding_id: str      # XEW-F-<accession>-<pattern>
    pattern_id: str      # XEW-P001, XEW-M001, etc.
    accession: str       # XXXXXXXXXX-XX-XXXXXX
    instance_id: str | None = None  # SHA256 of canonical signature (optional)

    def __post_init__(self):
        # Validate all components on construction
        validate_accession_number(self.accession)
        validate_pattern_id(self.pattern_id)

        # Validate finding_id format
        parsed = parse_finding_id(self.finding_id)
        if parsed['accession'] != self.accession or parsed['pattern_id'] != self.pattern_id:
            raise ValueError(f"finding_id components don't match provided accession/pattern_id")

    @classmethod
    def from_signature(
        cls,
        accession: str,
        pattern_id: str,
        signature_bytes: bytes
    ) -> 'XEWIdentifiers':
        """Create identifiers from canonical signature."""
        return cls(
            finding_id=generate_finding_id(accession, pattern_id),
            pattern_id=validate_pattern_id(pattern_id),
            accession=validate_accession_number(accession),
            instance_id=generate_instance_id(signature_bytes)
        )

    @classmethod
    def from_finding_only(
        cls,
        accession: str,
        pattern_id: str
    ) -> 'XEWIdentifiers':
        """Create identifiers without instance ID (for finding-level metadata)."""
        return cls(
            finding_id=generate_finding_id(accession, pattern_id),
            pattern_id=validate_pattern_id(pattern_id),
            accession=validate_accession_number(accession),
            instance_id=None
        )


@dataclass(frozen=True)
class FileHash:
    path: str
    sha256: str
    bytes: int
