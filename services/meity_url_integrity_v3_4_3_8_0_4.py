from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.4"
SOURCE_VERSION = "3.4.3.8.0.3"

ROLE_SCHEME = "SCHEME_INFORMATION_PAGE"
ROLE_CALL = "CALL_INFORMATION_PAGE"
ROLE_APPLICATION = "APPLICATION_ROUTE"
ROLE_REGISTRATION = "REGISTRATION_ROUTE"
ROLE_GUIDELINE = "GUIDELINE_DOCUMENT"
ROLE_RESULT = "RESULT_NOTICE"
ROLE_HISTORICAL = "HISTORICAL_SOURCE"
ROLE_SUPPORTING = "SUPPORTING_DOCUMENT"
ROLE_LOGIN = "LOGIN_ROUTE"
ROLE_NAVIGATION = "NAVIGATION_PAGE"
ROLE_ABOUT = "ABOUT_PAGE"
ROLE_CONTACT = "CONTACT_PAGE"
ROLE_UNRELATED = "UNRELATED_ROUTE"
ROLE_BROKEN = "BROKEN_OR_UNVERIFIED"

STATUS_VERIFIED = "VERIFIED"
STATUS_WITHHELD = "WITHHELD"
STATUS_UNVERIFIED = "UNVERIFIED"

TEMPORAL_CURRENT = "CURRENT_STATUS_EVIDENCE_COMPLETE"
TEMPORAL_HISTORICAL = "HISTORICAL_BY_TITLE_OR_DEADLINE"

APPLICATION_ROLES = {ROLE_APPLICATION, ROLE_REGISTRATION}
SAFE_INFORMATION_ROLES = {
    ROLE_SCHEME,
    ROLE_CALL,
    ROLE_GUIDELINE,
    ROLE_RESULT,
    ROLE_HISTORICAL,
    ROLE_SUPPORTING,
}
PERMANENT_TYPES = {
    "PERMANENT_SCHEME",
    "PERMANENT_PROGRAMME",
    "ACCELERATOR_PROGRAMME",
    "GRANT_PROGRAMME",
    "INCUBATION_PROGRAMME",
    "ECOSYSTEM_PROGRAMME",
    "IMPLEMENTATION_PROGRAMME",
}
CALL_TYPES = {
    "APPLICATION_CALL",
    "CHALLENGE_CALL",
    "GRAND_CHALLENGE",
    "HACKATHON",
    "ACCELERATOR_COHORT",
    "EOI",
    "RFP",
    "IMPLEMENTATION_PARTNER_CALL",
}


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def normalize(value: str) -> str:
    decoded = urllib.parse.unquote(clean(value))
    return clean(re.sub(r"[^a-z0-9]+", " ", decoded.casefold()))


def parse_bool(value: Any) -> bool:
    return clean(value).casefold() in {"1", "true", "yes", "y"}


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=field_list,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in field_list})


def official_domain(url: str, domains: Iterable[str]) -> bool:
    try:
        host = urllib.parse.urlsplit(clean(url)).hostname or ""
    except ValueError:
        return False
    host = host.casefold()
    return any(
        host == clean(domain).casefold()
        or host.endswith("." + clean(domain).casefold())
        for domain in domains
    )


