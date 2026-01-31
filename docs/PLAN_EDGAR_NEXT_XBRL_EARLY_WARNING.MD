# CMD+RVL Outcome Plan: EDGAR Next XBRL Early Warning

## Objective (30-Day)
Ship a pilot that repeatably produces early-warning alerts when a monitored issuer's filed inline XBRL shows specific, reproducible fragility patterns that meet the plan's "elevated risk" definition for avoidable EDGAR rejection risk in the next filing cycle, with an Evidence Pack that can be handed to an SEC reporting team or filing vendor.

## Outcome (What the Customer Gets)
**Early warning when a monitored issuer's filed inline XBRL is enforcement-fragile under evolving EDGAR enforcement (including during EDGAR Next), surfaced as soon as the filing is analyzed (typically with lead time before the next submission).**

This is an outcome, not a tool, workflow, or service.

The customer does not "use" CMD+RVL day-to-day.
They **receive signals** when a concrete, testable fragility mechanism is observed.

---

## Definitions (Non-Negotiable)
### "Enforcement-fragile"
XBRL that:
- is accepted as filed on EDGAR (i.e., was accepted at submission time), but
- contains an observable pattern with a specific, testable break mechanism under (a) disclosure structure change, (b) taxonomy change, or (c) changes in EDGAR validation/enforcement behavior.

### "Alert"
A single alert-eligible pattern observation, tied to a specific filing artifact (or a specific delta vs the prior comparable filing), that can be reviewed in minutes.
In v1, alert-eligible patterns are the target v1 shipping patterns that pass the Gate (rule basis pinned), as listed below.

### "Evidence Pack"
A reproducible bundle (built from public artifacts: EDGAR filing artifacts plus any public taxonomy/rule sources needed to resolve/validate) that lets a third party confirm what CMD+RVL saw using the included artifacts + repro steps, without relying on opaque scoring or opinion.

### "Filing failure" (for this outcome)
Any avoidable late-cycle outcome where the issuer incurs urgent rework or delay due to an XBRL validation/rejection issue discovered too late (including EDGAR submission rejections that force rework, and deadline misses attributable to late-cycle XBRL rework).

### "EDGAR rejection" (for this outcome)
An EDGAR submission rejection attributable to XBRL/inline XBRL validation rules (fatal errors), not mere warnings.

### "Avoidable" (for this outcome)
A reject/failure that can be resolved by issuer/vendor changes to the filing artifacts (tagging, taxonomy packaging, contexts/units, relationships), without requiring SEC-side system changes (e.g., EDGAR outages) or special exemptions.

### "Prior comparable filing"
The issuer's most recent filing of the same base form type (10-Q compares to the prior 10-Q; 10-K compares to the prior 10-K). Amended filings (10-Q/A, 10-K/A) are treated as the same base form type as their original.
If an amendment/restatement exists for the prior comparable period, use the latest filed version (the /A) as the comparator and record the choice in the Evidence Pack.
If no prior comparable filing exists (e.g., new registrant, or first filing of a form type), comparator-based checks are skipped and alerts must be supported by within-filing evidence alone.

### "Next filing cycle" (in this plan)
The issuer's next submission of the same form type (next 10-Q or next 10-K). CMD+RVL analyzes each filed artifact as soon as it is available; the "next cycle" language describes when the flagged fragility could materialize as a problem, not when analysis occurs. Note: fragility patterns detected in a 10-Q may also be relevant to the upcoming 10-K if similar structures are reused, but v1 comparisons are same-form-type only.

### "EDGAR Next" (in this plan)
Shorthand for the EDGAR modernization period in which operational behavior may change. This plan does not assume EDGAR Next implies stricter XBRL validation; CMD+RVL treats validation/enforcement shifts as external facts to measure, not assumptions to argue about.

### "Elevated risk" (in this plan)
Means: at least one fragility pattern is observed in the latest filed artifacts and there is a concrete, testable mechanism + break trigger described. CMD+RVL does not provide numeric probabilities in v1.
The term "elevated" is a structural risk flag (mechanism-first), not a calibrated probability or a promise that an EDGAR rejection will occur. It signals "a known fragility mechanism is present" rather than "rejection is likely."
In v1, this is asserted only when a target v1 shipping pattern passes the Gate and is detected; absence of an alert is not evidence of absence (the pattern catalog is intentionally narrow).

### "Adaptation marker" (in this plan)
A historical change-point in filing structure that is consistent with a filer/vendor changing XBRL structure (e.g., to address new rules/guidance, taxonomy updates, validator behavior, or vendor/tooling migration). Markers are context, not proof:
- Marker present: suggests a structural migration happened; partial migrations are plausible.
- No marker detected: does not mean no change (it may be outside the window or not detectable).

