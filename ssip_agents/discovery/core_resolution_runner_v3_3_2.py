from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from ssip_agents.discovery.batch1_actual_runner_v3_3_1 import (
    NOT_SPECIFIED,
    SUPPORT_KIND_MAP,
    clean,
    deduplicate_preview_rows,
    infer_sector,
    status_from_text,
    utc_now,
    visible_application_call_count,
    visible_unique_count,
    visible_text,
    write_csv,
    write_json,
)
from ssip_agents.discovery.catalogue_expansion_planner_v3_3_1 import (
    existing_catalogue_rows,
    load_policy,
)
from ssip_agents.discovery.source_registry_loader_v3_3 import (
    canonical_host,
    load_registry_sources,
    load_validator_config,
    normalize_url,
)


VERSION = "3.3.2"
USER_AGENT = "SSIP-CoreResolution/3.3.2 (+bounded same-domain evidence recovery)"
INPUT_RUN_ID = "batch_1_actual_v3_3_1_20260710"
INPUT_ROOT = Path("outputs") / "catalogue_expansion_v3_3_1" / INPUT_RUN_ID
OUTPUT_ROOT = Path("outputs") / "catalogue_resolution_v3_3_2"
PREVIEW_ROOT = Path("data") / "catalogue_preview" / "v3_3_2"
MAX_REQUESTS = 150
MAX_REQUESTS_PER_CANDIDATE = 5
MIN_DOMAIN_DELAY_SECONDS = 1.0
CORE_URL_PATTERNS = (
    "/schemes/",
    "/startup-scheme.html",
    "/credit-guarantee-scheme-for-startups.html",
    "/incubator-schemes.html",
    "/bharat-startup-grand-challenge.html",
    "/nsa-landing.html",
    "/public_procurement.html",
    "/startupgov/imb.html",
    "/startupgov/self-certification.html",
    "/international.html",
    "/startupindia-mybharat.html",
)
NON_CORE_MARKERS = {
    "sitemap",
    "search",
    "faq",
    "contact",
    "about",
    "dashboard",
    "disclaimer",
    "terms",
    "screen-reader",
    "accessibility",
    "market-research",
    "knowledge-bank",
}
MAIN_EVIDENCE_KINDS = set(SUPPORT_KIND_MAP.values())
PREVIEW_FIELDS = [
    "master_id",
    "scheme_name",
    "source",
    "ministry",
    "department",
    "implementing_agency",
    "normalized_record_kind",
    "record_kind",
    "programme_status",
    "application_status",
    "status_evidence",
    "sector",
    "scheme_type",
    "target_beneficiaries",
    "startup_stage",
    "catalogue_inclusion",
    "catalogue_section",
    "current_decision",
    "official_page_url",
    "application_url",
    "guideline_urls",
    "opening_date",
    "closing_date",
    "funding_minimum",
    "funding_maximum",
    "currency",
    "eligibility",
    "benefits",
    "application_process",
    "required_documents",
    "contact_details",
    "last_verified_date",
    "field_evidence",
]


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    content_type: str
    title: str
    text: str
    source_id: str = ""
    raw_path: str = ""
    from_saved_batch: bool = False


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def stable_master_id(source: str, name: str, url: str) -> str:
    digest = hashlib.sha1(f"{source}|{name}|{canonical_programme_url(url)}".lower().encode("utf-8")).hexdigest()
    return f"v332_{digest[:20]}"


def canonical_programme_url(url: str) -> str:
    parsed = urlparse(url)
    return normalize_url(f"{parsed.scheme}://{parsed.netloc}{parsed.path}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def page_title(html: str, fallback: str = "") -> str:
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.string if soup.title else "")
    meta_title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "title"})
    if not title and meta_title and clean(meta_title.get("content")):
        title = clean(meta_title.get("content"))
    return title or fallback


def title_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1] or urlparse(url).netloc
    name = re.sub(r"\.(html|aspx|pdf)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[_-]+", " ", name)
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return re.sub(r"\s+", " ", name).strip().title()


def programme_name_from_title(title: str, url: str) -> str:
    text = clean(title) or title_from_url(url)
    text = re.sub(r"\s*-\s*NSIC\s*:.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\|\s*www\..*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\|\s*NSIC.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*-\s*Startup India\s*$", "", text, flags=re.IGNORECASE)
    return clean(text) or title_from_url(url)