def canonical_url(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    try:
        split = urllib.parse.urlsplit(text)
    except ValueError:
        return text
    scheme = split.scheme.casefold() or "https"
    host = (split.hostname or "").casefold()
    port = f":{split.port}" if split.port else ""
    path = re.sub(r"/+", "/", split.path or "/")
    query = urllib.parse.parse_qsl(
        split.query,
        keep_blank_values=True,
    )
    query_text = urllib.parse.urlencode(sorted(query))
    return urllib.parse.urlunsplit(
        (
            scheme,
            host + port,
            path,
            query_text,
            "",
        )
    )


def split_source_urls(value: str) -> list[str]:
    text = clean(value)
    if not text:
        return []
    candidates = re.findall(r"https?://[^\s;|,\"]+", text)
    if candidates:
        return [candidate.rstrip(".)]") for candidate in candidates]
    return [
        item.strip()
        for item in re.split(r"[;|]", text)
        if item.strip().startswith(("http://", "https://"))
    ]


def meaningful_tokens(
    value: str,
    stopwords: Iterable[str],
) -> set[str]:
    stopped = {normalize(item) for item in stopwords}
    return {
        token
        for token in normalize(value).split()
        if len(token) >= 3
        and token not in stopped
        and not token.isdigit()
    }


def entity_match_score(
    child: dict[str, Any],
    final_url: str,
    title: str,
    page_text: str,
    config: dict[str, Any],
) -> float:
    entity_text = clean(
        f"{child.get('canonical_name', '')} "
        f"{child.get('original_canonical_name', '')} "
        f"{child.get('repaired_parent_scheme_name', '')}"
    )
    entity_tokens = meaningful_tokens(
        entity_text,
        config.get("entity_stopwords", []),
    )
    if not entity_tokens:
        return 0.0

    page_tokens = meaningful_tokens(
        clean(f"{final_url} {title} {page_text[:8000]}"),
        config.get("entity_stopwords", []),
    )
    overlap = entity_tokens & page_tokens
    base = len(overlap) / len(entity_tokens)

    entity_key = normalize(
        child.get("canonical_name")
        or child.get("original_canonical_name")
        or ""
    )
    direct_text = normalize(f"{final_url} {title}")
    if entity_key and entity_key in direct_text:
        base = max(base, 0.9)

    path = normalize(urllib.parse.urlsplit(final_url).path)
    compact_tokens = "".join(sorted(entity_tokens))
    compact_path = path.replace(" ", "")
    if compact_tokens and compact_tokens in compact_path:
        base = max(base, 0.85)

    return round(min(base, 1.0), 3)


def extract_title(content: str) -> str:
    match = re.search(
        r"(?is)<title[^>]*>(.*?)</title>",
        content,
    )
    if not match:
        return ""
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def visible_text(content: str) -> str:
    without_script = re.sub(
        r"(?is)<(script|style|noscript)[^>]*>.*?</\1>",
        " ",
        content,
    )
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_script)
    return clean(html.unescape(without_tags))


def find_browser() -> str:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    page_title: str
    page_text: str
    fetch_method: str
    error: str
    checked_at: str


class LinkFetcher:
    def __init__(
        self,
        timeout_seconds: int = 20,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.browser = find_browser()
        self._cache: dict[str, FetchResult] = {}

    def fetch(self, url: str) -> FetchResult:
        key = canonical_url(url)
        if key in self._cache:
            return self._cache[key]

        result = self._fetch_http(url)
        if result.http_status >= 400 or not result.page_text:
            browser_result = self._fetch_browser(url)
            if browser_result and browser_result.page_text:
                result = browser_result
        self._cache[key] = result
        return result

    def _fetch_http(self, url: str) -> FetchResult:
        checked_at = utc_now()
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36 "
                    "SSIP-LinkIntegrity/3.4.3.8.0.4"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/pdf,"
                    "application/json;q=0.9,*/*;q=0.8"
                ),
            },
        )
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=context,
            ) as response:
                raw = response.read(3_000_000)
                final_url = response.geturl()
                status = int(response.status or 200)
                content_type = clean(response.headers.get("Content-Type"))
                charset = response.headers.get_content_charset() or "utf-8"
                if (
                    "html" in content_type.casefold()
                    or "json" in content_type.casefold()
                    or "text" in content_type.casefold()
                ):
                    content = raw.decode(charset, errors="replace")
                    title = extract_title(content)
                    text = visible_text(content)
                else:
                    title = Path(
                        urllib.parse.urlsplit(final_url).path
                    ).name
                    text = ""
                return FetchResult(
                    requested_url=url,
                    final_url=final_url,
                    http_status=status,
                    content_type=content_type,
                    page_title=title,
                    page_text=text,
                    fetch_method="HTTP",
                    error="",
                    checked_at=checked_at,
                )
        except urllib.error.HTTPError as exc:
            final_url = exc.geturl() or url
            content_type = clean(exc.headers.get("Content-Type")) if exc.headers else ""
            try:
                content = exc.read(500_000).decode("utf-8", errors="replace")
            except Exception:
                content = ""
            return FetchResult(
                requested_url=url,
                final_url=final_url,
                http_status=int(exc.code or 0),
                content_type=content_type,
                page_title=extract_title(content),
                page_text=visible_text(content),
                fetch_method="HTTP",
                error=f"HTTPError:{exc.code}",
                checked_at=checked_at,
            )
        except Exception as exc:
            return FetchResult(
                requested_url=url,
                final_url=url,
                http_status=0,
                content_type="",
                page_title="",
                page_text="",
                fetch_method="HTTP",
                error=f"{type(exc).__name__}:{exc}",
                checked_at=checked_at,
            )

    def _fetch_browser(self, url: str) -> FetchResult | None:
        if not self.browser:
            return None
        checked_at = utc_now()
        command = [
            self.browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--ignore-certificate-errors",
            "--dump-dom",
            url,
        ]
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(self.timeout_seconds * 2, 30),
                encoding="utf-8",
                errors="replace",
            )
            content = process.stdout
            if not content:
                return None
            return FetchResult(
                requested_url=url,
                final_url=url,
                http_status=200 if process.returncode == 0 else 0,
                content_type="text/html; browser-rendered",
                page_title=extract_title(content),
                page_text=visible_text(content),
                fetch_method="BROWSER",
                error=clean(process.stderr[-600:]) if process.returncode else "",
                checked_at=checked_at,
            )
        except Exception:
            return None


