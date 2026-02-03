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
- Findings are populated when detectors run successfully; if the XBRL model cannot be loaded, the pack will emit empty findings with warnings (use `--require-arelle` to fail fast instead).
- `--p001-conflict-mode` controls how XEW-P001 flags numeric value conflicts: `rounded` (default) tolerates rounding-consistent duplicates; `strict` flags any mismatch.

Pack flags:
- Required: `--pack-id`, `--out`, `--primary`, `--cik`, `--accession`, `--form`, `--filed-date`, `--primary-document-url`
- Optional: `--issuer-name`, `--period-end`, `--retrieved-at`, `--arelle-version`, `--resolution-mode`, `--p001-conflict-mode`, `--require-arelle`, `--no-arelle`, `--arelle-xdg-config-home`, `--derive-artifact-urls`
- History window (repeatable, all-or-nothing): `--history-accession`, `--history-primary-document-url`, `--history-primary-artifact-path`
- Comparator (optional, all-or-nothing): `--comparator-accession`, `--comparator-primary-document-url`, `--comparator-primary-artifact-path`

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
  --url https://xbrl.fasb.org/us-gaap/2025/us-gaap-2025.zip \
  --url https://xbrl.fasb.org/srt/2025/srt-2025.zip \
  --url https://xbrl.sec.gov/dei/2025/ \
  --url https://xbrl.sec.gov/exch/2025/

# Then run pack using the same config home, offline-only:
cmdrvl-xew pack ... \
  --resolution-mode offline_only \
  --arelle-xdg-config-home ~/.cmdrvl-xew/arelle
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

cmdrvl-xew pack ... \
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

Fetch a small set of representative extracted iXBRL filings from S3:

```bash
scripts/fetch_samples.sh

# Optional overrides
scripts/fetch_samples.sh --profile edgar-readonly --bucket edgar-data-full --out sample
```

Included accessions:
- 10-K: `0000020639-25-010025`
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
- v1 detectors (P001/P002/P004/P005) are implemented; `pack` loads a real Arelle model by default (install `arelle-release`). Use `--no-arelle` to force the mock model, or `--require-arelle` to fail fast if Arelle cannot be used.

Next steps (v1):
- Harden Arelle loading and detector inputs for broader filing coverage.
- Freeze issue-code enums and pin rule basis per shipped issue code.
- Add deterministic truncation/capping rules for large instance lists.

## License

MIT
