"""Deterministic cache + retrieval metadata for Evidence Pack reproducibility.

Provides transparent caching of EDGAR artifacts with deterministic cache keys
and comprehensive retrieval metadata recording for pack reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from .util import sha256_file, utc_now_iso, _ensure_ascii


@dataclass(frozen=True)
class CacheKey:
    """Deterministic cache key for artifacts."""

    url: str
    method: str = "GET"
    headers_sig: Optional[str] = None  # Signature of relevant headers

    def __post_init__(self):
        _ensure_ascii(self.url, "cache key URL")
        _ensure_ascii(self.method, "cache key method")
        if self.headers_sig:
            _ensure_ascii(self.headers_sig, "headers signature")

    def key_string(self) -> str:
        """Generate deterministic cache key string."""
        parts = [self.url, self.method.upper()]
        if self.headers_sig:
            parts.append(self.headers_sig)
        return sha256("|".join(parts).encode('utf-8')).hexdigest()


@dataclass
class RetrievalMetadata:
    """Metadata about artifact retrieval for reproducibility."""

    cache_key: str
    source_url: str
    retrieved_at: str
    cache_hit: bool
    file_size: int
    content_sha256: str
    headers: Dict[str, str] = field(default_factory=dict)
    response_status: Optional[int] = None
    user_agent: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self):
        _ensure_ascii(self.cache_key, "cache key")
        _ensure_ascii(self.source_url, "source URL")
        _ensure_ascii(self.retrieved_at, "retrieved_at timestamp")
        _ensure_ascii(self.content_sha256, "content SHA256")
        for key, value in self.headers.items():
            _ensure_ascii(key, "header key")
            _ensure_ascii(value, "header value")
        if self.user_agent:
            _ensure_ascii(self.user_agent, "user agent")
        if self.notes:
            _ensure_ascii(self.notes, "notes")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = {
            "cache_key": self.cache_key,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "cache_hit": self.cache_hit,
            "file_size": self.file_size,
            "content_sha256": self.content_sha256,
            "headers": self.headers,
        }
        if self.response_status is not None:
            data["response_status"] = self.response_status
        if self.user_agent:
            data["user_agent"] = self.user_agent
        if self.notes:
            data["notes"] = self.notes
        return data


@dataclass
class CacheConfig:
    """Configuration for deterministic caching."""

    cache_directory: Optional[Path] = None
    enable_cache: bool = True
    max_cache_size_mb: Optional[int] = None  # Future: cache size limits
    cache_ttl_seconds: Optional[int] = None  # Future: cache TTL
    include_headers_in_key: List[str] = field(default_factory=list)  # Headers that affect caching
    metadata_file: str = "retrieval_metadata.jsonl"

    def __post_init__(self):
        if self.cache_directory:
            self.cache_directory = Path(self.cache_directory)


class DeterministicCache:
    """Deterministic cache with retrieval metadata recording."""

    def __init__(self, config: CacheConfig):
        self.config = config
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Ensure cache directory exists if caching is enabled."""
        if self.config.enable_cache and self.config.cache_directory:
            self.config.cache_directory.mkdir(parents=True, exist_ok=True)

    def cache_key_for_url(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> CacheKey:
        """Generate deterministic cache key for a URL request."""
        headers = headers or {}

        # Include only relevant headers in cache key signature
        relevant_headers = {}
        for header_name in self.config.include_headers_in_key:
            if header_name.lower() in {k.lower() for k in headers.keys()}:
                # Find actual header with case-insensitive match
                for k, v in headers.items():
                    if k.lower() == header_name.lower():
                        relevant_headers[header_name.lower()] = v
                        break

        headers_sig = None
        if relevant_headers:
            # Sort headers for determinism
            sorted_headers = sorted(relevant_headers.items())
            headers_sig = sha256("|".join(f"{k}:{v}" for k, v in sorted_headers).encode('utf-8')).hexdigest()

        return CacheKey(url=url, headers_sig=headers_sig)

    def cache_path_for_key(self, cache_key: CacheKey) -> Path:
        """Get cache file path for a cache key."""
        if not self.config.cache_directory:
            raise ValueError("Cache directory not configured")

        key_str = cache_key.key_string()
        # Use first 2 chars as subdirectory for better filesystem performance
        subdir = key_str[:2]
        return self.config.cache_directory / "artifacts" / subdir / f"{key_str}.bin"

    def metadata_path(self) -> Path:
        """Get path to retrieval metadata file."""
        if not self.config.cache_directory:
            raise ValueError("Cache directory not configured")
        return self.config.cache_directory / self.config.metadata_file

    def is_cached(self, cache_key: CacheKey) -> bool:
        """Check if artifact is cached."""
        if not self.config.enable_cache:
            return False
        try:
            cache_path = self.cache_path_for_key(cache_key)
            return cache_path.exists() and cache_path.is_file()
        except Exception:
            return False

    def get_cached(self, cache_key: CacheKey) -> Optional[bytes]:
        """Retrieve cached artifact bytes."""
        if not self.is_cached(cache_key):
            return None

        try:
            cache_path = self.cache_path_for_key(cache_key)
            return cache_path.read_bytes()
        except Exception:
            return None

    def store_cached(self, cache_key: CacheKey, content: bytes) -> bool:
        """Store artifact in cache."""
        if not self.config.enable_cache or not self.config.cache_directory:
            return False

        try:
            cache_path = self.cache_path_for_key(cache_key)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)
            return True
        except Exception:
            return False

    def record_retrieval(self, metadata: RetrievalMetadata) -> None:
        """Record retrieval metadata for reproducibility."""
        if not self.config.cache_directory:
            return

        try:
            metadata_path = self.metadata_path()
            metadata_path.parent.mkdir(parents=True, exist_ok=True)

            # Append to JSONL file
            with metadata_path.open('a', encoding='utf-8') as f:
                json.dump(metadata.to_dict(), f, ensure_ascii=True, separators=(',', ':'))
                f.write('\n')
        except Exception:
            # Don't fail retrieval if metadata recording fails
            pass

    def get_retrieval_metadata_for_pack(self) -> List[Dict[str, Any]]:
        """Get all retrieval metadata for pack recording."""
        if not self.config.cache_directory:
            return []

        metadata_path = self.metadata_path()
        if not metadata_path.exists():
            return []

        records = []
        try:
            with metadata_path.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception:
            pass

        return records


