"""Export the facts Arelle loads from an inline XBRL filing as flat Parquet tables.

Schema ``xew.facts.v1``, documented in ``docs/XEW_FACT_TABLES_V1.md``. This path is separate from
Evidence Pack generation: it reuses pack's Arelle loader, runs offline only, and changes nothing
that ``pack`` writes.
"""

from __future__ import annotations

import argparse
import decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import __version__
from .exit_codes import (
    ExitCode,
    exit_config_error,
    exit_invocation_error,
    exit_processing_error,
    exit_system_error,
)
from .pack import (
    _load_xbrl_model_with_arelle,
    _normalize_accession,
    _normalize_cik,
    _validate_date_format,
    _validate_form_type,
)
from .util import exact_decimal_context

SCHEMA_ID = "xew.facts.v1"
MANIFEST_NAME = "export_manifest.json"

DECIMAL_PRECISION = 38
DECIMAL_SCALE = 18

_XBRLI = "http://www.xbrl.org/2003/instance"
_IX_NAMESPACES = ("http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL")
_XML_SPACE = " \t\r\n"

# The only load errors an export may carry: the affected facts are kept and marked.
_TOLERATED_ERROR_SUFFIX = ":invalidTransformation"

# (name, type) in column order. Types: "str", "int", "bool", "decimal".
FACT_COLUMNS = (
    ("fact_key", "str"),
    ("aspect_key", "str"),
    ("duplicate_ordinal", "int"),
    ("duplicate_count", "int"),
    ("fact_ordinal", "int"),
    ("fact_id", "str"),
    ("fact_kind", "str"),
    ("concept", "str"),
    ("concept_namespace", "str"),
    ("concept_local_name", "str"),
    ("concept_type", "str"),
    ("context_id", "str"),
    ("entity_scheme", "str"),
    ("entity_identifier", "str"),
    ("period_type", "str"),
    ("period_start", "str"),
    ("period_end", "str"),
    ("period_instant", "str"),
    ("dimensions", "str"),
    ("unit_id", "str"),
    ("unit", "str"),
    ("lang", "str"),
    ("value_status", "str"),
    ("value_text", "str"),
    ("value_decimal", "decimal"),
    ("decimal_status", "str"),
    ("is_nil", "bool"),
    ("decimals", "str"),
    ("precision", "str"),
    ("scale", "str"),
    ("sign", "str"),
    ("format", "str"),
    ("source_text", "str"),
    ("source_document", "str"),
    ("source_element_path", "str"),
    ("source_line", "int"),
    ("continuation_ids", "str"),
    ("in_ix_hidden", "bool"),
    ("accession", "str"),
)
CONTEXT_COLUMNS = (
    ("context_id", "str"),
    ("entity_scheme", "str"),
    ("entity_identifier", "str"),
    ("period_type", "str"),
    ("period_start", "str"),
    ("period_end", "str"),
    ("period_instant", "str"),
    ("dimensions", "str"),
    ("dimension_count", "int"),
    ("accession", "str"),
)
DIMENSION_COLUMNS = (
    ("context_id", "str"),
    ("axis_ordinal", "int"),
    ("container", "str"),
    ("axis", "str"),
    ("axis_namespace", "str"),
    ("axis_local_name", "str"),
    ("member_kind", "str"),
    ("member", "str"),
    ("member_namespace", "str"),
    ("member_local_name", "str"),
    ("typed_member_json", "str"),
    ("accession", "str"),
)
UNIT_COLUMNS = (
    ("unit_id", "str"),
    ("unit", "str"),
    ("numerator", "str"),
    ("denominator", "str"),
    ("accession", "str"),
)
FILING_COLUMNS = (
    ("accession", "str"),
    ("cik", "str"),
    ("form", "str"),
    ("filed_date", "str"),
    ("period_end", "str"),
    ("primary_document_url", "str"),
    ("amends_accession", "str"),
    ("amendment_flag", "str"),
    ("primary_document", "str"),
    ("primary_document_sha256", "str"),
    ("schema_id", "str"),
)
DOCUMENT_COLUMNS = (
    ("uri", "str"),
    ("role", "str"),
    ("sha256", "str"),
    ("accession", "str"),
)

