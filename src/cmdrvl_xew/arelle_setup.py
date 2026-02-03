from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import tarfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin
from urllib.parse import urlparse
import zipfile

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


def _looks_like_directory_url(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    if parsed.path.endswith("/"):
        return True
    # Treat URLs without an extension as directory URLs (e.g. .../dei/2025).
    return Path(parsed.path).suffix == ""


def _normalize_base_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        exit_invocation_error(f"URL must use http/https: {url}")
    if not parsed.netloc:
        exit_invocation_error(f"URL must include a host: {url}")
    base = url
    if not base.endswith("/"):
        base += "/"
    return base


_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)


def _download_bundle_uri_to_path(
    uri: str,
    *,
    download_dir: Path,
    aws_profile: str | None,
    force: bool,
) -> Path:
    uri = (uri or "").strip()
    if not uri:
        exit_invocation_error("--bundle-uri must not be empty")

    parsed = urlparse(uri)
    if parsed.scheme == "file":
        p = Path(parsed.path).expanduser().resolve()
        if not p.exists():
            exit_invocation_error(f"Bundle file not found: {p}")
        return p

    if parsed.scheme in ("http", "https"):
        filename = _download_filename_from_url(uri)
        dest = (download_dir / filename).resolve()
        if dest.exists() and not force:
            return dest
        req = urllib.request.Request(uri, headers={"User-Agent": f"cmdrvl-xew/{__version__}"})
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req) as resp:
            with dest.open("wb") as f:
                shutil.copyfileobj(resp, f)
        return dest

    if uri.startswith("s3://"):
        filename = Path(uri.rstrip("/")).name or "bundle.tgz"
        dest = (download_dir / filename).resolve()
        if dest.exists() and not force:
            return dest
        cmd = ["aws"]
        if aws_profile:
            cmd.extend(["--profile", aws_profile])
        cmd.extend(["s3", "cp", "--only-show-errors", uri, str(dest)])
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            exit_invocation_error("AWS CLI not found; install `aws` or use a file:// bundle.")
        except subprocess.CalledProcessError as e:
            exit_processing_error(f"Failed to download bundle from S3 ({uri}): {e}")
        return dest

    # Fall back to local filesystem path (relative or absolute).
    p = Path(uri).expanduser().resolve()
    if not p.exists():
        exit_invocation_error(f"Unknown bundle URI (expected s3://, http(s)://, file://, or local path): {uri}")
    return p


