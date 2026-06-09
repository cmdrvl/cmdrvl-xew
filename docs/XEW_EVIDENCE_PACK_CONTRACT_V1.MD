# XEW Evidence Pack Contract (v1)

This document defines the v1 execution + output contract for CMD+RVL XBRL Early Warning (XEW).
Goal: make every alert reproducible using only the Evidence Pack and pinned toolchain inputs.

## Scope (v1)
Alert-eligible canon patterns:
- `XEW-P001` Duplicate Facts With Equivalent Context/Unit
- `XEW-P002` Extension Anchoring Defects (objective checks only)
- `XEW-P004` Invalid or Discouraged Data-Type / Unit / Numeric Attributes
- `XEW-P005` Inconsistent Taxonomy References (internal inconsistency focus)
- `XEW-P006` Fee Exhibit Fragility (warning reclassification)
- `XEW-P008` Instrument Identity Collapse (review-grade identity fragility)
- `XEW-P009` Temporal Instrument Identity Drift (review-grade identity fragility)

Roadmap (not alert-eligible in v1):
- `XEW-P003` Inconsistent Dimensional Application
- `XEW-P007` Duplicate-by-Substance Contexts

Note: `XEW-P006` was repurposed to Fee Exhibit Fragility; the prior draft P006 semantic pattern is retired from the v1 contract (not alert-eligible).

## Toolchain (reference implementation)
Detection logic is implemented as:
- an Arelle-based loader/validator (Arelle used as a library or via CLI), plus
- CMD+RVL custom detectors (plugin or wrapper) that emit `xew_findings.json`.

SEC/EFM rule outputs and third-party validation results (e.g., XBRL US Data Quality Committee rules) may be attached as additional evidence, but XEW patterns are not defined as "whatever Arelle warns about."

## Evidence Pack Layout (directory)
An Evidence Pack is a directory with a stable internal layout.

Recommended layout:
```
XEW-EP-<pack_id>/
  pack_manifest.json
  xew_findings.json
  artifacts/
    <downloaded EDGAR artifacts...>
  generated/
    instrument_identity_collapse.v1.json   # present when XEW-P008 emits collapse evidence
    instrument_identity_drift.v1.json      # present when XEW-P009 emits drift evidence
  toolchain/
    toolchain.json
```

Notes:
- `artifacts/` contains the exact byte content used for detection (downloaded from EDGAR and any other public sources required to load/validate the filing). When P008 uses a local canon/OpenFIGI registry snapshot, the exact snapshot bytes are copied into `artifacts/p008_registry_snapshot.json`.
- `generated/` contains deterministic XEW-generated evidence artifacts. These files are listed in `pack_manifest.json` and are reproducibility-relevant.
- `toolchain/toolchain.json` is a small file containing pinned tool versions/config (see below).

## Required Files
### 1) `xew_findings.json`
- Must validate against `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json`.
- Must include enough evidence to reproduce each triggered pattern.
- Future schema versions (v2+) may add optional fields (e.g., severity tiers), but v1 packs must validate against the v1 schema.

### 2) `pack_manifest.json`
This is the authoritative inventory of reproducibility-relevant files in the Evidence Pack.
The manifest file itself is not required to appear in `files[]` (if it does, it must be excluded from `pack_sha256`).

Required fields:
- `pack_id`: unique string (format is internal; must be stable once issued)
- `retrieved_at`: ISO 8601 UTC timestamp for when artifacts were fetched
- `files`: array of:
  - `path`: pack-relative path (e.g., `artifacts/primary.html`)
  - `sha256`: lowercase hex sha256 of raw file bytes
  - `bytes`: integer size in bytes
  - `role`: one of: `xew_output`, `edgar_artifact`, `taxonomy_input`, `toolchain`, `manifest` (if listed), `generated`, `other`
  - `source_url`: required for `edgar_artifact` and other fetched inputs

### 3) `toolchain/toolchain.json`
Minimum fields (v1):
- `cmdrvl_xew_version`: git SHA or semver
- `arelle_version`: version string
- `config`: key settings that affect reproducibility (e.g., offline/online resolution mode, cache policy)

Recommended fields (when applicable):
- `arelle_sec_plugin_version`: version string or git SHA
- `dqcrt_version`: version string or git SHA
- `taxonomy_inputs`: list of any taxonomy packages/files used to resolve/validate (each with `source_url` or identifier + `sha256`)

### 4) P008 local registry snapshot
When `--p008-registry-snapshot` is supplied, XEW copies the exact file to `artifacts/p008_registry_snapshot.json` and records the copied bytes in `pack_manifest.json`.

