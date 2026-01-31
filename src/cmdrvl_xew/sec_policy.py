"""SEC EDGAR access policy compliance for respectful and lawful data retrieval.

This module implements SEC-compliant request patterns, rate limiting, and user-agent
policies to ensure cmdrvl-xew accesses EDGAR data responsibly and legally.

Reference: SEC EDGAR Access Policy
https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class SECAccessError(Exception):
    """Exception raised for SEC access policy violations or errors."""
    pass


@dataclass
class SECRequestConfig:
    """Configuration for SEC-compliant HTTP requests."""

    # User-Agent Requirements (SEC mandates proper identification)
    company_name: str = "CMD+RVL"
    contact_email: str = "compliance@cmdrvl.com"
    application_name: str = "cmdrvl-xew"
    application_version: str = "1.0"

    # Rate Limiting (SEC recommends max 10 requests per second)
    max_requests_per_second: float = 8.0  # Conservative limit
    request_delay_seconds: float = 0.125  # 1/8 second = 8 requests/second

    # Timeout and Retry Policy
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0

    # Request Headers
    accept_encoding: str = "gzip, deflate"
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    def __post_init__(self):
        """Validate configuration parameters."""
        if self.max_requests_per_second <= 0:
            raise ValueError("max_requests_per_second must be positive")
        if self.request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative")
        if not self.company_name or not self.contact_email:
            raise ValueError("company_name and contact_email are required for SEC compliance")

        # Ensure delay matches rate limit
        if self.max_requests_per_second > 0:
            calculated_delay = 1.0 / self.max_requests_per_second
            if calculated_delay > self.request_delay_seconds:
                self.request_delay_seconds = calculated_delay

    def get_user_agent(self) -> str:
        """Generate SEC-compliant User-Agent header.

        Format: CompanyName ContactEmail ApplicationName/Version
        """
        return f"{self.company_name} {self.contact_email} {self.application_name}/{self.application_version}"

    def get_request_headers(self) -> Dict[str, str]:
        """Generate complete HTTP headers for SEC requests."""
        return {
            "User-Agent": self.get_user_agent(),
            "Accept": self.accept,
            "Accept-Encoding": self.accept_encoding,
            "Connection": "keep-alive",  # Efficient but not excessive
        }


@dataclass
class SECRateLimiter:
    """Rate limiter for SEC EDGAR requests with request timing tracking."""

    config: SECRequestConfig
    last_request_time: Optional[float] = field(default=None, init=False)
    request_count: int = field(default=0, init=False)
    session_start_time: float = field(default_factory=time.time, init=False)

    def wait_if_needed(self) -> None:
        """Wait if necessary to comply with rate limits."""
        current_time = time.time()

        if self.last_request_time is not None:
            time_since_last = current_time - self.last_request_time
            required_delay = self.config.request_delay_seconds

            if time_since_last < required_delay:
                sleep_time = required_delay - time_since_last
                logger.debug(f"Rate limiting: sleeping {sleep_time:.3f} seconds")
                time.sleep(sleep_time)
                current_time = time.time()

        self.last_request_time = current_time
        self.request_count += 1

    def get_session_stats(self) -> Dict[str, Any]:
        """Get request statistics for this session."""
        session_duration = time.time() - self.session_start_time
        avg_rate = self.request_count / session_duration if session_duration > 0 else 0

        return {
            "requests_made": self.request_count,
            "session_duration_seconds": session_duration,
            "average_requests_per_second": avg_rate,
            "configured_max_rate": self.config.max_requests_per_second,
            "last_request_timestamp": datetime.fromtimestamp(
                self.last_request_time, tz=timezone.utc
            ).isoformat() if self.last_request_time else None
        }


class SECCompliantHTTPClient:
    """HTTP client with SEC EDGAR access policy compliance."""

    def __init__(self, config: Optional[SECRequestConfig] = None):
        self.config = config or SECRequestConfig()
        self.rate_limiter = SECRateLimiter(self.config)

    def fetch_text(self, url: str, *, additional_headers: Optional[Dict[str, str]] = None) -> str:
        """Fetch text content from URL with SEC compliance.

        Args:
            url: URL to fetch
            additional_headers: Optional additional HTTP headers

        Returns:
            Text content of the response

        Raises:
            SECAccessError: If request fails after retries
        """
        headers = self.config.get_request_headers()
        if additional_headers:
            headers.update(additional_headers)

        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                # Rate limit before request
                self.rate_limiter.wait_if_needed()

                # Log request for compliance auditing
                logger.info(f"SEC request: {url} (attempt {attempt + 1})")

                # Make request
                req = urllib.request.Request(url, headers=headers)

                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    content = response.read()

                    # Handle different encodings
                    if hasattr(response, 'headers'):
                        encoding = response.headers.get_content_charset('utf-8')
                    else:
                        encoding = 'utf-8'

                    return content.decode(encoding, errors='replace')

            except HTTPError as e:
                last_exception = e
                if e.code in (403, 429):  # Rate limited or forbidden
                    wait_time = self.config.retry_delay_seconds * (self.config.backoff_multiplier ** attempt)
                    logger.warning(f"SEC rate limit/forbidden (HTTP {e.code}), waiting {wait_time:.1f}s")
                    time.sleep(wait_time)
                    continue
                elif e.code in (500, 502, 503, 504):  # Server errors
                    wait_time = self.config.retry_delay_seconds * (self.config.backoff_multiplier ** attempt)
                    logger.warning(f"SEC server error (HTTP {e.code}), retrying after {wait_time:.1f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    # Other HTTP errors (404, etc.) - don't retry
                    break

            except URLError as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    wait_time = self.config.retry_delay_seconds * (self.config.backoff_multiplier ** attempt)
                    logger.warning(f"Network error: {e}, retrying after {wait_time:.1f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    break

        # All retries exhausted
        if isinstance(last_exception, HTTPError):
            raise SECAccessError(f"HTTP {last_exception.code}: {last_exception.reason}") from last_exception
        elif isinstance(last_exception, URLError):
            raise SECAccessError(f"Network error: {last_exception.reason}") from last_exception
        else:
            raise SECAccessError(f"Failed to fetch {url} after {self.config.max_retries} retries") from last_exception

    def get_compliance_metadata(self) -> Dict[str, Any]:
        """Get metadata about SEC compliance configuration and usage."""
        return {
            "sec_compliance": {
                "user_agent": self.config.get_user_agent(),
                "rate_limiting": {
                    "max_requests_per_second": self.config.max_requests_per_second,
                    "request_delay_seconds": self.config.request_delay_seconds
                },
                "retry_policy": {
                    "max_retries": self.config.max_retries,
                    "retry_delay_seconds": self.config.retry_delay_seconds,
                    "backoff_multiplier": self.config.backoff_multiplier
                },
                "session_stats": self.rate_limiter.get_session_stats()
            }
        }


# Default factory functions
def create_default_sec_config() -> SECRequestConfig:
    """Create SEC configuration with conservative defaults."""
    return SECRequestConfig()


def create_sec_client(config: Optional[SECRequestConfig] = None) -> SECCompliantHTTPClient:
    """Create SEC-compliant HTTP client with optional custom configuration."""
    return SECCompliantHTTPClient(config or create_default_sec_config())


# Validation functions for configuration
def validate_user_agent(user_agent: str) -> bool:
    """Validate that user-agent meets SEC requirements.

    SEC requires identification including company name and contact info.
    """
    # Basic validation - should include company name and email/contact
    user_agent_lower = user_agent.lower()

    # Check for email pattern (simple validation)
    has_email = '@' in user_agent and '.' in user_agent.split('@')[-1]

    # Check for reasonable length and content
    has_company_info = len(user_agent) > 10 and any(
        char.isalpha() for char in user_agent
    )

    return has_email and has_company_info


def validate_rate_limit(requests_per_second: float) -> bool:
    """Validate that rate limit is within SEC acceptable bounds."""
    # SEC recommends max 10 requests per second
    return 0 < requests_per_second <= 10.0


def get_sec_policy_summary() -> Dict[str, Any]:
    """Get summary of SEC EDGAR access policies implemented."""
    return {
        "policy_source": "https://www.sec.gov/os/accessing-edgar-data",
        "implemented_controls": {
            "rate_limiting": "Max 8 requests/second (conservative)",
            "user_agent": "Company name + contact email + application identification",
            "retry_policy": "Exponential backoff for server errors and rate limits",
            "timeout_handling": "30 second timeouts with appropriate error handling",
            "compliance_logging": "Request logging for audit trail"
        },
        "best_practices": {
            "concurrent_connections": "Single threaded requests (no excessive parallelism)",
            "request_timing": "Minimum delay between requests",
            "error_handling": "Respectful retry behavior",
            "identification": "Clear application and organization identification"
        }
    }


# Integration with existing edgar_fetch module
def create_compliant_fetch_function(config: Optional[SECRequestConfig] = None):
    """Create a drop-in replacement for _fetch_text with SEC compliance."""
    client = create_sec_client(config)

    def compliant_fetch_text(url: str, *, user_agent: str) -> str:
        """SEC-compliant replacement for edgar_fetch._fetch_text.

        Note: user_agent parameter is ignored in favor of SEC-compliant configuration.
        """
        logger.debug(f"Replacing provided user-agent with SEC-compliant version")
        return client.fetch_text(url)

    return compliant_fetch_text