### "QName"
Namespace-qualified name used to identify an XBRL concept/dimension/member (e.g., `dei:EntityRegistrantName`).

## Why This Outcome Exists
- EDGAR XBRL validation/enforcement behavior can change unevenly and incrementally.
- Many XBRL patterns still pass until something *changes*.
- Failures surface late (submission time), when fixes are expensive.
- Filing vendors validate drafts; monitoring last cycle's filed artifacts for next-cycle fragility is not always performed.
- Accountability for "what could break next quarter" is often diffuse.

CMD+RVL targets that gap.

---

## Outcome Scope
This outcome answers one question only:

> "Do we observe enforcement-fragile XBRL patterns in this issuer's last filing that meet the plan's \"elevated risk\" definition for the next cycle, and what is the specific mechanism?"

It does **not**:
- prepare filings
- tag XBRL
- review draft/pre-submission filing packages (v1)
- replace filing vendors
- offer speculative compliance advice

---

## Inputs (What the Customer Provides)
- A list of **CIKs to monitor**

Optional later:
- Alert preferences
- Severity thresholds
- Escalation contacts

That's it.

---

## Outputs (What CMD+RVL Delivers)
When risk is detected, the customer receives:

- Issuer (CIK)
- Filing reference (form + filed date + accession number)
- Specific XBRL fragility pattern (stable ID)
- Why this pattern can exist in an accepted filing (i.e., it was not fatal at the time of submission), per the pinned rule basis
- Mechanism (testable): why the observed pattern is enforcement-fragile (break mechanism + conditions)
- Break trigger: `XEW-BT###` + what type of future change could turn this into a rejection/failure

Delivered as:
- A concise alert
- An attached or linked **Evidence Pack** suitable for internal or vendor handoff

No dashboards required.

---

## Positioning (Non-Negotiable)
This is not generic XBRL QA or "validation as a service."

Say this:
- "Pre-flight early warning for what could break next cycle."
- "Vendor-neutral evidence pack for fast triage."

Do not say this:
- "We validate your filings"
- "We replace your filing vendor"
- "We keep you compliant"

---

## Hard Scope Limits (So You Actually Ship)
### Filing coverage (v1)
- Forms: 10-Q and 10-K only (the CLI can process other forms like 8-K, but v1 alerts are scoped to periodic filings)
- XBRL format: inline XBRL as filed on EDGAR

### Issuer set (v1)
- 10-25 issuers (pilot list; start with 5 for initial end-to-end testing)
- US domestic issuers first; expand to FPIs and additional forms (e.g., 20-F/6-K) later if it helps

### Alert policy (v1)
- One pattern per alert (the Evidence Pack may include multiple instances)
- Default: at most 1 externally-sent alert per issuer per filing (selected by explicit priority order defined in the pattern catalog, not by a confidence score).
- If multiple patterns trip in one filing, record the rest internally (and optionally include them as an appendix in the Evidence Pack) but do not send separate alerts by default.
- Optional mode: if the customer explicitly requests "all patterns", send one alert per alert-eligible v1 pattern (still human reviewed).
- Human review gate before sending anything externally (until precision is proven)

---

## Pilot Hypotheses (Must Prove)
- Filed inline XBRL contains detectable enforcement-fragile patterns (per the XEW pattern catalog) that can be reproduced from public EDGAR artifacts, without issuer cooperation.
- Adaptation markers derived from filing history improve triage clarity (they help distinguish "stable filers" from "recently migrated filers") without being treated as causal proof.
- Evidence Packs built from public artifacts (EDGAR filing artifacts plus pinned taxonomy/rule sources) are sufficient for a third party (issuer team or vendor) to reproduce the issue quickly.
- For each target v1 shipping pattern, a defensible rule basis can be pinned (SEC/EDGAR guidance or XBRL spec) and included in the Evidence Pack (or else the pattern is demoted and does not ship).
- Alert volume can stay low without sacrificing actionability (quality beats coverage in v1).

---

## Historical Adaptation Markers (v1)
These markers are not alerts by themselves. They are context signals derived from a rolling filing history window (e.g., approximately 2-3 years of prior filings of the same form type) to detect a likely "migration/update event."

Marker ID format: `XEW-M###` (XBRL Early Warning Marker).