Required snapshot fields:
- `schema_id`: use `cmdrvl.canon.openfigi_registry_snapshot`
- `schema_version`: snapshot contract version string
- `snapshot_id`: stable snapshot identifier
- `generated_at`: UTC ISO timestamp from the external producer
- `source`: object identifying the producer, normally `{"provider": "canon", "dataset": "openfigi"}`
- `rows`: array of registry rows

P008 consumes these row fields when present:
- `figi` (required, 12 uppercase alphanumeric characters)
- `ticker`
- `exchange`
- `security_title`
- `normalized_title`
- `canonical_signature`
- `cusip`
- `isin`
- `sedol`
- `composite_figi`
- `share_class_figi`
- `market_sector`
- `security_type`
- `name`

XEW validates and consumes this snapshot only. It does not generate the snapshot, call OpenFIGI, call canon/twinning, or perform live enrichment during detection.

### 5) P009 local corpus and registry boundary
P009 consumes provider-neutral local corpus and observation artifacts. Source-specific adapters may produce observations from iXBRL facts, XML filings, or pre-extracted local exports, but the P009 detector core consumes only the normalized observation contract. XEW does not discover filings from SEC, private warehouses, orchestrator APIs, or provider services during detection.

When a local canon/OpenFIGI registry snapshot is supplied for P009, XEW copies the exact file into the Evidence Pack artifacts and records its hash in `pack_manifest.json`. P009 uses registry evidence only as a local deterministic bridge across reported identifiers. It never calls OpenFIGI, canon, twinning, HTTP, or model runtimes during scan, pack, or verify.

P009 registry states:
- `resolved`: one deterministic local registry row bridges the reported identifiers.
- `missing`: a bridge is needed but the local snapshot has no usable row.
- `ambiguous`: multiple non-identical local rows match the evidence.
- `duplicate_identical`: duplicate local rows are byte-equivalent for P009 identity purposes.
- `snapshot_absent`: no local snapshot was supplied.
- `snapshot_invalid`: the supplied local snapshot failed validation.

Weak continuity evidence such as issuer name, title, ticker, value, or other economic facts cannot create a resolved canonical instrument identity. Weak evidence can only support `weak_continuity_only` or `weak_key_temporal_collision` findings.

## Hashing Rules (tamper-evident)
### Per-file hashes
For each file listed in `files[]`, compute:
- `sha256(file_bytes)`

Store each file hash in `pack_manifest.json`.

### Pack integrity hash
Compute `pack_sha256` deterministically from the manifest entries (not from the manifest file bytes).

Algorithm (v1):
1. Build the list of manifest entries as strings:
   - `"<path>\\t<sha256>\\n"`
   - If `pack_manifest.json` is listed in `files[]`, exclude it to avoid self-referential hashing.
2. Sort entries by `path` ascending (byte-order).
3. Concatenate into a single UTF-8 byte stream.
4. Compute `sha256(concatenated_bytes)` and record as `pack_sha256` in `pack_manifest.json`.

Rule: `pack_manifest.json` must include `pack_sha256` and the value must verify.

## Stable IDs
### Finding IDs
`finding_id` MUST be deterministic:
- `XEW-F-<accession>-<pattern_id>`

Example:
- `XEW-F-0000123456-26-000005-XEW-P001`

### Instance IDs (within a finding)
Each finding includes one or more pattern instances.
Instance IDs are deterministic sha256s of a canonical signature string.

Canonical signature rules (v1; ASCII only; use Clark notation for QNames):
- Prefix every signature with the literal version tag `v1`:
  - `sig = "v1|<pattern-specific-fields>"`
- If the signature format changes, bump the version tag (e.g., `v2|...`) and the contract/schema version.
- `XEW-P001` (duplicate facts):
  - `sig = "v1|P001|<concept_clark>|<entity_scheme>|<entity_identifier>|<period_sig>|<dim_sig>|<unit_id_or_empty>"`
- `XEW-P002` (extension concept):
  - `sig = "v1|P002|<extension_concept_clark>|<sorted_issue_codes_csv>"`
- `XEW-P004` (numeric/type/unit/attribute issue):
  - `sig = "v1|P004|<concept_clark>|<context_id>|<unit_id_or_empty>|<issue_code>"`
- `XEW-P005` (taxonomy references):
  - `sig = "v1|P005|<issue_code>|schemaRefSha256=<sha256(schemaRef_hrefs_joined_by_newline)>|nsSha256=<sha256(namespaces_joined_by_newline)>"`
