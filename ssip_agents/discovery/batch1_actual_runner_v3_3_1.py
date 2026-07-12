from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from ssip_agents.discovery.catalogue_expansion_planner_v3_3_1 import (
    existing_catalogue_rows,
    load_policy,
    summarize_catalogue_count,
)
from ssip_agents.discovery.source_registry_loader_v3_3 import (
    RegistrySource,
    canonical_host,
    load_registry_sources,
    load_validator_config,
    normalize_url,
)


VERSION = "3.3.1"
USER_AGENT = "SSIP-CatalogueExpansion/3.3.1 (+bounded official-source discovery)"
ELIGIBLE_KINDS = {
    "SCHEME",
    "PROGRAMME",
    "GRANT",
    "FUND",
    "CREDIT_SUPPORT",
    "CREDIT_GUARANTEE",
    "SUBSIDY",
    "INCENTIVE",
    "FELLOWSHIP",
    "INCUBATION_SUPPORT",
    "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT",
}
SUPPORT_KIND_MAP = {
    "SCHEME": "SCHEME_OR_PROGRAMME",
    "PROGRAMME": "SCHEME_OR_PROGRAMME",
    "GRANT": "GRANT",
    "FUND": "FUND",
    "CREDIT_SUPPORT": "CREDIT_SUPPORT",
    "CREDIT_GUARANTEE": "CREDIT_GUARANTEE",
    "SUBSIDY": "SUBSIDY",
    "INCENTIVE": "INCENTIVE",
    "FELLOWSHIP": "FELLOWSHIP",
    "INCUBATION_SUPPORT": "INCUBATION_SUPPORT",
    "INFRASTRUCTURE_SUPPORT": "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT": "RESEARCH_SUPPORT",
}
NOT_SPECIFIED = "Not specified on the verified official source"
NON_CORE_URL_TOKENS = {
    "sitemap",
    "search",
    "directory",
    "faq",
    "news",
    "press-release",
    "result",
    "archive",
}
GENERIC_DIRECTORY_TITLES = {
    "scheme",
    "schemes",
    "programme",
    "programmes",
    "program",
    "programs",
    "government schemes",
    "startup schemes",
}


@dataclass
class PageFetch:
    source_id: str
    url: str
    final_url: str
    depth: int
    status_code: int
    content_type: str
    title: str
    text: str
    raw_path: str
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def clean(value: Any) -> str:
    return str(value or "").strip()


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text[:80] or "record"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def pick_batch_sources(project_root: Path, batch_id: str) -> list[RegistrySource]:
    policy = load_policy(project_root)
    sources, _registry = load_registry_sources(project_root)
    by_id = {source.source_id: source for source in sources}
    batch = next(item for item in policy["batches"] if item["batch_id"] == batch_id)
    return [by_id[source_id] for source_id in batch["source_ids"] if source_id in by_id]


def allowed_hosts_for(sources: list[RegistrySource], validator: dict[str, Any]) -> set[str]:
    aliases = validator.get("trusted_domain_aliases", {})
    hosts = set()
    for source in sources:
        for url in [source.official_url, *source.seed_urls]:
            host = canonical_host(url, aliases)
            if host:
                hosts.add(host)
    return hosts


def visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:25000]


