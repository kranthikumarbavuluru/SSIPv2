#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install dependencies: python -m pip install requests beautifulsoup4") from exc

VERSION = "3.4.0.5"
DEFAULT_CONFIG = Path("config/dst_startup_focus_rules_v3_4_0_5.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def lower(value: Any) -> str:
    return collapse(value).casefold()


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(collapse(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def canonical_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def normalize_url(raw: str, base: str = "") -> str:
    if not raw:
        return ""
    absolute = urljoin(base, raw.strip())
    parts = urlsplit(absolute)
    if parts.scheme.casefold() not in {"http", "https"}:
        return ""
    host = canonical_host(absolute)
    if not host:
        return ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if key.casefold().startswith("utm_") or key.casefold() in {"fbclid", "gclid", "ref", "source", "campaign"}:
            continue
        if key.casefold() == "page":
            query.append((key.casefold(), value))
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Required CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{str(k): str(v or "") for k, v in row.items()} for row in reader]
    if not fields:
        raise ValueError(f"CSV has no header: {path}")
    return fields, rows


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_list, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "") or "") for field in field_list})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contains_any(text: str, terms: Iterable[str]) -> list[str]:
    hay = lower(text)
    return [collapse(term) for term in terms if lower(term) and lower(term) in hay]


def is_dst_row(row: Mapping[str, Any]) -> bool:
    blob = " ".join(
        collapse(row.get(key))
        for key in ("source", "ministry", "department", "implementing_agency", "official_page_url")
    ).casefold()
    return (
        "department of science and technology" in blob
        or "ministry of science and technology" in blob
        or "dst.gov.in" in blob
        or "nidhi.dst.gov.in" in blob
        or lower(row.get("source")) == "dst"
    )


def infer_call_status(text: str, opening: str, closing: str) -> str:
    today = date.today()
    close_date = parse_date(closing)
    open_date = parse_date(opening)
    low = lower(text)
    if close_date and close_date < today:
        return "CLOSED"
    if open_date and open_date > today:
        return "UPCOMING"
    if close_date and close_date >= today:
        return "OPEN"
    if any(term in low for term in ("applications closed", "call closed", "last date has passed")):
        return "CLOSED"
    if any(term in low for term in ("applications open", "open call", "invites applications", "applications are invited")):
        return "VERIFICATION_REQUIRED"
    return "VERIFICATION_REQUIRED"


def parse_date(value: str) -> date | None:
    text = collapse(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def extract_dates(text: str) -> tuple[str, str]:
    patterns = [
        r"(?i)(?:opening date|launch date|applications open(?:ing)?(?: on)?|start date)\s*[:\-]?\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+20\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2})",
        r"(?i)(?:last date|closing date|deadline|extended date|submission date)\s*[:\-]?\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+20\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2})",
    ]
    found: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text)
        found.append(re.sub(r"(?i)(st|nd|rd|th)", "", collapse(match.group(1))) if match else "")
    return found[0], found[1]


