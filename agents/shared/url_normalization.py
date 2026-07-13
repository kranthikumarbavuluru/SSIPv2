from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


TRACKING_PARAMETERS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source", "src_trk",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
}


def normalize_url(url: str, base_url: str = "") -> str:
    """Return one deterministic HTTP(S) URL while preserving identity queries."""
    absolute = urljoin(base_url, (url or "").strip())
    try:
        parts = urlsplit(absolute)
    except ValueError:
        return ""
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold().strip(".")
    if scheme not in {"http", "https"} or not host:
        return ""
    port = parts.port
    netloc = host if port in {None, 80, 443} else f"{host}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_PARAMETERS
    ]
    query.sort(key=lambda item: (item[0].casefold(), item[1]))
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold().strip(".")
    except ValueError:
        return ""