def classify_url(url: str, title: str = "", text: str = "") -> str:
    haystack = f"{url} {title} {text[:1200]}".lower()
    if any(token in haystack for token in ["faq", "frequently-asked"]):
        return "FAQ"
    if any(token in haystack for token in ["result", "selected", "winner"]):
        return "RESULT_PAGE"
    if any(token in haystack for token in ["news", "press-release", "media"]):
        return "NEWS_PAGE"
    if any(token in haystack for token in ["archive", "archived"]):
        return "ARCHIVE_PAGE"
    if any(token in haystack for token in ["guideline", "guidelines"]):
        return "GUIDELINE"
    if "manual" in haystack:
        return "MANUAL"
    if any(token in haystack for token in ["apply", "application", "registration"]):
        if any(token in haystack for token in ["scheme", "program", "challenge", "grant"]):
            return "APPLICATION_CALL"
        return "APPLICATION_PORTAL"
    if any(token in haystack for token in ["challenge", "hackathon", "competition"]):
        return "CHALLENGE"
    if "credit guarantee" in haystack or "guarantee scheme" in haystack:
        return "CREDIT_GUARANTEE"
    if "credit" in haystack or "loan" in haystack:
        return "CREDIT_SUPPORT"
    if "incubat" in haystack:
        return "INCUBATION_SUPPORT"
    if "infrastructure" in haystack or "facility" in haystack:
        return "INFRASTRUCTURE_SUPPORT"
    if "research" in haystack or "r&d" in haystack:
        return "RESEARCH_SUPPORT"
    if "fellowship" in haystack:
        return "FELLOWSHIP"
    if "subsidy" in haystack:
        return "SUBSIDY"
    if "incentive" in haystack:
        return "INCENTIVE"
    if "fund" in haystack:
        return "FUND"
    if "grant" in haystack:
        return "GRANT"
    if "scheme" in haystack or "yojana" in haystack:
        return "SCHEME"
    if "program" in haystack or "programme" in haystack:
        return "PROGRAMME"
    if any(token in haystack for token in ["directory", "schemes", "search"]):
        return "DIRECTORY_PAGE"
    if "policy" in haystack:
        return "POLICY_PAGE"
    if any(token in haystack for token in ["scheme", "grant", "startup", "entrepreneur", "msme"]):
        return "UNCERTAIN"
    return "NON_SCHEME"


def is_relevant_kind(kind: str) -> bool:
    return kind not in {"NON_SCHEME", "DIRECTORY_PAGE", "NEWS_PAGE"}


