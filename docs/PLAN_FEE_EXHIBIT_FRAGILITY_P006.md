# XEW Fee Exhibit Fragility Detection (XEW-P006)

## Status
- **Created**: 2026-02-08
- **Status**: Planning (pre-implementation)
- **Deadline driver**: March 16, 2026 SEC/EDGAR enforcement shift
- **Scope**: XEW engine enhancement only (Kovrex agent + Outcomes are follow-on)

---

## 1. Background

### The Enforcement Shift

Starting **March 16, 2026**, SEC/EDGAR have announced they will **suspend** (hard-reject) filings containing incorrect or incomplete structured filing-fee exhibits. This enforcement change is associated with the Filing Fee Disclosure and Payment Methods Modernization effort (SEC Final Rule 33-11079) and related EDGAR implementation guidance.

Before March 16: many fee-exhibit defects are non-suspension-level (the filing can be accepted, often with warnings).
After March 16: the reclassified defects become suspension-level and can halt the EDGAR submission until remedied.

This is primarily an **enforcement consequence shift** (non-suspension-level → suspension-level) on a set of fee-exhibit validation conditions. The underlying validation rules may be the same or materially similar, but the consequence changes. Artifacts accepted under the old regime may be rejected under the new one.

**Terminology (used in this document)**:
- **Suspension-level**: EDGAR hard-rejects the submission.
- **Non-suspension-level**: EDGAR accepts the submission (the condition may still be reported as a warning or other non-fatal validation output).
- **Warning**: shorthand for "non-suspension-level validation output" (not necessarily the literal severity label in every tool).
- **Normalized consequence labels (instance data)**: `non_suspension_level` and `suspension_level`.

### What P006 Actually Detects

P006 is a **reclassification detector**, not a validator.

The question P006 answers is not "does this fee exhibit have errors?" (any validator can tell you that). The question is: **"Does this accepted filing contain fee-exhibit validation conditions that SEC/EDGAR have announced will be enforced as suspension-level errors starting March 16, 2026?"**

Selecting which filing to analyze (e.g., "most recent accepted") is orchestration/monitoring and is out of scope for this repo; P006 runs on whatever accepted filing is packaged into an Evidence Pack.

That's a genuine fragility finding in the same spirit as P001-P005:
- The filing was **accepted** — it passed EDGAR submission
- The artifact **hasn't changed** — the filer may assume it's fine because it was accepted
- The enforcement context **is changing** — the same artifact, resubmitted after March 16, is subject to suspension-level enforcement on the reclassified conditions
- The filer **may not know** — non-suspension-level validation output is routinely ignored; the reclassification is the news

P006 checks for the same conditions a validator would (e.g., missing `ffd:FormTp`). The detection logic is trivial — what a validator can also tell you. The value P006 adds is: (a) running those checks on *accepted* filings retrospectively, (b) identifying which of those conditions are being reclassified to suspension-level on a specific date, and (c) packaging the finding in an Evidence Pack with the reclassification citation, the SEC error code, and the deadline. The detection is commodity; the reclassification context is not.

### Source Material (Primary + Secondary)

Primary sources (used for the Gate + rule basis; do not rely on secondary summaries):
- SEC/EDGAR announcement/notice describing the March 16, 2026 suspension-level enforcement change
- SEC Final Rule 33-11079 (Filing Fee Disclosure and Payment Methods Modernization)
- SEC Interactive Data Public Test Suite (for predicate semantics + case corroboration)
- SEC EDGAR XBRL Validation Errors catalog (for canonical error IDs/codes)

Secondary sources (context only): the three articles below. Before shipping, replace these labels with concrete titles + URLs and ensure all shipped mappings are grounded in the primary sources above.

| Article | Core content | XEW relevance |
|---------|-------------|---------------|
| **1. EDGAR structured-data suspensions coming March 2026** | SEC/EDGAR will suspend filings for incorrect/incomplete structured fee exhibits starting March 16, 2026. The safety net of non-suspension-level handling is being removed. | The "why now" — accepted filings can become rejected filings under the enforcement shift. Classic XEW break trigger. |
| **2. SEC error codes + FFD taxonomy** | Catalogs specific EDGAR XBRL validation error codes (e.g., 11010201, 11010401) and Filing Fee Disclosure (FFD) taxonomy rules. | The reclassification map — which specific validation conditions are being promoted to suspension-level. |
| **3. Arelle + SEC test suite in CI** | Recommends `arelleCmdLine --validate` against the SEC Interactive Data Public Test Suite. Names the exact toolchain XEW already uses. | The toolchain — Arelle loads fee exhibit models, P006 inspects them directly. SEC test suite validates our check logic. |

### Why This Fits XEW (and Not Just "Run a Validator")

The naive approach is: "run validation on the fee exhibit and report errors." Any filing vendor already does this. XEW's value is different:

1. **XEW analyzes accepted filings retrospectively.** The filer already submitted. The filing was accepted. XEW scans the accepted artifact and flags defects that were tolerated but are about to become fatal. The filer's toolchain may not re-run validation on past filings.

2. **The reclassification is the finding, not the defect itself.** P006 detects missing `ffd:FormTp` — same as a validator. But the finding it emits isn't "you have a missing `ffd:FormTp`." It's: "Your S-1 filed 2025-11-15 (accession 0001234-25-000042) was accepted with a fee-exhibit defect on a rule that SEC/EDGAR have announced will be enforced as suspension-level starting March 16, 2026. Here's the evidence and the citations." The detection is identical; the framing and packaging are not.

3. **The Evidence Pack cites the reclassification, not just the rule.** The rule basis isn't "XBRL spec says FormTp is required" (the filer's vendor already knows that). The rule basis is "SEC/EDGAR announced (announcement date pinned in the Evidence Pack) that these rules become suspension-level on March 16, 2026" + the specific defect found in the accepted filing + the SEC error code being reclassified.

### GTM Context

This enhancement is step 1 of a 3-part GTM strategy:

1. **XEW engine** (this plan) - Detect reclassified fee-exhibit conditions in accepted past filings
2. **Kovrex agent** (follow-on) - Wrap XEW as an opinionated agent on kovrex.ai
3. **CMD+RVL Outcomes** (follow-on) - Host as an Outcome on cmdrvl.com ("give us your portfolio, we will send you alerts")

