from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import socket
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

from agents.action_link_agent_v3_4_3_5 import (
    EXPECTED_SOURCE_SHA256,
    load_json,
    sha256_file,
    snapshot_hashes,
)


VERSION = "3.4.3.5"
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36 "
    "SSIP-LinkVerifier/3.4.3.5"
)

EXPECTED_SCHEME_NAMES = {
    "SAMRIDH",
    "TIDE 2.0",
    "SASACT",
    "GENESIS",
}

ENTITY_MARKERS = {
    "samridh": (
        "samridh",
        "startup accelerator of meity",
        "meity for product innovation development and growth",
    ),
    "tide 2.0": (
        "tide 2.0",
        "tide 2",
        "technology incubation and development of entrepreneurs",
    ),
    "sasact": (
        "sasact",
        "scheme for accelerating startups around post covid technology",
        "scheme for accelerating start-ups around post-covid technology",
        "scheme for accelerating start-ups around post covid technology",
    ),
    "genesis": (
        "genesis",
        "gen-next support for innovative startups",
        "gen next support for innovative startups",
        "gen-next support for innovative start-ups",
    ),
}

VERIFICATION_COLUMNS = [
    "verification_id",
    "classification_id",
    "inventory_id",
    "source_row_number",
    "master_id",
    "canonical_name",
    "requested_url",
    "final_url",
    "requested_domain",
    "final_domain",
    "redirect_count",
    "redirect_chain",
    "http_status",
    "content_type",
    "response_bytes_read",
    "page_title",
    "meta_description",
    "entity_evidence",
    "official_final_domain",
    "proposed_action_type",
    "link_role",
    "verification_status",
    "confidence",
    "eligible_for_public_button",
    "network_status",
    "verification_evidence",
    "error_type",
    "error_detail",
    "verified_at_utc",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"[\u2010-\u2015]", "-", value)
    value = re.sub(r"[^a-zA-Z0-9.+&/\- ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def stable_id(prefix: str, *parts: str) -> str:
    material = "|".join([VERSION, prefix, *parts])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def read_csv(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(50_000_000)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key): (value or "") for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def domain_is_official(domain: str, policy: dict[str, Any]) -> bool:
    host = normalize_text(domain).strip(".")
    if not host:
        return False

    exact = {
        normalize_text(item).strip(".")
        for item in policy.get("trusted_exact_domains", [])
    }
    if host in exact:
        return True

    for suffix in policy.get("permitted_domain_suffixes", []):
        clean_suffix = normalize_text(suffix).strip(".")
        if host == clean_suffix or host.endswith("." + clean_suffix):
            return True
    return False


def entity_key(canonical_name: str) -> str:
    name = normalize_text(canonical_name)
    for key in ENTITY_MARKERS:
        if key in name:
            return key
    return ""


def route_matches_entity(
    canonical_name: str,
    requested_url: str,
    final_url: str,
) -> bool:
    """Routing evidence is diagnostic only; it can never verify page content."""
    key = entity_key(canonical_name)
    if not key:
        return False

    route_blob = normalize_text(f"{requested_url} {final_url}")
    return any(
        normalize_text(marker) in route_blob
        for marker in ENTITY_MARKERS[key]
        if normalize_text(marker)
    )


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._ignored_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta_description = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        attr_map = {
            str(key).casefold(): str(value or "")
            for key, value in attrs
        }

        if tag == "title":
            self._in_title = True
        if tag in {"style", "noscript"}:
            self._ignored_depth += 1

        if tag == "meta":
            name = attr_map.get("name", "").casefold()
            prop = attr_map.get("property", "").casefold()
            if name == "description" or prop in {
                "og:description",
                "twitter:description",
            }:
                content = attr_map.get("content", "").strip()
                if content and not self.meta_description:
                    self.meta_description = content

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "title":
            self._in_title = False
        if tag in {"style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if not self._ignored_depth:
            self.text_parts.append(value)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()

    @property
    def visible_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text_parts)).strip()


