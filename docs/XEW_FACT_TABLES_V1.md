# XEW fact tables, schema `xew.facts.v1`

`cmdrvl-xew export-facts` writes the facts Arelle loads from one inline XBRL filing as flat Parquet
tables, for `lock`, `profile`, `shape`, `rvl`, `verify` and filing reconciliation. It is separate
from Evidence Packs: nothing that `pack` writes changes.

Any change to a table, a column, a type, row order, a status value or how a key is built needs a new
schema id.

## Command

```bash
uv sync --extra arelle --extra parquet

cmdrvl-xew flatten sample/0000034903-25-000063 --out /tmp/flat

cmdrvl-xew export-facts \
  --primary /tmp/flat/frt-20250930.htm \
  --out /tmp/facts \
  --cik 0000034903 --accession 0000034903-25-000063 \
  --form 10-Q --filed-date 2025-10-31 --period-end 2025-09-30 \
  --primary-document-url "https://www.sec.gov/..." \
  --arelle-xdg-config-home <DIR with taxonomy packages>
```

| Option | Meaning |
|---|---|
| `--amends-accession` | The filing this one amends. Recorded only when given; never inferred. |
| `--arelle-xdg-config-home` | Arelle config holding the taxonomy packages the filing imports (see `arelle install-packages`). |

**Offline only.** There is no online mode and no User-Agent is needed. The packages must cover every
import. For a 2025 filing that includes `srt`, `us-gaap`, `dei`, `country` and `stpr` for 2025.

`--out` must be new or empty. Nothing is overwritten or deleted.

| Exit | Meaning |
|---|---|
| 0 | Exported |
| 1 | Bad argument value |
| 2 | Missing input, occupied `--out`, Arelle or pyarrow not installed |
| 3 | Refused: the export could be incomplete or wrong. Nothing is written. |
| 4 | I/O error |

An export is refused when Arelle reports any load error other than `invalidTransformation` (for
example `IOerror` for a taxonomy file that is not available offline), when a fact has no concept
definition, when row and fact counts differ, when a context has non-dimensional segment or scenario
content, when a continuation chain is broken, or when the taxonomy set uses a local file outside the
primary document's directory.

## Files

`export_manifest.json` records the schema id, facts loaded, facts exported, facts excluded (always
empty: every exclusion today is a refusal), counts per `value_status`, Arelle load error counts, the
row count and SHA-256 of each table, and the Arelle, pyarrow and cmdrvl-xew versions. It holds no
timestamp and no path.

Every table is flat: UTF-8 strings, `int64`, `bool` and one `decimal128(38,18)` column. No
floating-point type is used. Every table carries `accession`. A column that does not apply is NULL.

### `facts.parquet`

One row per loaded fact, in document order.

| Column | Type | Content |
|---|---|---|
| `fact_key` | str | `aspect_key:duplicate_ordinal`. Unique in an export; the join key for `shape` and `rvl`. |
| `aspect_key` | str | SHA-256 of the fact's aspects: concept namespace and name, entity, period, dimensions, unit measures and (text facts) language. It does not depend on prefixes, ids, the filing or the value. |
| `duplicate_ordinal`, `duplicate_count` | int | Position among facts with the same `aspect_key`, in document order, and how many there are. All are kept. |
| `fact_ordinal` | int | 1-based document order. |
| `fact_id` | str | The element's `id` in the filing, if any. |
| `fact_kind` | str | `numeric`, `non_numeric`, `fraction`, `tuple`. |
| `concept`, `concept_namespace`, `concept_local_name`, `concept_type` | str | `concept` uses the filing's prefix. |
| `context_id`, `entity_scheme`, `entity_identifier` | str | |
| `period_type` | str | `instant`, `duration`, `forever`. |
| `period_start`, `period_end`, `period_instant` | str | The filing's XML text, surrounding whitespace removed. A date `period_end` is the inclusive date as written. |
| `dimensions` | str | JSON array of `{axis, container, member}` or `{axis, container, typed}`, names as `{namespace}local`, sorted by axis. |
| `unit_id`, `unit` | str | `unit` is e.g. `iso4217:USD/xbrli:shares`. |
| `lang` | str | `xml:lang`, text facts only. |
| `value_status` | str | See below. |
| `value_text` | str | The XBRL value, as exact text: the filing's text after the inline transform, `scale` and `sign`. Text blocks with `escape="true"` hold markup. |
| `value_decimal` | decimal128(38,18) | Numeric facts only, built from the digits of `value_text`. |
| `decimal_status` | str | `exact`; `out_of_range` (more than 20 integer or 18 fraction digits, or not finite: `value_decimal` is NULL, nothing is rounded); `no_value`; `not_numeric`. |
| `is_nil` | bool | |
| `decimals`, `precision` | str | As written (`INF` or an integer). |
| `scale`, `sign`, `format` | str | The inline attributes as written. |
| `source_text` | str | The document's own text: all text inside the fact element and its continuations, `ix:exclude` removed. No transform, scale, sign or whitespace change. Markup is dropped. |
| `source_document` | str | File name relative to the primary document's directory. |
| `source_element_path` | str | XPath by element position, e.g. `/*[1]/*[2]/*[7]`; comments are not counted. |
| `source_line` | int | Line of the element. Generated filings can put most of a document on one line, so use the path or `fact_id`. |
| `continuation_ids` | str | Space-separated `ix:continuation` ids, in order. |
| `in_ix_hidden` | bool | Inside `ix:hidden`. |
| `accession` | str | |

