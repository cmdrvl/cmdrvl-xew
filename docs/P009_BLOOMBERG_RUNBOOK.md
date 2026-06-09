# XEW-P009 Bloomberg Runbook

Purpose: show temporal instrument identity fragility as a reproducible evidence outcome. XEW starts from a broad local corpus, ranks fragile source scopes, packages the top ranked case, and verifies the pack without runtime provider calls.

## Outcome

The story to show:

1. A reporting history contains instrument observations for the same source-defined scope.
2. XEW scans the broad corpus and selects the strongest P009 candidate by deterministic rank.
3. A local canon/OpenFIGI snapshot proves that a reported identifier basis changed, or records why the bridge is missing or ambiguous.
4. The Evidence Pack reproduces that result from cached source bytes and hashed normalized observations.
5. `verify-pack` proves the artifacts and hashes are internally consistent.

The important distinction is that XEW is not looking up one CUSIP. It is finding identity fragility across time, preserving ambiguity, and making the proof portable.

## Boundaries

Allowed before XEW pack generation:
- Use orchestrator, warehouse exports, SEC caches, or private tools to create a local `p009_corpus_manifest.v1.jsonl`.
- Use source adapters outside or inside XEW to create `p009_observations.v1.jsonl`.
- Use canon/OpenFIGI to materialize a local registry snapshot from P009 seed files.
- Use a local OpenFIGI twin by default. Live provider calls require an explicit maintenance run and `--allow-live-provider`.

Forbidden during `scan-corpus`, `pack`, and `verify-pack`:
- SEC network fetches.
- OpenFIGI, canon, twinning, HTTP, warehouse, orchestrator, or LLM calls.
- Fuzzy identity collapse from ticker, issuer name, title, value, or other weak fields.

Weak fields are evidence only. They can create `weak_continuity_only` or `weak_key_temporal_collision`, but they cannot create resolved continuity.

## Inputs

Required local inputs:
- `p009_corpus_manifest.v1.jsonl`: provider-neutral source rows with `scope_key`, dates, source id or accession, and cached artifact refs.
- `p009_observations.v1.jsonl`: normalized instrument identity observations with strong identifiers, weak evidence, source refs, and report periods.
- `artifacts-root/`: local cached files referenced by manifest `local_path`.

Optional local input:
- `p009-openfigi-snapshot.json`: canon/OpenFIGI registry snapshot. It may prove a CUSIP to FIGI, ISIN to CUSIP, SEDOL to FIGI, or typed-identifier bridge. If omitted, XEW still scans and emits absent/missing bridge evidence where applicable.

## Step 1: Scan A Broad Corpus

Do not start by hand-picking one filing. Start from the broad local corpus export and let XEW rank the source scopes.

```bash
cmdrvl-xew p009 scan-corpus \
  --manifest /tmp/p009-corpus/p009_corpus_manifest.v1.jsonl \
  --observations /tmp/p009-corpus/p009_observations.v1.jsonl \
  --registry-snapshot /tmp/p009-registry/p009-openfigi-snapshot.json \
  --out-dir /tmp/p009-work/scan
```

Inspect:

```bash
head -n 20 /tmp/p009-work/scan/p009_scan_summary.v1.csv
head -n 1 /tmp/p009-work/scan/p009_scan_candidates.v1.jsonl | python3 -m json.tool
head -n 1 /tmp/p009-work/scan/p009_registry_seeds.v1.jsonl | python3 -m json.tool
```

Expected strongest case:
- `continuity_class=registry_bridged` when local registry evidence proves the same instrument across identifier-basis drift.
- `issue_codes=identifier_basis_transition,registry_bridge_available`.
- `source_ids`, `observation_ids`, and `pack_input_plan` identify the exact source rows that will be packaged.

If the registry snapshot is omitted, a CUSIP to FIGI history should not be guessed. It should appear as unresolved evidence such as `weak_key_temporal_collision` or `registry_bridge_missing`, depending on the observations.

