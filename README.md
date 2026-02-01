# cmdrvl-xew

`cmdrvl-xew` is the open-source CMD+RVL XBRL Early Warning (XEW) engine.

It produces a reproducible **Evidence Pack** directory from inline XBRL (iXBRL) filing artifacts and emits a machine-readable `xew_findings.json` report.

The goal is **deterministic reproduction**: a third party (issuer team, filing vendor, auditor) should be able to verify what the detector saw using only the Evidence Pack.

## Built on Arelle

cmdrvl-xew uses [Arelle](https://arelle.org) — the open-source XBRL processor — to load and validate inline XBRL filings. Arelle provides the XBRL model (facts, contexts, units, relationships); cmdrvl-xew adds targeted fragility detection and Evidence Pack generation on top.

- **Arelle handles**: iXBRL parsing, DTS resolution, SEC/EFM validation
- **cmdrvl-xew adds**: pattern detection (XEW-P001–P005), deterministic Evidence Packs, reproducible findings

This is not a fork or replacement — it's a focused layer that turns Arelle's XBRL model into actionable early-warning output.

## What XEW Is (and Is Not)

XEW is:
- an engine for detecting **objective, evidence-backed fragility patterns** in filed iXBRL artifacts,
- an Evidence Pack generator (manifest + hashes + toolchain + artifacts + findings),
- designed to be run in automation (orchestration systems, pipelines, backfills).

XEW is NOT:
- a filing preparation tool,
- a guarantee of EDGAR acceptance,
- legal/compliance advice,
- a replacement for filing vendors.

## Core Concepts

### Findings
`xew_findings.json` is the machine output. It is validated by the v1 JSON schema.

- Schema: `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json`
- Example: `docs/examples/xew_findings.example.v1.json`
- V2 schema (future): `src/cmdrvl_xew/schemas/xew_findings.schema.v2.json` adds optional `severity_tier`.

### Evidence Pack
An Evidence Pack is a directory that contains:
- the **exact bytes** used for detection (artifacts),
- deterministic sha256 hashes for each file,
- a `pack_sha256` integrity hash,
- the `xew_findings.json` output,
- toolchain metadata sufficient for reproduction.

Contract: `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`

## CLI

The CLI is named `cmdrvl-xew`.

Supported EDGAR form directories for `flatten` include 10-Q, 10-K, 8-K, 20-F, 6-K, and amendments (e.g., 10-Q/A).

### Install (dev)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional schema validation during pack verification:

```bash
pip install -e '.[jsonschema]'
```

### Flatten EDGAR Directories (artifact prep)

`flatten` normalizes EDGAR’s typed directory structure into a flat layout that Arelle can load.

```bash
cmdrvl-xew flatten sample/0000034903-25-000063 --out /tmp/flat

# Overwrite existing output directory contents if needed
cmdrvl-xew flatten sample/0000034903-25-000063 --out /tmp/flat --force
```

Notes:
- The output directory must be empty unless `--force` is used.
- The flat output directory is the input for `pack`.

Flatten flags:
- Required: `edgar_dir` (positional), `--out`
- Optional: `--force`

### Fetch EDGAR Accession Artifacts (planned; not yet implemented)

Note: `cmdrvl-xew fetch` is not implemented in the CLI yet. This section documents the intended interface for a future EDGAR-driven mode.

Planned interface (not yet implemented):
```bash
cmdrvl-xew fetch \
  --cik 0000123456 \
  --accession 0000123456-26-000005 \
  --out /tmp/flat \
  --user-agent "Example Name example@example.com"
```

Notes:
- When implemented, `--user-agent` will be required to comply with SEC access policies.
- The output directory must be empty unless `--force` is used.
- This is an EDGAR-driven convenience mode; artifact-driven `pack` remains the default.

Fetch flags:
- Required (planned): `--cik`, `--accession`, `--out`, `--user-agent`
- Optional (planned): `--min-interval`, `--force`

### Generate a Pack (artifact-driven)

Artifact-driven mode is the default posture (recommended for production systems that already stage filing artifacts in object storage).

```bash
cmdrvl-xew pack \
  --pack-id XEW-EP-0007 \
  --out ./XEW-EP-0007 \
  --primary /tmp/flat/primary-document.html \
  --cik 0000123456 \
  --accession 0000123456-26-000005 \
  --form 10-Q \
  --filed-date 2026-01-20 \
  --primary-document-url https://www.sec.gov/Archives/edgar/data/123456/000012345626000005/primary-document.html
```

Notes:
- The output directory must not exist (or must be empty).
- `pack` currently copies only the primary HTML to `artifacts/primary.html`; referenced schema/linkbase artifacts are not yet included (planned).
- Findings are currently empty until detectors are implemented.

Pack flags:
- Required: `--pack-id`, `--out`, `--primary`, `--cik`, `--accession`, `--form`, `--filed-date`, `--primary-document-url`
- Optional: `--issuer-name`, `--period-end`, `--retrieved-at`, `--arelle-version`, `--resolution-mode`, `--derive-artifact-urls`
- Comparator (optional, all-or-nothing): `--comparator-accession`, `--comparator-primary-document-url`, `--comparator-primary-artifact-path`

### Verify a Pack

```bash
cmdrvl-xew verify-pack --pack ./XEW-EP-0007

# With optional schema validation
cmdrvl-xew verify-pack --pack ./XEW-EP-0007 --validate-schema
```

Verify flags:
- Required: `--pack`
- Optional: `--validate-schema` (requires `jsonschema` extra)

## Sample Filings (Local Only)

Real filings should not be committed. The local `sample/` folder is gitignored and intended only for ad-hoc testing.

Fetch a small set of representative extracted iXBRL filings from S3:

```bash
scripts/fetch_samples.sh

# Optional overrides
scripts/fetch_samples.sh --profile edgar-readonly --bucket edgar-data-full --out sample
```

Included accessions:
- 10-K: `0001140361-25-010025`
- 10-Q: `0000034903-25-000063`
- 8-K: `0000036104-25-000066`

## Project Plan

The outcome plan that defines the v1 scope, patterns, and Evidence Pack requirements is included as:
- `docs/PLAN_EDGAR_NEXT_XBRL_EARLY_WARNING.MD`

Key v1 blocking artifacts (to be populated):
- Issue code catalog: `src/cmdrvl_xew/spec/xew_issue_codes.v1.json`
- Rule basis map (Gate input): `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json`

## Open Source Boundary

This repo is intended to be the **public engine**.

Hosted systems (outside this repo) can provide:
- monitoring/orchestration (issuer targeting, scheduling, suppression across time),
- delivery/integrations (APIs, routing, customer policies),
- opinionated agent workflows for interpreting Evidence Packs.

## Status / Roadmap

Current status:
- Evidence Pack writer and verifier are implemented.
- Detectors are not implemented yet (findings are empty).

Next steps (v1):
- Implement v1 detectors (starting with the most deterministic checks).
- Freeze issue-code enums and pin rule basis per shipped issue code.
- Add deterministic truncation/capping rules for large instance lists.

## License

MIT