### XEW-M001: Taxonomy Refresh Event
- Signal: schemaRef/taxonomy package references change materially vs the prior comparable filing.
- Interpretation: filer/vendor may have performed a taxonomy refresh; follow-on structural changes are plausible.
- Evidence must include: schemaRef hrefs (before/after) + accession numbers.

### XEW-M002: Extension Refactor Event
- Signal: extension concepts show high churn (many retire + many new) across one filing boundary.
- Interpretation: suggests a remapping/rebuild of extension taxonomy; partial migrations are plausible.
- Evidence must include: counts of new/retired extension QNames + top changed concepts + accession numbers.

### XEW-M003: Anchoring Retrofit Event
- Signal: anchoring coverage changes sharply across one filing boundary (e.g., many previously-unanchored extension concepts gain anchors, or anchor targets change en masse).
- Interpretation: suggests the filer/vendor attempted to update anchoring; partial remediation is plausible.
- Evidence must include: anchoring coverage metrics (before/after) + example anchors added/changed + accession numbers.

### XEW-M004: Context Model Rewrite
- Signal: context count and/or the distribution of dimension-member sets changes sharply across one filing boundary.
- Interpretation: suggests a structural rewrite that can introduce new edge cases (duplicates, invalid combos).
- Evidence must include: context counts (before/after) + summary of dimension-member set deltas + accession numbers.

### XEW-M005: Duplicate Cleanup Event
- Signal: duplicate-fact signatures present historically drop sharply (or disappear) across one filing boundary.
- Interpretation: suggests duplicate-related cleanup/refactor; remaining duplicates (if any) may be subtler.
- Evidence must include: duplicate signature counts (before/after) + example signatures + accession numbers.

Marker caution (important): these are not proof the filer was reacting to "stricter guidelines." Business events can also cause structural change. Treat markers as triage context only.
Rule (v1): any "material" / "sharp change" thresholds used to detect markers must be explicit (versioned) and recorded in the Evidence Pack/toolchain config so results are reproducible.

## V1 Shipping Pattern Set (Scope Lock)
In v1, CMD+RVL generates alert candidates only for the following target shipping patterns (subject to the Gate):
- `XEW-P001` Duplicate Facts With Equivalent Context/Unit (rule basis required)
- `XEW-P002` Extension Anchoring Defects (objective checks only; rule basis required; no "semantic unrelatedness" claims)
- `XEW-P004` Invalid or Discouraged Data-Type / Unit / Numeric Attributes (rule-basis required)
- `XEW-P005` Inconsistent Taxonomy References (rule-basis required; focus on internal inconsistency in v1)

Gate (v1): if a defensible rule basis cannot be pinned for a listed pattern, it is demoted to a candidate and does not ship.

Other patterns remain documented as candidates, but are treated as roadmap until proven low-noise:
- `XEW-P003` Inconsistent Dimensional Application (likely useful; high false-positive risk without strict comparability rules)
- `XEW-P006` Ambiguous Dimensional Member Reuse (semantic; not safe to auto-alert)
- `XEW-P007` Duplicate-by-Substance Contexts (potentially useful; log internally in v1 but do not auto-alert due to high noise risk and unclear reject mechanism)

## XEW Pattern Catalog
A construct is fragile if it meets all three:
- The SEC, EDGAR guidance, or the XBRL spec classifies it as incorrect, discouraged, or ambiguity-prone, and
- it can be accepted as filed in practice due to tolerance or stable context, and
- a reasonable disclosure change could surface it as a rejection/failure.

Canon rule: a pattern is "canon" only once its rule basis is explicitly pinned and included in the Evidence Pack. Until then, it is a candidate and must not be auto-alerted.

Provenance note: this catalog starts as a hypothesis derived from published SEC/EDGAR guidance + XBRL spec constraints + common validator check classes. "Real" in CMD+RVL terms means: pinned rule basis + reproducible evidence + low-noise behavior in the pilot.

This is a catalog with a canon rule, not a backlog. Additions require the same burden of proof; removals require explicit justification.

Out of scope (do not alert):
- stylistic tagging preferences
- taxonomy choices within valid alternatives
- minor labeling differences
- cosmetic extension naming
- purely presentation-level issues

Pattern ID format: `XEW-P###` (XBRL Early Warning Pattern).

Note (v1): "v1 status: ship" means "in the target v1 shipping set; it ships only if the Gate is satisfied (rule basis pinned)."

