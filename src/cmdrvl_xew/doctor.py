from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .exit_codes import ExitCode


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str  # OK | WARN | FAIL
    message: str
    fix: str | None = None


def run_doctor(args: argparse.Namespace) -> int:
    """Check local environment configuration for deterministic `pack` runs."""
    checks: list[DoctorCheck] = []

    xdg_home = _resolve_arelle_xdg_config_home(getattr(args, "arelle_xdg_config_home", None))
    registry_path = xdg_home / "arelle" / "taxonomyPackages.json"

    checks.extend(_check_arelle_importable())
    checks.extend(_check_xdg_config_home_writable(xdg_home))
    checks.extend(_check_taxonomy_registry(registry_path))
    checks.extend(_check_bundle_env())
    checks.extend(_check_user_agent_env())

    _print_checks(checks, xdg_home=xdg_home, registry_path=registry_path)

    has_fail = any(c.status == "FAIL" for c in checks)
    has_warn = any(c.status == "WARN" for c in checks)
    _print_summary(has_warn=has_warn, has_fail=has_fail)
    return ExitCode.CONFIG_ERROR if has_fail else ExitCode.SUCCESS


def _resolve_arelle_xdg_config_home(cli_value: str | None) -> Path:
    configured = (cli_value or os.environ.get("XEW_ARELLE_XDG_CONFIG_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("/tmp") / "cmdrvl-xew-arelle"


def _check_arelle_importable() -> list[DoctorCheck]:
    try:
        from arelle import Version  # type: ignore

        version = getattr(Version, "version", None) or getattr(Version, "__version__", None) or "unknown"
        return [DoctorCheck("arelle", "OK", f"import ok (version={version})")]
    except Exception as e:
        return [
            DoctorCheck(
                "arelle",
                "FAIL",
                f"cannot import ({e})",
                fix="Install Arelle (pip install arelle-release).",
            )
        ]


def _check_xdg_config_home_writable(xdg_home: Path) -> list[DoctorCheck]:
    try:
        xdg_home.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return [
            DoctorCheck(
                "arelle_xdg_config_home",
                "FAIL",
                f"not writable: {xdg_home} ({e})",
                fix="Choose a writable path and pass --arelle-xdg-config-home, or set XEW_ARELLE_XDG_CONFIG_HOME.",
            )
        ]
    return [DoctorCheck("arelle_xdg_config_home", "OK", f"{xdg_home}")]


def _check_taxonomy_registry(registry_path: Path) -> list[DoctorCheck]:
    if not registry_path.exists():
        return [
            DoctorCheck(
                "taxonomy_packages",
                "FAIL",
                f"missing registry: {registry_path}",
                fix=(
                    "Run: cmdrvl-xew arelle install-packages --arelle-xdg-config-home <DIR>\n"
                    "Then run packs with the same --arelle-xdg-config-home and --resolution-mode offline_only."
                ),
            )
        ]

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [
            DoctorCheck(
                "taxonomy_packages",
                "FAIL",
                f"invalid registry JSON: {registry_path} ({e})",
                fix="Re-run: cmdrvl-xew arelle install-packages --arelle-xdg-config-home <DIR> --force",
            )
        ]

    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        return [
            DoctorCheck(
                "taxonomy_packages",
                "FAIL",
                f"registry has no packages: {registry_path}",
                fix="Re-run: cmdrvl-xew arelle install-packages --arelle-xdg-config-home <DIR>",
            )
        ]

    return [DoctorCheck("taxonomy_packages", "OK", f"{len(packages)} package(s) installed")]


def _check_bundle_env() -> list[DoctorCheck]:
    uri = (os.environ.get("XEW_ARELLE_BUNDLE_URI") or "").strip()
    if not uri:
        return [
            DoctorCheck(
                "bundle_uri",
                "WARN",
                "XEW_ARELLE_BUNDLE_URI not set",
                fix="Optional: set XEW_ARELLE_BUNDLE_URI (s3://, http(s)://, file://, or local path) for easy bootstrap.",
            )
        ]

    sha = (os.environ.get("XEW_ARELLE_BUNDLE_SHA256") or "").strip()
    if not sha:
        return [
            DoctorCheck(
                "bundle_uri",
                "WARN",
                f"set: {uri} (no XEW_ARELLE_BUNDLE_SHA256)",
                fix="Recommended: set XEW_ARELLE_BUNDLE_SHA256 to pin bundle integrity.",
            )
        ]

    profile = (os.environ.get("AWS_PROFILE") or "").strip()
    if uri.startswith("s3://") and not profile:
        return [
            DoctorCheck(
                "bundle_uri",
                "WARN",
                f"set: {uri} (AWS_PROFILE not set)",
                fix="If using S3 bundle URIs, set AWS_PROFILE or configure IAM role credentials.",
            )
        ]

    return [DoctorCheck("bundle_uri", "OK", f"set: {uri}")]


def _check_user_agent_env() -> list[DoctorCheck]:
    user_agent = (os.environ.get("XEW_USER_AGENT") or "").strip()
    if not user_agent:
        return [
            DoctorCheck(
                "user_agent",
                "WARN",
                "XEW_USER_AGENT not set",
                fix="Required for `cmdrvl-xew fetch` and any online taxonomy resolution.",
            )
        ]

    try:
        from .edgar_fetch import _validate_user_agent  # type: ignore

        _validate_user_agent(user_agent)
        return [DoctorCheck("user_agent", "OK", "set (SEC-compliant)")]
    except Exception as e:
        return [
            DoctorCheck(
                "user_agent",
                "WARN",
                f"set but invalid: {e}",
                fix="Set XEW_USER_AGENT to a descriptive value with contact info (email/URL/phone).",
            )
        ]


def _print_checks(checks: list[DoctorCheck], *, xdg_home: Path, registry_path: Path) -> None:
    print("cmdrvl-xew doctor")
    print(f"Arelle XDG_CONFIG_HOME: {xdg_home}")
    print(f"Taxonomy package registry: {registry_path}")
    print("")
    for c in checks:
        print(f"[{c.status}] {c.name}: {c.message}")
        if c.fix:
            print(f"      fix: {c.fix}")


def _print_summary(*, has_warn: bool, has_fail: bool) -> None:
    if has_fail:
        summary = "FAIL (not configured)"
    elif has_warn:
        summary = "WARN (not fully configured)"
    else:
        summary = "OK"
    print("")
    print(f"Overall: {summary}")