def requested_role_for_field(
    child: dict[str, Any],
    source_field: str,
) -> str:
    if source_field == "application_url":
        return ROLE_APPLICATION
    temporal = clean(child.get("temporal_validation"))
    entity_type = clean(child.get("entity_type"))
    if temporal == TEMPORAL_HISTORICAL:
        return ROLE_HISTORICAL
    if entity_type in PERMANENT_TYPES:
        return ROLE_SCHEME
    if entity_type in CALL_TYPES:
        return ROLE_CALL
    return ROLE_SUPPORTING


def page_role(
    child: dict[str, Any],
    source_field: str,
    fetch: FetchResult,
    config: dict[str, Any],
) -> tuple[str, list[str]]:
    url = canonical_url(fetch.final_url or fetch.requested_url)
    split = urllib.parse.urlsplit(url)
    path = (split.path or "/").casefold()
    path_title = clean(
        f"{path} {fetch.page_title}"
    ).casefold()
    focused_text = clean(
        f"{path} {fetch.page_title} {fetch.page_text[:2500]}"
    ).casefold()
    combined = clean(
        f"{path} {fetch.page_title} {fetch.page_text[:10000]}"
    ).casefold()
    flags: list[str] = []

    if fetch.http_status == 0 or fetch.http_status >= 400:
        return ROLE_BROKEN, ["FETCH_FAILED_OR_NON_SUCCESS_STATUS"]
    if not official_domain(
        fetch.final_url,
        config.get("official_domains", []),
    ):
        return ROLE_UNRELATED, ["FINAL_REDIRECT_OUTSIDE_OFFICIAL_DOMAIN"]

    if any(
        marker.casefold() in path
        for marker in config.get("blocked_application_path_markers", [])
    ):
        if "contact" in path:
            return ROLE_CONTACT, ["BLOCKED_APPLICATION_PATH"]
        if "login" in path or "signin" in path or "sign-in" in path:
            return ROLE_LOGIN, ["BLOCKED_APPLICATION_PATH"]
        return ROLE_ABOUT, ["BLOCKED_APPLICATION_PATH"]

    if path.rstrip("/") in {
        clean(item).casefold().rstrip("/")
        for item in config.get("navigation_paths", [])
    }:
        return ROLE_NAVIGATION, ["GENERIC_NAVIGATION_PATH"]

    if any(
        marker.casefold() in path_title
        for marker in config.get("about_markers", [])
    ):
        return ROLE_ABOUT, ["ABOUT_PAGE_MARKERS"]
    if any(
        marker.casefold() in path_title
        for marker in config.get("contact_markers", [])
    ):
        return ROLE_CONTACT, ["CONTACT_PAGE_MARKERS"]
    if any(
        marker.casefold() in path_title
        for marker in config.get("login_markers", [])
    ):
        return ROLE_LOGIN, ["LOGIN_PAGE_MARKERS"]

    is_pdf = (
        path.endswith(".pdf")
        or "application/pdf" in fetch.content_type.casefold()
    )
    if is_pdf:
        if any(
            marker.casefold() in combined
            for marker in config.get("result_markers", [])
        ):
            return ROLE_RESULT, []
        if any(
            marker.casefold() in combined
            for marker in config.get("guideline_markers", [])
        ):
            return ROLE_GUIDELINE, []
        return ROLE_SUPPORTING, []

    application_marker = any(
        marker.casefold() in focused_text
        for marker in config.get("application_markers", [])
    )
    registration_marker = any(
        marker.casefold() in focused_text
        for marker in config.get("registration_markers", [])
    )
    if source_field == "application_url":
        if registration_marker:
            return ROLE_REGISTRATION, []
        if application_marker:
            return ROLE_APPLICATION, []
        flags.append("APPLICATION_FIELD_WITHOUT_APPLICATION_PAGE_MARKERS")

    temporal = clean(child.get("temporal_validation"))
    if temporal == TEMPORAL_HISTORICAL:
        if any(
            marker.casefold() in combined
            for marker in config.get("result_markers", [])
        ):
            return ROLE_RESULT, flags
        return ROLE_HISTORICAL, flags

    if any(
        marker.casefold() in combined
        for marker in config.get("result_markers", [])
    ):
        return ROLE_RESULT, flags
    if any(
        marker.casefold() in combined
        for marker in config.get("call_markers", [])
    ):
        return ROLE_CALL, flags
    if any(
        marker.casefold() in combined
        for marker in config.get("scheme_markers", [])
    ):
        return ROLE_SCHEME, flags

    return ROLE_UNRELATED, flags + ["PAGE_ROLE_NOT_ESTABLISHED"]