### XEW-P001: Duplicate Facts With Equivalent Context/Unit
- v1 status: ship (report duplicates and whether values conflict; rule basis required).
- Signal: two or more facts with the same QName + equivalent context (same entity identifier (scheme + value) + period + dimension-member set), and the same unit when applicable.
- Why fragile: XBRL 2.1 spec section 4.6.1 states facts with identical concept/context/unit should be considered duplicates. Duplicates create ambiguity for consumers; they may be tolerated in stable filings but can become reject-risk under enforcement tightening (e.g., stricter EFM validation) or disclosure evolution that surfaces the ambiguity.
- Break trigger examples: roll-forward period edits; dimensional changes; validator/enforcement tightening around duplicates.
- Evidence must include: the duplicate fact set(s) (QName, unitRef when applicable, values), the context IDs involved and their equivalent context signature (entity identifier (scheme + value) + period + dimension-member set), whether values conflict, and a reproducible query or extraction that finds them.

### XEW-P002: Extension Anchoring Defects
- v1 status: ship (objective checks only; rule basis required; do not make "semantic unrelatedness" claims).
- Signal: extension concepts are used, but are unanchored to standard taxonomy concepts, or fail objective anchoring checks (e.g., anchor target is abstract; periodType mismatch; type mismatch; anchor-to-extension).
- Why fragile: weak anchoring makes extension meaning brittle across reuse, expansion, and evolving validation expectations.
- Break trigger examples: extension reuse/expansion; taxonomy refresh; validator/enforcement tightening on anchoring rules.
- Evidence must include: the extension QName(s) used; the anchoring relationships (or lack thereof); and the standard concept(s) involved when anchors exist.

### XEW-P003: Inconsistent Dimensional Application
- v1 status: roadmap (high false-positive risk without strict comparability rules; do not auto-alert).
- Signal: the same concept is reported both with dimensions and without dimensions (or with materially different dimension-member sets) in comparable contexts.
- Why fragile: dimensional inconsistency is a known error class and can be "quiet" until the disclosure structure shifts.
- Break trigger examples: segment changes; adding/removing members; roll-forward edits; validator/enforcement tightening around dimensional validity.
- Evidence must include: the concept QName; the dimension-member set(s) observed; and representative fact/context examples showing the inconsistency.

### XEW-P004: Invalid or Discouraged Data-Type / Unit / Numeric Attributes
- v1 status: ship (objective checks; rule basis required).
- Signal: numeric facts with invalid numeric attributes (e.g., decimals/precision issues under the applicable rule basis), or units that are incompatible with the concept type (e.g., shares vs currency), or other type/unit mismatches the SEC/XBRL rules treat as incorrect/discouraged.
- Why fragile: these are correctness issues that can be accepted as filed due to tolerance or non-fatal enforcement, but can become fatal under enforcement tightening or when the tagging pattern is reused/expanded.
- Break trigger examples: validator/enforcement tightening; reuse of the same tagging pattern on new facts; taxonomy refresh.
- Evidence must include: the fact(s) (QName, contextRef, unitRef, decimals/precision where applicable) and the rule basis referenced in the Evidence Pack.

### XEW-P005: Inconsistent Taxonomy References
- v1 status: ship (alert on internal inconsistency/mismatch only; rule basis required).
  - Note: "deprecated/old taxonomy" claims require an explicit, pinned rule basis as-of `retrieved_at` and are not default v1 alerts.
- Signal: taxonomy references are internally inconsistent within the same filing (e.g., extension schema imports us-gaap/2024 but facts use us-gaap/2025 namespace), or schemaRef hrefs don't match the namespaces actually used in facts.
- Why fragile: taxonomy mismatches can be tolerated until a change forces a stricter validation path (new extensions, new disclosures, or updated validation rules).
- Break trigger examples: taxonomy refresh; validator/enforcement tightening; extension reuse/expansion.
- Evidence must include: the schemaRef href(s)/namespace(s) observed; the filing artifacts where they appear; and the rule basis referenced in the Evidence Pack.

### XEW-P006: Ambiguous Dimensional Member Reuse
- v1 status: roadmap (semantic; not safe to auto-alert).
- Signal: the same dimension member is reused in ways that create ambiguity across disclosures (e.g., a generic "Other" member used as a catch-all in multiple unrelated contexts, or a custom member reused with inconsistent meaning across statements/footnotes).
- Why fragile: semantic ambiguity is often tolerated until disclosure structure changes, at which point conflicts can surface interpretability issues and downstream tooling disagreements.
- Break trigger examples: segment changes; roll-forward edits; adding new members; enforcement tightening around dimensional validity.
- Evidence must include: the member QName; examples of where it is used (concepts/roles/contexts); and the specific ambiguity claim (what meaning conflict exists).

