# AGENTS.md - cmdrvl-xew

Open-source CMD+RVL XBRL Early Warning (XEW) engine.

This repo owns the CLI + library that:
- loads inline XBRL (iXBRL) filing artifacts,
- runs objective XEW detectors,
- emits `xew_findings.json`, and
- writes a reproducible Evidence Pack directory (manifest + artifacts + toolchain).

This repo does NOT own monitoring/orchestration or alert delivery.

---

## Critical Safety Rules

**RULE NUMBER 1**: Never delete any file without express permission. Even files you created (like test files). Always ask and receive clear, written permission before deleting any file or folder.

### Irreversible Git & Filesystem Actions -- DO NOT BREAK GLASS

1. **Absolutely forbidden commands:** `git reset --hard`, `git clean -fd`, `rm -rf`, or any command that can delete or overwrite code/data must never be run unless the user explicitly provides the exact command and states they understand and want the irreversible consequences.
2. **No guessing:** If there is any uncertainty about what a command might delete or overwrite, stop immediately and ask the user for specific approval.
3. **Safer alternatives first:** When cleanup or rollbacks are needed, request permission to use non-destructive options (`git status`, `git diff`, `git stash`, copying to backups) before ever considering a destructive command.
4. **Mandatory explicit plan:** Even after explicit user authorization, restate the command verbatim, list exactly what will be affected, and wait for confirmation. Only then may you execute it.
5. **Document the confirmation:** When running any approved destructive command, record the exact user text that authorized it, the command actually run, and the execution time.

### Code File Management

- **No uncontrolled proliferation**: If you want to change something or add a feature, revise the existing code file in place. Never create "V2", "improved", "enhanced", or "unified" versions of existing files.
- **No backwards compatibility hacks**: Prefer correct design with explicit versioning (schemas/contracts). Avoid compatibility shims.
- New code files are reserved for genuinely new functionality that makes zero sense to include in any existing code file.

---

## Repository Role

**Role**: Deterministic detection engine for XBRL Early Warning (XEW)

**Position in stack**: Evidence Pack generator (engine) used by hosted monitoring/delivery systems.

**What it owns**:
- CLI: `cmdrvl-xew` (`pack`, `verify-pack`)
- Evidence Pack contract: `docs/XEW_EVIDENCE_PACK_CONTRACT_V1.MD`
- Findings schema: `src/cmdrvl_xew/schemas/xew_findings.schema.v1.json`
- v1 detector logic (patterns + issue codes) as objective checks

---

## Key Invariants (Do Not Break)

- **Reproducibility is the product**: A third party should be able to reproduce findings from the Evidence Pack.
- **Determinism**: IDs, ordering, truncation, and hashing must be deterministic.
- **Evidence over interpretation**: Emit only claims derivable from artifacts + pinned rule basis.
- **No semantic claims in v1**: Avoid "semantic unrelatedness" assertions or other meaning claims that cannot be derived objectively.
- **No silent drift**: Any change that affects output must be versioned (schema/contract/spec).
- **No secrets**: Do not commit credentials, tokens, customer identifiers, or large filing artifacts.

---

## CLI Contract (v1)

- `cmdrvl-xew flatten`: normalize EDGAR directory structure into flat Arelle-compatible layout.
- `cmdrvl-xew pack`: generate an Evidence Pack directory (requires flat input from `flatten`).
- `cmdrvl-xew verify-pack`: verify `pack_manifest.json` hashes and (optionally) validate `xew_findings.json` against the schema.

Workflow:
```bash
# 1. Flatten EDGAR directory structure
cmdrvl-xew flatten sample/0000034903-25-000063 --out /tmp/flat

# 2. Generate Evidence Pack from flat artifacts
cmdrvl-xew pack --primary /tmp/flat/frt-20250930.htm \
    --pack-id XEW-EP-0001 --out /tmp/pack \
    --cik 0000034903 --accession 0000034903-25-000063 \
    --form 10-Q --filed-date 2025-11-01 \
    --primary-document-url "https://www.sec.gov/..."

# 3. Verify the pack
cmdrvl-xew verify-pack --pack /tmp/pack --validate-schema
```

Design intent:
- Artifact-driven mode is first-class (production systems already stage artifacts).
- The `flatten` command handles EDGAR's typed directory structure.
- EDGAR-driven fetch mode is optional and must respect SEC access policies if implemented.

---

## Project Structure

```
cmdrvl-xew/
|- AGENTS.md
|- README.md
|- docs/
|  |- PLAN_EDGAR_NEXT_XBRL_EARLY_WARNING.MD
|  |- XEW_EVIDENCE_PACK_CONTRACT_V1.MD
|  `- examples/
|     `- xew_findings.example.v1.json
|- sample/                          # Sample EDGAR accessions for testing
|  `- <accession>/
|     |- 10-Q/ or 10-K/             # Primary iXBRL
|     |- EX-101.SCH/                # Extension schema
|     |- EX-101.CAL/                # Calculation linkbase
|     |- EX-101.DEF/                # Definition linkbase
|     |- EX-101.LAB/                # Label linkbase
|     `- EX-101.PRE/                # Presentation linkbase
|- src/
|  `- cmdrvl_xew/
|     |- cli.py                     # CLI entrypoint
|     |- flatten.py                 # EDGAR -> flat directory normalization
|     |- pack.py                    # Evidence Pack generation
|     |- verify.py                  # Pack verification
|     |- util.py                    # Shared utilities
|     |- schemas/
|     |  `- xew_findings.schema.v1.json
|     `- spec/
|        |- xew_issue_codes.v1.json
|        `- xew_rule_basis_map.v1.json
`- pyproject.toml
```

---

## Development Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cmdrvl-xew --help
cmdrvl-xew pack --help
cmdrvl-xew verify-pack --help

# Optional schema validation support
pip install -e '.[jsonschema]'
```

---

## Detector Development Rules

- Every shipped `issue_code` must have pinned rule basis in `src/cmdrvl_xew/spec/xew_rule_basis_map.v1.json`.
- Do not change canonical signature rules without updating the contract (and bumping versions when required).
- Keep fixtures tiny; do not commit real filings or full taxonomy packages.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   br sync --flush-only
   git add .beads/
   git commit -m "sync beads"
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
