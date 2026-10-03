"""URL normalization helpers."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "ftp:", "sms:", "#")
ASSET_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".mjs",
    ".pdf",
    ".zip",
    ".gz",
    ".mp4",
    ".mp3",
    ".webm",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".xml",
    ".json",
    ".txt",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".dmg",
    ".exe",
)


def normalize(url: str, base: str | None = None) -> str | None:
    """Resolve, drop fragment, lowercase scheme/host, strip default ports. None if not http(s)."""
    url = url.strip()
    if not url or url.lower().startswith(SKIP_SCHEMES):
        return None
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def bare_host(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, site: str) -> bool:
    return bare_host(url) == bare_host(site)


def is_asset(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(ASSET_EXTENSIONS)


def path_of(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")