TABLES = (
    ("facts.parquet", FACT_COLUMNS),
    ("contexts.parquet", CONTEXT_COLUMNS),
    ("dimensions.parquet", DIMENSION_COLUMNS),
    ("units.parquet", UNIT_COLUMNS),
    ("filing.parquet", FILING_COLUMNS),
    ("documents.parquet", DOCUMENT_COLUMNS),
)


class ExportRefused(Exception):
    """The filing cannot be exported completely and faithfully; nothing is written."""


def typed_decimal(value_text: str) -> tuple[decimal.Decimal | None, str]:
    """Return ``(value, status)`` for the decimal column without ever rounding.

    ``status`` is ``exact`` or ``out_of_range``. The digits are taken from ``value_text``; no
    arithmetic is performed on them.
    """
    try:
        parsed = decimal.Decimal(value_text.strip(_XML_SPACE))
    except decimal.InvalidOperation:
        return None, "out_of_range"
    if not parsed.is_finite():
        return None, "out_of_range"
    _, digits, exponent = parsed.as_tuple()
    significant = "".join(map(str, digits)).lstrip("0")
    if not significant:
        return decimal.Decimal(0), "exact"
    trimmed = significant.rstrip("0")
    exponent += len(significant) - len(trimmed)
    fraction_digits = max(0, -exponent)
    integer_digits = max(0, len(trimmed) + exponent)
    if fraction_digits > DECIMAL_SCALE or integer_digits > DECIMAL_PRECISION - DECIMAL_SCALE:
        return None, "out_of_range"
    return parsed, "exact"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _clark(qname: Any) -> str:
    return f"{{{qname.namespaceURI or ''}}}{qname.localName}"


def _xml_children(element: Any) -> list[Any]:
    """Every XML child node, including comments (their tail text belongs to the parent).

    Never iterate an element directly: Arelle's inline fact classes override ``__iter__`` to yield
    only tuple members, which would silently drop nested markup, facts and text.
    """
    from lxml import etree  # type: ignore

    return list(etree.ElementBase.iterchildren(element))


def _child_elements(element: Any) -> list[Any]:
    return [child for child in _xml_children(element) if isinstance(child.tag, str)]


def _is_ix(element: Any, local_name: str) -> bool:
    return isinstance(element.tag, str) and element.tag in {f"{{{ns}}}{local_name}" for ns in _IX_NAMESPACES}


class _DocumentIndex:
    """Document-order positions, element paths and continuation targets for one source file."""

    def __init__(self, root: Any) -> None:
        self.positions: dict[Any, tuple[int, str, bool]] = {}
        self.continuations: dict[str, Any] = {}
        order = 0
        stack = [(root, "/*[1]", False)]
        while stack:
            element, path, hidden = stack.pop()
            self.positions[element] = (order, path, hidden)
            order += 1
            if _is_ix(element, "continuation") and element.get("id"):
                self.continuations[element.get("id")] = element
            child_hidden = hidden or _is_ix(element, "hidden")
            children = _child_elements(element)
            for number in range(len(children), 0, -1):
                stack.append((children[number - 1], f"{path}/*[{number}]", child_hidden))

    def source_text(self, element: Any) -> tuple[str, list[str]]:
        """The document's own text of a fact: no transform, scale, sign or whitespace change."""
        parts: list[str] = []
        chain: list[str] = []
        self._collect_text(element, parts)
        next_id = element.get("continuedAt")
        while next_id:
            if next_id in chain or next_id not in self.continuations:
                raise ExportRefused(f"broken ix continuation chain at id {next_id!r}")
            chain.append(next_id)
            continuation = self.continuations[next_id]
            self._collect_text(continuation, parts)
            next_id = continuation.get("continuedAt")
        return "".join(parts), chain

    def _collect_text(self, element: Any, parts: list[str]) -> None:
        # Explicit stack: filings nest markup deeply.
        stack: list[Any] = [element]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                parts.append(item)
                continue
            pending: list[Any] = []
            if item.text:
                pending.append(item.text)
            for child in _xml_children(item):
                if isinstance(child.tag, str) and not _is_ix(child, "exclude"):
                    pending.append(child)
                if child.tail:
                    pending.append(child.tail)
            stack.extend(reversed(pending))


