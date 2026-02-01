from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .util import sha256_file


def _compute_pack_sha256(files: list[dict]) -> str:
    entries = [f"{f['path']}\t{f['sha256']}\n" for f in files]
    entries.sort(key=lambda s: s.split("\t", 1)[0])
    data = "".join(entries).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def run_verify_pack(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack)
    manifest_path = pack_dir / "pack_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Missing pack_manifest.json: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_pack_sha256 = manifest.get("pack_sha256")
    files = manifest.get("files")

    if not expected_pack_sha256 or not isinstance(expected_pack_sha256, str):
        raise SystemExit("pack_manifest.json missing pack_sha256")
    if not files or not isinstance(files, list):
        raise SystemExit("pack_manifest.json missing files[]")

    ok = True

    for f in files:
        rel = f.get("path")
        exp_sha = f.get("sha256")
        exp_bytes = f.get("bytes")
        if not rel or not exp_sha or exp_bytes is None:
            ok = False
            print(f"bad manifest entry: {f}")
            continue

        abs_path = pack_dir / rel
        if not abs_path.is_file():
            ok = False
            print(f"missing file: {rel}")
            continue

        sha, n = sha256_file(abs_path)
        if sha != exp_sha:
            ok = False
            print(f"sha256 mismatch: {rel}: expected {exp_sha}, got {sha}")
        if n != exp_bytes:
            ok = False
            print(f"bytes mismatch: {rel}: expected {exp_bytes}, got {n}")

    calc_pack_sha256 = _compute_pack_sha256(files)
    if calc_pack_sha256 != expected_pack_sha256:
        ok = False
        print(f"pack_sha256 mismatch: expected {expected_pack_sha256}, got {calc_pack_sha256}")

    if args.validate_schema:
        ok = _validate_findings_schema(pack_dir) and ok

    return 0 if ok else 2


def _validate_findings_schema(pack_dir: Path) -> bool:
    findings_path = pack_dir / "xew_findings.json"
    if not findings_path.is_file():
        print("missing xew_findings.json")
        return False

    try:
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"failed to parse xew_findings.json: {e}")
        return False

    try:
        import jsonschema  # type: ignore
        from importlib import resources

        schema_text = resources.files("cmdrvl_xew").joinpath("schemas/xew_findings.schema.v1.json").read_text(
            encoding="utf-8"
        )
        schema = json.loads(schema_text)
        try:
            format_checker = jsonschema.FormatChecker()
        except AttributeError:
            format_checker = None
        if format_checker is None:
            jsonschema.validate(instance=findings, schema=schema)
        else:
            jsonschema.validate(instance=findings, schema=schema, format_checker=format_checker)
        return True
    except ModuleNotFoundError:
        print("jsonschema not installed; skipping schema validation")
        return True
    except Exception as e:
        print(f"schema validation failed: {e}")
        return False