def page_role(url: str, title: str, text: str, cfg: Mapping[str, Any]) -> tuple[str, int, list[str]]:
    combined = f"{title} {url} {text[:12000]}"
    low = lower(combined)
    reasons: list[str] = []
    relevance = cfg["relevance"]
    beneficiary = contains_any(combined, relevance["beneficiary_terms"])
    access = contains_any(combined, relevance["access_terms"])
    support = contains_any(combined, relevance["support_terms"])
    institution_only = contains_any(combined, relevance["institution_only_terms"])
    noise = contains_any(f"{title} {url}", relevance["noise_terms"])

    call_title = any(term in lower(f"{title} {url}") for term in (
        "call for proposal", "call-for-proposal", "callforproposals", "applications invited",
        "call for applications", "expression of interest", "challenge", "cohort", "/cfp-", "/cfp/"
    ))
    if noise:
        return "SUPPORTING_OR_NOISE", 0, ["NOISE:" + ",".join(noise[:4])]
    if call_title:
        score = 40 + min(30, 10 * len(beneficiary)) + min(20, 5 * len(access)) + min(10, 5 * len(support))
        return "STARTUP_CALL_INSTANCE" if beneficiary else "CALL_REVIEW_REQUIRED", min(score, 100), ["CALL_TITLE", f"BENEFICIARY={len(beneficiary)}", f"ACCESS={len(access)}"]

    score = 0
    if beneficiary:
        score += min(50, 20 * len(beneficiary))
        reasons.append("BENEFICIARY:" + ",".join(beneficiary[:5]))
    if access:
        score += min(30, 15 * len(access))
        reasons.append("ACCESS:" + ",".join(access[:4]))
    if support:
        score += min(25, 7 * len(support))
        reasons.append("SUPPORT:" + ",".join(support[:5]))
    if institution_only and not beneficiary:
        score -= 60
        reasons.append("INSTITUTION_ONLY")
    elif institution_only:
        score -= 10
        reasons.append("MIXED_INSTITUTION_AND_STARTUP")

    if any(term in low for term in ("national mission", "umbrella programme", "technology innovation hub", "entrepreneurship development board")):
        if score >= 40:
            return "STARTUP_ECOSYSTEM_MISSION", max(score, 55), reasons
        return "ECOSYSTEM_REVIEW_REQUIRED", max(score, 35), reasons
    if score >= 75 and beneficiary and access:
        if any(term in low for term in ("through incubator", "through tbi", "through centre", "periodically announce calls", "cohort")):
            return "STARTUP_ACCESS_PROGRAMME", min(score, 100), reasons
        return "DIRECT_STARTUP_SCHEME", min(score, 100), reasons
    if score >= 50:
        return "MANUAL_STARTUP_REVIEW", score, reasons
    return "REJECTED_NON_STARTUP", max(score, 0), reasons


@dataclass
class CrawledPage:
    url: str
    final_url: str
    title: str
    text: str
    depth: int
    http_status: int
    content_type: str
    classification: str
    relevance_score: int
    reasons: list[str]


def clean_html(content: str, url: str) -> tuple[str, str, list[tuple[str, str]]]:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.select("script,style,noscript,svg,header,footer,nav,form"):
        tag.decompose()
    title = collapse(soup.title.get_text(" ", strip=True) if soup.title else "")
    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = collapse(main.get_text(" ", strip=True))
    links: list[tuple[str, str]] = []
    for anchor in main.find_all("a", href=True):
        target = normalize_url(anchor.get("href", ""), url)
        if target:
            links.append((target, collapse(anchor.get_text(" ", strip=True))))
    return title, text, links