- `XEW-P006` (fee exhibit fragility):
  - `sig = "v1|P006|<issue_code>|exhibit_sha256=<sha256(fee_exhibit_bytes)>|sec_error=<sec_error_code>"`
- `XEW-P007` (duplicate-by-substance context; roadmap/non-alert in v1):
  - `sig = "v1|P007|<entity_scheme>|<entity_identifier>|<period_sig>|<dim_sig>"`
- `XEW-P008` (instrument identity collapse):
  - instrument signatures use `P008:instrument|<key=value...>` with context, normalized title fields, ticker, exchange, no-trading-symbol flag, CUSIP, and ISIN.
  - weak-key signatures use `P008:weak|ticker=<ticker>|exchange=<exchange>`.
  - collapse instance signatures use `P008|collapse|<weak_key>|<sorted_member_instrument_signatures>`.
  - `instance_id = sha256(collapse_instance_signature)`.
- `XEW-P009` (temporal instrument identity drift):
  - observation signatures use `P009:observation|<source_family>|<source_adapter>|<accession>|<report_period>|<scope_key>|<observation_ordinal>|<source_path>|<strong_id_fields>|<weak_key_fields>`.
  - event signatures use `P009:event|<issue_codes_csv>|<scope_key>|<ordered_observation_signatures>|<basis_before>|<basis_after>|<registry_status>|<registry_candidate_ids>`.
  - weak-key signatures use `P009:weak|issuer=<normalized_issuer>|title=<normalized_title>|ticker=<normalized_ticker>|economic=<normalized_economic_facts>`.
  - weak-key signatures never become canonical instrument signatures without exact identifier or local registry support.
  - `instance_id = sha256(event_signature)`.

Where:
- `sha256(x)`: sha256 over UTF-8 bytes of `x` with no trailing newline, returned as lowercase hex.
- `<sorted_issue_codes_csv>`: objective issue codes sorted ascending and joined by `,` (no trailing comma).
- `<period_sig>`: `instant:YYYY-MM-DD` or `duration:YYYY-MM-DD..YYYY-MM-DD`.
- `<dim_sig>`: dimension-member set for the context, sorted by dimension Clark string and encoded as `<dim_clark>=<member_clark|typed:sha256(typed_value)>`, joined by `;` (empty string when no dimensions).
- `<unit_id_or_empty>`: normalized unit signature or empty string for non-numeric facts (see Unit Equivalence Policy below).
- `schemaRef_hrefs_joined_by_newline`: sorted schemaRef hrefs joined by `\n` (no trailing newline).
- `namespaces_joined_by_newline`: sorted namespaces joined by `\n` (no trailing newline).

Then:
- `instance_id = sha256(sig)` (lowercase hex)

## Unit Equivalence Policy (v1)

For XBRL units referenced in canonical signatures and duplicate detection:

### Unit Normalization
- **Non-numeric facts**: Use empty string in signatures (`<unit_id_or_empty>` = "")
- **Numeric facts**: Normalize unit to measures in sorted Clark notation
- **Multi-measure units** (e.g., ratios): Join measures with `;` (e.g., `"{http://iso4217}USD;{http://xbrldt}shares"`)
- **Single measure**: Use Clark notation directly (e.g., `"{http://iso4217}USD"`)

### Unit Equivalence Rules
Two units are equivalent if:
1. Both are non-numeric (no unit), OR
2. Both have identical normalized measures (same Clark notations, ignoring original order)

### Policy Selection (v1)
- **Semantic equivalence**: Compare normalized measures when available (preferred for duplicate detection)
- **Reference equivalence**: Fall back to unitRef comparison when measures unavailable (signatures only)

### Examples
```
Non-numeric fact:     unit_signature = ""
USD currency:         unit_signature = "{http://www.xbrl.org/2003/iso4217}USD"
Shares count:         unit_signature = "{http://www.xbrl.org/2005/xbrldt}shares"
USD per share ratio:  unit_signature = "{http://www.xbrl.org/2003/iso4217}USD;{http://www.xbrl.org/2005/xbrldt}shares"
```

Note: Units with different measure order but identical content are equivalent (`USD;shares` == `shares;USD`), but the canonical signature always uses sorted order for determinism.