def _structure(element: Any) -> dict[str, Any]:
    """A prefix-independent form of a typed dimension member element."""
    node: dict[str, Any] = {"name": str(element.tag)}
    attributes = {str(k): v for k, v in element.attrib.items()}
    if attributes:
        node["attributes"] = attributes
    children = _child_elements(element)
    if children:
        node["children"] = [_structure(child) for child in children]
    else:
        node["text"] = (element.text or "").strip(_XML_SPACE)
    return node


def _context_record(context: Any) -> dict[str, Any]:
    if context.segNonDimValues or context.scenNonDimValues:
        raise ExportRefused(
            f"context {context.id!r} has non-dimensional segment or scenario content, which xew.facts.v1 cannot hold"
        )
    scheme, identifier = context.entityIdentifier
    period = {"startDate": None, "endDate": None, "instant": None}
    period_type = None
    for element in context.iter(f"{{{_XBRLI}}}startDate", f"{{{_XBRLI}}}endDate", f"{{{_XBRLI}}}instant"):
        name = element.tag.rsplit("}", 1)[1]
        period[name] = (element.text or "").strip(_XML_SPACE)
        period_type = "instant" if name == "instant" else "duration"
    if context.isForeverPeriod:
        period_type = "forever"

    dimensions = []
    for container, values in (("segment", context.segDimValues), ("scenario", context.scenDimValues)):
        for value in values.values():
            # The mapping's keys are concept objects, whose namespaceURI and localName describe the
            # schema's <element> tag; the axis name is dimensionQname.
            axis = value.dimensionQname
            row = {
                "container": container,
                "axis": str(axis),
                "axis_namespace": axis.namespaceURI,
                "axis_local_name": axis.localName,
                "axis_clark": _clark(axis),
                "member": None,
                "member_namespace": None,
                "member_local_name": None,
                "typed_member_json": None,
            }
            if value.isTyped:
                structure = _structure(value.typedMember)
                row["member_kind"] = "typed"
                row["typed_member_json"] = _canonical_json(structure)
                row["key"] = {"axis": row["axis_clark"], "container": container, "typed": structure}
            else:
                member = value.memberQname
                row["member_kind"] = "explicit"
                row["member"] = str(member)
                row["member_namespace"] = member.namespaceURI
                row["member_local_name"] = member.localName
                row["key"] = {"axis": row["axis_clark"], "container": container, "member": _clark(member)}
            dimensions.append(row)
    dimensions.sort(key=lambda item: (item["axis_clark"], item["container"]))

    return {
        "context_id": context.id,
        "entity_scheme": scheme,
        "entity_identifier": identifier.strip(_XML_SPACE),
        "period_type": period_type,
        "period_start": period["startDate"],
        "period_end": period["endDate"],
        "period_instant": period["instant"],
        "dimension_rows": dimensions,
        "dimension_keys": [item["key"] for item in dimensions],
        "dimensions": _canonical_json([item["key"] for item in dimensions]),
    }


def _unit_record(unit: Any) -> dict[str, Any]:
    numerator, denominator = unit.measures
    top = "*".join(sorted(str(q) for q in numerator))
    bottom = "*".join(sorted(str(q) for q in denominator))
    return {
        "unit_id": unit.id,
        "unit": f"{top}/{bottom}" if bottom else top,
        "numerator": top,
        "denominator": bottom or None,
        "key": [sorted(_clark(q) for q in numerator), sorted(_clark(q) for q in denominator)],
    }


def _fact_value(fact: Any) -> tuple[str, str | None]:
    """Return ``(value_status, value_text)`` as Arelle reports the fact."""
    from arelle import FunctionIxt  # type: ignore
    from arelle.ModelValue import INVALIDixVALUE  # type: ignore
    from arelle.XmlValidateConst import VALID  # type: ignore

    if fact.isNil:
        return "nil", None
    if fact.localName == "tuple":
        return "not_applicable", None
    value = fact.value
    if value is INVALIDixVALUE:
        transform = fact.format
        if transform is not None and not (
            transform.namespaceURI in FunctionIxt.ixtNamespaceFunctions
            or transform in (fact.modelXbrl.modelManager.customTransforms or {})
        ):
            return "transform_unavailable", None
        return "invalid", None
    if fact.localName == "fraction":
        numerator, denominator = fact.fractionValue
        return "reported", f"{numerator}/{denominator}"
    if fact.xValid < VALID:
        return "invalid", str(value)
    text = str(value)
    return ("reported" if text else "empty"), text