def _safe_extract_tarball(tar_path: Path, *, dest_dir: Path, force: bool) -> None:
    """Extract a tarball into dest_dir, preventing traversal and symlinks.

    If the tar contains a single top-level directory, strip it (so bundles created as
    `tar -C <parent> -czf bundle.tgz <childdir>` extract cleanly into dest_dir).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()

    with tarfile.open(tar_path, mode="r:*") as tf:
        members = tf.getmembers()

        top_levels: set[str] = set()
        for m in members:
            name = (m.name or "").lstrip("./")
            if not name or name == ".":
                continue
            parts = Path(name).parts
            if parts:
                top_levels.add(parts[0])
        strip_top = next(iter(top_levels)) if len(top_levels) == 1 else None

        for m in members:
            name = (m.name or "").lstrip("./")
            if not name or name == ".":
                continue

            if strip_top and name.startswith(strip_top + "/"):
                name = name[len(strip_top) + 1 :]
            if not name:
                continue

            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts:
                exit_invocation_error(f"Unsafe path in bundle tarball: {m.name}")

            out_path = (dest_root / rel).resolve()
            if not str(out_path).startswith(str(dest_root) + os.sep) and out_path != dest_root:
                exit_invocation_error(f"Unsafe extraction target in bundle tarball: {m.name}")

            if m.isdir():
                out_path.mkdir(parents=True, exist_ok=True)
                continue

            if m.issym() or m.islnk():
                exit_invocation_error(f"Refusing to extract symlink from bundle tarball: {m.name}")

            if not m.isreg():
                exit_invocation_error(f"Unsupported tar entry type in bundle tarball: {m.name}")

            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.exists() and not force:
                continue
            src = tf.extractfile(m)
            if src is None:
                exit_invocation_error(f"Failed to read tar entry from bundle: {m.name}")
            with src:
                with out_path.open("wb") as f:
                    shutil.copyfileobj(src, f)


def _discover_local_taxonomy_packages(download_dir: Path) -> list[Path]:
    """Discover taxonomy packages under download_dir for registration in Arelle.

    - Includes taxonomy package .zip files in download_dir root.
    - Includes mirrored directory packages: **/_mirror/**/META-INF/taxonomyPackage.xml
    """
    discovered: list[Path] = []
    if not download_dir.exists():
        return discovered

    for p in sorted(download_dir.glob("*.zip")):
        if _is_arelle_taxonomy_package_zip(p):
            discovered.append(p.resolve())

    mirror_root = download_dir / "_mirror"
    if mirror_root.exists():
        for p in sorted(mirror_root.rglob("META-INF/taxonomyPackage.xml")):
            discovered.append(p.resolve())

    return discovered


def _fetch_text(
    url: str,
    *,
    user_agent: str,
    min_interval_seconds: float,
    last_request_time: list[float],
) -> str:
    # Basic rate limiting across requests.
    now = time.monotonic()
    elapsed = now - last_request_time[0]
    if elapsed < min_interval_seconds:
        time.sleep(min_interval_seconds - elapsed)

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    last_request_time[0] = time.monotonic()
    return data.decode("utf-8", errors="replace")


def _is_arelle_taxonomy_package_zip(path: Path) -> bool:
    if path.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            return any(name.endswith("META-INF/taxonomyPackage.xml") for name in zf.namelist())
    except zipfile.BadZipFile:
        return False


def _catalog_xml(base_url: str, rewrite_prefix: str) -> str:
    base_url = _normalize_base_url(base_url)
    mappings = [base_url]
    if base_url.startswith("https://"):
        mappings.append("http://" + base_url[len("https://"):])
    elif base_url.startswith("http://"):
        mappings.append("https://" + base_url[len("http://"):])

    lines = ['<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">']
    for mapping in sorted(set(mappings)):
        lines.append(f'  <rewriteURI uriStartString="{mapping}" rewritePrefix="{rewrite_prefix}"/>')
    lines.append("</catalog>")
    return "\n".join(lines) + "\n"


def _taxonomy_package_xml(base_url: str) -> str:
    base_url = _normalize_base_url(base_url)
    identifier = base_url.rstrip("/")
    version = base_url.rstrip("/").split("/")[-1]
    name = f"Mirror {identifier}"
    description = "Local mirror for offline Arelle resolution (generated by cmdrvl-xew)."
    # Keep this minimal; Arelle can parse without schema validation when offline.
    return (
        "<tp:taxonomyPackage xml:lang='en' xmlns:tp='http://xbrl.org/2016/taxonomy-package'>\n"
        f"<tp:identifier>{identifier}</tp:identifier>\n"
        f"<tp:name>{name}</tp:name>\n"
        f"<tp:description>{description}</tp:description>\n"
        f"<tp:version>{version}</tp:version>\n"
        "</tp:taxonomyPackage>\n"
    )


def _mirror_directory(
    base_url: str,
    *,
    download_root: Path,
    user_agent: str,
    min_interval_seconds: float,
    last_request_time: list[float],
    force: bool,
) -> tuple[Path, list[dict]]:
    base_url = _normalize_base_url(base_url)
    parsed = urlparse(base_url)
    rel_path = parsed.path.lstrip("/").rstrip("/")
    mirror_dir = (download_root / "_mirror" / parsed.netloc / rel_path).resolve()
    mirror_dir.mkdir(parents=True, exist_ok=True)

    index_html = _fetch_text(
        base_url,
        user_agent=user_agent,
        min_interval_seconds=min_interval_seconds,
        last_request_time=last_request_time,
    )
    hrefs = _HREF_RE.findall(index_html)
    xsd_files = sorted(
        {
            href
            for href in hrefs
            if href
            and not href.startswith("?")
            and not href.startswith("/")
            and not href.endswith("/")
            and href.lower().endswith(".xsd")
        }
    )
    if not xsd_files:
        exit_processing_error(f"No .xsd files found at directory URL: {base_url}")

    downloaded: list[dict] = []
    for filename in xsd_files:
        file_url = urljoin(base_url, filename)
        dest = mirror_dir / filename
        path, digest, size = _download_url_to_file(
            file_url,
            dest,
            user_agent=user_agent,
            min_interval_seconds=min_interval_seconds,
            last_request_time=last_request_time,
            force=force,
        )
        downloaded.append({"url": file_url, "path": str(path), "sha256": digest, "size": size})

    meta_inf = mirror_dir / "META-INF"
    meta_inf.mkdir(parents=True, exist_ok=True)

    taxonomy_pkg_path = meta_inf / "taxonomyPackage.xml"
    if not taxonomy_pkg_path.exists():
        taxonomy_pkg_path.write_text(_taxonomy_package_xml(base_url), encoding="utf-8")

    catalog_path = meta_inf / "catalog.xml"
    if not catalog_path.exists():
        # Mirror files live at the package root; from META-INF/, that is "../".
        catalog_path.write_text(_catalog_xml(base_url, "../"), encoding="utf-8")

    return taxonomy_pkg_path, downloaded


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
    bundle_uri = (getattr(args, "bundle_uri", None) or "").strip() or None
    bundle_sha256 = (getattr(args, "bundle_sha256", None) or "").strip() or None
    aws_profile = (getattr(args, "aws_profile", None) or "").strip() or None
    no_bundle = bool(getattr(args, "no_bundle", False))
    if no_bundle:
        bundle_uri = None

    if not packages and not urls and not bundle_uri:
        exit_invocation_error("At least one of --bundle-uri, --package, or --url is required")

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
    mirrored: list[dict] = []
    user_agent = ""

    bundle_path: Path | None = None
    if bundle_uri:
        bundle_download_dir = xdg_home / "arelle" / "taxonomy-bundles"
        bundle_path = _download_bundle_uri_to_path(
            bundle_uri,
            download_dir=bundle_download_dir,
            aws_profile=aws_profile,
            force=force,
        )
        if bundle_sha256:
            digest, _size = sha256_file(bundle_path)
            if digest.lower() != bundle_sha256.lower():
                exit_processing_error(
                    f"Bundle sha256 mismatch: expected {bundle_sha256} got {digest} ({bundle_path})"
                )

        # If packages already exist and we're not forcing, avoid re-extracting.
        existing_packages = bool(download_dir.exists() and any(download_dir.iterdir()))
        if not existing_packages or force:
            _safe_extract_tarball(bundle_path, dest_dir=xdg_home, force=force)

        package_paths.extend(_discover_local_taxonomy_packages(download_dir))

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
        mirror_base_urls: set[str] = set()
        for url in urls:
            if _looks_like_directory_url(url):
                mirror_base_urls.add(_normalize_base_url(url))
                continue
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

            if path.suffix.lower() == ".zip":
                if _is_arelle_taxonomy_package_zip(path):
                    package_paths.append(path.resolve())
                else:
                    # SEC "zip" downloads are often plain archives (not Arelle taxonomy packages).
                    # Fall back to mirroring the parent directory (download .xsd files + catalog.xml).
                    mirror_base_urls.add(_normalize_base_url(url.rsplit("/", 1)[0]))

        for base_url in sorted(mirror_base_urls):
            catalog_path, mirror_downloads = _mirror_directory(
                base_url,
                download_root=download_dir,
                user_agent=user_agent,
                min_interval_seconds=min_interval,
                last_request_time=last_request_time,
                force=force,
            )
            package_root = str(Path(catalog_path).parent.parent)
            mirrored.append({"base_url": base_url, "package_dir": package_root, "files": mirror_downloads})
            package_paths.append(Path(catalog_path).resolve())

    # De-dupe paths (keep stable ordering).
    unique: list[Path] = []
    seen: set[str] = set()
    for p in package_paths:
        k = str(p)
        if k in seen:
            continue
        unique.append(p)
        seen.add(k)
    package_paths = unique

    if not package_paths:
        exit_invocation_error("No taxonomy packages found to install (check bundle contents and --download-dir)")

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

        # Arelle versions differ in how taxonomyPackages.json is keyed. Newer versions key by
        # package "identifier" and may raise KeyError when older configs are missing it.
        cfg = getattr(PackageManager, "packagesConfig", None)
        if isinstance(cfg, dict):
            pkgs = cfg.get("packages")
            if isinstance(pkgs, list):
                changed = False
                for pkg in pkgs:
                    if isinstance(pkg, dict) and "identifier" not in pkg:
                        pkg["identifier"] = pkg.get("URL") or f"{pkg.get('name', '')}|{pkg.get('version', '')}"
                        changed = True
                if changed and hasattr(PackageManager, "packagesConfigChanged"):
                    PackageManager.packagesConfigChanged = True

        if bundle_uri:
            print(f"Bundle source: {bundle_uri}")
            if bundle_path:
                print(f"Bundle file: {bundle_path}")

        if downloaded:
            print(f"Downloaded {len(downloaded)} URL file(s) to {download_dir}:")
            for entry in downloaded:
                print(
                    f"  {Path(entry['path']).name} sha256={entry['sha256']} bytes={entry['size']} url={entry['url']}"
                )
        if mirrored:
            print(f"Mirrored {len(mirrored)} taxonomy directory URL(s) into local catalogs:")
            for entry in mirrored:
                print(f"  {entry['base_url']} -> {entry['package_dir']} ({len(entry['files'])} file(s))")

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
