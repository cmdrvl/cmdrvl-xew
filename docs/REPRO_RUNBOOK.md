# XEW Evidence Pack Repro Runbook (v1)

Purpose
- Provide a deterministic, step-by-step procedure to reproduce XEW findings from filing artifacts.
- Keep outputs reproducible and auditable using only the Evidence Pack.

Scope
- This runbook covers artifact-driven reproduction using `cmdrvl-xew pack` and `cmdrvl-xew verify-pack`.
- EDGAR-driven fetching is available via `cmdrvl-xew fetch` (SEC-compliant User-Agent required).

## 1) Prerequisites

- Python 3 and a virtual environment
- Install the CLI:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e .
  ```
- Optional schema validation:
  ```bash
  pip install -e '.[jsonschema]'
  ```
- Optional: Arelle installed in the environment for real XBRL model loading. Without Arelle, pack runs with a mock model and findings may be empty.

## 2) Inputs and directories

You need:
- A flat artifact directory (primary iXBRL HTML + related local artifacts).
- The primary HTML path used for detection.
- Filing metadata (CIK, accession, form, filed date, primary document URL).

If you want adaptation markers that rely on history/comparators, provide all related arguments (all-or-nothing):
- History window: `--history-accession`, `--history-primary-document-url`, `--history-primary-artifact-path` (repeatable)
- Comparator: `--comparator-accession`, `--comparator-primary-document-url`, `--comparator-primary-artifact-path`

For deterministic outputs, always pass a fixed `--retrieved-at` timestamp (UTC ISO 8601).

## 3) Prepare artifacts

Option A (recommended): use pre-staged artifacts
- Ensure the primary HTML and any local schema/linkbase files are available in a flat directory.

Option B: flatten an extracted EDGAR directory
```bash
cmdrvl-xew flatten /path/to/extracted/0000034903-25-000063 --out /tmp/flat
```

Notes:
- The output directory must be empty unless you pass `--force`.
- `flatten` is the standard way to get a flat directory for `pack`.

## 4) Generate the Evidence Pack

```bash
cmdrvl-xew pack \
  --pack-id XEW-EP-0007 \
  --out /tmp/XEW-EP-0007 \
  --primary /tmp/flat/primary-document.html \
  --cik 0000123456 \
  --accession 0000123456-26-000005 \
  --form 10-Q \
  --filed-date 2026-01-20 \
  --primary-document-url https://www.sec.gov/Archives/edgar/data/123456/000012345626000005/primary-document.html \
  --retrieved-at 2026-01-20T12:00:00Z
```

Optional (when applicable):
- `--issuer-name`, `--period-end`, `--arelle-version`, `--resolution-mode`, `--p001-conflict-mode`, `--p008-registry-snapshot`, `--p008-require-registry`, `--derive-artifact-urls`
- History window and comparator arguments (see section 2)

For XEW-P008 Instrument Identity Collapse, pass a local canon/OpenFIGI snapshot:

```bash
cmdrvl-xew pack \
  --pack-id XEW-EP-P008-MSFT \
  --out /tmp/XEW-EP-P008-MSFT \
  --primary /path/to/msft-primary.html \
  --cik 0000789019 \
  --accession 0001193125-26-191507 \
  --form 10-Q \
  --filed-date 2026-04-24 \
  --primary-document-url https://www.sec.gov/Archives/edgar/data/789019/000119312526191507/msft-20260331.htm \
  --retrieved-at 2026-06-09T00:00:00Z \
  --p008-registry-snapshot /path/to/p008-openfigi-snapshot.json \
  --p008-require-registry
```

The Microsoft-style deterministic fixture used by the test suite expects one collapse group for `MSFT`/`Nasdaq` with common stock, `3.125% Notes due 2028`, and `2.625% Notes due 2033`; the registry snapshot fixture resolves them to `BBG000BPH459`, `BBG005NPW5Z2`, and `BBG004HDR2M6`.

To prepare a local snapshot from canon registry output, keep the provider call outside `pack`:

```bash
cmdrvl-xew p008 materialize-registry \
  --corpus-id msft-proof \
  --filing-manifest /path/to/corpus.jsonl \
  --out-dir /tmp/msft-registry-work \
  --version 2026.06.09 \
  --provider-config base_url=http://127.0.0.1:9000/v3/mapping

cmdrvl-xew p008 snapshot-from-canon \
  --registry-dir /tmp/msft-registry-work/registries/openfigi-cusip-2026.06.09 \
  --overlay /path/to/p008-overlay.json \
  --out /tmp/p008-openfigi-snapshot.json
```

For cached S3 filings, use `fetch-s3` before `pack`:

```bash
cmdrvl-xew fetch-s3 \
  --bucket edgar-data-full \
  --date-partition 20260429 \
  --accession 0001193125-26-191507 \
  --source-layout extracted \
  --aws-profile salt_profile \
  --out /tmp/msft-flat
```

## 5) Verify the pack

```bash
cmdrvl-xew verify-pack --pack /tmp/XEW-EP-0007

# Optional schema validation
cmdrvl-xew verify-pack --pack /tmp/XEW-EP-0007 --validate-schema
```

## 6) Review outputs

Key files in the pack:
- `xew_findings.json` (findings output)
- `pack_manifest.json` (file hashes + pack_sha256)
- `toolchain/toolchain.json` (reproducibility config, marker thresholds, history window, comparator selection)
- `reproduction_steps.json` (built-in step list)
- `artifacts/` (bytes used for detection)
- `generated/instrument_identity_collapse.v1.json` (present when XEW-P008 emits collapse evidence)

Basic inspection:
```bash
python3 -m json.tool /tmp/XEW-EP-0007/xew_findings.json | head -n 40
python3 -m json.tool /tmp/XEW-EP-0007/pack_manifest.json | head -n 60
```

## 7) Determinism check (optional)

To check byte-for-byte determinism:
1) Re-run `cmdrvl-xew pack` with the same inputs and the same `--retrieved-at`.
2) Compare `pack_manifest.json` or `pack_sha256` values between runs.

Note: toolchain system info may differ across machines. To compare bytes, re-run in the same environment and pass the same `--retrieved-at`.

## 8) Troubleshooting

- If findings are empty and you expect detections, ensure Arelle is installed and the primary HTML is valid iXBRL.
- If `verify-pack --validate-schema` fails, install the `jsonschema` extra and re-run.
- If external taxonomy inputs are not bundled, check `toolchain/toolchain.json` for non-redistributable references and fetch those inputs using the recorded URLs and sha256.
- If P008 emits `registry_snapshot_missing`, rerun with `--p008-registry-snapshot`; if strict proof is required, also pass `--p008-require-registry`.
- If P008 emits `registry_snapshot_ambiguous`, fix the local snapshot producer or narrow the corpus snapshot before treating FIGI enrichment as resolved.

## References

- Evidence Pack contract: `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`
- Findings schema: `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json`