def source_for_url(url: str, rows_by_source: dict[str, dict[str, str]], aliases: dict[str, str]) -> dict[str, str]:
    host = canonical_host(url, aliases)
    if host == "nsic.co.in":
        return {
            "source": "National Small Industries Corporation",
            "ministry": "Ministry of Micro, Small and Medium Enterprises",
            "department": "National Small Industries Corporation",
            "implementing_agency": "NSIC",
            "source_id": "nsic_schemes",
        }
    if host == "startupindia.gov.in":
        return {
            "source": "Startup India - Central Government Schemes",
            "ministry": "Ministry of Commerce and Industry",
            "department": "Department for Promotion of Industry and Internal Trade (DPIIT)",
            "implementing_agency": "Startup India",
            "source_id": "startup_india_central_schemes",
        }
    for row in rows_by_source.values():
        if canonical_host(clean(row.get("official_page_url")), aliases) == host:
            return {
                "source": row.get("source", ""),
                "ministry": row.get("ministry", ""),
                "department": row.get("department", ""),
                "implementing_agency": row.get("implementing_agency", ""),
                "source_id": "",
            }
    return {"source": host, "ministry": "", "department": "", "implementing_agency": "", "source_id": ""}


def kind_from_url_title(url: str, title: str) -> str:
    haystack = f"{url} {title}".lower()
    if "credit guarantee" in haystack:
        return "CREDIT_GUARANTEE"
    if any(token in haystack for token in ["credit", "loan", "rawmaterial", "billdiscounting"]):
        return "CREDIT_SUPPORT"
    if any(token in haystack for token in ["fund", "funding", "saarthi"]):
        return "FUND"
    if any(token in haystack for token in ["incubator", "incubation", "training"]):
        return "INCUBATION_SUPPORT"
    if any(token in haystack for token in ["procurement", "single point registration", "exhibition", "marketing"]):
        return "PROCUREMENT_SUPPORT" if "procurement" in haystack else "SCHEME_OR_PROGRAMME"
    return "SCHEME_OR_PROGRAMME"