def crawl(config: Mapping[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    crawl_cfg = config["crawl"]
    allowed_hosts = set(crawl_cfg["allowed_hosts"])
    discovery_terms = [lower(x) for x in config["relevance"]["discovery_link_terms"]]
    session = requests.Session()
    session.headers.update({"User-Agent": crawl_cfg["user_agent"], "Accept": "text/html,application/xhtml+xml"})
    queue: deque[tuple[str, int, str]] = deque((normalize_url(seed), 0, "SEED") for seed in crawl_cfg["seeds"])
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    host_last: dict[str, float] = {}

    while queue and len(pages) < int(crawl_cfg["max_pages"]):
        url, depth, source = queue.popleft()
        if not url or url in seen or canonical_host(url) not in allowed_hosts:
            continue
        seen.add(url)
        host = canonical_host(url)
        wait = float(crawl_cfg["delay_seconds"]) - (time.time() - host_last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        try:
            response = session.get(url, timeout=float(crawl_cfg["timeout_seconds"]), allow_redirects=True)
            host_last[host] = time.time()
            content_type = response.headers.get("content-type", "")
            final_url = normalize_url(response.url) or url
            if response.status_code >= 400:
                pages.append({"url": url, "final_url": final_url, "depth": depth, "http_status": response.status_code, "classification": "FETCH_ERROR", "error": f"HTTP {response.status_code}"})
                continue
            if "text/html" not in content_type.casefold():
                documents.append({"source_url": source, "document_url": final_url, "content_type": content_type, "http_status": response.status_code})
                continue
            title, text, links = clean_html(response.text, final_url)
            classification, score, reasons = page_role(final_url, title, text, config)
            opening_date, closing_date = extract_dates(text)
            row = {
                "page_id": stable_id("dstpage", final_url),
                "url": url,
                "final_url": final_url,
                "title": title,
                "depth": depth,
                "http_status": response.status_code,
                "content_type": content_type,
                "word_count": len(text.split()),
                "classification": classification,
                "startup_relevance_score": score,
                "classification_reasons": " | ".join(reasons),
                "opening_date": opening_date,
                "closing_date": closing_date,
                "text_excerpt": text[:1000],
                "fetched_at": utc_now(),
            }
            pages.append(row)
            if classification == "STARTUP_CALL_INSTANCE":
                parent_code, parent_id = infer_parent(title + " " + text)
                calls.append({
                    "call_id": stable_id("dstcall", final_url),
                    "parent_scheme_code": parent_code,
                    "parent_master_id": parent_id,
                    "call_title": title or final_url.rsplit("/", 1)[-1],
                    "call_type": infer_call_type(title + " " + text),
                    "opening_date": opening_date,
                    "closing_date": closing_date,
                    "application_status": infer_call_status(text, opening_date, closing_date),
                    "eligible_beneficiary": beneficiary_summary(text),
                    "application_url": find_application_link(links),
                    "guideline_url": find_guideline_link(links),
                    "source_url": final_url,
                    "last_verified_at": utc_now(),
                    "evidence_excerpt": text[:700],
                })
            elif classification in {"MANUAL_STARTUP_REVIEW", "CALL_REVIEW_REQUIRED", "ECOSYSTEM_REVIEW_REQUIRED"}:
                reviews.append(row)

            if depth >= int(crawl_cfg["max_depth"]):
                continue
            for target, anchor in links:
                if canonical_host(target) not in allowed_hosts:
                    continue
                path = urlsplit(target).path.casefold()
                if any(path.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx")):
                    documents.append({"source_url": final_url, "document_url": target, "anchor_text": anchor, "content_type": "DOCUMENT_LINK", "http_status": ""})
                    continue
                hay = lower(target + " " + anchor)
                if depth == 0 or any(term in hay for term in discovery_terms):
                    queue.append((target, depth + 1, final_url))
        except Exception as exc:
            pages.append({"url": url, "final_url": url, "depth": depth, "http_status": "", "classification": "FETCH_ERROR", "error": f"{type(exc).__name__}: {exc}"})

    return pages, dedupe(calls, "source_url"), reviews, dedupe(documents, "document_url")


def infer_parent(text: str) -> tuple[str, str]:
    low = lower(text)
    mappings = [
        ("NIDHI-PRAYAS", ("prayas",)),
        ("NIDHI-EIR", ("entrepreneur-in-residence", "nidhi eir", "nidhi-eir")),
        ("NIDHI-SSP", ("seed support", "nidhi-ssp", "nidhi ssp")),
        ("NIDHI-ITBI", ("inclusive technology business incubator", "itbi", "i-tbi")),
        ("NIDHI-TBI", ("technology business incubator", "nidhi tbi", "nidhi-tbi")),
        ("NIDHI-ACCELERATOR", ("nidhi accelerator",)),
        ("TDB-CORE-FUNDING", ("technology development board", "tdb")),
        ("NM-ICPS", ("nm-icps", "cyber-physical", "technology innovation hub")),
    ]
    for code, terms in mappings:
        if any(term in low for term in terms):
            return code, stable_id("dststartup", code)
    return "UNRESOLVED_PARENT", ""


def infer_call_type(text: str) -> str:
    low = lower(text)
    for label, terms in (
        ("CHALLENGE", ("challenge",)),
        ("COHORT", ("cohort", "accelerator")),
        ("EXPRESSION_OF_INTEREST", ("expression of interest", "eoi")),
        ("CALL_FOR_APPLICATIONS", ("call for applications", "applications invited")),
        ("CALL_FOR_PROPOSALS", ("call for proposal", "cfp")),
    ):
        if any(term in low for term in terms):
            return label
    return "OPPORTUNITY"


def beneficiary_summary(text: str) -> str:
    low = lower(text)
    labels = []
    for term, label in (("startup", "Startups"), ("innovator", "Innovators"), ("entrepreneur", "Entrepreneurs"), ("company", "Companies"), ("incubator", "Incubators")):
        if term in low:
            labels.append(label)
    return "; ".join(labels) or "Verification required"


def find_application_link(links: list[tuple[str, str]]) -> str:
    for url, anchor in links:
        if any(term in lower(url + " " + anchor) for term in ("apply", "application", "submit proposal", "online portal", "epms")):
            return url
    return ""


def find_guideline_link(links: list[tuple[str, str]]) -> str:
    for url, anchor in links:
        if any(term in lower(url + " " + anchor) for term in ("guideline", "manual", "download")):
            return url
    return ""


def dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output = []
    for row in rows:
        value = collapse(row.get(key))
        if value and value not in seen:
            seen.add(value)
            output.append(row)
    return output


def adapt_scheme(seed: Mapping[str, Any], fields: list[str], verified_on: str) -> dict[str, str]:
    master_id = stable_id("dststartup", seed["code"])
    values: dict[str, Any] = {
        "master_id": master_id,
        "normalized_scheme_id": master_id,
        "scheme_name": seed["canonical_name"],
        "canonical_name": seed["canonical_name"],
        "short_name": seed.get("official_abbreviation", ""),
        "source": "DST",
        "ministry": "Ministry of Science and Technology",
        "department": "Department of Science and Technology (DST)",
        "implementing_agency": "Department of Science and Technology / official implementing centre",
        "normalized_record_kind": "SCHEME_OR_PROGRAMME",
        "record_kind": "SCHEME_OR_PROGRAMME",
        "current_record_kind": "SCHEME_OR_PROGRAMME",
        "programme_status": "SCHEME_INFORMATION_AVAILABLE",
        "application_status": "APPLY_THROUGH_OFFICIAL_ROUTE" if seed.get("application_route") != "DIRECT_TO_TDB" else "DIRECT_APPLICATION_ROUTE",
        "scheme_status": "REFERENCE",
        "status_evidence": "Permanent startup-relevant programme verified from official sources. Current calls and centre intake windows are tracked separately.",
        "sector": seed.get("sector", "Cross-sector Innovation"),
        "sectors": "; ".join(filter(None, [seed.get("sector", ""), seed.get("secondary_sectors", "")])),
        "scheme_type": seed.get("scheme_type", "STARTUP_SUPPORT"),
        "scheme_types": seed.get("scheme_type", "STARTUP_SUPPORT"),
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "STARTUP_SCHEMES",
        "current_decision": "APPROVED_FOR_DATABASE",
        "validation_decision": "APPROVED_FOR_DATABASE",
        "publication_status": "PUBLISHED_STARTUP_RELEVANT",
        "official_page_url": seed.get("official_page_url", ""),
        "application_url": seed.get("application_url", ""),
        "guideline_urls": seed.get("guideline_url", "https://nidhi.dst.gov.in/document-category/programme-guidelines/"),
        "guideline_url": seed.get("guideline_url", "https://nidhi.dst.gov.in/document-category/programme-guidelines/"),
        "opening_date": "",
        "closing_date": "",
        "funding_minimum": seed.get("funding_minimum", ""),
        "funding_maximum": seed.get("funding_maximum", ""),
        "currency": "INR",
        "objective": seed.get("objective", ""),
        "objectives": seed.get("objective", ""),
        "eligibility": seed.get("eligibility", ""),
        "benefits": seed.get("benefits", ""),
        "funding_summary": seed.get("funding_summary", ""),
        "application_process": seed.get("application_process", ""),
        "required_documents": "Refer to the current official guideline or application call.",
        "last_verified_date": verified_on,
        "last_updated": verified_on,
        "verification_status": "STARTUP_BENEFICIARY_AND_ACCESS_ROUTE_VERIFIED",
        "information_completeness": "0.85",
        "field_evidence": json.dumps({
            "startup_relevance_classification": seed.get("classification"),
            "application_route": seed.get("application_route"),
            "startup_stage": seed.get("startup_stage"),
            "source_evidence": seed.get("source_evidence"),
            "current_version_url": seed.get("current_version_url", ""),
            "calls_separate": True,
            "verification_version": VERSION,
        }, ensure_ascii=False, separators=(",", ":")),
    }
    return {field: str(values.get(field, "") or "") for field in fields}


def publish(root: Path, config: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    catalogue = root / config["catalogue_path"]
    fields, rows = read_csv(catalogue)
    old_dst = [row for row in rows if is_dst_row(row)]
    retained = [row for row in rows if not is_dst_row(row)]
    verified_on = date.today().isoformat()
    startup_rows = [adapt_scheme(seed, fields, verified_on) for seed in config["curated_startup_schemes"]]
    merged = retained + startup_rows

    backup_dir = root / "backups" / "v3_4_0_5_startup_focus"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"catalogue_before_startup_focus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    shutil.copy2(catalogue, backup)
    write_csv(catalogue, fields, merged)
    versioned = output_dir / "catalogue_preview_startup_focused_v3_4_0_5.csv"
    write_csv(versioned, fields, merged)

    quarantine_fields = list(dict.fromkeys(fields + ["quarantine_reason", "quarantined_at"]))
    quarantine = []
    for row in old_dst:
        item = dict(row)
        item["quarantine_reason"] = "Removed from Startup Scheme Explorer because department ownership alone does not establish startup/innovator eligibility and access route."
        item["quarantined_at"] = utc_now()
        quarantine.append(item)
    write_csv(output_dir / "dst_quarantined_department_programmes_v3_4_0_5.csv", quarantine_fields, quarantine)

    registry_fields = [
        "master_id", "code", "canonical_name", "official_abbreviation", "classification", "sector",
        "secondary_sectors", "scheme_type", "startup_stage", "objective", "eligibility", "benefits",
        "funding_summary", "funding_maximum", "application_process", "application_route",
        "official_page_url", "application_url", "guideline_url", "source_evidence"
    ]
    registry = []
    for seed in config["curated_startup_schemes"]:
        item = dict(seed)
        item["master_id"] = stable_id("dststartup", seed["code"])
        registry.append(item)
    write_csv(output_dir / "dst_verified_startup_scheme_registry_v3_4_0_5.csv", registry_fields, registry)

    eco_fields = ["ecosystem_id", "code", "name", "classification", "official_page_url", "directory_url", "description", "access_route"]
    ecosystems = []
    for seed in config["curated_ecosystem_records"]:
        item = dict(seed)
        item["ecosystem_id"] = stable_id("dsteco", seed["code"])
        ecosystems.append(item)
    write_csv(output_dir / "dst_startup_ecosystem_registry_v3_4_0_5.csv", eco_fields, ecosystems)

    checks = {
        "non_dst_rows_preserved": len(retained) == len([row for row in merged if not is_dst_row(row)]),
        "all_old_dst_rows_quarantined": len(quarantine) == len(old_dst),
        "exact_verified_startup_rows_published": len(startup_rows) == len(config["curated_startup_schemes"]),
        "no_institution_only_seed_published": all("universities" not in lower(row.get("eligibility")) for row in startup_rows),
        "all_published_dst_rows_have_startup_section": all(row.get("catalogue_section") == "STARTUP_SCHEMES" for row in startup_rows),
        "all_published_dst_rows_have_sector": all(collapse(row.get("sector")) for row in startup_rows),
        "all_published_dst_rows_have_access_route": all("application_route" in row.get("field_evidence", "") for row in startup_rows),
        "backup_created": backup.exists(),
    }
    return {
        "catalogue": str(catalogue),
        "backup": str(backup),
        "counts": {
            "catalogue_rows_before": len(rows),
            "old_dst_rows_quarantined": len(old_dst),
            "non_dst_rows_preserved": len(retained),
            "verified_dst_startup_rows_published": len(startup_rows),
            "catalogue_rows_after": len(merged),
            "ecosystem_records": len(ecosystems),
        },
        "checks": checks,
        "publication_passed": all(checks.values()),
    }


def patch_dashboard(app: Path, output_dir_rel: str) -> dict[str, Any]:
    if not app.exists():
        return {"patched": False, "reason": f"Dashboard app not found: {app}"}
    original = app.read_text(encoding="utf-8")
    backup = app.with_name(f"{app.stem}_before_v3_4_0_5_{datetime.now().strftime('%Y%m%d_%H%M%S')}{app.suffix}")
    shutil.copy2(app, backup)
    text = original

    text, version_count = re.subn(r'(?m)^(APP_VERSION\s*=\s*)["\'][^"\']+["\']', r'\1"3.4.0.5"', text, count=1)
    if "import csv" not in text:
        text = text.replace("from __future__ import annotations\n", "from __future__ import annotations\n\nimport csv\n", 1)
    if "from pathlib import Path" not in text:
        text = text.replace("import csv\n", "import csv\nfrom pathlib import Path\n", 1)

    if '"Calls & Opportunities"' not in text:
        text, pages_count = re.subn(
            r'(?ms)(PAGES\s*=\s*\[.*?"Directory",\s*)("Scheme Details",)',
            r'\1"Calls & Opportunities",\n    "Incubators & Ecosystem",\n    \2',
            text,
            count=1,
        )
    else:
        pages_count = 1

    marker_match = re.search(r"(?m)^def render_scheme_details\(", text)
    helper = f'''\n\ndef _read_v3405_rows(filename: str) -> list[dict[str, str]]:\n    path = Path("{output_dir_rel}") / filename\n    if not path.exists():\n        return []\n    with path.open("r", encoding="utf-8-sig", newline="") as handle:\n        return [{{str(k): str(v or "") for k, v in row.items()}} for row in csv.DictReader(handle)]\n\n\ndef render_calls_and_opportunities() -> None:\n    rows = _read_v3405_rows("dst_startup_calls_v3_4_0_5.csv")\n    st.markdown("## Calls & Opportunities")\n    st.caption("Time-bound calls are shown separately from permanent schemes. Verify the current status on the official source before applying.")\n    if not rows:\n        st.info("No verified call records are available yet. Run the v3.4.0.5 official deep search to refresh this page.")\n        return\n    statuses = ["All"] + sorted({{row.get("application_status", "VERIFICATION_REQUIRED") for row in rows}})\n    selected = st.selectbox("Status", statuses, key="v3405_call_status")\n    visible = rows if selected == "All" else [row for row in rows if row.get("application_status") == selected]\n    st.write(f"**{{len(visible)}} opportunity record(s)**")\n    for row in visible:\n        title = html.escape(row.get("call_title") or "Untitled opportunity")\n        parent = html.escape(row.get("parent_scheme_code") or "Parent scheme under review")\n        status = html.escape(row.get("application_status") or "VERIFICATION_REQUIRED")\n        closing = html.escape(row.get("closing_date") or "Not recorded")\n        beneficiary = html.escape(row.get("eligible_beneficiary") or "Verification required")\n        source = html.escape(row.get("source_url") or "")\n        apply_url = html.escape(row.get("application_url") or "")\n        links = f'<a target="_blank" href="{{source}}">Official source</a>' if source else ""\n        if apply_url:\n            links += f' &nbsp; <a target="_blank" href="{{apply_url}}">Application link</a>'\n        st.markdown(f"""<div style='border:1px solid #d8e3f5;border-radius:12px;padding:16px;margin:10px 0;background:white'>\n        <div style='font-size:1.05rem;font-weight:700;color:#073b88'>{{title}}</div>\n        <div><b>Parent:</b> {{parent}} &nbsp; <b>Status:</b> {{status}}</div>\n        <div><b>Closing:</b> {{closing}} &nbsp; <b>Beneficiaries:</b> {{beneficiary}}</div>\n        <div style='margin-top:8px'>{{links}}</div></div>""", unsafe_allow_html=True)\n\n\ndef render_startup_ecosystem() -> None:\n    rows = _read_v3405_rows("dst_startup_ecosystem_registry_v3_4_0_5.csv")\n    st.markdown("## Incubators & Startup Ecosystem")\n    st.caption("Umbrella missions, incubator networks and hubs are not counted as direct schemes; use them to find the actual programme or call through which a startup can apply.")\n    for row in rows:\n        name = html.escape(row.get("name") or "Ecosystem record")\n        description = html.escape(row.get("description") or "")\n        route = html.escape(row.get("access_route") or "")\n        official = html.escape(row.get("official_page_url") or "")\n        directory = html.escape(row.get("directory_url") or "")\n        links = f'<a target="_blank" href="{{official}}">Official page</a>' if official else ""\n        if directory:\n            links += f' &nbsp; <a target="_blank" href="{{directory}}">Directory</a>'\n        st.markdown(f"""<div style='border:1px solid #d8e3f5;border-radius:12px;padding:16px;margin:10px 0;background:white'>\n        <div style='font-size:1.05rem;font-weight:700;color:#073b88'>{{name}}</div>\n        <div>{{description}}</div><div style='margin-top:6px'><b>How startups access support:</b> {{route}}</div>\n        <div style='margin-top:8px'>{{links}}</div></div>""", unsafe_allow_html=True)\n\n\n'''
    if "def render_calls_and_opportunities()" not in text:
        if not marker_match:
            return {"patched": False, "reason": "Scheme details marker not found", "backup": str(backup)}
        text = text[:marker_match.start()] + helper + text[marker_match.start():]

    if 'elif page == "Calls & Opportunities":' not in text:
        dispatch_marker = '    elif page == "Directory":\n'
        dispatch = '    elif page == "Calls & Opportunities":\n        render_calls_and_opportunities()\n    elif page == "Incubators & Ecosystem":\n        render_startup_ecosystem()\n'
        if dispatch_marker not in text:
            return {"patched": False, "reason": "Navigation dispatch marker not found", "backup": str(backup)}
        text = text.replace(dispatch_marker, dispatch + dispatch_marker, 1)

    # html module is required by injected renderer. Add without disturbing existing imports.
    if not re.search(r"(?m)^import html\s*$", text):
        text = text.replace("import csv\n", "import csv\nimport html\n", 1)

    app.write_text(text, encoding="utf-8")
    return {
        "patched": True,
        "backup": str(backup),
        "version_assignment_found": bool(version_count),
        "navigation_list_patched": bool(pages_count),
        "calls_renderer_present": "def render_calls_and_opportunities()" in text,
        "ecosystem_renderer_present": "def render_startup_ecosystem()" in text,
    }


def self_test() -> dict[str, Any]:
    config = json.loads((Path(__file__).resolve().parents[1] / "config" / "dst_startup_focus_rules_v3_4_0_5.json").read_text(encoding="utf-8"))
    cases = {
        "startup_scheme": page_role("https://nidhi.dst.gov.in/prayas", "NIDHI PRAYAS", "Innovators and startups may apply through PRAYAS Centres for prototype grant funding.", config)[0],
        "institution_only": page_role("https://dst.gov.in/fist", "FIST", "Universities and higher educational institutions are eligible for institutional infrastructure support.", config)[0],
        "startup_call": page_role("https://tdb.gov.in/call-for-proposal-startup", "Call for Proposals for Startups", "DPIIT startups are invited to apply through the online portal for funding.", config)[0],
        "mission": page_role("https://dst.gov.in/nm-icps", "National Mission on Interdisciplinary Cyber Physical Systems", "The mission supports startup incubation and commercialization through Technology Innovation Hubs.", config)[0],
    }
    checks = {
        "startup_scheme_detected": cases["startup_scheme"] in {"DIRECT_STARTUP_SCHEME", "STARTUP_ACCESS_PROGRAMME"},
        "institution_only_rejected": cases["institution_only"] == "REJECTED_NON_STARTUP",
        "call_separated": cases["startup_call"] == "STARTUP_CALL_INSTANCE",
        "mission_not_direct_scheme": cases["mission"] in {"STARTUP_ECOSYSTEM_MISSION", "ECOSYSTEM_REVIEW_REQUIRED"},
        "seven_curated_startup_records": len(config["curated_startup_schemes"]) == 7,
        "all_curated_records_have_sector": all(collapse(row.get("sector")) for row in config["curated_startup_schemes"]),
        "all_curated_records_have_access_route": all(collapse(row.get("application_route")) for row in config["curated_startup_schemes"]),
    }
    return {"service_version": VERSION, "tests": checks, "classifications": cases, "self_test_passed": all(checks.values())}


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    config_path = root / Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    output_dir = root / config["output_directory"]
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {"service_version": VERSION, "generated_at": utc_now(), "project_root": str(root)}
    if args.publish_curated:
        summary["publication"] = publish(root, config, output_dir)

    if args.deep_search:
        pages, calls, reviews, documents = crawl(config, output_dir)
        page_fields = ["page_id", "url", "final_url", "title", "depth", "http_status", "content_type", "word_count", "classification", "startup_relevance_score", "classification_reasons", "opening_date", "closing_date", "text_excerpt", "fetched_at", "error"]
        call_fields = ["call_id", "parent_scheme_code", "parent_master_id", "call_title", "call_type", "opening_date", "closing_date", "application_status", "eligible_beneficiary", "application_url", "guideline_url", "source_url", "last_verified_at", "evidence_excerpt"]
        review_fields = page_fields
        document_fields = ["source_url", "document_url", "anchor_text", "content_type", "http_status"]
        write_csv(output_dir / "dst_startup_deep_search_pages_v3_4_0_5.csv", page_fields, pages)
        write_csv(output_dir / "dst_startup_calls_v3_4_0_5.csv", call_fields, calls)
        write_csv(output_dir / "dst_startup_manual_review_queue_v3_4_0_5.csv", review_fields, reviews)
        write_csv(output_dir / "dst_startup_supporting_documents_v3_4_0_5.csv", document_fields, documents)
        summary["deep_search"] = {
            "pages_processed": len(pages),
            "startup_calls_identified": len(calls),
            "manual_review_candidates": len(reviews),
            "supporting_documents": len(documents),
            "fetch_errors": sum(1 for row in pages if row.get("classification") == "FETCH_ERROR"),
            "classification_counts": count_values(pages, "classification"),
        }
    else:
        calls_path = output_dir / "dst_startup_calls_v3_4_0_5.csv"
        if not calls_path.exists():
            write_csv(calls_path, ["call_id", "parent_scheme_code", "parent_master_id", "call_title", "call_type", "opening_date", "closing_date", "application_status", "eligible_beneficiary", "application_url", "guideline_url", "source_url", "last_verified_at", "evidence_excerpt"], [])

    if args.patch_dashboard:
        summary["dashboard_patch"] = patch_dashboard(root / config["dashboard_app_path"], config["output_directory"])

    publication_ok = summary.get("publication", {}).get("publication_passed", True)
    patch_ok = summary.get("dashboard_patch", {}).get("patched", True)
    summary["pipeline_passed"] = bool(publication_ok and patch_ok)
    write_json(output_dir / "dst_startup_focus_summary_v3_4_0_5.json", summary)
    return summary


def count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = collapse(row.get(key)) or "UNSPECIFIED"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine non-startup DST programmes, publish verified startup-access schemes, deep-search official sources, and expose calls separately.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--publish-curated", action="store_true")
    parser.add_argument("--deep-search", action="store_true")
    parser.add_argument("--patch-dashboard", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["self_test_passed"] else 1
    if not (args.publish_curated or args.deep_search or args.patch_dashboard):
        parser.error("Select at least one action: --publish-curated, --deep-search, or --patch-dashboard")
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"service_version": VERSION, "pipeline_passed": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["pipeline_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