def is_core_catalogue_page(url: str, title: str, classification: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    normalized_title = re.sub(r"\s+", " ", title.lower()).strip()
    if path.endswith((".xml", ".json", ".txt", ".pdf")):
        return False
    if classification not in ELIGIBLE_KINDS:
        return False
    if normalized_title in GENERIC_DIRECTORY_TITLES:
        return False
    if any(token in path or token in normalized_title for token in NON_CORE_URL_TOKENS):
        return False
    return True


def preview_priority(row: dict[str, Any]) -> tuple[int, int, int]:
    inclusion = clean(row.get("catalogue_inclusion"))
    decision = clean(row.get("current_decision"))
    kind = clean(row.get("normalized_record_kind") or row.get("record_kind"))
    return (
        2 if inclusion == "INCLUDED" or decision == "APPROVED" else 1 if inclusion == "PENDING_REVALIDATION" or decision == "NEEDS_REVIEW" else 0,
        1 if kind in SUPPORT_KIND_MAP.values() else 0,
        1 if clean(row.get("official_page_url")) else 0,
    )


def deduplicate_preview_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    selected: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for row in rows:
        master_id = clean(row.get("master_id"))
        if not master_id:
            master_id = stable_master_id(clean(row.get("source")), clean(row.get("scheme_name")), clean(row.get("official_page_url")))
            row = {**row, "master_id": master_id}
        existing = selected.get(master_id)
        if existing is None:
            selected[master_id] = row
            continue
        duplicate_count += 1
        if preview_priority(row) > preview_priority(existing):
            selected[master_id] = row
    return list(selected.values()), duplicate_count


def visible_unique_count(rows: list[dict[str, Any]], eligible_kinds: set[str]) -> int:
    ids: set[str] = set()
    for row in rows:
        if clean(row.get("current_decision")) == "REJECTED":
            continue
        kind = clean(row.get("normalized_record_kind") or row.get("record_kind") or row.get("current_record_kind"))
        if kind in eligible_kinds:
            ids.add(clean(row.get("master_id") or row.get("normalized_scheme_id")))
    return len(ids)


def visible_application_call_count(rows: list[dict[str, Any]]) -> int:
    ids: set[str] = set()
    for row in rows:
        if clean(row.get("current_decision")) == "REJECTED":
            continue
        kind = clean(row.get("normalized_record_kind") or row.get("record_kind") or row.get("current_record_kind"))
        if kind == "APPLICATION_CALL":
            ids.add(clean(row.get("master_id") or row.get("normalized_scheme_id")))
    return len(ids)


def extract_links(base_url: str, html: str, allowed_hosts: set[str], aliases: dict[str, str]) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = normalize_url(urldefrag(urljoin(base_url, href))[0])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if canonical_host(url, aliases) not in allowed_hosts:
            continue
        urls.append(url)
    return sorted(set(urls))


def parse_sitemap_urls(xml_text: str, base_url: str, allowed_hosts: set[str], aliases: dict[str, str]) -> list[str]:
    urls = re.findall(r"<loc>\s*([^<]+)\s*</loc>", xml_text, flags=re.IGNORECASE)
    output = []
    for raw in urls[:500]:
        url = normalize_url(urldefrag(urljoin(base_url, raw))[0])
        if canonical_host(url, aliases) in allowed_hosts:
            output.append(url)
    return sorted(set(output))


def fetch_robots(session: requests.Session, host: str, scheme: str, output_rows: list[dict[str, Any]]) -> RobotFileParser:
    robots_url = f"{scheme}://{host}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = session.get(robots_url, timeout=15, headers={"User-Agent": USER_AGENT})
        if response.status_code < 400:
            parser.parse(response.text.splitlines())
            output_rows.append({"host": host, "robots_url": robots_url, "status": response.status_code, "decision": "LOADED"})
        else:
            parser.parse([])
            output_rows.append({"host": host, "robots_url": robots_url, "status": response.status_code, "decision": "UNREADABLE_ALLOW"})
    except requests.RequestException as exc:
        parser.parse([])
        output_rows.append({"host": host, "robots_url": robots_url, "status": "", "decision": "FETCH_ERROR_ALLOW", "error": str(exc)})
    return parser


def master_key(name: str, source_id: str) -> str:
    base = re.sub(r"\b(apply|application|guidelines?|manual|scheme|programme|program|challenge)\b", " ", name, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip() or name
    return f"{source_id}:{slug(base)}"


def extract_name(title: str, url: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -|")
    if title and title.lower() not in {"home", "schemes", "search"}:
        return title[:180]
    parts = [part for part in urlparse(url).path.split("/") if part]
    if parts:
        return re.sub(r"[-_]+", " ", parts[-1]).strip().title()[:180]
    return urlparse(url).netloc


def infer_sector(text: str) -> str:
    lower = text.lower()
    if any(x in lower for x in ["msme", "enterprise", "entrepreneur"]):
        return "MSME / Entrepreneurship"
    if any(x in lower for x in ["startup", "incubat"]):
        return "Startup / Innovation"
    if "technology" in lower or "digital" in lower:
        return "Digital Technology"
    if "manufactur" in lower:
        return "Manufacturing"
    return NOT_SPECIFIED


def status_from_text(text: str) -> tuple[str, str]:
    lower = text.lower()
    if any(x in lower for x in ["closed", "last date", "deadline over", "archived"]):
        return "CLOSED_OR_HISTORICAL", "Status inferred from deadline/closed wording on official source."
    if any(x in lower for x in ["apply now", "applications open", "open for application"]):
        return "OPEN", "Status inferred from open/application wording on official source."
    return "VERIFICATION_REQUIRED", "No explicit current application status found on official source."


def stable_master_id(source_id: str, name: str, url: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{name.lower()}|{normalize_url(url)}".encode("utf-8")).hexdigest()[:20]
    return f"b1_{digest}"


def run_batch1_actual(project_root: Path, run_id: str, *, max_total_pages: int = 250) -> Path:
    batch_id = "batch_1_enterprise_startup_indexes"
    output_dir = project_root / "outputs" / "catalogue_expansion_v3_3_1" / run_id
    raw_dir = output_dir / "raw_pages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = project_root / "data" / "catalogue_preview" / "v3_3_1"
    preview_dir.mkdir(parents=True, exist_ok=True)

    policy = json.loads((project_root / "config" / "catalogue_expansion_policy_v3_3_1.json").read_text(encoding="utf-8"))
    validator = load_validator_config(project_root)
    aliases = validator.get("trusted_domain_aliases", {})
    sources = pick_batch_sources(project_root, batch_id)
    source_by_id = {source.source_id: source for source in sources}
    allowed_hosts = allowed_hosts_for(sources, validator)
    session = requests.Session()
    robots_cache: dict[str, RobotFileParser] = {}
    last_request: dict[str, float] = {}
    queue: deque[tuple[str, str, int]] = deque()
    seen: set[str] = set()
    discovered: dict[str, dict[str, Any]] = {}
    fetched_pages: dict[str, PageFetch] = {}
    fetch_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    redirects: list[dict[str, Any]] = []
    robots_rows: list[dict[str, Any]] = []
    robots_denied: list[dict[str, Any]] = []
    pdf_rows: list[dict[str, Any]] = []
    browser_required: list[dict[str, Any]] = []
    uncertain_rows: list[dict[str, Any]] = []

    for source in sources:
        for seed in source.seed_urls:
            queue.append((source.source_id, seed, 0))
            discovered[seed] = {"source_id": source.source_id, "url": seed, "depth": 0, "discovery_method": "seed"}
        for seed in source.seed_urls:
            parsed = urlparse(seed)
            sitemap_url = normalize_url(f"{parsed.scheme}://{parsed.netloc}/sitemap.xml")
            queue.append((source.source_id, sitemap_url, 1))
            discovered.setdefault(sitemap_url, {"source_id": source.source_id, "url": sitemap_url, "depth": 1, "discovery_method": "sitemap_probe"})

    while queue and len(fetch_rows) < max_total_pages:
        source_id, url, depth = queue.popleft()
        url = normalize_url(url)
        if not url or url in seen or depth > 2:
            continue
        seen.add(url)
        parsed = urlparse(url)
        host = canonical_host(url, aliases)
        if host not in allowed_hosts:
            continue
        if host not in robots_cache:
            robots_cache[host] = fetch_robots(session, host, parsed.scheme or "https", robots_rows)
        allowed = robots_cache[host].can_fetch(USER_AGENT, url)
        robots_rows.append({"host": host, "robots_url": f"{parsed.scheme}://{parsed.netloc}/robots.txt", "url": url, "decision": "ALLOW" if allowed else "DENY"})
        if not allowed:
            robots_denied.append({"source_id": source_id, "url": url, "host": host, "reason": "robots.txt denied"})
            continue
        elapsed = time.time() - last_request.get(host, 0)
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        last_request[host] = time.time()
        try:
            response = session.get(url, timeout=25, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
            content_type = response.headers.get("content-type", "")
            final_url = normalize_url(response.url)
            if final_url != url:
                redirects.append({"source_id": source_id, "requested_url": url, "final_url": final_url, "status_code": response.status_code})
            raw_name = hashlib.sha1(final_url.encode("utf-8")).hexdigest()
            ext = ".pdf" if "pdf" in content_type.lower() or final_url.lower().endswith(".pdf") else ".html"
            raw_path = raw_dir / f"{raw_name}{ext}"
            raw_path.write_bytes(response.content[:3_000_000])
            title = ""
            text = ""
            if ext == ".html":
                soup = BeautifulSoup(response.text, "html.parser")
                title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
                text = visible_text(soup)
                for link in extract_links(final_url, response.text, allowed_hosts, aliases):
                    if link not in seen:
                        discovered.setdefault(link, {"source_id": source_id, "url": link, "depth": depth + 1, "discovery_method": "html_link"})
                        queue.append((source_id, link, depth + 1))
                if "sitemap" in url.lower():
                    for link in parse_sitemap_urls(response.text, final_url, allowed_hosts, aliases):
                        if link not in seen:
                            discovered.setdefault(link, {"source_id": source_id, "url": link, "depth": depth + 1, "discovery_method": "sitemap"})
                            queue.append((source_id, link, depth + 1))
            else:
                title = extract_name("", final_url)
                text = title
                pdf_rows.append({"source_id": source_id, "url": final_url, "status_code": response.status_code, "content_type": content_type})
            page = PageFetch(source_id, url, final_url, depth, response.status_code, content_type, title, text, str(raw_path))
            fetched_pages[final_url] = page
            fetch_rows.append({
                "source_id": source_id,
                "requested_url": url,
                "final_url": final_url,
                "depth": depth,
                "status_code": response.status_code,
                "content_type": content_type,
                "raw_path": str(raw_path),
                "title": title,
                "text_length": len(text),
            })
        except requests.RequestException as exc:
            failed_rows.append({"source_id": source_id, "url": url, "depth": depth, "error": str(exc)})

    classified_rows = []
    for item in discovered.values():
        page = fetched_pages.get(item["url"])
        title = page.title if page else extract_name("", item["url"])
        text = page.text if page else ""
        kind = classify_url(item["url"], title, text)
        row = {
            **item,
            "title": title,
            "classification": kind,
            "is_relevant": is_relevant_kind(kind),
            "fetched": item["url"] in fetched_pages,
        }
        classified_rows.append(row)
        if kind == "UNCERTAIN":
            uncertain_rows.append(row)
        if item["url"].lower().endswith(".pdf"):
            pdf_rows.append({"source_id": item["source_id"], "url": item["url"], "status_code": "", "content_type": "application/pdf"})

    relevant = [row for row in classified_rows if row["is_relevant"]]
    master_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in relevant:
        key = master_key(row["title"], row["source_id"])
        master_groups[key].append(row)

    master_rows = []
    evidence_rows = []
    resolution_rows = []
    unresolved_rows = []
    duplicate_rows = []
    validated_rows = []
    review_rows = []
    rejected_rows = []
    used_master_ids: set[str] = set()
    for key, rows in master_groups.items():
        core = next((row for row in rows if row["classification"] in ELIGIBLE_KINDS and row["fetched"]), rows[0])
        page = fetched_pages.get(core["url"])
        source = source_by_id[core["source_id"]]
        name = extract_name(core["title"], core["url"])
        master_id = stable_master_id(source.source_id, name, core["url"])
        if master_id in used_master_ids:
            duplicate_rows.append({"master_id": master_id, "merged_key": key, "evidence_count": len(rows)})
            continue
        used_master_ids.add(master_id)
        text = page.text if page else core["title"]
        app_status, status_evidence = status_from_text(text)
        record_kind = SUPPORT_KIND_MAP.get(core["classification"], "APPLICATION_CALL" if core["classification"] in {"APPLICATION_CALL", "CHALLENGE"} else core["classification"])
        master_rows.append({
            "master_id": master_id,
            "scheme_name": name,
            "source_id": source.source_id,
            "record_kind": record_kind,
            "core_url": core["url"],
            "evidence_count": len(rows),
        })
        for row in rows:
            evidence_rows.append({"master_id": master_id, "source_id": row["source_id"], "url": row["url"], "classification": row["classification"], "relationship": "core" if row["url"] == core["url"] else "supporting_evidence"})
            if row["classification"] in {"APPLICATION_CALL", "CHALLENGE", "GUIDELINE", "MANUAL"}:
                resolution_rows.append({"evidence_url": row["url"], "evidence_type": row["classification"], "resolved_master_id": master_id, "core_url": core["url"], "resolution": "DETERMINISTIC_GROUPING"})
        validation_issues = []
        if not page:
            validation_issues.append("CORE_PAGE_NOT_FETCHED")
        if canonical_host(core["url"], aliases) not in allowed_hosts:
            validation_issues.append("UNTRUSTED_DOMAIN")
        if not source.ministry and not source.department and not source.agency:
            validation_issues.append("AUTHORITY_MISSING")
        if record_kind not in SUPPORT_KIND_MAP.values() and record_kind not in {"APPLICATION_CALL", "CHALLENGE"}:
            validation_issues.append("NON_CATALOGUE_RECORD_KIND")
        if record_kind in SUPPORT_KIND_MAP.values() and not is_core_catalogue_page(core["url"], name, core["classification"]):
            validation_issues.append("NON_CORE_INDEX_OR_SITEMAP_PAGE")
        record = {
            "master_id": master_id,
            "scheme_name": name,
            "short_name": NOT_SPECIFIED,
            "source": source.name,
            "ministry": source.ministry,
            "department": source.department,
            "implementing_agency": source.agency,
            "government_level": "Central Government" if source.scope == "Central" else "State Government",
            "state_or_ut": NOT_SPECIFIED,
            "record_kind": record_kind,
            "normalized_record_kind": record_kind,
            "sector": infer_sector(f"{name} {text[:1500]}"),
            "scheme_type": record_kind.replace("_", " ").title(),
            "target_beneficiaries": "Startups; MSMEs; Entrepreneurs" if "startup" in text.lower() or "msme" in text.lower() else NOT_SPECIFIED,
            "startup_stage": NOT_SPECIFIED,
            "programme_status": "OFFICIAL_INFORMATION_AVAILABLE",
            "application_status": app_status,
            "status_evidence": status_evidence,
            "opening_date": NOT_SPECIFIED,
            "closing_date": NOT_SPECIFIED,
            "funding_minimum": "",
            "funding_maximum": "",
            "currency": "INR",
            "eligibility": NOT_SPECIFIED,
            "benefits": NOT_SPECIFIED,
            "application_process": NOT_SPECIFIED,
            "required_documents": NOT_SPECIFIED,
            "official_page_url": core["url"],
            "application_url": NOT_SPECIFIED,
            "guideline_urls": "; ".join(row["url"] for row in rows if row["classification"] in {"GUIDELINE", "MANUAL"}),
            "contact_details": NOT_SPECIFIED,
            "last_verified_date": datetime.now(timezone.utc).date().isoformat(),
            "field_evidence": json.dumps({"official_page_url": core["url"], "status": status_evidence}, ensure_ascii=False),
            "validation_issues": "; ".join(validation_issues),
            "catalogue_inclusion": "INCLUDED" if not validation_issues and record_kind in SUPPORT_KIND_MAP.values() else "PENDING_REVALIDATION",
            "catalogue_section": "SCHEMES_AND_PROGRAMMES" if record_kind in SUPPORT_KIND_MAP.values() else "APPLICATION_CALLS",
            "current_decision": "" if not validation_issues else "NEEDS_REVIEW",
        }
        if not validation_issues and record_kind in SUPPORT_KIND_MAP.values():
            validated_rows.append(record)
        elif record_kind in SUPPORT_KIND_MAP.values() or record_kind in {"APPLICATION_CALL", "CHALLENGE"}:
            review_rows.append(record)
        else:
            rejected_rows.append({**record, "rejection_reason": "; ".join(validation_issues) or "Excluded record kind"})
    for row in relevant:
        if row["classification"] in {"APPLICATION_CALL", "CHALLENGE", "GUIDELINE", "MANUAL"} and not any(x["evidence_url"] == row["url"] for x in resolution_rows):
            unresolved_rows.append({"url": row["url"], "classification": row["classification"], "reason": "No deterministic parent programme resolved"})

    existing_rows = existing_catalogue_rows(project_root)
    policy_counts = summarize_catalogue_count(existing_rows, policy)
    existing_preview_rows = []
    for row in existing_rows:
        kind = clean(row.get("normalized_record_kind") or row.get("record_kind") or row.get("current_record_kind"))
        if kind in set(policy["counting_policy"]["main_scheme_total_record_kinds"]) or kind == "APPLICATION_CALL":
            existing_preview_rows.append(row)
    preview_rows, preview_duplicate_count = deduplicate_preview_rows(existing_preview_rows + validated_rows + review_rows)
    preview_path = preview_dir / "batch_1_catalogue_preview_v3_3_1.csv"
    preview_fields = [
        "master_id", "scheme_name", "source", "ministry", "department", "implementing_agency",
        "normalized_record_kind", "record_kind", "programme_status", "application_status",
        "status_evidence", "sector", "scheme_type", "target_beneficiaries", "startup_stage",
        "catalogue_inclusion", "catalogue_section", "current_decision", "official_page_url",
        "application_url", "guideline_urls", "opening_date", "closing_date", "funding_minimum",
        "funding_maximum", "currency", "eligibility", "benefits", "application_process",
        "required_documents", "contact_details", "last_verified_date", "field_evidence"
    ]
    write_csv(preview_path, preview_rows, preview_fields)
    final_counts = summarize_catalogue_count(preview_rows, policy)
    main_scheme_kinds = set(policy["counting_policy"]["main_scheme_total_record_kinds"])

    fields_common = ["source_id", "url", "depth", "discovery_method", "title", "classification", "is_relevant", "fetched"]
    write_csv(output_dir / "discovered_urls.csv", list(discovered.values()), ["source_id", "url", "depth", "discovery_method"])
    write_csv(output_dir / "fetch_audit.csv", fetch_rows, ["source_id", "requested_url", "final_url", "depth", "status_code", "content_type", "raw_path", "title", "text_length"])
    write_csv(output_dir / "failed_urls.csv", failed_rows, ["source_id", "url", "depth", "error"])
    write_csv(output_dir / "redirects.csv", redirects, ["source_id", "requested_url", "final_url", "status_code"])
    write_csv(output_dir / "robots_decisions.csv", robots_rows + robots_denied, ["source_id", "host", "robots_url", "url", "status", "decision", "reason", "error"])
    write_csv(output_dir / "pdf_candidates.csv", pdf_rows, ["source_id", "url", "status_code", "content_type"])
    write_csv(output_dir / "uncertain_candidates.csv", uncertain_rows, fields_common)
    write_csv(output_dir / "browser_required.csv", browser_required, ["source_id", "url", "reason"])
    write_csv(output_dir / "classified_urls_v3_3_1.csv", classified_rows, fields_common)
    write_csv(output_dir / "core_page_resolution_v3_3_1.csv", resolution_rows, ["evidence_url", "evidence_type", "resolved_master_id", "core_url", "resolution"])
    write_csv(output_dir / "unresolved_programme_families_v3_3_1.csv", unresolved_rows, ["url", "classification", "reason"])
    write_csv(output_dir / "master_candidates_v3_3_1.csv", master_rows, ["master_id", "scheme_name", "source_id", "record_kind", "core_url", "evidence_count"])
    write_csv(output_dir / "master_evidence_links_v3_3_1.csv", evidence_rows, ["master_id", "source_id", "url", "classification", "relationship"])
    write_csv(output_dir / "duplicate_merge_audit_v3_3_1.csv", duplicate_rows, ["master_id", "merged_key", "evidence_count"])
    write_csv(output_dir / "validated_catalogue_candidates_v3_3_1.csv", validated_rows, preview_fields + ["validation_issues"])
    write_csv(output_dir / "validation_review_queue_v3_3_1.csv", review_rows, preview_fields + ["validation_issues"])
    write_csv(output_dir / "rejected_candidates_v3_3_1.csv", rejected_rows, preview_fields + ["validation_issues", "rejection_reason"])

    classification_summary = dict(sorted(Counter(row["classification"] for row in classified_rows).items()))
    source_summary = {
        "run_id": run_id,
        "version": VERSION,
        "generated_at": utc_now(),
        "sources_processed": [source.source_id for source in sources],
        "requested_pages": len(fetch_rows) + len(failed_rows) + len(robots_denied),
        "successful_fetches": sum(1 for row in fetch_rows if int(row["status_code"]) < 400),
        "failed_fetches": len(failed_rows),
        "robots_denied": len(robots_denied),
        "redirects": len(redirects),
        "unique_discovered_urls": len(discovered),
        "html_candidates": sum(1 for row in fetch_rows if "html" in row["content_type"].lower()),
        "pdf_candidates": len(pdf_rows),
        "scheme_related_candidates": len(relevant),
        "pages_by_source": dict(sorted(Counter(row["source_id"] for row in fetch_rows).items())),
        "pages_by_domain": dict(sorted(Counter(canonical_host(row["final_url"], aliases) for row in fetch_rows).items())),
        "database_writes_performed": 0,
    }
    validation_summary = {
        "validated_new_scheme_programme_records": len(validated_rows),
        "review_required_records": len(review_rows),
        "rejected_records": len(rejected_rows),
        "existing_eligible_scheme_count": visible_unique_count(existing_preview_rows, main_scheme_kinds),
        "new_batch_1_eligible_scheme_count": len(validated_rows),
        "cumulative_preview_scheme_count": visible_unique_count(preview_rows, main_scheme_kinds),
        "application_call_count": visible_application_call_count(preview_rows),
        "duplicate_master_ids": final_counts.duplicate_master_ids,
        "duplicate_records_merged": len(duplicate_rows) + preview_duplicate_count,
    }
    write_json(output_dir / "source_summary.json", source_summary)
    write_json(output_dir / "classification_summary_v3_3_1.json", classification_summary)
    write_json(output_dir / "validation_summary_v3_3_1.json", validation_summary)
    write_json(preview_dir / "batch_1_catalogue_summary_v3_3_1.json", validation_summary)
    checkpoint = {
        "version": VERSION,
        "run_id": run_id,
        "status": "BATCH_1_COMPLETE_WAITING_FOR_APPROVAL",
        "completed_steps": [
            "discovery", "url_classification", "core_page_resolution", "master_grouping",
            "deterministic_core_extraction", "strict_validation", "preview_catalogue"
        ],
        "network_requests_performed": source_summary["requested_pages"],
        "database_writes_performed": 0,
        "next_step": "await_batch_2_approval",
        "preview_catalogue": str(preview_path),
    }
    write_json(output_dir / "checkpoint.json", checkpoint)
    return output_dir