### XEW-P007: Duplicate-by-Substance Contexts
- v1 status: roadmap (log as an internal observation; do not auto-alert due to high noise risk and unclear reject mechanism).
- Signal: two or more distinct context IDs share the same entity identifier (scheme + value) + period + dimension-member set (duplicate-by-substance).
- Why fragile: duplicate-by-substance contexts increase collision risk (e.g., they can lead to duplicate facts in `XEW-P001` as disclosures evolve), and make the tagging model more brittle under future changes.
- Break trigger examples: adding new facts; roll-forward edits; dimensional expansion; validator/enforcement tightening.
- Evidence must include: the context IDs involved; their entity identifier (scheme + value); their periods; their dimension-member sets; and a reproducible extraction demonstrating identical signatures.

### Break Trigger Catalog (Annotations, Not Alerts)
Break triggers are recorded on alerts as explicit "what could surface this" annotations. A break trigger is never an alert by itself.
This is where we encode "facts dependent on period coincidence" without turning it into a standalone alert category.

Break trigger ID format: `XEW-BT###`.

#### XEW-BT001: Period Coincidence / Period Shift
- Meaning: the construct is stable only because current period alignment hides collisions; a small period change (roll-forward, comparative structure shift) can surface duplicates/context conflicts.

#### XEW-BT002: Disclosure Reshaping
- Meaning: changes in table structure, roll-forward mechanics, or comparative presentation can surface latent structural issues.

#### XEW-BT003: Taxonomy Refresh
- Meaning: taxonomy updates (and related validation rule changes) can turn previously-tolerated structures into reject conditions.

#### XEW-BT004: Validator/Enforcement Tightening
- Meaning: rule enforcement changes can turn warnings/tolerated issues into fatal errors.

---

## Evidence Pack (Canonical)
An Evidence Pack must let a third party reproduce what was detected.

Minimum contents:
- Issuer: CIK, legal name (as filed)
- Filing: form, filed date, accession number
- Comparator filing (if delta-based): form, filed date, accession number
- History window (if markers used): list of accession numbers scanned + the marker(s) detected (if any)
- Evidence Pack ID: `XEW-EP-####` and `retrieved_at` timestamp (ISO 8601 UTC)
- Artifact references: the exact artifacts used for the filing and comparator (if applicable): primary inline XBRL HTML + any referenced XBRL schema/linkbase files (as retrieved) + any pinned taxonomy inputs used to resolve/validate (if any), with URLs captured at retrieval time when applicable
- Redistribution note: if a required taxonomy/rule source is not legally redistributable, record a pinned reference (URL/identifier + retrieved_at + sha256) and repro steps instead of embedding the bytes.
- Content integrity: sha256 for each retrieved artifact (tamper-evident / anti-silent-change)
- Toolchain: detector version + Arelle/plugin versions + key config affecting resolution/validation (so a third party can reproduce results using the same inputs)
- External references (if used): captured copies of EFM updates / taxonomy release notes referenced in the rule basis, with URLs + retrieved_at + sha256
- Pattern: stable pattern ID + short name
- Rule basis: citation(s) to SEC/EDGAR guidance (e.g., EFM section / validation rule) or XBRL spec section supporting why the pattern is incorrect/discouraged/ambiguity-prone (include URL + retrieved_at + sha256 when fetched)
- Evidence:
  - the specific fragment(s) that triggered the pattern (e.g., element name(s), context(s), dimension member(s))
  - a delta vs the prior comparable filing when applicable
- Break trigger: `XEW-BT###` + one-sentence description of what could turn this into a rejection/failure
- Repro steps: deterministic steps to re-run the check locally (scripted when possible; otherwise a documented manual procedure)

Deterministic IDs (v1):
- Use Clark notation (`{namespaceURI}localName`) for all QNames stored in Evidence Pack JSON and detector outputs.
- `finding_id`: `XEW-F-<accession>-<pattern_id>` (example: `XEW-F-0000123456-26-000005-XEW-P001`).
- `instance_id`: `sha256(canonical_signature_bytes)` (lowercase hex). Canonical signature serialization must be deterministic, versioned, and defined in `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`.

Canonical signature must include (at minimum):
- `XEW-P001`: concept Clark QName, unit (or empty), entity identifier (scheme + value), period, and dimension-member set (so duplicates are keyed by equivalent context, not context ID).
- `XEW-P002`: extension concept Clark QName + objective issue code(s) for the anchoring defect.
- `XEW-P004`: concept Clark QName + context ID + unit (or empty) + issue code.
- `XEW-P005`: issue code + the relevant sorted schemaRef href(s) and/or namespace(s) used to compute the inconsistency claim.

