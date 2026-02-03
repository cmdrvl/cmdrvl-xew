from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .exit_codes import ExitCode, exit_invocation_error, exit_processing_error
from .util import sha256_file


def _default_arelle_xdg_config_home() -> Path:
    configured = os.environ.get("XEW_ARELLE_XDG_CONFIG_HOME")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "cmdrvl-xew-arelle"


def _download_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        exit_invocation_error(f"URL must use http/https: {url}")
    name = Path(parsed.path).name
    if not name:
        exit_invocation_error(f"URL must end with a filename: {url}")
    return name


def _download_url_to_file(
    url: str,
    dest: Path,
    *,
    user_agent: str,
    min_interval_seconds: float,
    last_request_time: list[float],
    force: bool,
) -> tuple[Path, str, int]:
    """Download URL bytes to dest and return (path, sha256, size)."""
    if dest.exists() and not force:
        digest, size = sha256_file(dest)
        return dest, digest, size

    # Basic rate limiting across downloads.
    now = time.monotonic()
    elapsed = now - last_request_time[0]
    if elapsed < min_interval_seconds:
        time.sleep(min_interval_seconds - elapsed)

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)

    h = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(req) as resp:
        with tmp.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)

    # Atomic-ish move into place.
    tmp.replace(dest)
    last_request_time[0] = time.monotonic()
    return dest, h.hexdigest(), size


def run_arelle_install_packages(args: argparse.Namespace) -> int:
    """Install/register taxonomy packages in an Arelle config home.

    This writes/updates Arelle's taxonomy package registry file:
      <XDG_CONFIG_HOME>/arelle/taxonomyPackages.json

    Callers should pass the same `--arelle-xdg-config-home` to `cmdrvl-xew pack`
    and use `--resolution-mode offline_only` for production determinism.
    """
    packages = list(getattr(args, "package", None) or [])
    urls = list(getattr(args, "url", None) or [])
    if not packages and not urls:
        exit_invocation_error("At least one --package or --url is required")

    xdg_home = Path(getattr(args, "arelle_xdg_config_home", None) or _default_arelle_xdg_config_home())
    xdg_home.mkdir(parents=True, exist_ok=True)

    package_paths: list[Path] = []
    for raw in packages:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            exit_invocation_error(f"Taxonomy package not found: {p}")
        package_paths.append(p)

    download_dir = Path(
        getattr(args, "download_dir", None) or (xdg_home / "arelle" / "taxonomy-packages")
    ).expanduser().resolve()
    force = bool(getattr(args, "force", False))
    min_interval = float(getattr(args, "min_interval", 0.2))
    if min_interval < 0:
        exit_invocation_error("--min-interval must be >= 0")

    downloaded: list[dict] = []
    user_agent = ""
    if urls:
        download_dir.mkdir(parents=True, exist_ok=True)
        from .sec_policy import SECRequestConfig

        user_agent = (getattr(args, "user_agent", None) or "").strip()
        if not user_agent:
            user_agent = SECRequestConfig(application_version=__version__).get_user_agent()

        # Align with EDGAR fetch rules: require contact info to avoid default/bot UAs.
        try:
            from .edgar_fetch import _validate_user_agent  # type: ignore

            _validate_user_agent(user_agent)
        except Exception as e:
            exit_invocation_error(str(e))

        last_request_time = [0.0]
        for url in urls:
            filename = _download_filename_from_url(url)
            dest = download_dir / filename
            path, digest, size = _download_url_to_file(
                url,
                dest,
                user_agent=user_agent,
                min_interval_seconds=min_interval,
                last_request_time=last_request_time,
                force=force,
            )
            downloaded.append({"url": url, "path": str(path), "sha256": digest, "size": size})
            package_paths.append(path.resolve())

    previous_xdg = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(xdg_home)
    try:
        from arelle import Cntlr, PackageManager  # type: ignore

        from .sec_policy import SECRequestConfig

        cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
        cntlr.webCache.httpUserAgent = user_agent or SECRequestConfig(application_version=__version__).get_user_agent()

        # In command-line mode, Arelle doesn't load taxonomyPackages.json by default.
        # Force loading so addPackage/save reads/writes the expected registry file.
        PackageManager.init(cntlr, loadPackagesConfig=True)

        if downloaded:
            print(f"Downloaded {len(downloaded)} package(s) to {download_dir}:")
            for entry in downloaded:
                print(
                    f"  {Path(entry['path']).name} sha256={entry['sha256']} bytes={entry['size']} url={entry['url']}"
                )

        installed: list[dict] = []
        for p in package_paths:
            info = PackageManager.addPackage(cntlr, str(p))
            if not info:
                exit_processing_error(f"Arelle could not load taxonomy package: {p}")
            installed.append(info)

        PackageManager.rebuildRemappings(cntlr)
        PackageManager.save(cntlr)

        registry_path = Path(cntlr.userAppDir) / "taxonomyPackages.json"
        print(f"Arelle XDG_CONFIG_HOME: {xdg_home}")
        print(f"Taxonomy package registry: {registry_path}")
        print(f"Installed {len(installed)} package(s):")
        for info in installed:
            name = info.get("name") or "unknown"
            version = info.get("version") or "unknown"
            identifier = info.get("identifier") or ""
            suffix = f" id={identifier}" if identifier else ""
            print(f"  {name} version={version}{suffix}")

        return ExitCode.SUCCESS

    except SystemExit:
        raise
    except Exception as e:
        exit_processing_error(f"Failed to install taxonomy packages via Arelle: {e}")
    finally:
        if previous_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = previous_xdg