class TrackingRedirectHandler(HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.chain: list[str] = []

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def decode_body(raw: bytes, content_type_header: str) -> str:
    charset_match = re.search(
        r"charset\s*=\s*[\"']?([a-zA-Z0-9._\-]+)",
        content_type_header or "",
        flags=re.IGNORECASE,
    )
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def find_entity_evidence(
    canonical_name: str,
    title: str,
    meta_description: str,
    visible_text: str,
) -> list[str]:
    """Return entity evidence from rendered/user-facing content only.

    Requested/final URLs and raw JavaScript source are deliberately excluded:
    a route slug is not proof of page content, and a shared application bundle
    may contain names for unrelated schemes.
    """
    key = entity_key(canonical_name)
    if not key:
        return []

    sources = {
        "title": normalize_text(title),
        "meta_description": normalize_text(meta_description),
        "visible_text": normalize_text(visible_text),
    }

    evidence: list[str] = []
    for marker in ENTITY_MARKERS[key]:
        normalized_marker = normalize_text(marker)
        if not normalized_marker:
            continue
        for source_name, source_value in sources.items():
            if normalized_marker in source_value:
                evidence.append(f"{source_name}:{marker}")
                break
    return list(dict.fromkeys(evidence))


def looks_like_error_page(
    title: str,
    visible_text: str,
) -> bool:
    combined = normalize_text(f"{title} {visible_text[:4000]}")
    markers = (
        "page not found",
        "404 not found",
        "access denied",
        "request blocked",
        "temporarily unavailable",
        "service unavailable",
        "under maintenance",
    )
    return any(marker in combined for marker in markers)


def build_verification_record(
    row: dict[str, str],
    *,
    requested_url: str,
    final_url: str = "",
    redirect_chain: list[str] | None = None,
    http_status: int | str = "",
    content_type: str = "",
    response_bytes_read: int = 0,
    page_title: str = "",
    meta_description: str = "",
    entity_evidence: list[str] | None = None,
    official_final_domain: bool = False,
    verification_status: str = "UNVERIFIED",
    confidence: float = 0.0,
    eligible: bool = False,
    network_status: str = "NOT_REQUESTED",
    verification_evidence: list[str] | None = None,
    error_type: str = "",
    error_detail: str = "",
    verified_at: str,
) -> dict[str, Any]:
    redirects = redirect_chain or []
    final_domain = (urlsplit(final_url).hostname or "").casefold() if final_url else ""
    requested_domain = (urlsplit(requested_url).hostname or "").casefold()

    return {
        "verification_id": stable_id(
            "online-verification",
            row.get("classification_id", ""),
            requested_url,
        ),
        "classification_id": row.get("classification_id", ""),
        "inventory_id": row.get("inventory_id", ""),
        "source_row_number": row.get("source_row_number", ""),
        "master_id": row.get("master_id", ""),
        "canonical_name": row.get("canonical_name", ""),
        "requested_url": requested_url,
        "final_url": final_url,
        "requested_domain": requested_domain,
        "final_domain": final_domain,
        "redirect_count": len(redirects),
        "redirect_chain": " -> ".join(redirects),
        "http_status": http_status,
        "content_type": content_type,
        "response_bytes_read": response_bytes_read,
        "page_title": page_title,
        "meta_description": meta_description,
        "entity_evidence": " | ".join(entity_evidence or []),
        "official_final_domain": str(official_final_domain),
        "proposed_action_type": row.get("proposed_action_type", ""),
        "link_role": row.get("link_role", ""),
        "verification_status": verification_status,
        "confidence": f"{confidence:.2f}",
        "eligible_for_public_button": str(eligible),
        "network_status": network_status,
        "verification_evidence": " | ".join(verification_evidence or []),
        "error_type": error_type,
        "error_detail": error_detail[:1000],
        "verified_at_utc": verified_at,
    }


def verify_one(
    row: dict[str, str],
    config: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    requested_url = row["normalized_url"].strip()
    verified_at = utc_now_iso()
    redirect_handler = TrackingRedirectHandler()
    ssl_context = ssl.create_default_context()
    opener = build_opener(
        redirect_handler,
        HTTPSHandler(context=ssl_context),
    )

    request = Request(
        requested_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )

    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", response.getcode()))
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raw = raw[:MAX_RESPONSE_BYTES]
            body = decode_body(raw, content_type)

        parser = PageTextParser()
        try:
            parser.feed(body)
        except Exception:
            pass

        final_domain = (urlsplit(final_url).hostname or "").casefold()
        official = domain_is_official(
            final_domain,
            config["official_domain_policy"],
        )
        entity_evidence = find_entity_evidence(
            row.get("canonical_name", ""),
            parser.title,
            parser.meta_description,
            parser.visible_text,
        )
        route_match = route_matches_entity(
            row.get("canonical_name", ""),
            requested_url,
            final_url,
        )

        verification_evidence = [
            f"http_status={status}",
            f"content_type={content_type}",
            f"official_final_domain={official}",
            f"route_entity_match={route_match}",
            f"content_entity_evidence_count={len(entity_evidence)}",
            "verification_policy=CONTENT_EVIDENCE_ONLY",
        ]

        status_value = "UNVERIFIED"
        confidence = 0.45
        eligible = False

        if not official:
            status_value = "REJECTED_NON_OFFICIAL"
            confidence = 0.00
        elif status in {401, 403, 429}:
            status_value = "ACCESS_BLOCKED"
            confidence = 0.00
        elif status in {404, 410}:
            status_value = "BROKEN_LINK"
            confidence = 0.00
        elif not (200 <= status < 300):
            status_value = "UNVERIFIED"
            confidence = 0.20
        elif "text/html" not in content_type.casefold():
            status_value = "UNVERIFIED"
            confidence = 0.35
            verification_evidence.append("expected_html_content=False")
        elif looks_like_error_page(parser.title, parser.visible_text):
            status_value = "BROKEN_LINK"
            confidence = 0.00
            verification_evidence.append("error_page_markers=True")
        elif entity_evidence:
            status_value = "VERIFIED_INFORMATION_PAGE"
            confidence = 0.96 if len(entity_evidence) >= 2 else 0.92
            threshold = float(
                config["confidence_thresholds"]["SCHEME_DETAILS"]
            )
            eligible = confidence >= threshold
        else:
            status_value = "UNVERIFIED"
            confidence = 0.55
            verification_evidence.append(
                "rendered_entity_specific_content_not_found=True"
            )
            verification_evidence.append(
                "possible_javascript_shell_requires_browser_verification=True"
            )

        return build_verification_record(
            row,
            requested_url=requested_url,
            final_url=final_url,
            redirect_chain=redirect_handler.chain,
            http_status=status,
            content_type=content_type,
            response_bytes_read=len(raw),
            page_title=parser.title,
            meta_description=parser.meta_description,
            entity_evidence=entity_evidence,
            official_final_domain=official,
            verification_status=status_value,
            confidence=confidence,
            eligible=eligible,
            network_status="COMPLETED",
            verification_evidence=verification_evidence,
            verified_at=verified_at,
        )

    except HTTPError as exc:
        status = int(exc.code)
        final_url = exc.geturl() or requested_url
        final_domain = (urlsplit(final_url).hostname or "").casefold()
        official = domain_is_official(
            final_domain,
            config["official_domain_policy"],
        )
        status_value = (
            "ACCESS_BLOCKED"
            if status in {401, 403, 429}
            else "BROKEN_LINK"
            if status in {404, 410}
            else "UNVERIFIED"
        )
        return build_verification_record(
            row,
            requested_url=requested_url,
            final_url=final_url,
            redirect_chain=redirect_handler.chain,
            http_status=status,
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
            official_final_domain=official,
            verification_status=status_value,
            confidence=0.00,
            eligible=False,
            network_status="HTTP_ERROR",
            verification_evidence=[f"http_error={status}"],
            error_type=type(exc).__name__,
            error_detail=str(exc),
            verified_at=verified_at,
        )

    except (URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
        reason_text = str(getattr(exc, "reason", exc))
        return build_verification_record(
            row,
            requested_url=requested_url,
            verification_status="UNVERIFIED",
            confidence=0.00,
            eligible=False,
            network_status="TRANSPORT_ERROR",
            verification_evidence=["network_transport_error=True"],
            error_type=type(exc).__name__,
            error_detail=reason_text,
            verified_at=verified_at,
        )


def select_scheme_page_candidates(
    classification_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    selected = [
        row
        for row in classification_rows
        if row.get("proposed_action_type") == "SCHEME_DETAILS"
        and row.get("link_role") == "SCHEME_MASTER"
        and row.get("official_domain_policy_result") == "PASS"
        and row.get("file_extension", "") == ""
        and row.get("normalized_url", "").casefold().startswith("https://")
    ]
    return sorted(selected, key=lambda row: row.get("canonical_name", ""))


def validate_preflight(
    selected: list[dict[str, str]],
) -> dict[str, Any]:
    selected_names = {row.get("canonical_name", "") for row in selected}
    selected_urls = [row.get("normalized_url", "") for row in selected]

    checks = {
        "candidate_count_is_four": len(selected) == 4,
        "expected_names_present": selected_names == EXPECTED_SCHEME_NAMES,
        "all_urls_are_https": all(
            url.casefold().startswith("https://") for url in selected_urls
        ),
        "all_urls_are_meity_scheme_pages": all(
            (urlsplit(url).hostname or "").casefold() == "msh.meity.gov.in"
            and urlsplit(url).path.casefold().startswith("/schemes/")
            for url in selected_urls
        ),
        "no_document_urls_selected": all(
            not Path(urlsplit(url).path).suffix for url in selected_urls
        ),
        "no_apply_actions_selected": all(
            row.get("proposed_action_type") != "APPLY_NOW"
            for row in selected
        ),
    }
    return {
        "version": VERSION,
        "stage": "ONLINE_SCHEME_PAGE_PREFLIGHT",
        "selected_candidate_count": len(selected),
        "selected_names": sorted(selected_names),
        "selected_urls": selected_urls,
        "checks": checks,
        "preflight_passed": all(checks.values()),
        "network_requests": 0,
    }


def load_inputs(
    project_root: Path,
) -> tuple[dict[str, Any], Path, Path, list[dict[str, str]]]:
    config_path = project_root / "config" / "action_link_rules_v3_4_3_5.json"
    config = load_json(config_path)
    if config.get("schema_version") != VERSION:
        raise RuntimeError("Configuration version mismatch.")
    if config.get("execution_mode") != "PREVIEW_ONLY":
        raise RuntimeError("Configuration is not PREVIEW_ONLY.")
    if config.get("output", {}).get("publication_allowed") is not False:
        raise RuntimeError("Publication must remain disabled.")
    if config.get("output", {}).get("database_writes_allowed") is not False:
        raise RuntimeError("Database writes must remain disabled.")

    source_path = project_root / Path(config["source"]["catalogue_path"])
    if sha256_file(source_path) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Frozen v3.4.3.4 source candidate hash mismatch.")

    output_dir = project_root / Path(config["output"]["directory"])
    classification_path = (
        output_dir / "meity_action_link_offline_classification_v3_4_3_5.csv"
    )
    classification_summary_path = (
        output_dir
        / "meity_action_link_offline_classification_summary_v3_4_3_5.json"
    )

    if not classification_path.exists():
        raise FileNotFoundError(
            f"Offline classification not found: {classification_path}"
        )
    if not classification_summary_path.exists():
        raise FileNotFoundError(
            f"Offline classification summary not found: {classification_summary_path}"
        )

    classification_summary = load_json(classification_summary_path)
    if classification_summary.get("stage") != "OFFLINE_CLASSIFICATION_ONLY":
        raise RuntimeError("Offline classification stage is not current.")
    if classification_summary.get("network_requests") != 0:
        raise RuntimeError(
            "Offline classification summary reports network requests."
        )
    if not all(classification_summary.get("safety", {}).values()):
        raise RuntimeError(
            "Offline classification safety checks were not all successful."
        )

    return (
        config,
        source_path,
        classification_path,
        read_csv(classification_path),
    )


def run_preflight(project_root: Path) -> dict[str, Any]:
    _, _, _, rows = load_inputs(project_root)
    selected = select_scheme_page_candidates(rows)
    preflight = validate_preflight(selected)
    if not preflight["preflight_passed"]:
        raise RuntimeError(f"Online verification preflight failed: {preflight}")
    return preflight


def run_content_evidence_policy_self_test() -> dict[str, Any]:
    """Prove that a matching URL slug alone cannot verify a scheme page."""
    url_only_evidence = find_entity_evidence(
        "SAMRIDH",
        "MeityStartupHub",
        "",
        "Welcome to MeitY Startup Hub",
    )
    content_evidence = find_entity_evidence(
        "TIDE 2.0",
        "TIDE 2.0 Scheme",
        "",
        "Technology Incubation and Development of Entrepreneurs",
    )
    route_match = route_matches_entity(
        "SAMRIDH",
        "https://msh.meity.gov.in/schemes/samridh",
        "https://msh.meity.gov.in/schemes/samridh",
    )

    checks = {
        "matching_route_is_detected": route_match is True,
        "matching_route_does_not_create_content_evidence": (
            url_only_evidence == []
        ),
        "rendered_scheme_content_creates_evidence": bool(content_evidence),
    }
    return {
        "policy": "CONTENT_EVIDENCE_ONLY",
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_online_verification(
    project_root: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    config, source_path, classification_path, rows = load_inputs(project_root)
    selected = select_scheme_page_candidates(rows)
    preflight = validate_preflight(selected)
    if not preflight["preflight_passed"]:
        raise RuntimeError(f"Online verification preflight failed: {preflight}")

    output_dir = project_root / Path(config["output"]["directory"])
    verification_path = (
        output_dir / "meity_scheme_page_online_verification_v3_4_3_5.csv"
    )
    summary_path = (
        output_dir
        / "meity_scheme_page_online_verification_summary_v3_4_3_5.json"
    )

    source_hash_before = sha256_file(source_path)
    classification_hash_before = sha256_file(classification_path)
    inventory_path = (
        output_dir / "meity_action_link_inventory_v3_4_3_5.csv"
    )
    quarantine_path = (
        output_dir / "meity_action_link_inventory_quarantine_v3_4_3_5.csv"
    )
    inventory_hash_before = sha256_file(inventory_path)
    quarantine_hash_before = sha256_file(quarantine_path)

    database_before = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_before = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_current = project_root / "publication" / "current"
    publication_existed_before = publication_current.exists()

    results = [
        verify_one(row, config, timeout_seconds)
        for row in selected
    ]
    write_csv(verification_path, results, VERIFICATION_COLUMNS)

    status_counts: dict[str, int] = {}
    network_counts: dict[str, int] = {}
    for item in results:
        status = str(item["verification_status"])
        network = str(item["network_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        network_counts[network] = network_counts.get(network, 0) + 1

    verified_count = status_counts.get("VERIFIED_INFORMATION_PAGE", 0)
    eligible_count = sum(
        item["eligible_for_public_button"] == "True"
        for item in results
    )
    review_required_count = len(results) - verified_count

    readiness = (
        "PASS"
        if verified_count == len(results) == 4
        else "PASS_WITH_REVIEW"
        if results
        else "FAIL"
    )

    summary: dict[str, Any] = {
        "version": VERSION,
        "stage": "ONLINE_SCHEME_PAGE_VERIFICATION",
        "execution_mode": "PREVIEW_ONLY",
        "verification_policy": "CONTENT_EVIDENCE_ONLY",
        "release_readiness_status": readiness,
        "selected_candidate_count": len(selected),
        "network_verification_attempts": len(selected),
        "result_row_count": len(results),
        "verification_status_counts": status_counts,
        "network_status_counts": network_counts,
        "verified_information_page_count": verified_count,
        "scheme_details_button_candidate_count": eligible_count,
        "review_required_count": review_required_count,
        "apply_now_button_count": 0,
        "open_call_button_count": 0,
        "pdf_requests": 0,
        "quarantined_link_requests": 0,
        "database_writes": 0,
        "dashboard_code_changes": 0,
        "publication_performed": False,
        "timeout_seconds": timeout_seconds,
        "verified_at_utc": utc_now_iso(),
        "verification_path": verification_path.relative_to(
            project_root
        ).as_posix(),
        "source_sha256": source_hash_before,
        "classification_sha256": classification_hash_before,
        "inventory_sha256": inventory_hash_before,
        "quarantine_sha256": quarantine_hash_before,
        "verification_sha256": sha256_file(verification_path),
        "preflight": preflight,
    }
    write_json(summary_path, summary)

    source_hash_after = sha256_file(source_path)
    classification_hash_after = sha256_file(classification_path)
    inventory_hash_after = sha256_file(inventory_path)
    quarantine_hash_after = sha256_file(quarantine_path)
    database_after = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_after = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_exists_after = publication_current.exists()

    safety = {
        "source_candidate_unchanged": source_hash_before == source_hash_after,
        "offline_classification_unchanged": (
            classification_hash_before == classification_hash_after
        ),
        "clean_inventory_unchanged": (
            inventory_hash_before == inventory_hash_after
        ),
        "quarantine_inventory_unchanged": (
            quarantine_hash_before == quarantine_hash_after
        ),
        "database_files_unchanged": database_before == database_after,
        "dashboard_python_files_unchanged": dashboard_before == dashboard_after,
        "publication_current_unchanged": (
            publication_existed_before == publication_exists_after
        ),
    }
    summary["safety"] = safety
    write_json(summary_path, summary)

    if not all(safety.values()):
        raise RuntimeError(f"Safety validation failed: {safety}")

    return summary