The time-pressure GTM pitch: _"Your last filing was accepted, but its fee exhibit contains conditions being reclassified to suspension-level on March 16. Here's the evidence."_

---

## 2. Architecture Decision

### Repurpose P006

**Decision**: Use `XEW-P006` for fee exhibit fragility detection.

P006 was previously reserved in the plan doc for "Ambiguous Dimensional Member Reuse" (roadmap status, semantic, never shipped, unlikely to ship). P007 is reserved for "Duplicate-by-Substance Contexts." Repurposing P006 provides cleaner numbering (P001-P006 covers the full v1+fee detection surface).

The old P006 definition in `docs/PLAN_EDGAR_NEXT_XBRL_EARLY_WARNING.MD` must be updated to note the retirement and redirection.

### Single Detector, Multiple Issue Codes

**Decision**: One new detector (`XEW-P006: Fee Exhibit Fragility`) with multiple issue codes.

Rationale: Fee exhibit fragility is a single domain — reclassified fee-exhibit validation conditions on fee-exhibit artifacts. One finding per filing, multiple instances per reclassified condition found. This follows the existing detector pattern (analogous to P002's multiple anchoring issue codes) and avoids fragmenting the pattern catalog.

### Detection Method: Direct Model Inspection (Same as P001-P005)

**Decision**: P006 inspects the fee exhibit XBRL model directly, the same way P001-P005 inspect the primary document model. No Arelle warning capture, no pattern matching against Arelle output.

P006 checks for specific FFD facts and properties in the parsed model:
- **Must-ship**: presence of `ffd:FormTp`, `ffd:FeeExhibitTp` (and not nil/empty per SEC semantics)
- **Phase 4 (post-ship)**: presence of `ffd:TtlFeeAmt`, arithmetic consistency of fee line items (defer until SEC-code + test-suite confirmation)

This is the same pattern as P004 checking for missing units or invalid decimals on numeric facts.

The **reclassification context** (prior_consequence, new_consequence, effective_date, SEC error code) is metadata attached to the finding, not a detection mechanism. The Evidence Pack cites the SEC reclassification announcement and the underlying rule. How the defect was detected (model inspection) is independent of how the finding is framed (reclassification).

This avoids introducing a second detection paradigm (Arelle warning capture + pattern matching) that would be architecturally inconsistent with P001-P005 and fragile (dependent on Arelle message format stability, warning severity classification, and programmatic capture methods).

### Fee Exhibits Are Separate XBRL Instances

**Decision**: Fee exhibits load as a separate Arelle model, passed via an extended `DetectorContext`.

Fee exhibits use the FFD (Filing Fee Disclosure) taxonomy, not US-GAAP/IFRS. They're expected to load as distinct XBRL instances; confirm this in the Phase 1 spike (if fee data is embedded in the primary, adjust to inspect the primary model instead of loading a second model). The approach:

- Extend `DetectorContext` with optional `fee_exhibit_model`, `fee_exhibit_source_path`, and `fee_exhibit_sha256` fields
- P006 checks `should_run()` by testing whether a fee exhibit model is present
- Existing P001-P005 detectors are unaffected (they ignore the new fields)
- The `pack` command accepts a `--fee-exhibit` path for the fee exhibit iXBRL document

---

## 3. Issue Codes and SEC Error Code Mappings

### Reclassification Framing

P006's issue codes represent **non-suspension-level → suspension-level reclassifications**, not just defect categories. Each issue code says: "This accepted filing has a fee-exhibit defect on a rule that becomes suspension-level on March 16 under the announced enforcement shift."

### Issue Code Catalog (P006)

| XEW Issue Code | SEC Validation Error ID | SEC Validation Error Code | Reclassification | Ship priority |
|---|---|---|---|---|
| `fee_reclassified_form_type` | ft-FormTp-Missing | 11010201 | Non-suspension-level missing `ffd:FormTp` becomes suspension-level | **Must-ship** |
| `fee_reclassified_exhibit_type` | ft-FeeExhibitTp-Missing | 11010401 | Non-suspension-level missing `ffd:FeeExhibitTp` becomes suspension-level | **Must-ship** |
| `fee_reclassified_total_amount` | TBD | TBD | Non-suspension-level missing `ffd:TtlFeeAmt` becomes suspension-level | Phase 4 (requires confirmed SEC code + test-suite case) |
| `fee_reclassified_total_inconsistency` | TBD | TBD | Non-suspension-level fee total / line item mismatch becomes suspension-level | Phase 4 |
| `fee_reclassified_prior_paid` | TBD | TBD | Non-suspension-level prior paid > total becomes suspension-level | Phase 4 |
| `fee_exhibit_unparseable` | NA | NA | Fee exhibit fails Arelle load entirely (not a reclassification — this is a structural defect that blocks all further analysis) | Phase 4 |

Interpretation: the SEC validation error code is the numeric code (e.g., `11010201`); the SEC validation error ID is the symbolic identifier used in SEC materials/test cases (when available).

**Naming convention**: `fee_reclassified_*` — the prefix makes explicit that the finding is about a non-suspension-level condition being promoted to suspension-level, not about a defect being discovered. This is the key distinction between P006 and a validator.

**Notes**:
- TBD codes must be confirmed from the SEC Interactive Data Public Test Suite and EDGAR XBRL Validation Errors catalog before those issue codes can ship (Phase 4)
- The must-ship set targets only reclassifications with confirmed SEC error codes and a Gate-compliant rule basis (including test-suite corroboration)
- `fee_exhibit_unparseable` is an exception — it's not a reclassification but a structural defect that prevents any further analysis. It's deferred to Phase 4.
- Keep the shipped reclassification map minimal: the v1 map file should contain only SEC-confirmed must-ship entries; Phase 4 expansions land via a new map version after confirmation.
- Treat the SEC ID/code values in this table as expected values until verified against SEC primary sources (test suite + error catalog); update if any mismatch is found.

### Mapping Gate (SEC-Canonical)

P006 only ships issue codes that can be tied to an SEC-published validation error **and** corroborated by at least one concrete example from the SEC Interactive Data Public Test Suite.

Concretely, for any shipped `fee_reclassified_*` issue code:
- The detector predicate must match the SEC error semantics (not just a guess like "missing fact").
- For "presence" predicates, confirm whether nil/empty facts count as missing in SEC semantics (use the SEC test suite) and implement the predicate accordingly.
- The reclassification map entry must include a pointer to the SEC test suite case ID(s) (or equivalent SEC-published error catalog entry) used to validate the mapping.
- If we cannot tie an issue code to a specific SEC error with test-suite corroboration, it does not ship (remains deferred/unimplemented) until it can be grounded in SEC sources.

### Break Triggers

P006 findings use existing break trigger `XEW-BT004` (Validator/Enforcement Tightening) as the primary trigger. This is the textbook case for BT004: rules that were previously non-suspension-level are being enforced as suspension-level errors on a specific date.

### Rule Basis

P006's rule basis is **two-layered** — it cites both the underlying rule AND the reclassification announcement:

| Layer | Source | Citation | What it proves |
|-------|--------|----------|----------------|
| **Rule** | SEC EFM / EDGAR XBRL Guide | FFD validation rules (e.g., "ffd:FormTp is required") | The underlying rule the condition is based on |
| **Reclassification** | SEC/EDGAR announcement implementing Final Rule 33-11079 | "Starting March 16, 2026, EDGAR will suspend filings..." | That the condition is being promoted to suspension-level |

Both layers are required for a P006 finding to pass the Gate. The rule alone is not sufficient (that's just validation). The reclassification alone is not sufficient (that's just news). Together they prove: "this accepted filing exhibits a condition on a rule that is being reclassified as fatal."

Each citation requires `retrieved_at`, `sha256`, `url` per the existing Gate requirements.

---

## 4. Detector Design

### Core Logic: Direct Model Inspection + Reclassification Metadata

P006 inspects the fee exhibit XBRL model directly — the same pattern as P001-P005. It checks for specific FFD facts and properties, then attaches reclassification context (SEC error code, consequence change, effective date) as metadata on each finding instance.

This keeps P006 architecturally consistent with the existing detector family and avoids fragile dependencies on Arelle's warning message format.

### Reclassification Metadata (New Spec File)

A new spec file: `src/cmdrvl_xew/spec/fee_exhibit_reclassification_map.v1.json`

This is a **metadata reference**, not a pattern-matching engine. It documents which SEC error codes are being reclassified and maps them to P006 issue codes. The detector reads this to populate finding instance data.

```json
{
  "schema_id": "cmdrvl.fee_exhibit_reclassification_map",
  "schema_version": "1.0",
  "effective_date": "2026-03-16",
  "authority": "SEC Final Rule 33-11079 (Filing Fee Disclosure and Payment Methods Modernization) / EDGAR implementation guidance",
  "reclassifications": [
    {
      "xew_issue_code": "fee_reclassified_form_type",
      "sec_error_id": "ft-FormTp-Missing",
      "sec_error_code": "11010201",
      "ffd_concept_local_name": "FormTp",
      "check_type": "presence",
      "prior_consequence": "non_suspension_level",
      "new_consequence": "suspension_level",
      "effective_date": "2026-03-16",
      "sec_test_suite_case_ids": ["<SEC-IDPTS-case-id>"]
    },
    {
      "xew_issue_code": "fee_reclassified_exhibit_type",
      "sec_error_id": "ft-FeeExhibitTp-Missing",
      "sec_error_code": "11010401",
      "ffd_concept_local_name": "FeeExhibitTp",
      "check_type": "presence",
      "prior_consequence": "non_suspension_level",
      "new_consequence": "suspension_level",
      "effective_date": "2026-03-16",
      "sec_test_suite_case_ids": ["<SEC-IDPTS-case-id>"]
    }
  ]
}
```

Notes:
- `sec_test_suite_case_ids` should use stable identifiers (e.g., relative paths within the SEC Interactive Data Public Test Suite, or any SEC-published case IDs).
- Any change to the map entries (adding/removing/modifying reclassifications) is output-affecting. Bump `schema_version` when entries change and record the map file sha256 in toolchain metadata to prevent silent drift.

### Pseudocode

```python
# Loaded from fee_exhibit_reclassification_map.v1.json (source of truth for the must-ship set).
P006_RECLASSIFICATIONS = load_fee_exhibit_reclassification_map()["reclassifications"]

# Phase 4 expands checks post-ship after SEC-code + test-suite confirmation (e.g., ffd:TtlFeeAmt presence,
# arithmetic consistency, and other fee-exhibit-specific rules).


class FeeExhibitFragilityDetector(BaseDetector):

    @property
    def pattern_id(self) -> str:
        return "XEW-P006"

    @property
    def pattern_name(self) -> str:
        return "Fee Exhibit Fragility"

    @property
    def alert_eligible(self) -> bool:
        return True

    def should_run(self, context: DetectorContext) -> bool:
        return context.fee_exhibit_model is not None

    def detect(self, context: DetectorContext) -> List[DetectorFinding]:
        model = context.fee_exhibit_model
        facts = getattr(model, "facts", [])

        # Build set of FFD fact local names present in the exhibit.
        # Filter to FFD namespace(s) to avoid local-name collisions with non-FFD facts.
        # The expected FFD namespace URI substring should be confirmed during Phase 1 spike.
        FFD_NAMESPACE_SUBSTRING = "xbrl.sec.gov/ffd"  # expected; confirm during Phase 1 spike
        present_concepts = {
            f.qname.localName for f in facts
            if hasattr(f, 'qname') and f.qname is not None
            and FFD_NAMESPACE_SUBSTRING in str(getattr(f.qname, "namespaceURI", "") or "")
        }
        # Note: SEC semantics may treat nil/empty facts as missing; confirm in Phase 1 spike + SEC test suite and implement presence accordingly.

        instances = []
        for entry in P006_RECLASSIFICATIONS:
            issue_code = entry["xew_issue_code"]
            if entry["check_type"] == "presence":
                if entry["ffd_concept_local_name"] not in present_concepts:
                    sig = canonical_signature_p006(
                        issue_code=issue_code,
                        exhibit_sha256=context.fee_exhibit_sha256,  # sha256 of exact bytes copied to artifacts/fee_exhibit.html
                        sec_error_code=entry["sec_error_code"],
                    )
                    instances.append(DetectorInstance(
                        instance_id=instance_id_from_signature(sig),
                        kind="fee_exhibit_reclassification",
                        primary=(len(instances) == 0),
                        data={
                            "issue_code": issue_code,
                            "ffd_concept_local_name": entry["ffd_concept_local_name"],
                            "sec_error_code": entry["sec_error_code"],
                            "sec_error_id": entry["sec_error_id"],
                            "prior_consequence": entry["prior_consequence"],
                            "new_consequence": entry["new_consequence"],
                            "effective_date": entry["effective_date"],
                            "fee_exhibit_artifact_path": "artifacts/fee_exhibit.html",
                            "details": f"Missing ffd:{entry['ffd_concept_local_name']} (reclassified effective {entry['effective_date']}).",
                        },
                    ))

        if not instances:
            return []

        return [DetectorFinding(
            finding_id=self.generate_finding_id(context),
            pattern_id=self.pattern_id,
            pattern_name=self.pattern_name,
            alert_eligible=self.alert_eligible,
            status="detected",
            break_triggers=self.get_break_triggers(),
            rule_basis=self.load_rule_basis(),
            instances=instances,
        )]

    def get_break_triggers(self) -> List[Dict[str, str]]:
        return [
            {"id": "XEW-BT004",
             "summary": "Validator Tightening - EDGAR reclassifying fee "
                        "exhibit defects from non-suspension-level to suspension-level (March 16, 2026)"},
        ]
```

This is structurally similar to how P004 iterates facts and checks properties. The reclassification metadata (`prior_consequence`, `new_consequence`, `effective_date`) is attached to each instance but doesn't change the detection mechanism.

### Canonical Signatures

P006 uses **document-level + condition-level** signatures:

```
sig = "v1|P006|{issue_code}|exhibit_sha256={sha256_of_fee_exhibit_bytes}|sec_error={sec_error_code}"
instance_id = sha256(sig)
```

Where:
- `{issue_code}` is the XEW issue code (e.g., `fee_reclassified_form_type`)
- `{sha256_of_fee_exhibit_bytes}` is the SHA-256 of the exact fee exhibit bytes copied to `artifacts/fee_exhibit.html` (exposed to the detector as `context.fee_exhibit_sha256`)
- `{sec_error_code}` is the SEC error code being reclassified (e.g., `11010201`)

Note: for issue codes without an SEC error code (e.g., `fee_exhibit_unparseable` in Phase 4), set `{sec_error_code}` to a fixed sentinel (e.g., `NA`) for signature stability.

This ensures deterministic IDs: the same fee exhibit with the same reclassified condition always produces the same instance ID.

Add to `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`:
```
- `XEW-P006` (fee exhibit fragility):
  - `sig = "v1|P006|<issue_code>|exhibit_sha256=<sha256(fee_exhibit_bytes)>|sec_error=<sec_error_code>"`
```

### Instance Data Schema

Each P006 instance uses a dedicated instance kind (new; e.g., `fee_exhibit_reclassification`). Example `instance.data` payload:

```json
{
  "issue_code": "fee_reclassified_form_type",
  "ffd_concept_local_name": "FormTp",
  "sec_error_code": "11010201",
  "sec_error_id": "ft-FormTp-Missing",
  "prior_consequence": "non_suspension_level",
  "new_consequence": "suspension_level",
  "effective_date": "2026-03-16",
  "fee_exhibit_artifact_path": "artifacts/fee_exhibit.html",
  "details": "This accepted filing is missing ffd:FormTp in its fee exhibit. SEC/EDGAR have announced suspension-level enforcement for incorrect/incomplete structured fee exhibits starting March 16, 2026."
}
```

`fee_exhibit_artifact_path` is the pack-relative path to the copied fee exhibit artifact (under `artifacts/`).

The `prior_consequence` / `new_consequence` / `effective_date` triple is the P006-specific payload that no validator provides. It answers: "why should I care about a defect that was accepted?"

---

## 5. Pipeline Changes

### DetectorContext Extension

In `src/cmdrvl_xew/detectors/_base.py`:

```python
# typing: from typing import Any, Dict, Optional
@dataclass
class DetectorContext:
    primary_document_path: str
    artifacts_dir: str
    cik: str
    accession: str
    form: str
    filed_date: str
    xbrl_model: Any              # Arelle model for primary document
    config: Dict[str, Any]
    # NEW: fee exhibit support
    fee_exhibit_model: Any = None                 # Arelle model for fee exhibit (optional)
    fee_exhibit_source_path: Optional[str] = None # Source path to fee exhibit iXBRL file (optional)
    fee_exhibit_sha256: Optional[str] = None      # sha256 of exact fee exhibit bytes (optional; copied artifact)
```

Three new optional fields. No warning capture infrastructure. P006 inspects `fee_exhibit_model` directly, same as P001-P005 inspect `xbrl_model`.

### CLI Changes

In `src/cmdrvl_xew/cli.py`, add to `pack` subcommand:

```
--fee-exhibit PATH    Path to fee exhibit iXBRL file (optional; enables P006)
```

Scope note (v1): support a single fee exhibit input per pack. Multi-fee-exhibit filings (if any) are deferred.

Validation rule (v1): require `--fee-exhibit` to reside in the same flat artifact directory as `--primary` so local relative references resolve deterministically (avoid introducing a second artifact-root abstraction in v1).

Manifest provenance (v1): when `--derive-artifact-urls` is enabled, populate `source_url` for the stable pack path `artifacts/fee_exhibit.html` by joining the primary document base URL with the fee exhibit input basename (so the stable pack filename still points back to the correct EDGAR artifact URL).

### Pack Pipeline

In `src/cmdrvl_xew/pack.py`:

1. Accept `--fee-exhibit` argument
2. When provided, load fee exhibit as a second Arelle model (separate DTS from primary)
3. Compute `fee_exhibit_sha256` (exact bytes) and pass to `DetectorContext` as `fee_exhibit_model`, `fee_exhibit_source_path`, and `fee_exhibit_sha256`
4. Copy the fee exhibit to `artifacts/fee_exhibit.html` (fixed name, analogous to `primary.html`), and include any local referenced artifacts required to load it (schema/linkbases present in the artifact set) in the Evidence Pack `artifacts/` directory
5. Record fee exhibit metadata in `pack_manifest.json`

Implementation note: collect fee-exhibit-referenced artifacts with the same `collect_artifacts(...)` logic used for the primary document, then union the two artifact sets deterministically (dedupe by relative path; fail fast if a relative path would collide with different bytes).

### Flatten

In `src/cmdrvl_xew/flatten.py`:

- Recognize fee exhibit typed directories alongside `EX-101.*` (directory naming to be confirmed from real accessions; `EX-FILING FEES` is the likely label)
- Copy fee exhibit iXBRL file(s) to the flat output directory
- Ensure any fee-exhibit-referenced local XBRL artifacts are present in the flat output (extract fee exhibit `schemaRef` when possible; otherwise fall back to scanning `EX-101.*` for XBRL files)
- Print the copied fee exhibit filenames so users can supply `--fee-exhibit` deterministically

### Fetch

In `src/cmdrvl_xew/edgar_fetch.py`:

- Recognize fee exhibit files in the EDGAR accession index
- Download them alongside primary and extension artifacts
- Fee exhibits are identified by a fee-exhibit document type in the filing index (label to be confirmed from real accessions; `EX-FILING FEES` is the likely string)

---

## 6. Files to Create and Modify

### New Files

| File | Purpose |
|------|---------|
| `src/cmdrvl_xew/detectors/p006_fee_exhibit.py` | P006 detector: direct model inspection + reclassification metadata |
| `src/cmdrvl_xew/spec/fee_exhibit_reclassification_map.v1.json` | Metadata reference: SEC error codes being promoted to suspension-level |
| `tests/test_p006_fee_exhibit.py` | Unit tests (mock Arelle model facts + reclassification metadata) |

### Files to Modify

| File | Change |
|------|--------|
| `src/cmdrvl_xew/detectors/_base.py` | Add `fee_exhibit_model`, `fee_exhibit_source_path`, `fee_exhibit_sha256` to `DetectorContext` |
| `src/cmdrvl_xew/detectors/registry.py` | Add `XEW-P006` to `PATTERN_PRIORITIES` dict |
| `src/cmdrvl_xew/util.py` | Add `canonical_signature_p006()` function |
| `src/cmdrvl_xew/spec/xew_issue_codes.v1.json` | Add `XEW-P006` pattern with `fee_reclassified_*` issue codes |
| `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json` | Add P006 two-layer rule basis (underlying rule + reclassification citation) |
| `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json` | Add `XEW-P006` to `pattern_id` enum; add `fee_exhibit_reclassification` instance kind + data schema |
| `src/cmdrvl_xew/pack.py` | Accept `--fee-exhibit` path, load second Arelle model, pass to DetectorContext |
| `src/cmdrvl_xew/cli.py` | Add `--fee-exhibit` argument to `pack` subcommand |
| `src/cmdrvl_xew/flatten.py` | Recognize `EX-FILING FEES` directories |
| `src/cmdrvl_xew/edgar_fetch.py` | Recognize and download fee exhibit files from EDGAR accession index |
| `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD` | Add P006 canonical signature spec |
| `docs/PLAN_EDGAR_NEXT_XBRL_EARLY_WARNING.MD` | Update P006 entry (retire old definition, redirect to this plan) |

---

## 7. Testing Strategy

### Unit Tests (`tests/test_p006_fee_exhibit.py`)

P006 tests follow the same pattern as P001/P004 tests: mock the Arelle model, inject facts, verify findings. No warning capture to test.

```python
class TestFeeExhibitFragilityDetector(unittest.TestCase):
    def setUp(self):
        self.detector = FeeExhibitFragilityDetector()
        self.mock_context = Mock(spec=DetectorContext)
        self.mock_context.fee_exhibit_sha256 = "0" * 64  # stable test value

    def _create_mock_model(self, fact_local_names):
        """Create mock Arelle model with facts having the given local names."""
        model = Mock()
        facts = []
        for name in fact_local_names:
            fact = Mock()
            fact.qname = Mock()
            fact.qname.localName = name
            # Ensure the mock facts pass any namespace filter used by the detector.
            fact.qname.namespaceURI = "http://xbrl.sec.gov/ffd"
            facts.append(fact)
        model.facts = facts
        return model

    # --- should_run guard ---
    def test_should_run_no_fee_exhibit(self):
        """P006 skips when no fee exhibit is present."""
        self.mock_context.fee_exhibit_model = None
        self.assertFalse(self.detector.should_run(self.mock_context))

    def test_should_run_with_fee_exhibit(self):
        """P006 runs when fee exhibit model is present."""
        self.mock_context.fee_exhibit_model = Mock()
        self.assertTrue(self.detector.should_run(self.mock_context))

    # --- presence checks ---
    def test_missing_form_type_produces_finding(self):
        """Fee exhibit missing ffd:FormTp produces a P006 finding."""
        self.mock_context.fee_exhibit_model = self._create_mock_model(
            ["FeeExhibitTp"]  # FormTp absent
        )
        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 1)
        issue_codes = [i.data["issue_code"] for i in findings[0].instances]
        self.assertIn("fee_reclassified_form_type", issue_codes)

    def test_all_required_facts_present_no_finding(self):
        """Fee exhibit with all required FFD facts produces no finding."""
        self.mock_context.fee_exhibit_model = self._create_mock_model(
            ["FormTp", "FeeExhibitTp"]
        )
        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 0)

    def test_multiple_missing_facts(self):
        """Multiple missing facts produce one finding with multiple instances."""
        self.mock_context.fee_exhibit_model = self._create_mock_model([])  # all absent
        findings = self.detector.detect(self.mock_context)
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(findings[0].instances), 2)  # FormTp, FeeExhibitTp

    # --- instance data correctness ---
    def test_instance_carries_reclassification_context(self):
        """Each instance includes prior_consequence, new_consequence, effective_date."""
        self.mock_context.fee_exhibit_model = self._create_mock_model(
            ["FeeExhibitTp"]  # FormTp absent
        )
        findings = self.detector.detect(self.mock_context)
        instance = findings[0].instances[0]
        self.assertEqual(instance.data["prior_consequence"], "non_suspension_level")
        self.assertEqual(instance.data["new_consequence"], "suspension_level")
        self.assertEqual(instance.data["effective_date"], "2026-03-16")
        self.assertEqual(instance.data["sec_error_code"], "11010201")

    # --- canonical signature determinism ---
    def test_canonical_signature_deterministic(self): ...

    # --- break trigger presence ---
    def test_break_triggers_present(self):
        triggers = self.detector.get_break_triggers()
        self.assertTrue(any(t["id"] == "XEW-BT004" for t in triggers))

    # --- properties ---
    def test_pattern_id(self):
        self.assertEqual(self.detector.pattern_id, "XEW-P006")

    def test_alert_eligible(self):
        self.assertTrue(self.detector.alert_eligible)
```

### Integration Tests

Add fee exhibit scenario to `tests/test_end_to_end_pack_verify.py`:

- Create a minimal fee exhibit iXBRL fixture with known missing FFD facts
- Run `pack` with `--fee-exhibit` pointing to the fixture
- Verify Evidence Pack includes fee exhibit artifact + P006 findings with reclassification context
- Verify `verify-pack` passes on the resulting pack

### Real-Filing Validation (Dev-Time Only, Not Committed)

The key validation: run P006 against accepted filings and confirm the defect rate is non-trivial.

1. Assemble a list of fee-bearing accessions (start with S-1, S-3, F-1), then fetch artifacts per accession using `cmdrvl-xew fetch`
2. Run `pack --fee-exhibit` on a sample — confirm P006 fires on filings with missing FFD facts
3. Confirm P006 does NOT fire on clean fee exhibits (no false positives)
4. Estimate the defect rate across the corpus — this is the market sizing validation
5. Document results in internal notes (not committed to repo)

---

## 8. Implementation Sequence

With direct model inspection (no Arelle warning capture), the estimated build time is ~7 days. P006 is structurally similar to P004 — just a different model and different checks.

### Phase 1: Spike + Foundation (Days 1-2)

| Step | Task | Output |
|------|------|--------|
| 1 | **Spike: validate the market** — Fetch an initial 10 real fee exhibits from EDGAR (S-1, S-3), load them in Arelle, inspect for must-ship `ffd:FormTp` / `ffd:FeeExhibitTp` presence (and optionally `ffd:TtlFeeAmt` to size Phase 4). If we observe at least one must-ship defect: proceed. If we observe zero in the initial sample: expand to ~30 across multiple issuers before concluding the defect rate is low (small-n "zero observed" is not evidence of zero prevalence; rule of three: 0 observed in n=30 implies ~10% 95% upper bound on prevalence). | Defect rate estimate + confirmed FFD concept names |
| 2 | Extend `DetectorContext` with `fee_exhibit_model` / `fee_exhibit_source_path` / `fee_exhibit_sha256` in `_base.py` | Updated dataclass, existing detectors unaffected |
| 3 | Add `canonical_signature_p006()` to `util.py` | New canonicalization function |
| 4 | Create `p006_fee_exhibit.py` skeleton (`should_run()`, `detect()`); wire it to load `fee_exhibit_reclassification_map.v1.json` (Step 6) into e.g. `P006_RECLASSIFICATIONS` | Detector auto-discovered by registry |
| 5 | Add P006 to `xew_issue_codes.v1.json`, `PATTERN_PRIORITIES` in `registry.py`, schema enum | P006 wired into the system |
| 6 | Create `fee_exhibit_reclassification_map.v1.json` metadata reference | Reclassification metadata documented |
| 7 | Add two-layer rule basis entries to `xew_rule_basis_map.v1.json` | Gate-compliant rule basis |
| 8 | Write unit tests: properties, `should_run` guard, presence checks, reclassification metadata on instances, canonical signature determinism | Green tests |

### Phase 2: Pipeline Integration (Days 3-5)

| Step | Task | Output |
|------|------|--------|
| 9 | Add `--fee-exhibit` CLI argument to `pack` subcommand, load second Arelle model, pass to DetectorContext | CLI accepts fee exhibits |
| 10 | Extend `flatten.py` for `EX-FILING FEES` directories | Flatten handles fee exhibits |
| 11 | Extend `edgar_fetch.py` to recognize and download fee exhibit files from EDGAR index | Fetch handles fee exhibits |
| 12 | Add integration test: end-to-end pack/verify with fee exhibit fixture | Integration test green |
| 13 | Handle fee exhibit Arelle load failures gracefully (no crash; log a warning, set `fee_exhibit_model=None` so P006 skips). The `fee_exhibit_unparseable` issue code (Phase 4 in Section 3) would change this to emit a finding instead of skipping — defer that until Phase 4. | Robustness |

### Phase 3: Validation + Ship (Days 6-7)

| Step | Task | Output |
|------|------|--------|
| 14 | Test against real accepted filings from EDGAR sample. Confirm P006 fires on filings with missing FFD facts and doesn't fire on clean ones. | Validated against real filings |
| 15 | Update `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD` (P006 canonical signature spec) | Contract updated |
| 16 | Update `docs/PLAN_EDGAR_NEXT_XBRL_EARLY_WARNING.MD` (retire old P006, note redirection) | Plan doc consistent |
| 17 | Full test suite pass (`PYTHONPATH=src python3 -m unittest discover -s tests`) | All green |
| 18 | Cut release | Shippable |

### Phase 4: Extended Checks (Post-Ship, Optional)

| Step | Task | Output |
|------|------|--------|
| 19 | Research and confirm SEC error codes for `fee_reclassified_total_amount`, `fee_reclassified_total_inconsistency`, and `fee_reclassified_prior_paid` | Confirmed codes |
| 20 | Implement arithmetic consistency checks (fee line items sum to `ffd:TtlFeeAmt`) | Extended detection |
| 21 | Add corresponding unit tests and rule basis entries | Coverage for extended checks |

---

## 9. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Spike shows zero defects** — sampled accepted filings have clean fee exhibits, P006 rarely/never fires | **High** — no market for the detector | Unknown (but see note) | Phase 1 Step 1 validates this before any engineering. Inspect an initial sample (~10) and, if zero observed, expand the sample (~30, multiple issuers) before concluding the defect rate is low. If still zero after ~30, treat it as evidence the prevalence is likely <~10% at 95% confidence (rule of three) and reconsider scope or pivot to other fee-exhibit checks with confirmed SEC mappings. Note: the SEC's decision to reclassify these conditions to suspension-level is indirect evidence that the conditions fire often enough to matter — but this inference has not been validated empirically. |
| **FFD concept names vary across taxonomy versions** — `FormTp` in one FFD release might be named differently in another | **Medium** — false negatives on newer/older filings | Unknown | Phase 1 spike checks concept names and namespaces across the FFD versions present in real filings. Prefer matching by namespace+localName when possible; record observed FFD namespace(s) in the Evidence Pack. |
| FFD taxonomy won't load in Arelle | **High** — no detection possible | Unknown | Test in Phase 1 spike and document required taxonomy packages/config (including any required taxonomy package installs). If Arelle loading cannot be made deterministic with pinned inputs, treat as a ship blocker for P006. |
| Exact SEC error codes unknown for Phase 4 checks (TBD codes) | **Medium** — can't ship Phase 4 expansions (`fee_reclassified_total_amount`, `fee_reclassified_total_inconsistency`, `fee_reclassified_prior_paid`) without confirmed codes | Medium | Ship must-ship set first (confirmed codes). Keep TBD-coded issue codes non-shipping until confirmed via SEC sources; Gate suppresses findings without valid rule basis. |
| Fee exhibit not present in older filings | **Low** — reduced detection coverage for historical analysis | High for older filings (varies by form) | P006 gracefully skips when no fee exhibit is present (`should_run` guard). |
| Arelle loading two models in one pack run causes memory/conflict issues | **Medium** — pack failures | Unknown | Fee exhibit model is loaded independently. Use separate Arelle controller instances if needed. Test in Phase 2. |
| **P006's value window is narrow** — after March 16, EDGAR enforces directly | **Low** — P006 is intentionally a wedge for P001-P005 adoption (see Section 11) | Certain | By design. P006 creates urgency to run XEW. P001-P005 findings on the same filings are evergreen. The first scan is the conversion event. |

---

## 10. Verification Steps

After implementation, verify end-to-end:

```bash
# 1. Install + run tests
cd /path/to/cmdrvl-xew
pip install -e '.[jsonschema]'
PYTHONPATH=src python3 -m unittest discover -s tests

# 2. Fetch a real accepted filing with fee exhibit
cmdrvl-xew fetch --cik <CIK> --accession <ACC> --out /tmp/flat \
  --user-agent "CMD+RVL XEW test@cmdrvl.com"

# Alternative to fetch (when you already have a typed EDGAR accession directory on disk):
# cmdrvl-xew flatten /path/to/<accession-dir> --out /tmp/flat

# 3. Pack with fee exhibit
# Use the primary iXBRL filename printed by fetch/flatten, and select the fee exhibit
# filename from the downloaded/copied list.
cmdrvl-xew pack --pack-id XEW-EP-FEE-TEST --out /tmp/pack \
  --primary /tmp/flat/primary.htm \
  --fee-exhibit /tmp/flat/fee-exhibit.htm \
  --cik <CIK> --accession <ACC> --form S-1 \
  --filed-date 2026-01-15 \
  --primary-document-url <URL> \
  --retrieved-at 2026-02-08T12:00:00Z

# 4. Verify pack + schema
cmdrvl-xew verify-pack --pack /tmp/pack --validate-schema

# 5. Inspect findings — verify reclassification context
python -m json.tool /tmp/pack/xew_findings.json
# Expected: XEW-P006 findings with reclassification context
# Each finding should have:
#   - pattern_id: "XEW-P006"
#   - instances with: issue_code (fee_reclassified_*), sec_error_code,
#     sec_error_id, prior_consequence ("non_suspension_level"),
#     new_consequence ("suspension_level"), effective_date ("2026-03-16")
#   - break_triggers including XEW-BT004
#   - rule_basis with TWO layers: underlying rule + reclassification citation
```

### Determinism Check

```bash
# Run pack twice with same inputs + same --retrieved-at
# Compare pack_sha256 values - must be identical
cmdrvl-xew pack ... --retrieved-at 2026-02-08T12:00:00Z --out /tmp/pack1
cmdrvl-xew pack ... --retrieved-at 2026-02-08T12:00:00Z --out /tmp/pack2
python -c 'import json; print(json.load(open("/tmp/pack1/pack_manifest.json"))["pack_sha256"])'
python -c 'import json; print(json.load(open("/tmp/pack2/pack_manifest.json"))["pack_sha256"])'
```

### Regression Check

```bash
# Existing P001-P005 tests must still pass
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_p001_duplicates.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_p002_anchoring.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_p004_type_unit.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_p005_taxonomy.py'

# End-to-end pack without fee exhibit must still work (P006 should_run = False)
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_end_to_end_pack_verify.py'
```

### Clean Exhibit Check

```bash
# Fetch a filing with a complete, well-formed fee exhibit
# Run P006 against it
# Expected: ZERO findings — confirms no false positives
```

---

## 11. GTM Context

### The Pitch (Reclassification, Not Validation)

The GTM message is NOT "your fee exhibit has errors" (every validator says that). The message is:

> **"Your last filing was accepted, but its fee exhibit contains conditions that are being reclassified to suspension-level starting March 16. Here's the evidence — the specific SEC validation IDs/rules affected, the reclassification citation, and the deadline."**

This is qualitatively different from validation output because:
- It starts with an **accepted filing** (the filer thinks they're fine)
- It references the **reclassification event** (the enforcement change, not just the rule)
- It includes an **Evidence Pack** with citations to both the underlying rule and the reclassification announcement
- It carries a **deadline** (March 16, 2026 — not "you should fix this sometime")

### Three Monetization Channels

| Channel | Surface | How P006 feeds it |
|---------|---------|-------------------|
| **Open-source XEW engine** | GitHub | Credibility + adoption. Anyone can run `cmdrvl-xew pack --fee-exhibit` against accepted filings. The reclassification context on each finding (SEC error code, consequence change, deadline) is what differentiates XEW from running a validator. |
| **Kovrex agent** (kovrex.ai) | API revenue | Agent takes a CIK, fetches the most recent accepted filing with a fee exhibit, runs P006, and returns: "N reclassified conditions found, M days until enforcement." Agents and filing vendors can call this via MCP/API. |
| **CMD+RVL Outcomes** (cmdrvl.com) | Recurring monitoring | "Give us your portfolio of CIKs, we monitor accepted filings for reclassified conditions and alert you before March 16." Outcome-grade: customer provides CIKs, CMD+RVL delivers early-warning signals with Evidence Pack provenance. |

### Time-Pressure Messaging

The March 16 deadline creates natural urgency, and the reclassification framing sharpens it:

- **Before March 16**: "Your last accepted filing contains fee-exhibit conditions that are currently non-suspension-level (often surfaced as warnings). On March 16, those conditions become suspension-level. XEW found [N] reclassified conditions. Here's the Evidence Pack."
- **After March 16**: "Your filing from [date] was accepted under the old enforcement regime. XEW identified [N] fee-exhibit conditions in that accepted artifact that SEC/EDGAR have announced will be enforced as suspension-level starting March 16, 2026."

### Wedge-to-Platform: P006 Opens the Door, P001-P005 Keep Them

P006's value window is narrow (~5 weeks before March 16). That's a feature, not a bug.

P006 is the **wedge** — the time-pressured finding that gets firms to run XEW for the first time. But `pack` runs all detectors. A firm that runs XEW because of P006's March 16 urgency also gets:

- **P001** findings: duplicate facts in their primary financial statements
- **P002** findings: unanchored or mis-anchored extension concepts
- **P004** findings: type/unit/numeric attribute violations
- **P005** findings: taxonomy version inconsistencies

These are evergreen. They don't expire on March 16. They apply to every filing, past and future.

The GTM sequence:
1. P006 creates urgency → firm runs `cmdrvl-xew pack --fee-exhibit` for the first time
2. P001-P005 fire on the same filing → firm discovers structural fragility beyond fees
3. P001-P005 keep firing on every subsequent filing → firm keeps using XEW

P006 is disposable. The relationship it creates is not. After March 16, the firm has seen its P001 duplicate-fact clusters and P002 anchoring gaps. Those don't go away because EDGAR started enforcing fee exhibits.

This also justifies the engineering investment: P006's 7-day build cost buys a GTM funnel into XEW's full detection surface, not just a 5-week detector.

### What This Is Not

Per XEW's existing positioning constraints, sharpened by the reclassification framing:

- NOT "we validate your filings" — P006 checks for the same conditions a validator would, but the finding is about the reclassification, not the defect. A validator tells you what's wrong right now. P006 tells you which conditions on your *accepted* filings are about to become suspension-level, with Evidence Pack citations to the SEC reclassification announcement.
- NOT "we replace your filing vendor" — vendor-neutral evidence. The Evidence Pack rule basis cites SEC announcements and SEC-published validation materials, not vendor-specific rules.
- NOT "we keep you compliant" — we show which accepted-filing conditions are being promoted and when. The filer decides what to do about it.
- NOT a filing preparation tool — post-filing, retrospective detection. P006 analyzes filings that have already been accepted.

---

## 12. Open Questions (Resolve in Phase 1 Spike)

### Critical (blocks must-ship)

1. **Do accepted filings actually have fee-exhibit defects on the must-ship checks?** The entire P006 premise rests on this. Fetch an initial ~10 real S-1/S-3 fee exhibits, load in Arelle, and check: (a) presence of `ffd:FormTp` / `ffd:FeeExhibitTp`, (b) optionally presence of `ffd:TtlFeeAmt` for Phase 4 sizing, (c) while inspecting, note any other obvious defects (wrong values, empty facts) that might indicate a richer defect surface than presence-only, and (d) confirm whether the structured fee exhibit is consistently a separate iXBRL document artifact (vs embedded in the primary). If zero defects are observed across the initial sample, expand to ~30 across multiple issuers before concluding the defect rate is low. This is the #1 question — answer it before writing any detector code.

2. **FFD concept local names**: Confirm that the must-ship local names (`FormTp`, `FeeExhibitTp`) are correct and stable across FFD taxonomy versions present in real filings (and optionally `TtlFeeAmt` for Phase 4 sizing). The spike resolves this empirically.

3. **Arelle FFD loading**: Does Arelle load FFD taxonomy from a standard taxonomy package, or does it require `arelle install-packages`? Test during the spike.

### Important (affects completeness)

4. **SEC error code completeness**: The TBD codes for `fee_reclassified_total_amount`, `fee_reclassified_total_inconsistency`, and `fee_reclassified_prior_paid` need confirmation from the SEC Interactive Data Public Test Suite or EDGAR XBRL Validation Errors catalog.

5. **Which SEC error codes are actually being reclassified?**: Confirm the complete list from the SEC announcement. Are there reclassifications beyond the fee-exhibit domain? (If so, future P006 expansion.)

6. **Fee exhibit form types**: Which form types commonly include fee exhibits? S-1, S-3, S-4, 424B, F-1? Affects GTM targeting (which CIKs to scan). If counts are used for sizing, pull them from a reproducible EDGAR query and record the query + as-of date (avoid hard-coded estimates here).

### Phase 4 (post-ship)

7. **Fee line item enumeration**: For `fee_reclassified_total_inconsistency`, which FFD facts constitute "fee line items" that should sum to `ffd:TtlFeeAmt`? Requires FFD taxonomy analysis.

---

## 13. Relationship to Existing Plan

This document extends `docs/PLAN_EDGAR_NEXT_XBRL_EARLY_WARNING.MD` (the master XEW outcome plan). Specifically:

- **P006 is being repurposed**: The old P006 ("Ambiguous Dimensional Member Reuse") is retired from the plan doc and replaced by "Fee Exhibit Fragility." The old definition was roadmap-only, semantic, and not safe to auto-alert.
- **P006 is alert-eligible in v1**: Unlike the old P006 (roadmap status), the new P006 enters the v1 shipping set because it detects objective, citable defects with reclassification context.
- **P006 is architecturally consistent with P001-P005**: All detectors inspect the XBRL model directly. P006 inspects the fee exhibit model for specific FFD facts/properties, the same way P004 inspects facts for type/unit violations. The reclassification context is metadata on the finding, not a different detection paradigm.
- **P006 is the GTM wedge**: Its narrow enforcement window (March 16, 2026) creates urgency that drives first-time XEW adoption. P001-P005 findings on the same filings are evergreen and keep firms engaged after the deadline passes.
- **Pattern priority**: P006 slots into `PATTERN_PRIORITIES` in `registry.py`. Suggested priority level: 2 (immediately after P001), bumping existing priorities down (P004→3, P005→4, P002→5). Rationale for P006 above P004: P006 has a hard enforcement deadline (March 16) while P004 violations are persistent but not date-driven. Keep priorities as integers (the registry expects ints).
- **Evidence Pack contract**: P006 canonical signature spec must be added to `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`.
- **Schema**: `xew_findings.schema.v1.json` must be extended with P006 pattern_id and instance data (including `prior_consequence`/`new_consequence`/`effective_date` reclassification context).
- **The reclassification map is a metadata reference**: It documents which SEC error codes are being promoted and maps them to P006 issue codes. It's a reference artifact, not a pattern-matching engine.
