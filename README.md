# cmdrvl-xew

`cmdrvl-xew` is the open-source CMD+RVL XBRL Early Warning (XEW) engine.

It produces a reproducible **Evidence Pack** directory from inline XBRL (iXBRL) filing artifacts and emits a machine-readable `xew_findings.json` report.

The goal is **deterministic reproduction**: a third party (issuer team, filing vendor, auditor) should be able to verify what the detector saw using only the Evidence Pack.

## Built on Arelle

cmdrvl-xew uses [Arelle](https://arelle.org) — the open-source XBRL processor — to load and validate inline XBRL filings. Arelle provides the XBRL model (facts, contexts, units, relationships); cmdrvl-xew adds targeted fragility detection and Evidence Pack generation on top.

- **Arelle handles**: iXBRL parsing, DTS resolution, SEC/EFM validation
- **cmdrvl-xew adds**: pattern detection (XEW-P001–P005, XEW-P008), deterministic Evidence Packs, reproducible findings

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

### XEW-P008 Instrument Identity Collapse
P008 detects filings where multiple registered instruments collapse under the same weak identity facts, usually ticker plus exchange. The detector is fully deterministic:

- it extracts DEI registered-security facts from Arelle when available, with a local iXBRL fallback for test/debug runs,
- it canonicalizes supported security titles such as common stock and notes due a maturity year,
- it groups by weak ticker/exchange keys and reports only groups with distinct canonical instrument identities,
- it optionally enriches evidence from a local canon/OpenFIGI registry snapshot, and
- it never performs live OpenFIGI, canon, twinning, HTTP, or LLM calls at runtime.

When P008 emits a finding, the Evidence Pack includes `generated/instrument_identity_collapse.v1.json` and hashes it in `pack_manifest.json`. The regression fixture uses the Bloomberg-facing Microsoft-style case: common stock, `3.125% Notes due 2028`, and `2.625% Notes due 2033` all share `MSFT`/`Nasdaq` weak facts while the local registry snapshot resolves separate FIGI-backed identities.

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

Production Arelle runs use a pinned Arelle runtime:

```bash
pip install -e '.[arelle]'
```

For production plus schema validation:

```bash
pip install -e '.[prod]'
```

Optional schema validation only:

```bash
pip install -e '.[jsonschema]'
```

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
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

### Fetch EDGAR Accession Artifacts

`fetch` downloads EDGAR accession artifacts into a flat directory suitable for `pack`.
It enforces SEC access policies by requiring a descriptive `--user-agent` with contact info.

Example:
```bash
cmdrvl-xew fetch \
  --cik 0000123456 \
  --accession 0000123456-26-000005 \
  --out /tmp/flat \
  --user-agent "Example Name example@example.com"
```

Notes:
- `--user-agent` must include contact info (email/URL/phone) for SEC compliance.
- `--min-interval` controls request pacing (default: 0.2s).
- The output directory must be empty unless `--force` is used.
- `fetch` prints the selected primary HTML filename; use that for `--primary` in `pack`.

Fetch flags:
- Required: `--cik`, `--accession`, `--out`, `--user-agent`
- Optional: `--min-interval`, `--force`

### Fetch Cached S3 Accession Artifacts

`fetch-s3` materializes cached EDGAR artifacts from object storage into the same flat directory shape consumed by `pack`. It never calls SEC EDGAR.

```bash
cmdrvl-xew fetch-s3 \
  --bucket edgar-data-full \
  --date-partition 20260429 \
  --accession 0001193125-26-191507 \
  --source-layout extracted \
  --aws-profile salt_profile \
  --out /tmp/msft-flat

cmdrvl-xew fetch-s3 \
  --s3-uri s3://edgar-data-full/xbrl/20260429/0001193125-26-191507.nc \
  --source-layout xbrl \
  --aws-profile salt_profile \
  --out /tmp/msft-flat-from-nc
```

Supported layouts:
- `extracted`: typed EDGAR directories under `extracted/YYYYMMDD/ACCESSION/`.
- `xbrl`: complete-submission SGML object at `xbrl/YYYYMMDD/ACCESSION.nc`; XEW extracts it deterministically before flattening.
- `auto`: prefer the extracted prefix when present; fall back to the `.nc` object.

The flat output includes `_xew_s3_provenance.json` with bucket/key/etag/last_modified/content_length metadata. When the `.nc` path is used, the provenance also includes SGML extraction metadata.

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
- `pack` copies the primary HTML to `artifacts/primary.html` and includes local schema/linkbase artifacts referenced by the primary document (and its schema). External taxonomy references are skipped (not bundled).
- For periodic forms (10-Q/10-K/20-F), providing a comparator enables comparator-based markers; running without one is allowed but those markers may be skipped.
- Packs are only meaningful when Arelle loads a real XBRL model. For production use, install taxonomy packages and run `cmdrvl-xew doctor`, then use `--require-arelle`.
- `--p001-conflict-mode` controls how XEW-P001 flags numeric value conflicts: `rounded` (default) tolerates rounding-consistent duplicates; `strict` flags any mismatch.
- `--p008-registry-snapshot` provides a local canon/OpenFIGI registry snapshot for XEW-P008 Instrument Identity Collapse. XEW consumes this file only; it does not call OpenFIGI, canon, twinning, HTTP, or an LLM at runtime.
- `--p008-require-registry` makes pack generation fail if P008 is enabled without a local registry snapshot.

Pack flags:
- Required: `--pack-id`, `--out`, `--primary`, `--cik`, `--accession`, `--form`, `--filed-date`, `--primary-document-url`
- Optional: `--issuer-name`, `--period-end`, `--retrieved-at`, `--arelle-version`, `--resolution-mode`, `--p001-conflict-mode`, `--p008-registry-snapshot`, `--p008-require-registry`, `--require-arelle`, `--no-arelle`, `--arelle-xdg-config-home`, `--derive-artifact-urls`
- History window (repeatable, all-or-nothing): `--history-accession`, `--history-primary-document-url`, `--history-primary-artifact-path`
- Comparator (optional, all-or-nothing): `--comparator-accession`, `--comparator-primary-document-url`, `--comparator-primary-artifact-path`

### Build Local Registry Snapshots

`pack` consumes local registry snapshots only. OpenFIGI/canon provider calls are allowed only before pack generation, during registry maintenance. The helper commands are still under `p008`, but P009 consumes the same snapshot format through exact CUSIP/ISIN/SEDOL/FIGI/typed-identifier lookups and never matches by ticker or name alone.

Create corpus-scoped seed files and a registry materialization manifest:

```bash
cmdrvl-xew p008 materialize-registry \
  --corpus-id msft-proof \
  --filing-manifest /path/to/corpus.jsonl \
  --out-dir /tmp/msft-registry-work \
  --version 2026.06.09 \
  --provider-config base_url=http://127.0.0.1:9000/v3/mapping
```

Add `--run-canon` to execute `canon registry build` for each non-empty CUSIP/ISIN/SEDOL/FIGI seed file. For OpenFIGI, `--run-canon` requires a local twin `base_url` unless `--allow-live-provider` is set explicitly for a maintenance run.

Convert canon registry output into the local snapshot consumed by `pack`:

```bash
cmdrvl-xew p008 snapshot-from-canon \
  --registry-dir /tmp/msft-registry-work/registries/openfigi-cusip-2026.06.09 \
  --overlay /path/to/p008-overlay.json \
  --out /tmp/p008-openfigi-snapshot.json
```

The optional overlay records filing-specific fields such as `security_title`, `normalized_title`, `canonical_signature`, and `exchange` when the filing does not expose a strong identifier for each registered instrument.

### Run The Identity-Fragility Proof

The MSFT proof command packages the cached S3, Arelle, `pack`, `verify-pack`, and focused P008 assertion steps. Use `--dry-run` first to inspect the exact local-file workflow:

```bash
cmdrvl-xew p008 prove-identity-fragility \
  --work-dir /tmp/xew-msft-proof \
  --aws-profile salt_profile \
  --taxonomy-home ~/.cmdrvl-xew/arelle \
  --dry-run
```

Run it after the taxonomy cache is installed:

```bash
cmdrvl-xew p008 prove-identity-fragility \
  --work-dir /tmp/xew-msft-proof \
  --aws-profile salt_profile \
  --taxonomy-home ~/.cmdrvl-xew/arelle \
  --p008-registry-snapshot /tmp/p008-openfigi-snapshot.json
```

The command never calls SEC or OpenFIGI. It reads cached S3 filing bytes, consumes local taxonomy packages, and optionally consumes a local P008 registry snapshot.

### Build A Deterministic Candidate Shortlist

Use the orchestrator only to create a local filing manifest. After the manifest exists, scanning and pack generation consume local files/cached S3 only.

```bash
cmdrvl-xew p008 manifest-from-orchestrator \
  --tenant salt \
  --query "recent Microsoft 10-Q filings with registered debt securities" \
  --out /tmp/p008-corpus.jsonl
```

Then rank candidates from existing packs:

```bash
cmdrvl-xew p008 scan-corpus \
  --manifest /tmp/p008-corpus.jsonl \
  --out-dir /tmp/p008-scan
```

Or explicitly allow the scanner to run cached S3 plus offline Arelle packs for each row:

```bash
cmdrvl-xew p008 scan-corpus \
  --manifest /tmp/p008-corpus.jsonl \
  --out-dir /tmp/p008-scan \
  --run-packs \
  --aws-profile salt_profile \
  --taxonomy-home ~/.cmdrvl-xew/arelle \
  --continue-on-error
```

The scanner emits stable JSONL and CSV summaries ranked by resolved or ambiguous P008 member count, max collapse group size, distinct instrument-kind count, newest filed date, and accession.

For temporal identity drift (XEW-P009), start from a provider-neutral corpus manifest plus normalized observations. The scanner groups observations by scope and time, applies the P009 ledger/alias-graph rules, ranks fragile scopes, and emits seed identifiers for local canon/OpenFIGI registry materialization. It never calls SEC, OpenFIGI, canon, an orchestrator, a warehouse, HTTP, or an LLM.

```bash
cmdrvl-xew p009 scan-corpus \
  --manifest /tmp/p009-corpus-manifest.jsonl \
  --observations /tmp/p009-observations.jsonl \
  --registry-snapshot /tmp/p009-openfigi-snapshot.json \
  --out-dir /tmp/p009-scan
```

P009 scan outputs:
- `p009_scan_candidates.v1.jsonl`: ranked candidate scopes with event details, source ids, observation ids, seed identifiers, and pack-input plans.
- `p009_scan_summary.v1.csv`: compact rank/actionability summary.
- `p009_registry_seeds.v1.jsonl`: exact CUSIP/ISIN/SEDOL/FIGI/typed-identifier seeds for local registry maintenance.
- `p009_pack_inputs.v1.json`: source-neutral handoff for later Evidence Pack generation.
- `diagnostics.json`: input hashes, row counts, candidate counts, and deterministic diagnostics.

If `--registry-snapshot` is omitted, P009 still scans deterministically and reports unresolved weak-key collisions or missing bridge evidence. A registry snapshot can convert a CUSIP-to-FIGI history into a proven local bridge, but stable CUSIP/ISIN continuity is not ranked as a fragility candidate merely because the registry contains a matching row.

### Install taxonomy packages for offline production runs

For deterministic production use, run Arelle in `offline_only` mode with a pinned set of local taxonomy packages (e.g., US-GAAP, DEI, SRT, SEC enumerations).

This command registers local taxonomy packages into an Arelle config home by writing:
`<XDG_CONFIG_HOME>/arelle/taxonomyPackages.json`

```bash
cmdrvl-xew arelle install-packages \
  --arelle-xdg-config-home ~/.cmdrvl-xew/arelle \
  --package /path/to/us-gaap-2025.zip \
  --package /path/to/dei-2025.zip

# Or download + install in one step:
cmdrvl-xew arelle install-packages \
  --arelle-xdg-config-home ~/.cmdrvl-xew/arelle \
  --download-dir ~/.cmdrvl-xew/taxonomy-packages \
  --user-agent "YourOrg your.email@example.com cmdrvl-xew/0.1.0" \
  --url https://xbrl.fasb.org/us-gaap/2025/us-gaap-2025.zip \
  --url https://xbrl.fasb.org/srt/2025/srt-2025.zip \
  --url https://xbrl.sec.gov/dei/2025/ \
  --url https://xbrl.sec.gov/exch/2025/

# Then run pack using the same config home, offline-only:
cmdrvl-xew pack ... \
  --require-arelle \
  --resolution-mode offline_only \
  --arelle-xdg-config-home ~/.cmdrvl-xew/arelle
```

### Check your environment (doctor)

Before running `pack`, verify that Arelle is installed and taxonomy packages are present:

```bash
cmdrvl-xew doctor --arelle-xdg-config-home ~/.cmdrvl-xew/arelle
```

#### Using an S3 taxonomy bundle cache (recommended in production)

For production runs, you may want to avoid hitting publisher websites (SEC/FASB) from every job. A practical pattern is:

1) Build a local Arelle taxonomy cache once (using `--url` or local `--package` files)
2) Bundle that cache into a tarball
3) Upload to your own S3 bucket
4) Configure `cmdrvl-xew` to bootstrap the cache from S3