_FACT_KINDS = {"nonFraction": "numeric", "nonNumeric": "non_numeric", "fraction": "fraction", "tuple": "tuple"}


def build_tables(model: Any, primary_path: Path, filing: dict[str, str | None]) -> tuple[dict[str, list], dict]:
    """Turn a loaded Arelle model into table rows plus the manifest's accounting."""
    error_counts: dict[str, int] = {}
    for error in model.errors:
        error_counts[str(error)] = error_counts.get(str(error), 0) + 1
    fatal = sorted(code for code in error_counts if not code.endswith(_TOLERATED_ERROR_SUFFIX))
    if fatal:
        raise ExportRefused(
            "Arelle reported load errors, so the export could be incomplete or mistyped: "
            + ", ".join(f"{code} x{error_counts[code]}" for code in fatal)
            + ". Load offline with taxonomy packages that cover every import "
            "(--arelle-xdg-config-home)."
        )
    undefined = len(model.undefinedFacts)
    if undefined:
        raise ExportRefused(f"{undefined} facts have no concept definition in the loaded taxonomy")

    primary_path = primary_path.resolve()
    base_dir = primary_path.parent
    accession = filing["accession"]

    contexts = {context_id: _context_record(context) for context_id, context in model.contexts.items()}
    units = {unit_id: _unit_record(unit) for unit_id, unit in model.units.items()}

    indexes: dict[str, _DocumentIndex] = {}
    located = []
    loaded = list(model.factsInInstance)  # a set: order is imposed below
    for fact in loaded:
        if fact.localName not in _FACT_KINDS or not _is_ix(fact, fact.localName):
            raise ExportRefused("only inline XBRL facts can be exported")
        document = _relative_name(fact.modelDocument.uri, base_dir)
        if document is None:
            raise ExportRefused("a fact comes from a document outside the primary document's directory")
        if document not in indexes:
            indexes[document] = _DocumentIndex(fact.getroottree().getroot())
        position = indexes[document].positions.get(fact)
        if position is None:
            raise ExportRefused(f"fact {fact.id!r} was not found in the tree of {document}")
        located.append((document, position, fact))
    located.sort(key=lambda item: (item[0], item[1][0]))

    rows = []
    amendment_flags = set()
    for ordinal, (document, (_, path, hidden), fact) in enumerate(located, start=1):
        concept = fact.concept
        context = contexts.get(fact.contextID)
        if concept is None or (context is None and fact.localName != "tuple"):
            raise ExportRefused(f"fact {fact.id!r} has no concept or context")
        unit = units.get(fact.unitID) if fact.unitID else None
        kind = _FACT_KINDS[fact.localName]
        status, value_text = _fact_value(fact)
        lang = (fact.xmlLang or None) if kind == "non_numeric" else None

        value_decimal = None
        if kind != "numeric":
            decimal_status = "not_numeric"
        elif status != "reported":
            decimal_status = "no_value"
        else:
            value_decimal, decimal_status = typed_decimal(value_text)

        aspect = {
            "concept": _clark(fact.qname),
            "entity": [context["entity_scheme"], context["entity_identifier"]] if context else None,
            "period": [context["period_type"], context["period_start"], context["period_end"], context["period_instant"]]
            if context
            else None,
            "dimensions": context["dimension_keys"] if context else [],
            "unit": unit["key"] if unit else None,
            "lang": lang,
        }
        source_text, chain = indexes[document].source_text(fact)
        transform = fact.get("format")
        context = context or {}
        rows.append(
            {
                "aspect_key": hashlib.sha256(_canonical_json(aspect).encode("utf-8")).hexdigest(),
                "fact_ordinal": ordinal,
                "fact_id": fact.id,
                "fact_kind": kind,
                "concept": str(fact.qname),
                "concept_namespace": fact.qname.namespaceURI,
                "concept_local_name": fact.qname.localName,
                "concept_type": str(concept.typeQname) if concept.typeQname is not None else None,
                "context_id": fact.contextID,
                "entity_scheme": context.get("entity_scheme"),
                "entity_identifier": context.get("entity_identifier"),
                "period_type": context.get("period_type"),
                "period_start": context.get("period_start"),
                "period_end": context.get("period_end"),
                "period_instant": context.get("period_instant"),
                "dimensions": context.get("dimensions"),
                "unit_id": fact.unitID,
                "unit": unit["unit"] if unit else None,
                "lang": lang,
                "value_status": status,
                "value_text": value_text,
                "value_decimal": value_decimal,
                "decimal_status": decimal_status,
                "is_nil": bool(fact.isNil),
                "decimals": fact.get("decimals"),
                "precision": fact.get("precision"),
                "scale": fact.get("scale"),
                "sign": fact.get("sign"),
                "format": transform,
                "source_text": source_text,
                "source_document": document,
                "source_element_path": path,
                "source_line": fact.sourceline,
                "continuation_ids": " ".join(chain) or None,
                "in_ix_hidden": hidden,
                "accession": accession,
            }
        )
        if fact.qname.localName == "AmendmentFlag" and "/dei/" in fact.qname.namespaceURI and value_text:
            amendment_flags.add(value_text)

    totals: dict[str, int] = {}
    for row in rows:
        totals[row["aspect_key"]] = totals.get(row["aspect_key"], 0) + 1
    seen: dict[str, int] = {}
    for row in rows:
        key = row["aspect_key"]
        seen[key] = seen.get(key, 0) + 1
        row["duplicate_ordinal"] = seen[key]
        row["duplicate_count"] = totals[key]
        row["fact_key"] = f"{key}:{seen[key]}"

    if len(rows) != len(loaded) or len({row["fact_key"] for row in rows}) != len(rows):
        raise ExportRefused(f"row accounting failed: {len(loaded)} facts loaded, {len(rows)} rows")

    context_rows, dimension_rows = [], []
    for context_id in sorted(contexts):
        record = contexts[context_id]
        context_rows.append({**record, "dimension_count": len(record["dimension_rows"]), "accession": accession})
        for number, dimension in enumerate(record["dimension_rows"], start=1):
            dimension_rows.append({**dimension, "context_id": context_id, "axis_ordinal": number, "accession": accession})

    document_rows = _document_rows(model, base_dir, accession)
    filing_row = {
        **filing,
        "amendment_flag": " ".join(sorted(amendment_flags)) or None,
        "primary_document": primary_path.name,
        "primary_document_sha256": _sha256(primary_path),
        "schema_id": SCHEMA_ID,
    }
    tables = {
        "facts.parquet": rows,
        "contexts.parquet": context_rows,
        "dimensions.parquet": dimension_rows,
        "units.parquet": [{**units[unit_id], "accession": accession} for unit_id in sorted(units)],
        "filing.parquet": [filing_row],
        "documents.parquet": document_rows,
    }

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["value_status"]] = status_counts.get(row["value_status"], 0) + 1
    accounting = {
        "facts_loaded": len(loaded) + undefined,
        "facts_exported": len(rows),
        "facts_excluded": [],
        "value_status_counts": status_counts,
        "arelle_load_error_counts": error_counts,
    }
    return tables, accounting


