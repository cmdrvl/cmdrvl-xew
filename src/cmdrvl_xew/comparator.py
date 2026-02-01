"""Comparator selection policy for filing forms.

This module defines deterministic comparator rules by form type. It does not
fetch or locate comparator filings; it only expresses the policy for which
form (if any) is considered comparable.

## Form-Specific Comparator Rules

**Periodic Reports** (require comparators for trend analysis):
- 10-Q: Compare to prior quarter (10-Q) or prior year same quarter
- 10-K: Compare to prior annual report (10-K)
- 20-F: Compare to prior annual report (20-F) for foreign private issuers

**Event-Driven Reports** (no default comparator requirement):
- 8-K: Current reports for material events (comparator optional)
- 6-K: Reports of foreign private issuers (comparator optional)

**Amendments** (/A suffix):
- Use same policy as base form (e.g., 10-K/A follows 10-K rules)
- Comparator should typically reference the original filing being amended

## Cross-Form Comparison Rules

- **Same base form only**: 10-Q compares to 10-Q, 10-K to 10-K, etc.
- **No cross-form mixing**: 10-Q should not compare to 10-K or 20-F
- **Amendment flexibility**: 10-K/A may compare to 10-K or 10-K/A
"""

from __future__ import annotations

from dataclasses import dataclass


_BASE_FORM_MAP = {
    "10-Q": "10-Q",
    "10-Q/A": "10-Q",
    "10-K": "10-K",
    "10-K/A": "10-K",
    "20-F": "20-F",
    "20-F/A": "20-F",
    "6-K": "6-K",
    "6-K/A": "6-K",
    "8-K": "8-K",
    "8-K/A": "8-K",
}


@dataclass(frozen=True)
class ComparatorPolicy:
    """Comparator policy for a form type."""

    base_form: str
    comparator_required: bool
    notes: str


def comparator_policy(form: str) -> ComparatorPolicy:
    """Return the comparator policy for a given filing form.

    10-Q, 10-K, and 20-F compare to the prior filing of the same base form.
    6-K and 8-K do not require a comparator by default (event-driven filings).
    """
    normalized = _normalize_form(form)
    base = _base_form(normalized)

    if base in ("10-Q", "10-K", "20-F"):
        return ComparatorPolicy(
            base_form=base,
            comparator_required=True,
            notes=f"Compare to the prior {base} (latest /A if present).",
        )

    if base in ("6-K", "8-K"):
        return ComparatorPolicy(
            base_form=base,
            comparator_required=False,
            notes="No comparator by default; event-driven filings are compared only when explicitly provided.",
        )

    raise ValueError(f"Unsupported form for comparator policy: {form}")


def _normalize_form(form: str) -> str:
    value = form.strip().upper()
    if not value:
        raise ValueError("Form must be a non-empty string.")
    return value


def _base_form(form: str) -> str:
    base = _BASE_FORM_MAP.get(form)
    if base is None:
        raise ValueError(f"Unsupported form type: {form}")
    return base


def validate_comparator_compatibility(primary_form: str, comparator_form: str) -> bool:
    """
    Validate that a comparator form is compatible with the primary form.

    Args:
        primary_form: The primary filing form (e.g., "10-Q")
        comparator_form: The comparator filing form (e.g., "10-Q")

    Returns:
        True if the forms are compatible for comparison

    Raises:
        ValueError: If either form is unsupported
    """
    primary_base = _base_form(_normalize_form(primary_form))
    comparator_base = _base_form(_normalize_form(comparator_form))

    # Same base form is always compatible
    if primary_base == comparator_base:
        return True

    # Cross-form comparisons are generally not recommended
    # but may be allowed in specific cases (future enhancement)
    return False


def get_supported_forms() -> list[str]:
    """Return list of all supported form types."""
    return list(_BASE_FORM_MAP.keys())


def is_amendment(form: str) -> bool:
    """Check if a form is an amendment (has /A suffix)."""
    normalized = _normalize_form(form)
    return normalized.endswith("/A")


def get_comparator_selection_rationale(form: str, comparator_provided: bool = False) -> str:
    """
    Get detailed rationale for comparator selection policy.

    Args:
        form: Filing form type
        comparator_provided: Whether a comparator was provided

    Returns:
        Human-readable explanation of the comparator policy
    """
    try:
        policy = comparator_policy(form)
        base = policy.base_form

        if policy.comparator_required:
            base_explanation = {
                "10-Q": "Quarterly reports benefit from quarter-over-quarter and year-over-year trend analysis",
                "10-K": "Annual reports require comparison to prior year for comprehensive analysis",
                "20-F": "Foreign private issuer annual reports need annual comparison for consistency"
            }.get(base, f"Periodic {base} reports require temporal comparison")

            if comparator_provided:
                return f"{base_explanation}. Comparator provided as required."
            else:
                return f"{base_explanation}. No comparator provided (policy violation)."
        else:
            event_explanation = {
                "8-K": "Current reports document specific events and typically stand alone",
                "6-K": "Foreign private issuer reports are event-driven and context-specific"
            }.get(base, f"Event-driven {base} reports typically standalone")

            if comparator_provided:
                return f"{event_explanation}. Optional comparator provided for enhanced analysis."
            else:
                return f"{event_explanation}. No comparator needed per policy."

    except ValueError as e:
        return f"Unsupported form type: {e}"
