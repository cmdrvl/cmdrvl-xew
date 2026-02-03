# Taxonomy Resolution and Rule Basis Policy (v1)

Purpose
- Define how taxonomy inputs are resolved and recorded for reproducibility.
- Define how rule basis citations are pinned and enforced (Gate).

Scope
- Applies to `cmdrvl-xew pack` and `cmdrvl-xew verify-pack` outputs.
- Covers taxonomy inputs, non-redistributable artifacts, and rule basis citations.

## 1) Taxonomy resolution policy

Goals:
- Deterministic processing across environments.
- Reproducible Evidence Packs with pinned inputs.

Resolution modes (see `src/cmdrvl_xew/taxonomy.py`):
- `offline_only`: use local/pinned packages only. Fail if missing.
- `offline_preferred`: use local/pinned packages when available; allow online fallback (default config).
- `online_only`: resolve from official online sources (validation/testing only).
- `hybrid`: local for standard taxonomies, online for extensions.

Current engine behavior:
- The pack pipeline records `resolution_mode` in toolchain config.
- Local artifacts are collected from the flat input directory.
- External taxonomy references (schemaRef/linkbaseRef URLs) are skipped during artifact collection.
- A full taxonomy resolver exists in `src/cmdrvl_xew/taxonomy.py` but is not wired into pack execution yet.
- Arelle taxonomy packages can be registered for offline runs using:
  - `cmdrvl-xew arelle install-packages --arelle-xdg-config-home <DIR> --package <PATH> [--package ...] [--url <URL> ...]`
  - This writes/updates `<DIR>/arelle/taxonomyPackages.json` (Arelle's taxonomy package registry).
  - When using `--url`, packages are downloaded to `<XDG_CONFIG_HOME>/arelle/taxonomy-packages` by default (override via `--download-dir`).

## 2) Recording taxonomy inputs

Evidence Packs must record taxonomy inputs used to resolve or validate filings:
- `toolchain/toolchain.json` SHOULD include `taxonomy_inputs` when taxonomy packages are used.
- Each entry should include a stable identifier and integrity hash:
  - `name`, `version`, `namespace_uri`, `sha256`, `source` (local vs remote)

When online resolution is used, record:
- `retrieved_at` (UTC ISO 8601)
- the source URL and `sha256` for any downloaded packages or rule sources

If a taxonomy input cannot be redistributed, record it as a non-redistributable reference (see section 3).

## 3) Non-redistributable artifacts

Some artifacts must not be embedded in the pack. The pack records them in toolchain metadata under `non_redistributable_artifacts` with:
- `source_url`
- `retrieved_at`
- `sha256`
- optional `content_type` and `notes`

Current non-redistributable rules (see `src/cmdrvl_xew/pack.py`):
- External sources not hosted on `sec.gov`, `xbrl.sec.gov`, or `xbrl.fasb.org`.
- Large artifacts over 10MB.
- Compressed package files (`.zip`, `.tar.gz`, `.7z`).

## 4) Rule basis policy (Gate)

Rule basis citations are required for any alert-eligible finding.

Source of truth:
- `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json`

Gate enforcement (see `src/cmdrvl_xew/detectors/registry.py`):
- Findings without valid rule basis are demoted:
  - `status = "suppressed"`
  - `alert_eligible = False`
  - `suppression_reason = "Missing or invalid rule basis citation"`
- Suppressed findings remain in `xew_findings.json` for review.

Minimum citation fields:
- `source` (authority label)
- `retrieved_at` (UTC ISO 8601)
- `sha256` (content hash of the referenced authority)
- `url` or `title` (location of the authority)

Policy constraints:
- No rule basis -> no shipping alert.
- Rule basis changes must be explicit and versioned to avoid silent drift.

## 5) Operational guidance

- Always pass a fixed `--retrieved-at` for deterministic pack output.
- If online taxonomy resolution is used, record all fetched inputs in toolchain metadata.
- Keep rule basis citations pinned to immutable URLs or archived copies with recorded hashes.

## References

- Evidence Pack contract: `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`
- Rule basis map: `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json`
- Taxonomy policy code: `src/cmdrvl_xew/taxonomy.py`