Build the cache (example):
```bash
XDG_HOME=~/.cmdrvl-xew/arelle

cmdrvl-xew arelle install-packages \
  --arelle-xdg-config-home "$XDG_HOME" \
  --user-agent "YourOrg your.email@example.com cmdrvl-xew/0.1.0" \
  --url https://xbrl.fasb.org/us-gaap/2025/us-gaap-2025.zip \
  --url https://xbrl.fasb.org/srt/2025/srt-2025.zip \
  --url https://xbrl.sec.gov/dei/2025/ \
  --url https://xbrl.sec.gov/exch/2025/
```

Bundle + upload (example, using AWS CLI):
```bash
XDG_HOME=~/.cmdrvl-xew/arelle
tar -C "$(dirname "$XDG_HOME")" -czf xew-arelle-bundle.tgz "$(basename "$XDG_HOME")"
shasum -a 256 xew-arelle-bundle.tgz

aws s3 cp xew-arelle-bundle.tgz s3://YOUR_BUCKET/xew/arelle-taxonomy-packages/xew-arelle-bundle.tgz
```

Bootstrap from S3 on a fresh machine/container:
```bash
export XEW_ARELLE_BUNDLE_URI=s3://YOUR_BUCKET/xew/arelle-taxonomy-packages/xew-arelle-bundle.tgz
export XEW_ARELLE_BUNDLE_SHA256=...  # optional, recommended
export AWS_PROFILE=...               # optional, or use IAM role creds

cmdrvl-xew arelle install-packages --arelle-xdg-config-home ~/.cmdrvl-xew/arelle
cmdrvl-xew doctor --arelle-xdg-config-home ~/.cmdrvl-xew/arelle

cmdrvl-xew pack ... \
  --require-arelle \
  --resolution-mode offline_only \
  --arelle-xdg-config-home ~/.cmdrvl-xew/arelle
```

