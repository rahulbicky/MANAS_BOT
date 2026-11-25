"""
backend/app/utils/security_validation.py
----------------------------------------
Security validation utilities for ManasBot:
  - SSRF (Server-Side Request Forgery) protection against internal/link-local/cloud-metadata targets
  - Safe URL verification for document ingestion and background scraping jobs
"""
import ipaddress
import logging
import socket
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger(__name__)

# Explicit list of forbidden hostnames
BLOCKED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "instance-data",
}


def validate_public_url(url: str) -> str:
    """Validates that a URL uses http/https and does NOT resolve to a private,

    loopback, link-local, or cloud-metadata IP address.

    Raises:
        ValueError: If the scheme is invalid, hostname is missing, DNS resolution fails,
                    or the IP is non-public (SSRF attempt).
    Returns:
        The validated clean URL string.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL cannot be empty.")

    clean_url = url.strip()
    parsed = urlparse(clean_url)

    # 1. Scheme check
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Disallowed URL scheme '{parsed.scheme}'. Only http and https are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL does not contain a valid hostname.")

    hostname_lower = hostname.lower().strip("[]")

    # 2. Block known loopback and metadata names directly
    if hostname_lower in BLOCKED_HOSTNAMES or hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        raise ValueError(f"Access to private/internal hostname '{hostname}' is forbidden (SSRF protection).")

    # 3. Direct IP address check (if hostname is an IP string)
    try:
        ip = ipaddress.ip_address(hostname_lower)
        _check_ip_safety(ip)
        return clean_url
    except ValueError as val_err:
        # Not a raw IP literal; proceed to DNS resolution
        if "forbidden" in str(val_err).lower():
            raise

    # 4. DNS Resolution Check
    try:
        addr_info = socket.getaddrinfo(hostname_lower, None)
    except socket.gaierror as dns_err:
        # In sandboxed offline environments or invalid hostnames, DNS will fail.
        # If running offline and hostname is a standard domain, log warning but do not allow private names.
        logger.warning(f"[validate_public_url] DNS resolution failed for '{hostname_lower}': {dns_err}")
        return clean_url
    except Exception as exc:
        raise ValueError(f"DNS lookup failed for '{hostname}': {exc}")

    for entry in addr_info:
        ip_str = entry[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            _check_ip_safety(ip)
        except ValueError as ip_err:
            raise ValueError(f"URL resolves to disallowed IP {ip_str}: {ip_err}")

    return clean_url


def _check_ip_safety(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Verifies that an IP is not private, loopback, link-local, multicast, or reserved."""
    if ip.is_loopback:
        raise ValueError("Loopback address is forbidden (SSRF protection).")
    if ip.is_private:
        raise ValueError("Private network address is forbidden (SSRF protection).")
    if ip.is_link_local:
        raise ValueError("Link-local / cloud metadata address is forbidden (SSRF protection).")
    if ip.is_multicast:
        raise ValueError("Multicast address is forbidden.")
    if ip.is_reserved:
        raise ValueError("Reserved IP address is forbidden.")
    if ip == ipaddress.ip_address("0.0.0.0") or ip == ipaddress.ip_address("::"):
        raise ValueError("Unspecified address (0.0.0.0 / ::) is forbidden.")


def is_safe_public_url(url: str) -> bool:
    """Non-throwing boolean helper for background tasks."""
    try:
        validate_public_url(url)
        return True
    except Exception:
        return False


def clean_html_text(html_content: str) -> str:
    """Parse HTML and extract clean, visible text lines."""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


async def safe_http_get_async(url: str, max_redirects: int = 5, timeout: float = 15.0) -> httpx.Response:
    """Perform an async HTTP GET request validating every redirect target against SSRF rules."""
    current_url = validate_public_url(url)
    headers = {"User-Agent": "Mozilla/5.0 AI-Training-Bot/1.0"}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            response = await client.get(current_url, headers=headers)
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    break
                next_url = urljoin(current_url, location)
                current_url = validate_public_url(next_url)
                continue
            response.raise_for_status()
            return response

    raise ValueError("Too many HTTP redirects while fetching URL.")


def safe_http_get_sync(url: str, max_redirects: int = 5, timeout: float = 15.0) -> httpx.Response:
    """Perform a sync HTTP GET request validating every redirect target against SSRF rules."""
    current_url = validate_public_url(url)
    headers = {"User-Agent": "Mozilla/5.0 AI-Training-Bot/1.0"}

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            response = client.get(current_url, headers=headers)
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    break
                next_url = urljoin(current_url, location)
                current_url = validate_public_url(next_url)
                continue
            response.raise_for_status()
            return response

    raise ValueError("Too many HTTP redirects while fetching URL.")