## Step 2: Generate Registry Seeds

If the initial scan lacked a registry snapshot, stop after seed generation.

```bash
cmdrvl-xew p009 prove-identity-drift \
  --manifest /tmp/p009-corpus/p009_corpus_manifest.v1.jsonl \
  --observations /tmp/p009-corpus/p009_observations.v1.jsonl \
  --artifacts-root /tmp/p009-corpus/artifacts \
  --out /tmp/p009-work \
  --select-rank 1 \
  --stop-after seeds \
  --retrieved-at 2026-06-09T00:00:00Z
```

Seed outputs:
- `registry_seeds/cusip.csv`
- `registry_seeds/isin.csv`
- `registry_seeds/sedol.csv`
- `registry_seeds/figi.csv`
- `registry_seeds/p009_selected_registry_seeds.v1.jsonl`

Materialize the local registry as a maintenance step. Prefer a local OpenFIGI twin.

```bash
cmdrvl-xew p009 prove-identity-drift \
  --manifest /tmp/p009-corpus/p009_corpus_manifest.v1.jsonl \
  --observations /tmp/p009-corpus/p009_observations.v1.jsonl \
  --artifacts-root /tmp/p009-corpus/artifacts \
  --out /tmp/p009-work-materialize \
  --select-rank 1 \
  --materialize-registry \
  --provider-source openfigi \
  --provider-config base_url=http://127.0.0.1:9000/v3/mapping \
  --registry-version 2026.06.09 \
  --retrieved-at 2026-06-09T00:00:00Z
```

Add `--run-canon` only when the local canon command should execute. Add `--allow-live-provider` only for an explicit maintenance run that is permitted to call the live provider.

## Step 3: Package The Ranked Candidate

Run the full workflow with the local registry snapshot.

```bash
cmdrvl-xew p009 prove-identity-drift \
  --manifest /tmp/p009-corpus/p009_corpus_manifest.v1.jsonl \
  --observations /tmp/p009-corpus/p009_observations.v1.jsonl \
  --registry-snapshot /tmp/p009-registry/p009-openfigi-snapshot.json \
  --artifacts-root /tmp/p009-corpus/artifacts \
  --out /tmp/p009-work \
  --select-rank 1 \
  --pack-id XEW-P009-BLOOMBERG-IDENTITY-FRAGILITY \
  --retrieved-at 2026-06-09T00:00:00Z
```

Use `--dry-run` first when presenting the plan. The dry run prints the selected candidate, seed/materialization plan, exact `pack` command, exact `verify-pack` command, and redacted provider config.

## Step 4: Verify

```bash
cmdrvl-xew verify-pack \
  --pack /tmp/p009-work/pack \
  --validate-schema
```

The pack is not meeting-ready until verification passes.

## Artifacts To Show

Show these files in this order:

1. `p009_identity_fragility_summary.v1.json`: one-page workflow summary with selected rank, issue codes, continuity class, pack status, and verify status.
2. `scan/p009_scan_summary.v1.csv`: proves the case came from broad deterministic ranking.
3. `scan/p009_scan_candidates.v1.jsonl`: source ids, observation ids, event details, and pack-input plan.
4. `pack/xew_findings.json`: `XEW-P009` finding with `instrument_identity_drift` instance data.
5. `pack/generated/instrument_identity_drift.v1.json`: timeline, alias graph, registry snapshot status, unresolved candidates, diagnostics.
6. `pack/artifacts/p008_registry_snapshot.json`: copied local canon/OpenFIGI snapshot bytes when a registry was supplied.
7. `pack/pack_manifest.json`: hashes for source artifacts, selected observations, registry snapshot, generated P009 artifact, and `pack_sha256`.
8. `verify-pack` output: final integrity check.

## Timeline Highlight Script

Use this after pack generation to print the strongest visual: the instrument's reported basis over time and the local registry result.