def _relative_name(uri: str, base_dir: Path) -> str | None:
    if not os.path.isabs(uri):
        return None
    try:
        return Path(uri).resolve().relative_to(base_dir).as_posix()
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document_rows(model: Any, base_dir: Path, accession: str | None) -> list[dict[str, str | None]]:
    rows = []
    for uri in model.urlDocs:
        if uri.startswith(("http://", "https://")):
            rows.append({"uri": uri, "role": "remote", "sha256": None, "accession": accession})
            continue
        name = _relative_name(uri, base_dir)
        if name is None:
            raise ExportRefused(
                "the taxonomy set includes a local file outside the primary document's directory; "
                "its path would make the export depend on this machine"
            )
        rows.append({"uri": name, "role": "local", "sha256": _sha256(base_dir / name), "accession": accession})
    return sorted(rows, key=lambda row: (row["role"], row["uri"]))


def parquet_bytes(rows: list[dict], columns: tuple) -> bytes:
    """Serialize one table with a fixed schema, one row group and no machine-dependent metadata."""
    import pyarrow  # type: ignore
    import pyarrow.parquet  # type: ignore

    types = {
        "str": pyarrow.string(),
        "int": pyarrow.int64(),
        "bool": pyarrow.bool_(),
        "decimal": pyarrow.decimal128(DECIMAL_PRECISION, DECIMAL_SCALE),
    }
    schema = pyarrow.schema([pyarrow.field(name, types[kind]) for name, kind in columns])
    arrays = [pyarrow.array([row.get(name) for row in rows], type=types[kind]) for name, kind in columns]
    table = pyarrow.Table.from_arrays(arrays, schema=schema)
    sink = pyarrow.BufferOutputStream()
    pyarrow.parquet.write_table(
        table,
        sink,
        row_group_size=max(1, len(rows)),
        version="2.6",
        data_page_version="1.0",
        compression="snappy",
        use_dictionary=True,
        write_statistics=True,
        store_schema=False,
    )
    return sink.getvalue().to_pybytes()