Rule: no alert ships without an Evidence Pack.

Implementation contract (v1):
- Evidence Pack layout + hashing: `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`
- Detector output schema: `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json`
- Example detector output: `docs/examples/xew_findings.example.v1.json`

### Implementation Shape (v1)
The v1 detector is a pack generator that writes an Evidence Pack directory (manifest + artifacts + findings).
It is designed to run as a CLI (and can be wrapped by a monitoring loop).

CLI name (v1): `cmdrvl-xew`

Inputs (v1):
- EDGAR-driven: an accession number (optionally with a comparator accession).
- Artifact-driven: a local primary inline XBRL HTML file (plus any required referenced artifacts).

Operational note (v1): when filing artifacts are already staged in object storage (e.g., S3) by the monitoring system, prefer artifact-driven execution (no web fetch). Use EDGAR-driven mode for ad-hoc repro/backfill.

Outputs (v1):
- An Evidence Pack directory containing `pack_manifest.json`, `xew_findings.json`, `toolchain/toolchain.json`, and `artifacts/`.

Commands (v1):
- `cmdrvl-xew pack`: generate an Evidence Pack from either EDGAR inputs or local artifacts.
- `cmdrvl-xew verify-pack`: verify `pack_manifest.json` integrity hashes and validate `xew_findings.json` against the schema.

### Open Source Strategy (v1)
Rationale: trust + reproducibility + vendor-neutrality. The outcome is hosted; the detector/pack format can be inspectable.

Open-source candidates:
- `cmdrvl-xew` CLI + Python library (load iXBRL, run v1 detectors, write an Evidence Pack)
- `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json` (output schema)
- `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD` (pack contract)
- `cmdrvl-xew verify-pack` (local verification tool)

Keep private/hosted (differentiation):
- Monitoring/orchestration (issuer targeting, scheduling, backfills, suppression across time)
- Delivery + integrations (MCP/API, customer routing, alert policies)
- Opinionated agent layer (analysis/playbooks) used by hosted systems
- Any tuned thresholds (markers/suppression) and internal datasets (as applicable)

### Engine Spec Gaps (Must Lock Before Shipping)
These are implementable, but must be pinned to avoid silent drift and false claims:
- Issue code catalogs: `src/cmdrvl_xew/spec/xew_issue_codes.v1.json` defines versioned `issue_code` / `issue_codes` enums for `XEW-P002`, `XEW-P004`, `XEW-P005`.
- Rule basis map (Gate input): `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json` pins citations per shipped issue code (include `retrieved_at` + sha256). No rule basis -> no shipping alert.
- Deterministic canonicalization:
  - Unit equivalence policy (unitRef equality vs measure equivalence)
  - Typed dimension canonical bytes for `typed:sha256(typed_value)`
  - Value normalization for `XEW-P001` conflict detection
  - Deterministic ordering + caps for instance lists (to make truncation reproducible)
- Taxonomy resolution policy (offline/online, taxonomy packages used, and what is pinned into the Evidence Pack vs referenced).
- EDGAR-driven fetch policy (when used): deterministic artifact selection + rate limiting + SEC user-agent compliance.

---

## Alert Template (Canonical)
### Subject
`[CMD+RVL XEW] <Issuer Name> (CIK <CIK>) <Form> filed <YYYY-MM-DD> - <Pattern ID>: <Short Name>`

### Required fields (v1)
- Issuer: legal name, CIK, ticker (if available)
- Filing: form, filed date, period end date, accession number, filing URL
- Comparator filing (if delta-based): accession number + filing URL
- Adaptation markers (if any): `XEW-M###` + the filing boundary where detected
- Pattern: `XEW-P###`, short name
- Observed evidence (facts only; 2 bullets max): what is directly observable in the filing artifacts
- Summary (1 sentence): what changed (if delta-based) / what is fragile
- Why it matters (2 bullets max): what failure mode this points to
- Break trigger (explicit): `XEW-BT###` + the most plausible future change that could turn this into a rejection/failure
- Evidence Pack: attachment or link + pack ID + retrieved_at timestamp
- Human review: `YES` (pilot default) or `NO` (only after precision is proven)
- Reply-to: where the customer should send questions (email/Slack handle)

### Example alert (fictional)
Subject:
`[CMD+RVL XEW] ExampleCo, Inc. (CIK 0000123456) 10-Q filed 2025-11-10 - XEW-P002: Extension Anchoring Defects`