def inspect_link(
    child: dict[str, Any],
    source_field: str,
    url: str,
    fetcher: LinkFetcher,
    config: dict[str, Any],
    global_current_complete_count: int,
) -> dict[str, Any]:
    fetch = fetcher.fetch(url)
    role, role_flags = page_role(
        child,
        source_field,
        fetch,
        config,
    )
    score = entity_match_score(
        child,
        fetch.final_url or url,
        fetch.page_title,
        fetch.page_text,
        config,
    )
    requested_role = requested_role_for_field(child, source_field)
    temporal = clean(child.get("temporal_validation"))
    same_child = source_field in {"official_page_url", "application_url"}
    flags = list(role_flags)

    status = STATUS_UNVERIFIED
    withheld_reason = ""
    verified_information = False
    verified_application = False

    if requested_role in APPLICATION_ROLES or source_field == "application_url":
        if global_current_complete_count <= 0:
            withheld_reason = "GLOBAL_CURRENT_EVIDENCE_INCOMPLETE"
        elif temporal != TEMPORAL_CURRENT:
            withheld_reason = "CHILD_NOT_CURRENT_EVIDENCE_COMPLETE"
        elif role not in APPLICATION_ROLES:
            withheld_reason = "PAGE_ROLE_NOT_APPLICATION_OR_REGISTRATION"
        elif not same_child:
            withheld_reason = "APPLICATION_LINK_NOT_DIRECT_CHILD_FIELD"
        elif score < float(
            config.get("minimum_application_entity_match", 0.55)
        ):
            withheld_reason = "APPLICATION_ENTITY_MATCH_INSUFFICIENT"
        elif not official_domain(
            fetch.final_url,
            config.get("official_domains", []),
        ):
            withheld_reason = "FINAL_URL_NOT_OFFICIAL"
        elif fetch.http_status < 200 or fetch.http_status >= 400:
            withheld_reason = "APPLICATION_ROUTE_NOT_REACHABLE"
        elif fetch.fetch_method not in {"HTTP", "TEST"}:
            withheld_reason = "FINAL_REDIRECT_NOT_PROVEN"
        else:
            verified_application = True
            status = STATUS_VERIFIED

        if not verified_application:
            status = STATUS_WITHHELD
            flags.append(withheld_reason)
    else:
        if role not in SAFE_INFORMATION_ROLES:
            withheld_reason = "UNSAFE_INFORMATION_PAGE_ROLE"
        elif score < float(
            config.get("minimum_information_entity_match", 0.25)
        ):
            withheld_reason = "INFORMATION_ENTITY_MATCH_INSUFFICIENT"
        elif fetch.http_status < 200 or fetch.http_status >= 400:
            withheld_reason = "INFORMATION_ROUTE_NOT_REACHABLE"
        elif not official_domain(
            fetch.final_url,
            config.get("official_domains", []),
        ):
            withheld_reason = "FINAL_URL_NOT_OFFICIAL"
        else:
            verified_information = True
            status = STATUS_VERIFIED

        if not verified_information:
            status = STATUS_WITHHELD
            flags.append(withheld_reason)

    provenance_payload = {
        "child_id": child.get("child_id", ""),
        "bundle_id": child.get("bundle_id", ""),
        "source_field": source_field,
        "requested_url": canonical_url(url),
        "final_url": canonical_url(fetch.final_url),
        "role": role,
    }
    provenance_id = "meitylink_" + hashlib.sha256(
        stable_json(provenance_payload).encode("utf-8")
    ).hexdigest()[:20]

    return {
        "provenance_id": provenance_id,
        "bundle_id": clean(child.get("bundle_id")),
        "child_id": clean(child.get("child_id")),
        "canonical_name": clean(child.get("canonical_name")),
        "entity_type": clean(child.get("entity_type")),
        "temporal_validation": temporal,
        "source_field": source_field,
        "direct_child_link": same_child,
        "requested_role": requested_role,
        "requested_url": canonical_url(url),
        "final_url": canonical_url(fetch.final_url),
        "http_status": fetch.http_status,
        "content_type": fetch.content_type,
        "page_title": fetch.page_title,
        "page_role": role,
        "entity_match_confidence": score,
        "link_integrity_status": status,
        "verified_information_link": verified_information,
        "verified_application_link": verified_application,
        "withheld_reason": withheld_reason,
        "integrity_flags": ";".join(
            item for item in dict.fromkeys(flags) if item
        ),
        "fetch_method": fetch.fetch_method,
        "fetch_error": fetch.error,
        "last_checked_at": fetch.checked_at,
        "source_candidate_id": clean(child.get("source_candidate_id")),
        "source_evidence_id": clean(child.get("source_evidence_id")),
    }