def is_core_programme_url(url: str, title: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    title_l = title.lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if path.endswith((".pdf", ".xml", ".json", ".txt", ".jpg", ".jpeg", ".png")):
        return False
    if any(marker in path or marker in title_l for marker in NON_CORE_MARKERS):
        return False
    return any(pattern in path for pattern in CORE_URL_PATTERNS)


def priority_for_candidate(row: dict[str, str]) -> tuple[str, str, str, float]:
    url = clean(row.get("official_page_url"))
    kind = clean(row.get("normalized_record_kind") or row.get("record_kind"))
    issue = clean(row.get("validation_issues"))
    path = urlparse(url).path.lower()
    if is_core_programme_url(url, clean(row.get("scheme_name"))):
        return ("P1_LIKELY_CORE_SCHEME", "Candidate URL resembles a permanent official programme page.", "Fetch/validate as core page", 0.82)
    if kind in {"APPLICATION_CALL", "CHALLENGE"}:
        return ("P2_APPLICATION_CALL_NEEDS_PARENT", "Application or challenge evidence must be attached to a parent programme.", "Resolve parent programme page", 0.62)
    if path.endswith(".pdf"):
        return ("P3_OFFICIAL_PDF_NEEDS_IDENTITY_CHECK", "Official PDF may be evidence but should not be counted as the permanent page.", "Find matching HTML programme page", 0.54)
    if "sitemap" in path or "schemes" in path or "search" in path or "directory" in issue.lower():
        return ("P4_DIRECTORY_OR_INDEX", "Directory/index evidence can seed core-page relationships but is not itself a scheme.", "Use contained same-domain links as evidence", 0.48)
    if any(token in path for token in ["news", "result", "faq", "contact", "about"]):
        return ("P5_NEWS_RESULT_FAQ", "News, result or FAQ evidence is supporting material only.", "Keep as supporting evidence/manual review", 0.32)
    return ("P6_UNRESOLVED", "No deterministic permanent-page signal found.", "Manual review", 0.2)


def build_saved_pages(run_dir: Path) -> dict[str, FetchedPage]:
    pages: dict[str, FetchedPage] = {}
    for row in read_csv(run_dir / "fetch_audit.csv"):
        url = clean(row.get("final_url") or row.get("requested_url"))
        raw_path = Path(clean(row.get("raw_path")))
        html = ""
        text = ""
        title = clean(row.get("title"))
        if raw_path.exists() and "html" in clean(row.get("content_type")).lower():
            html = raw_path.read_text(encoding="utf-8", errors="ignore")
            title = page_title(html, title_from_url(url))
            text = visible_text(BeautifulSoup(html, "html.parser"))
        pages[canonical_programme_url(url)] = FetchedPage(
            url=url,
            final_url=url,
            status_code=int(clean(row.get("status_code")) or 0),
            content_type=clean(row.get("content_type")),
            title=title,
            text=text,
            source_id=clean(row.get("source_id")),
            raw_path=clean(row.get("raw_path")),
            from_saved_batch=True,
        )
    return pages


def core_candidates_from_saved(classified_rows: list[dict[str, str]], saved_pages: dict[str, FetchedPage]) -> list[str]:
    urls = []
    for row in classified_rows:
        url = canonical_programme_url(clean(row.get("url")))
        page = saved_pages.get(url)
        title = page.title if page else clean(row.get("title"))
        if page and is_core_programme_url(url, title):
            urls.append(url)
    return sorted(set(urls))


def extract_official_links(page: FetchedPage, aliases: dict[str, str], allowed_hosts: set[str]) -> list[str]:
    raw_path = Path(page.raw_path)
    if not raw_path.exists() or "html" not in page.content_type.lower():
        return []
    soup = BeautifulSoup(raw_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    links = []
    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = canonical_programme_url(urljoin(page.final_url, href))
        if canonical_host(url, aliases) in allowed_hosts and is_core_programme_url(url, clean(anchor.get_text(" ", strip=True)) or title_from_url(url)):
            links.append(url)
    return sorted(set(links))


class ResolutionFetcher:
    def __init__(self, output_dir: Path, aliases: dict[str, str], allowed_hosts: set[str]) -> None:
        self.output_dir = output_dir
        self.aliases = aliases
        self.allowed_hosts = allowed_hosts
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.fetch_audit: list[dict[str, Any]] = []
        self.redirects: list[dict[str, Any]] = []
        self.browser_required: list[dict[str, Any]] = []
        self.requests_per_candidate: Counter[str] = Counter()
        self.request_count = 0
        (output_dir / "raw_pages").mkdir(parents=True, exist_ok=True)

    def allowed_by_robots(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        host = canonical_host(url, self.aliases)
        if host not in self.allowed_hosts:
            return False, "host_not_in_v3_3_registry"
        parser = self.robots.get(host)
        if parser is None:
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            parser = RobotFileParser()
            try:
                response = self.session.get(robots_url, timeout=15)
                parser.parse(response.text.splitlines() if response.status_code < 400 else [])
            except requests.RequestException:
                parser.parse([])
            self.robots[host] = parser
        return parser.can_fetch(USER_AGENT, url), "robots_txt"

    def fetch(self, url: str, candidate_id: str) -> FetchedPage | None:
        if self.request_count >= MAX_REQUESTS:
            return None
        if self.requests_per_candidate[candidate_id] >= MAX_REQUESTS_PER_CANDIDATE:
            return None
        allowed, reason = self.allowed_by_robots(url)
        if not allowed:
            self.fetch_audit.append({"candidate_id": candidate_id, "url": url, "final_url": "", "status_code": "", "content_type": "", "result": "ROBOTS_DENIED", "reason": reason})
            return None
        host = canonical_host(url, self.aliases)
        elapsed = time.monotonic() - self.last_request.get(host, 0.0)
        if elapsed < MIN_DOMAIN_DELAY_SECONDS:
            time.sleep(MIN_DOMAIN_DELAY_SECONDS - elapsed)
        self.last_request[host] = time.monotonic()
        self.request_count += 1
        self.requests_per_candidate[candidate_id] += 1
        try:
            response = self.session.get(url, timeout=25, allow_redirects=True)
        except requests.RequestException as exc:
            self.fetch_audit.append({"candidate_id": candidate_id, "url": url, "final_url": "", "status_code": "", "content_type": "", "result": "FAILED", "reason": str(exc)})
            self.browser_required.append({"candidate_id": candidate_id, "url": url, "reason": "HTTP retrieval failed; browser fallback not executed in automated v3.3.2 run"})
            return None
        final_url = canonical_programme_url(response.url)
        if final_url != canonical_programme_url(url):
            self.redirects.append({"candidate_id": candidate_id, "requested_url": url, "final_url": final_url, "status_code": response.status_code})
        content_type = response.headers.get("content-type", "")
        title = title_from_url(final_url)
        text = ""
        raw_path = ""
        if "html" in content_type.lower():
            title = page_title(response.text, title)
            text = visible_text(BeautifulSoup(response.text, "html.parser"))
            raw_path = str(self.output_dir / "raw_pages" / f"{hashlib.sha1(final_url.encode()).hexdigest()}.html")
            Path(raw_path).write_text(response.text, encoding="utf-8")
        self.fetch_audit.append({"candidate_id": candidate_id, "url": url, "final_url": final_url, "status_code": response.status_code, "content_type": content_type, "result": "FETCHED" if response.status_code < 400 else "HTTP_ERROR", "reason": ""})
        if response.status_code >= 400:
            return None
        return FetchedPage(url=url, final_url=final_url, status_code=response.status_code, content_type=content_type, title=title, text=text, raw_path=raw_path)


def build_record(url: str, page: FetchedPage, source_meta: dict[str, str], evidence_urls: list[str]) -> dict[str, Any]:
    name = programme_name_from_title(page.title, url)
    kind = kind_from_url_title(url, name)
    app_status, status_evidence = status_from_text(page.text)
    if app_status == "VERIFICATION_REQUIRED":
        status_evidence = "Official core page reachable; no deterministic open/closed deadline signal found."
    field_evidence = {
        "official_page_url": url,
        "scheme_name": url,
        "status": url,
        "source_text": url,
    }
    return {
        "master_id": stable_master_id(source_meta.get("source", ""), name, url),
        "scheme_name": name,
        "short_name": NOT_SPECIFIED,
        "source": source_meta.get("source", ""),
        "ministry": source_meta.get("ministry", ""),
        "department": source_meta.get("department", ""),
        "implementing_agency": source_meta.get("implementing_agency", ""),
        "government_level": "Central Government",
        "state_or_ut": NOT_SPECIFIED,
        "normalized_record_kind": kind,
        "record_kind": kind,
        "programme_status": "OFFICIAL_INFORMATION_AVAILABLE",
        "application_status": app_status,
        "status_evidence": status_evidence,
        "sector": infer_sector(f"{name} {page.text[:2000]}"),
        "scheme_type": kind.replace("_", " ").title(),
        "target_beneficiaries": "Startups; MSMEs; Entrepreneurs" if re.search(r"startup|msme|entrepreneur", page.text, re.IGNORECASE) else NOT_SPECIFIED,
        "startup_stage": NOT_SPECIFIED,
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "SCHEMES_AND_PROGRAMMES",
        "current_decision": "",
        "official_page_url": url,
        "application_url": "",
        "guideline_urls": "; ".join(sorted(set(evidence_urls))),
        "opening_date": NOT_SPECIFIED,
        "closing_date": NOT_SPECIFIED,
        "funding_minimum": "",
        "funding_maximum": "",
        "currency": "INR",
        "eligibility": NOT_SPECIFIED,
        "benefits": NOT_SPECIFIED,
        "application_process": NOT_SPECIFIED,
        "required_documents": NOT_SPECIFIED,
        "contact_details": NOT_SPECIFIED,
        "last_verified_date": datetime.now(timezone.utc).date().isoformat(),
        "field_evidence": json.dumps(field_evidence, ensure_ascii=False),
        "validation_issues": "",
    }


def validate_record(record: dict[str, Any], url: str, page: FetchedPage, allowed_hosts: set[str], aliases: dict[str, str], existing_ids: set[str], existing_keys: set[str]) -> list[str]:
    issues: list[str] = []
    if canonical_host(url, aliases) not in allowed_hosts:
        issues.append("UNTRUSTED_DOMAIN")
    if page.status_code >= 400:
        issues.append("CORE_PAGE_NOT_REACHABLE")
    if not clean(record.get("ministry")) and not clean(record.get("department")) and not clean(record.get("implementing_agency")):
        issues.append("AUTHORITY_MISSING")
    if clean(record.get("normalized_record_kind")) not in MAIN_EVIDENCE_KINDS and clean(record.get("normalized_record_kind")) != "PROCUREMENT_SUPPORT":
        issues.append("INVALID_RECORD_TYPE")
    key = f"{clean(record.get('scheme_name')).casefold()}|{clean(record.get('department')).casefold()}|{canonical_host(url, aliases)}"
    if clean(record.get("master_id")) in existing_ids or key in existing_keys:
        issues.append("DUPLICATE_EXISTING_PREVIEW_MASTER")
    if not is_core_programme_url(url, clean(record.get("scheme_name"))):
        issues.append("NON_CORE_EVIDENCE_PAGE")
    return issues


def run_resolution(project_root: Path | None = None, run_id: str | None = None, allow_network: bool = False) -> Path:
    root = project_root or project_root_from_file()
    run_id = run_id or f"resolution_v3_3_2_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    batch_dir = root / INPUT_ROOT
    output_dir = root / OUTPUT_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = root / PREVIEW_ROOT
    preview_dir.mkdir(parents=True, exist_ok=True)

    review_rows = read_csv(batch_dir / "validation_review_queue_v3_3_1.csv")
    classified_rows = read_csv(batch_dir / "classified_urls_v3_3_1.csv")
    saved_pages = build_saved_pages(batch_dir)
    validator = load_validator_config(root)
    aliases = validator.get("trusted_domain_aliases", {})
    trusted_domains = set(validator.get("trusted_domains", []))
    sources, _registry = load_registry_sources(root)
    registry_hosts = {
        canonical_host(url, aliases)
        for source in sources
        for url in [source.official_url, *source.seed_urls]
        if canonical_host(url, aliases)
    }
    allowed_hosts = trusted_domains & registry_hosts
    review_by_url = {canonical_programme_url(row.get("official_page_url", "")): row for row in review_rows}
    rows_by_source = {row.get("source", ""): row for row in review_rows}

    priority_rows = []
    for row in review_rows:
        priority, reason, action, confidence = priority_for_candidate(row)
        url = clean(row.get("official_page_url"))
        priority_rows.append({
            "master_id": row.get("master_id", ""),
            "original_url": url,
            "title": row.get("scheme_name", ""),
            "deterministic_classification": row.get("normalized_record_kind", ""),
            "official_domain": canonical_host(url, aliases),
            "ministry": row.get("ministry", ""),
            "department": row.get("department", ""),
            "implementing_agency": row.get("implementing_agency", ""),
            "evidence_type": row.get("normalized_record_kind", ""),
            "current_validation_issues": row.get("validation_issues", ""),
            "possible_programme_family": programme_name_from_title(row.get("scheme_name", ""), url),
            "possible_permanent_core_page": "" if priority.startswith(("P3", "P4", "P5", "P6")) else canonical_programme_url(url),
            "priority": priority,
            "resolution_confidence": confidence,
            "resolution_reason": reason,
            "recommended_action": action,
        })
    write_csv(output_dir / "candidate_resolution_priority_v3_3_2.csv", priority_rows, list(priority_rows[0].keys()))

    candidate_core_urls = set(core_candidates_from_saved(classified_rows, saved_pages))
    for page in list(saved_pages.values()):
        if canonical_host(page.final_url, aliases) in allowed_hosts:
            for link in extract_official_links(page, aliases, allowed_hosts):
                candidate_core_urls.add(link)
    for row in review_rows:
        url = canonical_programme_url(row.get("official_page_url", ""))
        if is_core_programme_url(url, row.get("scheme_name", "")):
            candidate_core_urls.add(url)

    fetcher = ResolutionFetcher(output_dir, aliases, allowed_hosts)
    resolved_pages: dict[str, FetchedPage] = {}
    for url in sorted(candidate_core_urls):
        page = saved_pages.get(canonical_programme_url(url))
        if page:
            resolved_pages[canonical_programme_url(url)] = page
            continue
        if allow_network:
            fetched = fetcher.fetch(url, review_by_url.get(url, {}).get("master_id", "derived_core"))
            if fetched and is_core_programme_url(fetched.final_url, fetched.title):
                resolved_pages[canonical_programme_url(fetched.final_url)] = fetched

    existing_preview = read_csv(root / "data" / "catalogue_preview" / "v3_3_1" / "batch_1_catalogue_preview_v3_3_1.csv")
    existing_valid_preview = [row for row in existing_preview if clean(row.get("current_decision")) != "REJECTED"]
    main_kinds = set(load_policy(root)["counting_policy"]["main_scheme_total_record_kinds"])
    existing_ids = {clean(row.get("master_id") or row.get("normalized_scheme_id")) for row in existing_valid_preview}
    existing_keys = {
        f"{clean(row.get('scheme_name')).casefold()}|{clean(row.get('department')).casefold()}|{canonical_host(clean(row.get('official_page_url')), aliases)}"
        for row in existing_valid_preview
    }

    evidence_by_core: dict[str, list[str]] = defaultdict(list)
    for row in review_rows:
        evidence_url = canonical_programme_url(row.get("official_page_url", ""))
        for core_url in resolved_pages:
            if canonical_host(evidence_url, aliases) == canonical_host(core_url, aliases):
                title_key = programme_name_from_title(row.get("scheme_name", ""), evidence_url).casefold()
                core_name = programme_name_from_title(resolved_pages[core_url].title, core_url).casefold()
                if title_key and (title_key in core_name or core_name in title_key or row.get("normalized_record_kind") in {"APPLICATION_CALL", "FUND", "SCHEME_OR_PROGRAMME"}):
                    evidence_by_core[core_url].append(evidence_url)
                    break

    validated: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    resolution_rows: list[dict[str, Any]] = []
    core_rows: list[dict[str, Any]] = []
    evidence_graph: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []
    seen_new_ids: set[str] = set()

    for url, page in sorted(resolved_pages.items()):
        source_meta = source_for_url(url, rows_by_source, aliases)
        evidence_urls = sorted(set(evidence_by_core.get(url, [])))
        record = build_record(url, page, source_meta, evidence_urls)
        issues = validate_record(record, url, page, allowed_hosts, aliases, existing_ids, existing_keys)
        if record["master_id"] in seen_new_ids:
            issues.append("DUPLICATE_NEW_MASTER_ID")
            duplicate_rows.append({"master_id": record["master_id"], "merged_url": url, "reason": "Duplicate generated master ID"})
        seen_new_ids.add(record["master_id"])
        core_rows.append({
            "master_id": record["master_id"],
            "programme_name": record["scheme_name"],
            "core_url": url,
            "source_domain": canonical_host(url, aliases),
            "status_code": page.status_code,
            "resolution_confidence": 0.9 if not issues else 0.55,
            "resolution_method": "saved_batch_core_page" if page.from_saved_batch else "targeted_same_domain_fetch",
        })
        for evidence_url in [url, *evidence_urls]:
            role = "permanent_scheme_page" if evidence_url == url else "supporting_evidence"
            evidence_graph.append({
                "master_id": record["master_id"],
                "programme_name": record["scheme_name"],
                "evidence_role": role,
                "evidence_url": evidence_url,
                "evidence_title": record["scheme_name"] if evidence_url == url else title_from_url(evidence_url),
                "source_domain": canonical_host(evidence_url, aliases),
                "current_or_historical": "current" if evidence_url == url else "supporting",
                "relationship_confidence": 0.92 if evidence_url == url else 0.62,
            })
            resolution_rows.append({
                "candidate_url": evidence_url,
                "candidate_title": title_from_url(evidence_url),
                "resolved_master_id": record["master_id"],
                "core_url": url,
                "resolution_status": "RESOLVED",
                "resolution_method": role,
                "resolution_confidence": 0.92 if evidence_url == url else 0.62,
            })
        if not issues:
            validated.append(record)
            existing_ids.add(record["master_id"])
            existing_keys.add(f"{record['scheme_name'].casefold()}|{record['department'].casefold()}|{canonical_host(url, aliases)}")
        elif "DUPLICATE" in ";".join(issues):
            rejected.append({**record, "validation_issues": "; ".join(issues), "rejection_reason": "; ".join(issues), "current_decision": "REJECTED", "catalogue_inclusion": "EXCLUDED"})
        else:
            manual_review.append({**record, "validation_issues": "; ".join(issues), "catalogue_inclusion": "PENDING_REVALIDATION", "current_decision": "NEEDS_REVIEW"})

    resolved_evidence_urls = {row["candidate_url"] for row in resolution_rows}
    unresolved = []
    for row in review_rows:
        url = canonical_programme_url(row.get("official_page_url", ""))
        if url not in resolved_evidence_urls:
            unresolved.append({
                "candidate_master_id": row.get("master_id", ""),
                "candidate_url": url,
                "candidate_title": row.get("scheme_name", ""),
                "reason": row.get("validation_issues", "") or "No deterministic permanent core page resolved",
                "recommended_action": "Manual review or separately approved focused source enhancement",
            })

    preview_rows, preview_duplicates = deduplicate_preview_rows(existing_valid_preview + validated + manual_review)
    preview_path = preview_dir / "catalogue_preview_v3_3_2.csv"
    write_csv(preview_path, preview_rows, PREVIEW_FIELDS)

    write_csv(output_dir / "core_page_resolution_v3_3_2.csv", resolution_rows, ["candidate_url", "candidate_title", "resolved_master_id", "core_url", "resolution_status", "resolution_method", "resolution_confidence"])
    write_csv(output_dir / "resolved_core_pages_v3_3_2.csv", core_rows, ["master_id", "programme_name", "core_url", "source_domain", "status_code", "resolution_confidence", "resolution_method"])
    write_csv(output_dir / "unresolved_candidates_v3_3_2.csv", unresolved, ["candidate_master_id", "candidate_url", "candidate_title", "reason", "recommended_action"])
    write_csv(output_dir / "browser_required_v3_3_2.csv", fetcher.browser_required, ["candidate_id", "url", "reason"])
    write_csv(output_dir / "resolution_fetch_audit_v3_3_2.csv", fetcher.fetch_audit, ["candidate_id", "url", "final_url", "status_code", "content_type", "result", "reason"])
    write_csv(output_dir / "redirects_v3_3_2.csv", fetcher.redirects, ["candidate_id", "requested_url", "final_url", "status_code"])
    write_csv(output_dir / "programme_evidence_graph_v3_3_2.csv", evidence_graph, ["master_id", "programme_name", "evidence_role", "evidence_url", "evidence_title", "source_domain", "current_or_historical", "relationship_confidence"])
    write_csv(output_dir / "validated_catalogue_candidates_v3_3_2.csv", validated, PREVIEW_FIELDS + ["validation_issues"])
    write_csv(output_dir / "manual_review_queue_v3_3_2.csv", manual_review, PREVIEW_FIELDS + ["validation_issues"])
    write_csv(output_dir / "rejected_candidates_v3_3_2.csv", rejected, PREVIEW_FIELDS + ["validation_issues", "rejection_reason"])
    write_csv(output_dir / "duplicate_merge_audit_v3_3_2.csv", duplicate_rows + [{"master_id": "", "merged_url": "", "reason": f"preview_duplicate_rows_merged={preview_duplicates}"}], ["master_id", "merged_url", "reason"])

    old_preview_scheme_count = visible_unique_count(existing_valid_preview, main_kinds)
    new_preview_scheme_count = visible_unique_count(preview_rows, main_kinds)
    summary = {
        "version": VERSION,
        "run_id": run_id,
        "generated_at": utc_now(),
        "candidates_reviewed": len(review_rows),
        "candidates_by_priority": dict(Counter(row["priority"] for row in priority_rows)),
        "targeted_network_requests": fetcher.request_count,
        "successful_resolution_fetches": sum(1 for row in fetcher.fetch_audit if row.get("result") == "FETCHED" and int(row.get("status_code") or 0) < 400),
        "browser_fallback_count": len(fetcher.browser_required),
        "permanent_core_pages_resolved": len(core_rows),
        "programme_families_created": len({row["master_id"] for row in evidence_graph}),
        "newly_validated_schemes": len(validated),
        "manual_review_records": len(manual_review),
        "rejected_records": len(rejected),
        "duplicates_merged": len(duplicate_rows) + preview_duplicates,
        "old_preview_scheme_count": old_preview_scheme_count,
        "new_preview_scheme_count": new_preview_scheme_count,
        "application_call_count": visible_application_call_count(preview_rows),
        "duplicate_master_id_count": len([count for count in Counter(row.get("master_id") for row in preview_rows).values() if count > 1]),
        "database_writes": 0,
        "preview_catalogue": str(preview_path),
        "status": "V3_3_2_COMPLETE_WAITING_FOR_APPROVAL",
    }
    write_json(output_dir / "validation_summary_v3_3_2.json", summary)
    write_json(preview_dir / "catalogue_summary_v3_3_2.json", summary)
    write_json(output_dir / "checkpoint.json", {
        "version": VERSION,
        "run_id": run_id,
        "status": "V3_3_2_COMPLETE_WAITING_FOR_APPROVAL",
        "database_writes": 0,
        "next_step": "await_approval_before_batch_2_or_publication",
    })
    return output_dir
