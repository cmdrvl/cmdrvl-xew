from __future__ import annotations

import json
import time
import urllib.request
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Dict, List, Tuple

_DEFAULT_MIN_INTERVAL_SECONDS = 0.2

_EXHIBIT_PREFIXES = ("ex",)
_PRIMARY_HTML_SUFFIXES = (".htm", ".html")
_LINKBASE_SUFFIXES = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
_USER_AGENT_MIN_LEN = 8
_USER_AGENT_CONTACT_TOKENS = ("@", "http://", "https://", "mailto:", "tel:")


@dataclass(frozen=True)
class EdgarDirectoryItem:
    name: str
    type: str | None = None
    size: int | None = None
    last_modified: str | None = None


@dataclass
class RateLimiter:
    min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_SECONDS
    _last_request: float = 0.0

    def wait(self) -> None:
        """Sleep as needed to enforce a minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_request = time.monotonic()


def accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


def cik_dirname(cik: str) -> str:
    return str(int(cik))


def accession_base_url(cik: str, accession: str) -> str:
    return f"https://data.sec.gov/Archives/edgar/data/{cik_dirname(cik)}/{accession_no_dashes(accession)}"


def fetch_accession_items(cik: str, accession: str, *, user_agent: str) -> list[EdgarDirectoryItem]:
    """Fetch EDGAR index (JSON/HTML) for an accession with SEC-compliant headers."""
    _validate_user_agent(user_agent)
    limiter = RateLimiter()
    base = accession_base_url(cik, accession)
    json_url = f"{base}/index.json"
    html_url = f"{base}/index.html"
    try:
        text = _fetch_text(json_url, user_agent=user_agent, rate_limiter=limiter)
        return parse_index_json(text)
    except (HTTPError, URLError, ValueError):
        text = _fetch_text(html_url, user_agent=user_agent, rate_limiter=limiter)
        return parse_index_html(text)


def parse_index_json(text: str) -> list[EdgarDirectoryItem]:
    data = json.loads(text)
    directory = data.get("directory") or {}
    items = directory.get("item") or []
    parsed: list[EdgarDirectoryItem] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        parsed.append(
            EdgarDirectoryItem(
                name=name,
                type=item.get("type"),
                size=_coerce_int(item.get("size")),
                last_modified=item.get("last-modified") or item.get("last_modified"),
            )
        )
    return parsed


def parse_index_html(text: str) -> list[EdgarDirectoryItem]:
    items: list[EdgarDirectoryItem] = []
    start = 0
    needle = "<a href=\""
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            break
        name_start = idx + len(needle)
        name_end = text.find("\"", name_start)
        if name_end == -1:
            break
        name = text[name_start:name_end]
        start = name_end + 1
        lower = name.lower()
        if name == "../" or lower.startswith("parent"):
            continue
        if lower in ("index.html", "index.htm"):
            continue
        items.append(EdgarDirectoryItem(name=name))
    return items


def select_primary_html(items: Iterable[EdgarDirectoryItem]) -> EdgarDirectoryItem | None:
    candidates: list[EdgarDirectoryItem] = []
    for item in items:
        name_lower = item.name.lower()
        if not name_lower.endswith(_PRIMARY_HTML_SUFFIXES):
            continue
        if "-index" in name_lower or name_lower in ("index.html", "index.htm"):
            continue
        if name_lower.startswith(_EXHIBIT_PREFIXES):
            continue
        candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=_primary_sort_key)
    return candidates[0]


def select_extension_artifacts(items: Iterable[EdgarDirectoryItem]) -> list[EdgarDirectoryItem]:
    selected: list[EdgarDirectoryItem] = []
    for item in items:
        name_lower = item.name.lower()
        if name_lower.endswith(".xsd"):
            selected.append(item)
        elif name_lower.endswith(_LINKBASE_SUFFIXES):
            selected.append(item)
    selected.sort(key=lambda item: item.name)
    return selected


def collect_accession_artifacts(items: Iterable[EdgarDirectoryItem]) -> tuple[EdgarDirectoryItem, list[EdgarDirectoryItem]]:
    primary = select_primary_html(items)
    if primary is None:
        raise ValueError("primary HTML not found in accession directory listing")
    extensions = select_extension_artifacts(items)
    return primary, extensions


def download_artifacts(
    base_url: str,
    items: Iterable[EdgarDirectoryItem],
    out_dir: Path,
    *,
    user_agent: str,
    min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_SECONDS,
    rate_limiter: RateLimiter | None = None,
) -> list[Path]:
    """Download accession artifacts with rate limiting and required User-Agent."""
    _validate_user_agent(user_agent)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    limiter = rate_limiter or RateLimiter(min_interval_seconds=min_interval_seconds)
    for item in sorted(items, key=lambda i: i.name):
        url = f"{base_url.rstrip('/')}/{item.name}"
        dest = out_dir / item.name
        _download(url, dest, user_agent=user_agent, rate_limiter=limiter)
        saved.append(dest)
    return saved


def _download(url: str, dest: Path, *, user_agent: str, rate_limiter: RateLimiter | None = None) -> None:
    _validate_user_agent(user_agent)
    if rate_limiter:
        rate_limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req) as resp:
        dest.write_bytes(resp.read())


def _primary_sort_key(item: EdgarDirectoryItem) -> tuple[int, str]:
    size = item.size if item.size is not None else -1
    # Prefer largest HTML file; tie-breaker by name for determinism.
    return (-size, item.name)


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fetch_text(url: str, *, user_agent: str, rate_limiter: RateLimiter | None = None) -> str:
    _validate_user_agent(user_agent)
    if rate_limiter:
        rate_limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _validate_user_agent(user_agent: str) -> None:
    if not user_agent or len(user_agent.strip()) < _USER_AGENT_MIN_LEN:
        raise ValueError("User-Agent must be a non-empty, descriptive string with contact info.")
    lower = user_agent.lower()
    if "python-urllib" in lower or "urllib" == lower.strip():
        raise ValueError("User-Agent must not be the default urllib value; include identifying contact info.")
    if not any(token in lower for token in _USER_AGENT_CONTACT_TOKENS):
        raise ValueError("User-Agent must include contact info (email, URL, or phone).")


# Cache-integrated versions for deterministic retrieval + metadata recording

def fetch_accession_items_cached(
    cik: str,
    accession: str,
    *,
    user_agent: str,
    cache: Optional['DeterministicCache'] = None
) -> Tuple[List[EdgarDirectoryItem], List['RetrievalMetadata']]:
    """Fetch EDGAR index with optional caching and metadata recording."""
    from .cache import create_retrieval_metadata

    _validate_user_agent(user_agent)
    base = accession_base_url(cik, accession)
    json_url = f"{base}/index.json"
    html_url = f"{base}/index.html"

    metadata_records = []

    # Try JSON first, then HTML fallback
    try:
        if cache:
            from .cache import cached_edgar_download
            content, metadata = cached_edgar_download(
                cache, json_url, user_agent=user_agent,
                notes=f"EDGAR index.json for {accession}"
            )
            metadata_records.append(metadata)
            text = content.decode('utf-8', errors='replace')
        else:
            # Non-cached path
            limiter = RateLimiter()
            text = _fetch_text(json_url, user_agent=user_agent, rate_limiter=limiter)

        return parse_index_json(text), metadata_records

    except (HTTPError, URLError, ValueError):
        # Fallback to HTML
        if cache:
            from .cache import cached_edgar_download
            content, metadata = cached_edgar_download(
                cache, html_url, user_agent=user_agent,
                notes=f"EDGAR index.html for {accession} (JSON fallback)"
            )
            metadata_records.append(metadata)
            text = content.decode('utf-8', errors='replace')
        else:
            # Non-cached path
            limiter = RateLimiter()
            text = _fetch_text(html_url, user_agent=user_agent, rate_limiter=limiter)

        return parse_index_html(text), metadata_records


def download_artifacts_cached(
    base_url: str,
    items: Iterable[EdgarDirectoryItem],
    out_dir: Path,
    *,
    user_agent: str,
    min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_SECONDS,
    rate_limiter: Optional[RateLimiter] = None,
    cache: Optional['DeterministicCache'] = None,
) -> Tuple[List[Path], List['RetrievalMetadata']]:
    """Download accession artifacts with optional caching and metadata recording."""
    _validate_user_agent(user_agent)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    metadata_records: List['RetrievalMetadata'] = []
    limiter = rate_limiter or RateLimiter(min_interval_seconds=min_interval_seconds)

    for item in sorted(items, key=lambda i: i.name):
        url = f"{base_url.rstrip('/')}/{item.name}"
        dest = out_dir / item.name

        if cache:
            # Use cached download
            from .cache import cached_edgar_download
            if limiter:
                limiter.wait()
            content, metadata = cached_edgar_download(
                cache, url, user_agent=user_agent,
                notes=f"EDGAR artifact: {item.name}"
            )
            dest.write_bytes(content)
            metadata_records.append(metadata)
        else:
            # Direct download (existing logic)
            _download(url, dest, user_agent=user_agent, rate_limiter=limiter)

        saved.append(dest)

    return saved, metadata_records


def collect_accession_artifacts_cached(
    cik: str,
    accession: str,
    out_dir: Path,
    *,
    user_agent: str,
    min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_SECONDS,
    cache: Optional['DeterministicCache'] = None,
) -> Tuple[Path, List[Path], List['RetrievalMetadata']]:
    """Complete cached workflow: fetch index, select artifacts, download with metadata."""
    # Fetch directory listing with caching
    items, index_metadata = fetch_accession_items_cached(
        cik, accession, user_agent=user_agent, cache=cache
    )

    # Select primary and extension artifacts
    primary, extensions = collect_accession_artifacts(items)

    # Download artifacts with caching
    base_url = accession_base_url(cik, accession)
    downloaded, download_metadata = download_artifacts_cached(
        base_url, [primary] + extensions, out_dir,
        user_agent=user_agent, min_interval_seconds=min_interval_seconds, cache=cache
    )

    # Combine all metadata
    all_metadata = index_metadata + download_metadata

    # Return primary path, extension paths, and metadata
    primary_path = downloaded[0]  # Primary is always first
    extension_paths = downloaded[1:]  # Extensions are the rest

    return primary_path, extension_paths, all_metadata
