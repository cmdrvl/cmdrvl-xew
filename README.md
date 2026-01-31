# cmdrvl-xew

`cmdrvl-xew` is the open-source CMD+RVL XBRL Early Warning (XEW) engine.

It produces a reproducible **Evidence Pack** directory from inline XBRL (iXBRL) filing artifacts and emits a machine-readable `xew_findings.json` report.

The goal is **deterministic reproduction**: a third party (issuer team, filing vendor, auditor) should be able to verify what the detector saw using only the Evidence Pack.

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

### Generate a Pack (artifact-driven)

Artifact-driven mode is the default posture (recommended for production systems that already stage filing artifacts in object storage).

```bash
cmdrvl-xew pack \
  --pack-id XEW-EP-0007 \
  --out ./XEW-EP-0007 \
  --primary ./primary-document.html \
  --cik 0000123456 \
  --accession 0000123456-26-000005 \
  --form 10-Q \
  --filed-date 2026-01-20 \
  --primary-document-url https://www.sec.gov/Archives/edgar/data/123456/000012345626000005/primary-document.html
```

Notes:
- The output directory must not exist (or must be empty).
- In the current skeleton, `pack` copies the primary HTML into `artifacts/primary.html` and emits an empty `findings` list.

### Verify a Pack

```bash
cmdrvl-xew verify-pack --pack ./XEW-EP-0007

# With optional schema validation
cmdrvl-xew verify-pack --pack ./XEW-EP-0007 --validate-schema
```

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