Body:
- Issuer: ExampleCo, Inc. (CIK 0000123456), Ticker: EXMPL
- Filing: 10-Q filed 2025-11-10, period end 2025-09-30, accession 0000123456-25-000042
- Filing URL: <EDGAR filing URL>
- Comparator filing: 10-Q filed 2025-08-10, accession 0000123456-25-000031 (Q2 2025)
- Comparator URL: <EDGAR filing URL>
- Adaptation markers: XEW-M002 detected between 0000123456-25-000031 -> 0000123456-25-000042
- Pattern: XEW-P002 - Extension Anchoring Defects
- Observed evidence:
  - New extension QNames appear in tagged facts in the revenue footnote vs the comparator 10-Q.
  - In the retrieved taxonomy/linkbase artifacts, no anchoring relationships to standard taxonomy concepts were found for those extension QNames (or the anchors found exhibit objective defects such as anchoring only to abstract concepts).
- Summary: New extension concepts were introduced in the revenue footnote without anchoring to standard taxonomy concepts (or with objective anchoring defects), increasing fragility under future reuse or tightened anchoring enforcement.
- Why it matters:
  - If validator/enforcement strictness tightens around anchoring, this can become a late-cycle reject risk.
  - This can be a signature of a tagging model change; partial migrations are plausible.
- Break trigger: XEW-BT004 - Validator/Enforcement Tightening.
- Evidence Pack: XEW-EP-0007 (retrieved_at 2025-11-10T14:32:10Z), attached
- Human review: YES
- Reply-to: <your contact>

## What "Monitoring" Actually Means
CMD+RVL monitors **structural risk**, not filing volume.

Specifically:
- Newly filed XBRL artifacts
- Deltas vs the prior comparable filing (structure, dimensions, extensions, taxonomy references)
- Public change signals (taxonomy releases, EDGAR Filer Manual updates) to keep pattern logic current (initially manual)
- A rolling history window per issuer to detect adaptation markers (change-points) that affect triage
- Changes in disclosure structure
- Introduction or reuse of extensions
- Dimensional shifts
- Enforcement-sensitive schema patterns

CMD+RVL does **not** send an alert on every filing; repeated unchanged findings are suppressed by default.

---

## Event Triggers (High-Level)
In v1, an alert candidate is generated when CMD+RVL detects one of the target v1 shipping patterns (subject to the Gate):

- Duplicate facts with equivalent context/unit
- Extension anchoring defects
- Invalid/discouraged data-type, unit, or numeric attribute usage
- Inconsistent taxonomy references (mixed versions / namespace-schemaRef mismatch)

These are **structural events**, not cosmetic tagging differences.

Patterns not in the v1 shipping set are logged as internal observations/roadmap items (not auto-alerted).

---

## When This Outcome Matters Most
The outcome becomes critical during:

- Year-end / 10-K filing period (when annual roll-forward happens)
- Segment or reporting structure changes
- Restatements
- Acquisitions or divestitures
- Introduction of new disclosures
- First filing after an enforcement shift

CMD+RVL surfaces risk **ahead of the next submission** (from the last filed artifacts), when those moments are most likely to surface latent issues.

---

## Who This Outcome Is For
Primary:
- Controllers
- Chief Accounting Officers
- Directors of SEC Reporting
- Finance leaders overseeing multiple issuers

Secondary:
- Foreign private issuers (after adding 20-F coverage)
- Infrequent or complex filers
- Filing vendors monitoring many clients (indirect users)

---

## Why This Is an Outcome (Not a Feature)
Because:

- The customer defines *who* to watch.
- CMD+RVL decides *when* to act.
- The customer receives *signals*, not software.

If the customer asks:
> "What do I need to do?"

The answer is:
> "Tell us which CIKs matter."

That is outcome-grade.

---

## Constraints (Deliberate)
- No fear-based messaging
- No speculative claims
- No uncalibrated probabilities or "will fail" language; alerts describe conditional mechanisms and risk
- No vendor-replacement positioning
- No alert spam
- No opinions without evidence
- No alert unless it maps to a v1 shipping `XEW-P###` pattern (passed the Gate) and the Evidence Pack includes the rule basis
- Rule basis must be anchored to SEC/EDGAR guidance (e.g., EFM) or the XBRL spec; third-party rule sets/validator outputs (e.g., XBRL US Data Quality Committee rules, Arelle messages) may be included as supporting evidence but are not sufficient alone
- Separate observed evidence from mechanism; the mechanism must be testable and tied to the Evidence Pack

Every alert must be:
- factual
- reproducible
- defensible using public artifacts

---

## Rules of Engagement
- Monitor only public filings
- Contact only roles accountable for filings
- One pattern per alert
- Evidence over interpretation
- Vendor-neutral framing