def create_retrieval_metadata(
    url: str,
    content: bytes,
    *,
    cache_key: Optional[str] = None,
    cache_hit: bool = False,
    headers: Optional[Dict[str, str]] = None,
    response_status: Optional[int] = None,
    user_agent: Optional[str] = None,
    notes: Optional[str] = None,
    retrieved_at: Optional[str] = None,
) -> RetrievalMetadata:
    """Create retrieval metadata from download results."""
    content_hash = sha256(content).hexdigest()

    return RetrievalMetadata(
        cache_key=cache_key or sha256(url.encode('utf-8')).hexdigest(),
        source_url=url,
        retrieved_at=retrieved_at or utc_now_iso(),
        cache_hit=cache_hit,
        file_size=len(content),
        content_sha256=content_hash,
        headers=headers or {},
        response_status=response_status,
        user_agent=user_agent,
        notes=notes,
    )


def sha256(data: bytes) -> 'hashlib._Hash':
    """Helper for SHA256 hashing."""
    return hashlib.sha256(data)


# Cache integration with EDGAR fetcher
def cached_edgar_download(
    cache: DeterministicCache,
    url: str,
    *,
    user_agent: str,
    headers: Optional[Dict[str, str]] = None,
    notes: Optional[str] = None,
) -> tuple[bytes, RetrievalMetadata]:
    """Download artifact with transparent caching and metadata recording."""
    headers = headers or {}
    headers["User-Agent"] = user_agent

    # Generate cache key
    cache_key = cache.cache_key_for_url(url, headers=headers)
    key_str = cache_key.key_string()

    # Check cache first
    cached_content = cache.get_cached(cache_key)
    if cached_content is not None:
        metadata = create_retrieval_metadata(
            url,
            cached_content,
            cache_key=key_str,
            cache_hit=True,
            headers=headers,
            user_agent=user_agent,
            notes=notes or "Retrieved from cache",
        )
        cache.record_retrieval(metadata)
        return cached_content, metadata

    # Download fresh
    import urllib.request
    from urllib.error import HTTPError

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            response_headers = dict(resp.headers)
            status_code = resp.getcode()

        # Cache the content
        cache.store_cached(cache_key, content)

        # Record metadata
        metadata = create_retrieval_metadata(
            url,
            content,
            cache_key=key_str,
            cache_hit=False,
            headers=response_headers,
            response_status=status_code,
            user_agent=user_agent,
            notes=notes,
        )
        cache.record_retrieval(metadata)

        return content, metadata

    except Exception as e:
        # If download fails, create metadata for the failure
        metadata = create_retrieval_metadata(
            url,
            b"",  # Empty content on failure
            cache_key=key_str,
            cache_hit=False,
            user_agent=user_agent,
            notes=f"Download failed: {e}",
        )
        cache.record_retrieval(metadata)
        raise


# Default cache configuration factory
def create_default_cache(cache_directory: Optional[Path] = None) -> DeterministicCache:
    """Create cache with default configuration."""
    config = CacheConfig(
        cache_directory=cache_directory,
        enable_cache=True,
        include_headers_in_key=["user-agent"],  # Include user-agent in cache key
    )
    return DeterministicCache(config)


def create_pack_cache(pack_cache_dir: Path) -> DeterministicCache:
    """Create cache configured for Evidence Pack generation.

    Args:
        pack_cache_dir: Directory for pack-specific cache storage

    Returns:
        Configured cache for deterministic artifact retrieval

    The cache is configured to:
    - Include user-agent in cache keys for SEC compliance tracking
    - Store artifacts in subdirectories for filesystem performance
    - Record comprehensive retrieval metadata for reproducibility
    """
    config = CacheConfig(
        cache_directory=pack_cache_dir,
        enable_cache=True,
        include_headers_in_key=["user-agent"],
        metadata_file="pack_retrieval_metadata.jsonl",
    )
    return DeterministicCache(config)


# Cache utilities for pack integration
def get_cache_metadata_for_toolchain(cache: DeterministicCache) -> Dict[str, Any]:
    """Get cache metadata for inclusion in toolchain.json."""
    if not cache.config.enable_cache or not cache.config.cache_directory:
        return {"cache_enabled": False}

    retrieval_records = cache.get_retrieval_metadata_for_pack()

    return {
        "cache_enabled": True,
        "cache_directory": str(cache.config.cache_directory),
        "retrieval_count": len(retrieval_records),
        "cache_hits": sum(1 for r in retrieval_records if r.get("cache_hit", False)),
        "network_requests": sum(1 for r in retrieval_records if not r.get("cache_hit", False)),
        "total_bytes_retrieved": sum(r.get("file_size", 0) for r in retrieval_records),
    }