```bash
python3 - /tmp/p009-work/pack/generated/instrument_identity_drift.v1.json <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    artifact = json.load(handle)

print("XEW-P009 temporal identity timeline")
print(f"registry snapshot: {artifact.get('registry_snapshot', {}).get('status', 'unknown')}")
for event in artifact.get("events", []):
    print()
    print(f"event: {event.get('continuity_class')} / {','.join(event.get('issue_codes', []))}")
    print(f"basis: {event.get('basis_before', {})} -> {event.get('basis_after', {})}")
    refs = sorted(
        event.get("observation_refs", []),
        key=lambda ref: (
            ref.get("report_period", ""),
            ref.get("accession", ""),
            ref.get("source_id", ""),
            str(ref.get("observation_ordinal", "")),
        ),
    )
    for ref in refs:
        reported = ref.get("reported_basis", {})
        resolved = ref.get("resolved_basis", {})
        lookup = ref.get("registry_lookup", {})
        source = ",".join(ref.get("source_paths", []))
        print(
            f"{ref.get('report_period', '')} "
            f"{ref.get('source_id', ref.get('accession', ''))}: "
            f"reported={reported.get('basis_type')}:{reported.get('basis_value', '')} "
            f"resolved={resolved.get('basis_type')}:{resolved.get('basis_value', '')} "
            f"registry={lookup.get('status', '')} "
            f"source={source}"
        )
PY
```

## Talking Points

Why this matters:
- A downstream join can silently change meaning when a filer reports CUSIP in one period and FIGI, ISIN, ticker, or only descriptive text later.
- XEW separates proven continuity from fragile continuity. It can say "local registry proves this bridge", "the bridge is missing", or "the bridge is ambiguous".
- The evidence is reproducible. The pack contains the bytes, normalized observations, local registry snapshot, generated timeline, hashes, and verification result.

Why OpenFIGI is better than ticker or CUSIP alone in this workflow:
- Tickers are exchange-local, reused, and often describe a trading symbol rather than a durable instrument identity.
- CUSIP is strong but jurisdictional, licensing-constrained, and not consistently present across all reporting contexts.
- OpenFIGI provides global persistent identifiers and contextual levels: the listed instrument FIGI, composite FIGI for country or market-level aggregation, and share-class FIGI for grouping listings of the same share class. That hierarchy lets XEW connect local identifiers across contexts while preserving the exact level of identity being asserted.

What makes the outcome different from a direct OpenFIGI lookup:
- The scan is corpus-scale and temporal.
- Registry calls are isolated to a materialization step and become local bytes.
- Ambiguity is first-class evidence, not an error to hide.
- The final pack verifies with no provider dependency.

## Fallback Synthetic Path

If live corpus selection, cached source retrieval, or registry materialization is blocked, use the committed synthetic workflow coverage to prove the same chain end to end:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_p009_workflow.TestP009Workflow.test_full_workflow_runs_scan_pack_verify_and_emits_summary \
  tests.test_p009_pack_e2e.TestP009PackE2E.test_pack_emits_p009_finding_generated_artifact_and_manifest_entry \
  tests.test_p009_scan.TestP009Scan.test_scan_discovers_one_fragile_scope_among_clean_histories
```

Those fixtures cover:
- broad scan with clean histories plus one ranked fragile scope,
- CUSIP to FIGI registry bridge,
- pack generation,
- generated `instrument_identity_drift.v1.json`,
- `verify-pack --validate-schema`.

## Failure Modes To Call Out

- `registry_snapshot.status=absent`: no local registry snapshot was supplied; no live lookup was attempted.
- `registry_status=missing`: a bridge was needed, but the supplied local snapshot did not contain a usable exact identifier row.
- `registry_status=ambiguous`: multiple local rows matched; XEW preserves sorted candidates instead of choosing one.
- `weak_continuity_only`: weak fields line up, but strong identity continuity is not proven.
- `weak_key_temporal_collision`: the same weak key maps to multiple strong identities over the history window.

The review posture is intentional: false precision is worse than explicit unresolved evidence.