## Determinism Requirements (v1)
To avoid "it worked on my machine" evidence packs:
- Use Clark notation (`{namespace}localName`) for all QNames stored in JSON.
- Record toolchain versions and taxonomy inputs used to build the DTS.
- Cap noisy instance lists with explicit truncation fields (see schema).
- Do not emit semantic claims that cannot be derived from artifacts (e.g., "semantically unrelated" anchoring).
- P008 and P009 must not call OpenFIGI, canon, twinning, HTTP, or LLM/model runtimes during detection. Registry evidence must come from a local snapshot copied into the Evidence Pack.

## P009 Generated Artifact Contract

When P009 emits evidence, `generated/instrument_identity_drift.v1.json` is required and must be listed in `pack_manifest.json` with role `generated`.

Required top-level fields:
- `schema_version`: `1.0`.
- `inputs`: manifest hash, current accession, history accessions, cached artifact paths, source family, source adapter, and parser mode when a parser adapter is used.
- `registry_snapshot`: local snapshot metadata and copied artifact hash when supplied.
- `source_scope`: source-defined scope key, source family, source adapter, CIK when present, series id/name when present, and ordered accessions.
- `observations`: deterministic observation refs with report period when present, observation ordinal, reported identifiers, weak keys, and source paths.
- `identity_chains`: exact or registry-bridged chains only.
- `drift_events`: ordered P009 events with issue codes, continuity class, basis before/after, registry status, observation refs, and source paths.
- `findings`: finding and instance ids that appear in `xew_findings.json`.
- `diagnostics`: parser, corpus, registry, and truncation diagnostics.
- `hashes`: sha256 values for source bytes, registry snapshot bytes, and generated artifact inputs.

Allowed P009 issue codes:
- `identifier_basis_transition`
- `strong_identifier_removed`
- `registry_bridge_available`
- `registry_bridge_missing`
- `registry_bridge_ambiguous`
- `weak_continuity_only`
- `weak_key_temporal_collision`

Allowed continuity classes:
- `proven_transition`
- `registry_bridged`
- `registry_missing`
- `registry_ambiguous`
- `weak_unresolved`
- `weak_collision`

P009 output ordering:
1. Sort source scopes by `scope_key`.
2. Sort observations by source family, source adapter, report period when present, accession, observation ordinal, and source path.
3. Sort registry candidates by FIGI if present, then id type, id value, and stable row hash.
4. Sort events by continuity class priority, issue-code list, newest report period descending, and event id.
5. Sort diagnostics by code, source path, and stable diagnostic id.

## Artifact Preparation (flatten)

EDGAR downloads use typed directories that don't match the flat relative paths in iXBRL/schema files:

```
EDGAR structure:                    XBRL references:
0000034903-25-000063/               schemaRef="frt-20250930.xsd"
├── 10-Q/frt-20250930.htm           linkbaseRef="frt-20250930_cal.xml"
├── EX-101.SCH/frt-20250930.xsd
├── EX-101.CAL/frt-20250930_cal.xml
└── ...
```

The `cmdrvl-xew flatten` command normalizes EDGAR directories into a flat layout that Arelle can load:

```bash
cmdrvl-xew flatten sample/0000034903-25-000063 --out /tmp/flat
```

Output:
```
/tmp/flat/
├── frt-20250930.htm      (primary iXBRL)
├── frt-20250930.xsd      (extension schema)
├── frt-20250930_cal.xml  (calculation linkbase)
├── frt-20250930_def.xml  (definition linkbase)
├── frt-20250930_lab.xml  (label linkbase)
└── frt-20250930_pre.xml  (presentation linkbase)
```

The `pack` command expects flat input directories.

## External Taxonomy Resolution

Extension schemas import standard taxonomies via HTTPS:
```xml
<xs:import namespace="http://fasb.org/us-gaap/2025"
           schemaLocation="https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-2025.xsd"/>
```

For reproducibility, use Arelle's taxonomy package cache or offline mode:
- Download taxonomy packages from FASB/SEC
- Configure Arelle's `--packages` option or taxonomy cache directory
- Record taxonomy inputs in `toolchain/toolchain.json`

When online resolution is used, the `retrieved_at` timestamp and any fetched taxonomy files should be recorded in the Evidence Pack.

## Arelle Integration Points (where custom logic runs)
Custom detectors run after the filing is loaded and the XBRL model is built (facts/contexts/units/relationships available).

Two acceptable integration styles:
1) Arelle plugin: add CLI options for output paths and run detectors at end-of-load.
2) Arelle-as-library: a CMD+RVL runner imports Arelle, builds `modelXbrl`, then runs detectors.

The contract is the output artifacts, not the integration style.