CMD+RVL creates accountability without blame.

---

## Implementation Context (Assumed Existing)
This plan assumes the monitoring business logic and delivery stack already exist. The missing build is the CLI engine that generates Evidence Packs.

Assumed components:
- XBRL artifacts staged in object storage (e.g., S3) with lineage/catalog metadata
- Orchestration (e.g., Airflow) to schedule detection and backfills
- Delivery (MCP + API) to route alerts + Evidence Packs
- Product surfaces:
  - `cmdrvl.com`: hosts the outcome (monitoring + alert delivery + Evidence Pack access)
  - `kovrex.ai`: hosts an opinionated agent that helps recipients interpret Evidence Packs and draft vendor-friendly handoffs (without inventing facts or giving speculative compliance advice)

New build (v1):
- `cmdrvl-xew`: the CLI engine that turns filing artifacts into `xew_findings.json` + an Evidence Pack directory.

---

## Execution Plan (30 Days)
### Days 1-7: Define the Canon + Prove Reproducibility
- Lock the target v1 pattern set (4 patterns), subject to the Gate (rule basis pinned), and freeze the detector output + Evidence Pack contract
- Define v1 issue code catalogs + canonicalization rules needed for deterministic IDs and low-noise detection
- Build ingestion + artifact retrieval for 10-Q/10-K inline XBRL artifacts (pilot issuer list)
- Produce 3-5 internal alerts end-to-end with Evidence Packs (human reviewed)
- Define "no-alert" baselines (what is *not* worth alerting on)

Deliverables by Day 7:
- Pattern catalog (v1) documented in this plan
- Rule basis map (v1): `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json` (citations + retrieved_at + sha256; pinned per shipped issue code)
- Issue code catalog (v1): `src/cmdrvl_xew/spec/xew_issue_codes.v1.json` (stable enums for `XEW-P002` / `XEW-P004` / `XEW-P005`)
- `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json` + `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD` (v1)
- `cmdrvl-xew` CLI skeleton: `pack` + `verify-pack`
- Open-source engine repo initialized (if OSS route chosen), with docs for local reproduction
- 3-5 example Evidence Packs (internal)
- A repeatable internal runbook ("how an alert is produced")

### Days 8-21: Automate the Loop + Start a Pilot
- Automate daily polling for new filings across the pilot issuer list and run pattern checks on any new filing
- Run `cmdrvl-xew pack` as the execution engine inside the orchestration system (artifact-driven in production; EDGAR-driven for ad-hoc repro)
- Add delta logic (compare to prior comparable filing for each issuer/form)
- Add alert gating rules to control spam
- Start sending alerts to a small pilot group (or internal proxy) with feedback loop

Deliverables by Day 21:
- Monitoring loop runs daily without manual artifact hunting
- Evidence Packs generated within 15 minutes of new filing availability on EDGAR (target; excludes artifact download time)
- Pilot running with at least 5 issuers (target)

### Days 22-30: Precision, Packaging, and Trust
- Measure precision via indirect proxies (human review disagreement rate, recipient "not an issue" feedback, "actioned" rate, time-to-triage). Note: true precision requires knowing whether flagged patterns would have caused actual failures, which is unknowable without ground truth; treat recall as similarly unknown.
- Tighten pattern definitions based on pilot outcomes
- Standardize alert template + Evidence Pack layout
- Define v2 expansion options (more forms, more issuers, severity tiers) without changing the v1 promise

Deliverables by Day 30:
- A credible pilot with real recipients (or signed-off internal stakeholder)
- A stable set of patterns that do not spam
- A clear go/no-go for v2 expansion

---

## Success Criteria
Early signals of success:
- Alerts forwarded internally or to vendors
- "We didn't know this yet" responses
- Repeat monitoring across filing cycles
- CMD+RVL referenced in pre-filing checklists

Longer term:
- CMD+RVL treated as standing pre-flight signal
- Outcome embedded in reporting calendars

---

## What Comes Next (Later Expansion)
- Codified fragility taxonomy (pattern catalog becomes formal)
- Severity tiers and optional scoring (only after precision is proven)
- Formal Outcome SKUs (by issuer count, forms covered, SLA)
- Expansion beyond XBRL into other EDGAR Next enforcement surfaces

---

## Core Outcome Statement
> CMD+RVL monitors the issuers you care about and flags evidence-backed XBRL fragility that meets the plan's "elevated risk" definition for avoidable EDGAR rejection risk in the next cycle -- with a reproducible Evidence Pack.
