from __future__ import annotations

import argparse
import sys

from .pack import run_pack
from .verify import run_verify_pack


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    p = argparse.ArgumentParser(prog="cmdrvl-xew")
    sub = p.add_subparsers(dest="cmd", required=True)

    pack = sub.add_parser("pack", help="Generate an Evidence Pack")
    pack.add_argument("--pack-id", required=True)
    pack.add_argument("--out", required=True, help="Output directory (will be created)")

    pack.add_argument("--primary", required=True, help="Path to primary inline XBRL HTML")

    pack.add_argument("--issuer-name")
    pack.add_argument("--cik", required=True)
    pack.add_argument("--accession", required=True)
    pack.add_argument("--form", required=True)
    pack.add_argument("--filed-date", required=True)
    pack.add_argument("--period-end")
    pack.add_argument("--primary-document-url", required=True)

    pack.add_argument("--comparator-accession")
    pack.add_argument("--comparator-primary-document-url")
    pack.add_argument("--comparator-primary-artifact-path")

    pack.add_argument("--retrieved-at", help="ISO 8601 UTC timestamp; default: now")
    pack.add_argument("--arelle-version", help="Record the Arelle version used")
    pack.add_argument("--resolution-mode", default="offline_preferred")

    verify = sub.add_parser("verify-pack", help="Verify an Evidence Pack")
    verify.add_argument("--pack", required=True, help="Evidence Pack directory")
    verify.add_argument("--validate-schema", action="store_true", help="Validate xew_findings.json if jsonschema is installed")

    args = p.parse_args(argv)

    if args.cmd == "pack":
        args._invocation_argv = ["cmdrvl-xew", *argv]
        return run_pack(args)
    if args.cmd == "verify-pack":
        return run_verify_pack(args)

    p.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