@dataclass(frozen=True)
class IntegrityPaths:
    project_root: Path
    source_dir: Path
    ledger_dir: Path
    output_dir: Path
    config_path: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "IntegrityPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_3",
            ledger_dir=root / "data/departments/meity/v3_4_3_8_0_2",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_4",
            config_path=root / "config/meity_url_integrity_v3_4_3_8_0_4.json",
            database_path=root / "database/ssip_staging_v1.db",
        )


class URLIntegrityGate:
    def __init__(
        self,
        paths: IntegrityPaths,
        config: dict[str, Any],
        fetcher: LinkFetcher | None = None,
    ) -> None:
        self.paths = paths
        self.config = config
        self.fetcher = fetcher or LinkFetcher(
            parse_int(config.get("request_timeout_seconds"), 20)
        )

    def _load_manifest(self) -> dict[str, Any]:
        return json.loads(
            (
                self.paths.source_dir
                / "meity_temporal_parent_safety_manifest_v3_4_3_8_0_3.json"
            ).read_text(encoding="utf-8-sig")
        )

    def _load_bundles(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_safe_admin_decision_bundles_v3_4_3_8_0_3.csv"
        )

    def _load_children(self) -> list[dict[str, str]]:
        children = read_csv(
            self.paths.source_dir
            / "meity_safe_decision_children_v3_4_3_8_0_3.csv"
        )
        ledger = {
            clean(row.get("child_id")): row
            for row in read_csv(
                self.paths.ledger_dir
                / "meity_decision_bundle_children_v3_4_3_8_0_2.csv"
            )
            if clean(row.get("child_id"))
        }
        for child in children:
            source = ledger.get(clean(child.get("child_id")), {})
            for key in (
                "source_candidate_id",
                "source_evidence_id",
                "source_candidate_ids",
                "evidence_ids",
            ):
                if not clean(child.get(key)):
                    child[key] = clean(source.get(key))
        return children

    def _candidate_links(
        self,
        child: dict[str, str],
    ) -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        for field in ("official_page_url", "application_url"):
            url = clean(child.get(field))
            if url:
                values.append((field, url))
        for url in split_source_urls(clean(child.get("source_urls"))):
            values.append(("source_urls", url))

        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        maximum = parse_int(
            self.config.get("maximum_links_per_child"),
            8,
        )
        for field, url in values:
            key = canonical_url(url)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append((field, url))
            if len(unique) >= maximum:
                break
        return unique

    def run(self) -> dict[str, Any]:
        source_manifest = self._load_manifest()
        bundles = self._load_bundles()
        children = self._load_children()
        current_complete_count = parse_int(
            source_manifest.get("current_status_evidence_complete_count"),
            0,
        )

        provenance: list[dict[str, Any]] = []
        links_by_child: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for child in children:
            for source_field, url in self._candidate_links(child):
                record = inspect_link(
                    child,
                    source_field,
                    url,
                    self.fetcher,
                    self.config,
                    current_complete_count,
                )
                provenance.append(record)
                links_by_child[clean(child.get("child_id"))].append(record)

        sanitized_children: list[dict[str, Any]] = []
        verified_application_count = 0
        verified_information_count = 0
        historical_application_exposed = 0
        cross_entity_exposed = 0
        about_application_exposed = 0

        for child in children:
            child_links = links_by_child.get(clean(child.get("child_id")), [])
            info_links = [
                link
                for link in child_links
                if parse_bool(link.get("verified_information_link"))
            ]
            app_links = [
                link
                for link in child_links
                if parse_bool(link.get("verified_application_link"))
            ]
            info_links.sort(
                key=lambda item: (
                    0 if item["source_field"] == "official_page_url" else 1,
                    -float(item["entity_match_confidence"]),
                )
            )
            app_links.sort(
                key=lambda item: -float(item["entity_match_confidence"])
            )

            info = info_links[0] if info_links else None
            app = app_links[0] if app_links else None
            verified_information_count += 1 if info else 0
            verified_application_count += 1 if app else 0

            if (
                clean(child.get("temporal_validation")) == TEMPORAL_HISTORICAL
                and app
            ):
                historical_application_exposed += 1
            if app and app["page_role"] in {
                ROLE_ABOUT,
                ROLE_CONTACT,
                ROLE_LOGIN,
                ROLE_NAVIGATION,
                ROLE_UNRELATED,
            }:
                cross_entity_exposed += 1
            if app and app["page_role"] == ROLE_ABOUT:
                about_application_exposed += 1

            withheld_application = [
                link
                for link in child_links
                if link["source_field"] == "application_url"
                and not parse_bool(link.get("verified_application_link"))
            ]
            application_reason = (
                withheld_application[0]["withheld_reason"]
                if withheld_application
                else (
                    "NO_APPLICATION_ROUTE_CAPTURED"
                    if not app
                    else ""
                )
            )

            sanitized = dict(child)
            sanitized.update(
                {
                    "verified_information_url": (
                        info["final_url"] if info else ""
                    ),
                    "verified_information_role": (
                        info["page_role"] if info else ""
                    ),
                    "verified_information_title": (
                        info["page_title"] if info else ""
                    ),
                    "verified_information_provenance_id": (
                        info["provenance_id"] if info else ""
                    ),
                    "verified_application_url": (
                        app["final_url"] if app else ""
                    ),
                    "verified_application_role": (
                        app["page_role"] if app else ""
                    ),
                    "verified_application_title": (
                        app["page_title"] if app else ""
                    ),
                    "verified_application_provenance_id": (
                        app["provenance_id"] if app else ""
                    ),
                    "application_route_withheld": not bool(app),
                    "application_route_withheld_reason": application_reason,
                    "link_count_inspected": len(child_links),
                    "link_integrity_complete": bool(info) and (
                        clean(child.get("temporal_validation"))
                        != TEMPORAL_CURRENT
                        or bool(app)
                    ),
                    "raw_application_url": clean(child.get("application_url")),
                    "application_url": "",
                    "official_page_url": (
                        info["final_url"] if info else ""
                    ),
                    "publication_eligible": False,
                    "apply_action_allowed": False,
                }
            )
            sanitized_children.append(sanitized)

        if historical_application_exposed:
            raise RuntimeError("Historical application links survived the gate.")
        if cross_entity_exposed:
            raise RuntimeError("Cross-entity application links survived the gate.")
        if about_application_exposed:
            raise RuntimeError("About-page application links survived the gate.")

        bundle_children: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for child in sanitized_children:
            bundle_children[clean(child.get("bundle_id"))].append(child)

        sanitized_bundles: list[dict[str, Any]] = []
        for bundle in bundles:
            attached = bundle_children.get(clean(bundle.get("bundle_id")), [])
            link_complete = bool(attached) and all(
                parse_bool(child.get("link_integrity_complete"))
                for child in attached
            )
            current_children = [
                child
                for child in attached
                if clean(child.get("temporal_validation")) == TEMPORAL_CURRENT
            ]
            current_application_complete = all(
                clean(child.get("verified_application_url"))
                for child in current_children
            )
            integrity_flags: list[str] = []
            if not link_complete:
                integrity_flags.append("LINK_INTEGRITY_INCOMPLETE")
            if current_children and not current_application_complete:
                integrity_flags.append(
                    "CURRENT_APPLICATION_ROUTE_NOT_VERIFIED"
                )

            safe_positive_allowed = (
                link_complete
                and current_application_complete
            )
            source_allowed = [
                value
                for value in clean(bundle.get("allowed_decisions")).split(";")
                if value
            ]
            positive = [
                value
                for value in source_allowed
                if value.startswith("CONFIRM_")
            ]
            if not safe_positive_allowed:
                allowed = [
                    value
                    for value in source_allowed
                    if not value.startswith("CONFIRM_")
                ]
                if "NEEDS_MORE_EVIDENCE" not in allowed:
                    allowed.insert(1 if allowed else 0, "NEEDS_MORE_EVIDENCE")
                if "PENDING" not in allowed:
                    allowed.insert(0, "PENDING")
            else:
                allowed = source_allowed

            signature_payload = {
                "source_bundle_signature": bundle.get("bundle_signature", ""),
                "child_integrity": [
                    {
                        "child_id": child.get("child_id", ""),
                        "information": child.get(
                            "verified_information_provenance_id",
                            "",
                        ),
                        "application": child.get(
                            "verified_application_provenance_id",
                            "",
                        ),
                        "withheld": child.get(
                            "application_route_withheld_reason",
                            "",
                        ),
                    }
                    for child in attached
                ],
            }
            integrity_signature = hashlib.sha256(
                stable_json(signature_payload).encode("utf-8")
            ).hexdigest()

            sanitized_bundles.append(
                {
                    **bundle,
                    "link_integrity_complete": link_complete,
                    "current_application_integrity_complete": (
                        current_application_complete
                    ),
                    "safe_positive_decision_allowed": safe_positive_allowed,
                    "allowed_decisions": ";".join(allowed),
                    "link_integrity_flags": ";".join(integrity_flags),
                    "link_integrity_signature": integrity_signature,
                    "publication_eligible": False,
                    "apply_action_allowed": False,
                    "database_action": "NONE",
                    "publication_action": "NONE",
                }
            )

        role_counts = Counter(
            link["page_role"]
            for link in provenance
        )
        status_counts = Counter(
            link["link_integrity_status"]
            for link in provenance
        )
        withheld_count = sum(
            1
            for link in provenance
            if link["source_field"] == "application_url"
            and link["link_integrity_status"] == STATUS_WITHHELD
        )
        broken_count = sum(
            1
            for link in provenance
            if link["page_role"] == ROLE_BROKEN
        )
        cross_entity_contamination = sum(
            1
            for link in provenance
            if link["verified_application_link"]
            and link["entity_match_confidence"]
            < float(
                self.config.get(
                    "minimum_application_entity_match",
                    0.55,
                )
            )
        )

        output_dir = self.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        provenance_fields = [
            "provenance_id",
            "bundle_id",
            "child_id",
            "canonical_name",
            "entity_type",
            "temporal_validation",
            "source_field",
            "direct_child_link",
            "requested_role",
            "requested_url",
            "final_url",
            "http_status",
            "content_type",
            "page_title",
            "page_role",
            "entity_match_confidence",
            "link_integrity_status",
            "verified_information_link",
            "verified_application_link",
            "withheld_reason",
            "integrity_flags",
            "fetch_method",
            "fetch_error",
            "last_checked_at",
            "source_candidate_id",
            "source_evidence_id",
        ]
        child_fields = list(
            dict.fromkeys(
                [
                    *(
                        sanitized_children[0].keys()
                        if sanitized_children
                        else []
                    ),
                ]
            )
        )
        bundle_fields = list(
            dict.fromkeys(
                [
                    *(
                        sanitized_bundles[0].keys()
                        if sanitized_bundles
                        else []
                    ),
                ]
            )
        )

        write_csv(
            output_dir
            / "meity_url_provenance_ledger_v3_4_3_8_0_4.csv",
            provenance,
            provenance_fields,
        )
        write_csv(
            output_dir
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv",
            sanitized_children,
            child_fields,
        )
        write_csv(
            output_dir
            / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv",
            sanitized_bundles,
            bundle_fields,
        )
        write_csv(
            output_dir
            / "meity_withheld_application_routes_v3_4_3_8_0_4.csv",
            [
                link
                for link in provenance
                if link["source_field"] == "application_url"
                and not parse_bool(link.get("verified_application_link"))
            ],
            provenance_fields,
        )

        summary = {
            "version": VERSION,
            "generated_at": utc_now(),
            "source_manifest_signature": source_manifest.get("signature", ""),
            "links_inspected": len(provenance),
            "unique_requested_urls": len(
                {link["requested_url"] for link in provenance}
            ),
            "verified_information_links": verified_information_count,
            "verified_application_routes": verified_application_count,
            "withheld_application_routes": withheld_count,
            "broken_or_unverified_links": broken_count,
            "role_counts": dict(sorted(role_counts.items())),
            "integrity_status_counts": dict(sorted(status_counts.items())),
            "current_status_evidence_complete_count": (
                current_complete_count
            ),
            "global_application_routes_withheld": (
                current_complete_count <= 0
            ),
            "historical_application_links_exposed": (
                historical_application_exposed
            ),
            "about_page_application_links_exposed": (
                about_application_exposed
            ),
            "cross_entity_link_contamination_count": (
                cross_entity_contamination
            ),
            "safe_bundle_count": len(sanitized_bundles),
            "safe_child_count": len(sanitized_children),
            "apply_action_allowed_count": 0,
            "publication_eligible_count": 0,
            "database_write_performed": False,
            "publication_performed": False,
        }
        signature_payload = {
            "summary": summary,
            "provenance": provenance,
            "bundles": sanitized_bundles,
            "children": sanitized_children,
        }
        summary["link_integrity_signature"] = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()
        summary["session_state_signature"] = hashlib.sha256(
            stable_json(
                {
                    "source": source_manifest.get(
                        "session_state_signature",
                        "",
                    ),
                    "link": summary["link_integrity_signature"],
                }
            ).encode("utf-8")
        ).hexdigest()

        (
            output_dir
            / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
        ).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return summary


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_url_integrity(
    project_root: Path,
    fetcher: LinkFetcher | None = None,
) -> dict[str, Any]:
    paths = IntegrityPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return URLIntegrityGate(
        paths,
        config,
        fetcher=fetcher,
    ).run()