def export_facts(
    primary_path: Path,
    out_dir: Path,
    filing: dict[str, str | None],
    *,
    arelle_xdg_config_home: str | None = None,
) -> dict:
    """Load ``primary_path`` offline and write the tables into ``out_dir``. Returns the manifest."""
    import pyarrow  # type: ignore

    # The loader computes values under this context; it also covers anything read here.
    with exact_decimal_context():
        model = _load_xbrl_model_with_arelle(
            primary_path,
            resolution_mode="offline_only",
            require_arelle=True,
            disable_arelle=False,
            arelle_xdg_config_home=arelle_xdg_config_home,
        )
        try:
            tables, accounting = build_tables(model, primary_path, filing)
        finally:
            model.close()

    payloads = {name: parquet_bytes(tables[name], columns) for name, columns in TABLES}

    from arelle import Version  # type: ignore

    manifest = {
        "schema_id": SCHEMA_ID,
        **accounting,
        "files": {
            name: {"rows": len(tables[name]), "sha256": hashlib.sha256(payload).hexdigest()}
            for name, payload in payloads.items()
        },
        "writers": {"arelle": Version.__version__, "cmdrvl-xew": __version__, "pyarrow": pyarrow.__version__},
    }
    payloads[MANIFEST_NAME] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        with open(out_dir / name, "xb") as handle:  # never overwrite
            handle.write(payload)
    return manifest


def run_export_facts(args: argparse.Namespace) -> int:
    try:
        filing = {
            "accession": _normalize_accession(args.accession),
            "cik": _normalize_cik(args.cik),
            "form": _validate_form_type(args.form),
            "filed_date": _validate_date_format(args.filed_date, "filed-date"),
            "period_end": _validate_date_format(args.period_end, "period-end") if args.period_end else None,
            "primary_document_url": args.primary_document_url.strip(),
            "amends_accession": _normalize_accession(args.amends_accession) if args.amends_accession else None,
        }
    except ValueError as error:
        exit_config_error(str(error))
    if not filing["primary_document_url"]:
        exit_config_error("--primary-document-url must not be empty")

    primary = Path(args.primary)
    if not primary.is_file():
        exit_invocation_error(f"primary document not found: {primary}")
    out_dir = Path(args.out)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        exit_invocation_error(f"--out must be a new or empty directory: {out_dir}")
    try:
        import pyarrow  # type: ignore # noqa: F401
    except ImportError:
        exit_invocation_error("export-facts needs pyarrow: uv sync --extra arelle --extra parquet")

    try:
        manifest = export_facts(primary, out_dir, filing, arelle_xdg_config_home=args.arelle_xdg_config_home)
    except ExportRefused as refusal:
        exit_processing_error(f"export refused, nothing written: {refusal}")
    except OSError as error:
        exit_system_error(f"export failed: {error}")

    print(
        f"{SCHEMA_ID}: {manifest['facts_exported']} of {manifest['facts_loaded']} loaded facts exported to {out_dir}"
    )
    unavailable = manifest["value_status_counts"].get("transform_unavailable", 0)
    if unavailable:
        print(f"{unavailable} facts have no value (value_status=transform_unavailable); their source_text is kept")
    return ExitCode.SUCCESS