Notes:
- For local development, you can put these variables in `.env.local` (gitignored) and `cmdrvl-xew` will auto-load it.
- You can install from local `--package` files, or use `--url` to download packages before installing.
- Downloaded packages default to `<XDG_CONFIG_HOME>/arelle/taxonomy-packages` (override with `--download-dir`).
- To bootstrap from a bundle tarball, set `--bundle-uri` (or `$XEW_ARELLE_BUNDLE_URI`) and optionally `--bundle-sha256`.
- Always comply with publisher licenses/terms.
- Using a persistent `--arelle-xdg-config-home` avoids relying on live network fetch during `pack`.

Coverage:
- A bundle is only as complete as the taxonomy versions you include. A 2020 filing may reference `us-gaap/2020/`, `dei/2020/`, etc. If you run in `offline_only` mode, you must include those versions in your bundle.

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

Fetch a small set of representative iXBRL filings from SEC EDGAR (requires a SEC-compliant User-Agent string):

```bash
export XEW_USER_AGENT="YourOrg your.email@example.com cmdrvl-xew/0.1.0"
scripts/fetch_samples.sh --out sample
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
- v1 detectors (P001/P002/P004/P005/P008) are implemented; `pack` loads a real Arelle model by default (install `arelle-release`). Use `--no-arelle` to force the mock model, or `--require-arelle` to fail fast if Arelle cannot be used.
- Arelle is pinned through the `arelle`/`prod` extras for deterministic production installs.
- Cached S3 artifact ingress supports both `extracted/YYYYMMDD/ACCESSION/` and complete-submission `xbrl/YYYYMMDD/ACCESSION.nc` layouts.
- P008 can materialize corpus-scoped seed files for canon/OpenFIGI and adapt local canon registry output into a P008 snapshot.

Next steps (v1):
- Harden real-S3 Arelle regression coverage for broader filing sets.
- Freeze issue-code enums and pin rule basis per shipped issue code.
- Add deterministic truncation/capping rules for large instance lists.
- Package the operator-facing identity-fragility runbook around the S3, Arelle, canon snapshot, pack, and verify steps.

## License

MIT