### `value_status`

| Value | `value_text` |
|---|---|
| `reported` | the value |
| `empty` | `""` |
| `nil` | NULL (`xsi:nil="true"`) |
| `transform_unavailable` | NULL: the fact uses an inline transform this Arelle install does not have. `source_text` and `format` are kept. |
| `invalid` | Arelle could not validate the value |
| `not_applicable` | NULL (tuple) |

CSV-based readers, including `shape` and `rvl`, show NULL and `""` the same way. **Use
`value_status` to tell them apart.**

SEC's `ixt-sec` transforms are not part of `arelle-release`; they come from Arelle's separate EDGAR
plugin, which this project does not install. Facts using them are therefore
`transform_unavailable`. In the sample 10-Q these are 10 of 1,336 facts, 3 of them numeric.

### Other tables

| File | One row per | Columns besides `accession` |
|---|---|---|
| `contexts.parquet` | context, ordered by id | `context_id`, `entity_scheme`, `entity_identifier`, `period_type`, `period_start`, `period_end`, `period_instant`, `dimensions`, `dimension_count` |
| `dimensions.parquet` | context dimension | `context_id`, `axis_ordinal`, `container` (`segment`/`scenario`), `axis`, `axis_namespace`, `axis_local_name`, `member_kind` (`explicit`/`typed`), `member`, `member_namespace`, `member_local_name`, `typed_member_json` |
| `units.parquet` | unit, ordered by id | `unit_id`, `unit`, `numerator`, `denominator` (measures joined by `*`) |
| `filing.parquet` | the filing (one row) | `cik`, `form`, `filed_date`, `period_end`, `primary_document_url`, `amends_accession`, `amendment_flag` (from `dei:AmendmentFlag`), `primary_document`, `primary_document_sha256`, `schema_id` |
| `documents.parquet` | document in the loaded taxonomy set | `uri`, `role` (`local`/`remote`), `sha256` (local files only) |

## Determinism

The same inputs and the same pinned Arelle, pyarrow and cmdrvl-xew versions give byte-identical
files, whatever directory the inputs are in. Row and column order are fixed, each table is one row
group, compression is Snappy and no timestamp is embedded. The Parquet footer names the writer
version, so another pyarrow version changes the bytes.

## Using the tables with the spine tools

Checked with the released lock 0.7.1, profile 0.12.1, shape 0.10.1, rvl 0.9.2 and verify 0.7.4
(vacuum 0.6.1 and hashbytes 0.6.0 build the lock manifest), on exports of the sample 10-Q.

```bash
shape old/facts.parquet new/facts.parquet --key fact_key

rvl old/facts.parquet new/facts.parquet --profile docs/examples/xew_facts_v1.rvl-profile.yaml

profile stats facts/facts.parquet
profile suggest-key facts/facts.parquet

verify run rules.verify.json --bind facts=facts/facts.parquet

vacuum facts | hashbytes | lock --dataset-id my-filing --out facts.lock.json
lock verify facts.lock.json --root facts
```

`rvl` needs the column profile. Without it, it refuses `facts.parquet` with `E_MIXED_TYPES`,
because `value_text` holds both numbers and words. With the profile it compares `value_decimal`
only. A change to a text fact, to nil, or to a value too wide for `value_decimal` is not reported by
that comparison. In `verify`, an empty string counts as missing for `not_null`; nil facts have an
empty `source_text`.

`--key fact_key` matches facts by their aspects, so two filings with different periods share few
keys. For a changed filing with added or removed facts, see `rvl --key-mode overlap`.

## Limits

- Footnotes and fact-to-footnote relationships are not exported.
- `documents.parquet` does not hash remote taxonomy documents, and the manifest does not identify
  the taxonomy package files used. Two package builds that differ under the same URLs would not be
  told apart.
- `duplicate_ordinal` follows document order. If an amendment reorders or removes one of several
  facts with the same aspects, their `fact_key` values shift. Compare duplicates as a group by
  `aspect_key`.
- `amends_accession` is only what the caller supplies.
- Only inline XBRL is supported.
- Released `verify` compares numbers as 64-bit floats (verify bead `bd-1t5`). A `verify` pass does
  not prove that wide values are exactly equal. `value_text` is the exact form.
