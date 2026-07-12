from __future__ import annotations

import csv
import gzip
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import clean, low, stable_id
from .profile import DepartmentProfile


DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d")


@dataclass(frozen=True)
class ExtractedCall:
    values: dict[str, str]
    evidence: list[dict[str, str]]


def parse_date(value: str) -> date | None:
    text = clean(value)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def calculate_status(opening: str, closing: str, today: date) -> tuple[str, str]:
    opened = parse_date(opening)
    closed = parse_date(closing)
    if closed and closed < today:
        return "CLOSED", "Official closing date is before the verification date."
    if opened and opened > today:
        return "UPCOMING", "Official opening date is after the verification date."
    if opened and closed and opened <= today <= closed:
        return "OPEN", "Verification date falls within the official opening and closing dates."
    return "STATUS_UNVERIFIED", "Official dates are incomplete; status cannot be asserted."


def trusted_url(url: str, allowed_domains: set[str]) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


class ParentResolver:
    def __init__(self, profile: DepartmentProfile) -> None:
        self.profile = profile

    @staticmethod
    def _identity_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", low(value)).strip()

    def resolve(self, title: str, detail_text: str = "") -> tuple[str, str, str]:
        title_value = self._identity_text(title)
        detail_value = self._identity_text(detail_text)
        matches: list[tuple[int, dict[str, Any], str]] = []
        for entity in self.profile.entities:
            for alias in entity.get("aliases", []):
                alias_text = self._identity_text(alias)
                title_match = alias_text and re.search(rf"(?<!\w){re.escape(alias_text)}(?!\w)", title_value)
                detail_allowed = entity.get("entity_type") != "PERMANENT_SUPPORT_PROGRAMME"
                detail_match = detail_allowed and len(alias_text) >= 8 and re.search(rf"(?<!\w){re.escape(alias_text)}(?!\w)", detail_value)
                if title_match or detail_match:
                    matches.append(((10000 if title_match else 0) + len(alias_text), entity, alias))
        if not matches:
            return "", "UNRESOLVED", "No authoritative programme alias occurs in the call evidence."
        matches.sort(key=lambda item: item[0], reverse=True)
        entity = matches[0][1]
        resolution = "UMBRELLA_ONLY_REVIEW" if entity.get("entity_type") == "UMBRELLA_PROGRAMME" else "ALIAS_MATCH"
        return str(entity["master_id"]), resolution, f"Matched authoritative alias: {matches[0][2]}."


class CallRelevanceClassifier:
    def __init__(self, profile: DepartmentProfile) -> None:
        rules = profile.call_relevance
        self.strong = [low(item) for item in rules.get("strong_terms", [])]
        self.beneficiary = [low(item) for item in rules.get("beneficiary_terms", [])]
        self.exclusions = [low(item) for item in rules.get("exclusion_terms", [])]
        self.review_terms = [low(item) for item in rules.get("review_terms", [])]

    def classify(self, title: str, detail_text: str, parent_id: str) -> tuple[str, str]:
        title_text = low(title)
        evidence_text = low(f"{title} {detail_text[:12000]}")
        strong_hits = [term for term in self.strong if term in title_text]
        beneficiary_hits = [term for term in self.beneficiary if term in evidence_text]
        exclusion_hits = [term for term in self.exclusions if term in title_text]
        review_hits = [term for term in self.review_terms if term in evidence_text]
        if exclusion_hits and not strong_hits:
            return "NOT_STARTUP_RELEVANT", f"Excluded call type: {', '.join(exclusion_hits[:4])}."
        if strong_hits:
            return "STARTUP_RELEVANT", f"Explicit title evidence: {', '.join(strong_hits[:6])}."
        if parent_id and beneficiary_hits:
            return "STARTUP_RELEVANT", f"Known programme parent and beneficiary evidence: {', '.join(beneficiary_hits[:6])}."
        if beneficiary_hits:
            return "REVIEW_REQUIRED", f"Beneficiary evidence without a resolved programme: {', '.join(beneficiary_hits[:6])}."
        if review_hits:
            return "REVIEW_REQUIRED", f"Company/MSME eligibility evidence requires startup applicability review: {', '.join(review_hits[:6])}."
        return "NOT_STARTUP_RELEVANT", "No explicit startup, innovator, entrepreneur or incubator beneficiary evidence."


class CallSectorClassifier:
    def __init__(self, profile: DepartmentProfile) -> None:
        self.rules = profile.payload.get("sector_phrases", [])

    def classify(self, title: str, detail_text: str) -> tuple[str, str, str, str]:
        def collect(value: str) -> list[tuple[str, str]]:
            matches: list[tuple[str, str]] = []
            for rule in self.rules:
                hits = [phrase for phrase in rule.get("phrases", []) if low(phrase) in value]
                if hits:
                    matches.append((str(rule["sector"]), hits[0]))
            return matches

        matches = collect(low(title))
        if not matches:
            matches = collect(low(detail_text[:12000]))
        unique: list[tuple[str, str]] = []
        for match in matches:
            if match[0] not in {item[0] for item in unique}:
                unique.append(match)
        if not unique:
            return "UNKNOWN", "", "", "No explicit sector phrase was found in official call evidence."
        primary = unique[0][0]
        secondary = "; ".join(item[0] for item in unique[1:])
        scope = "SPECIFIC" if len(unique) == 1 else "MULTI_SECTOR"
        evidence = "; ".join(f"{sector}: {phrase}" for sector, phrase in unique)
        return scope, primary, secondary, f"Official call evidence contains {evidence}."


def infer_call_type(title: str) -> str:
    value = low(title)
    if "deadline" in value and ("extend" in value or "extension" in value):
        return "DEADLINE_EXTENSION"
    if "challenge" in value or "hackathon" in value:
        return "CHALLENGE"
    if "award" in value:
        return "AWARD_CALL"
    if "application" in value or "applications" in value:
        return "CALL_FOR_APPLICATIONS"
    if "proposal" in value or "proposals" in value:
        return "CALL_FOR_PROPOSALS"
    return "OPPORTUNITY_NOTICE"


def infer_applicant_layer(title: str, detail_text: str) -> tuple[str, str]:
    value = low(f"{title} {detail_text[:12000]}")
    intermediary_terms = (
        "becoming prayas centre", "become program executive partner", "becoming program executive partner",
        "eligible incubators", "eligible tbi", "incubators may apply", "institutions may apply",
        "establishing technology business incubator", "itbi call for proposals", "inclusive technology business incubators",
    )
    direct_terms = (
        "startups may apply", "start-ups may apply", "innovators may apply", "entrepreneurs may apply",
        "application from startups", "applications from startups", "support startups", "student startup",
    )
    hits = [term for term in intermediary_terms if term in value]
    if hits:
        return "INTERMEDIARY_IMPLEMENTER", f"Official evidence indicates an intermediary applicant: {', '.join(hits[:4])}."
    hits = [term for term in direct_terms if term in value]
    if hits:
        return "DIRECT_BENEFICIARY", f"Official evidence indicates a startup/innovator applicant: {', '.join(hits[:4])}."
    return "UNKNOWN", "The direct applicant layer requires curation."


class SnapshotCallExtractor:
    """Expands official DST call index tables into individual call observations."""

    def __init__(self, profile: DepartmentProfile, today: date | None = None) -> None:
        self.profile = profile
        self.today = today or date.today()
        self.parents = ParentResolver(profile)
        self.relevance = CallRelevanceClassifier(profile)
        self.sectors = CallSectorClassifier(profile)

    @staticmethod
    def _read_snapshot(path: Path) -> str:
        if path.suffix.casefold() == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _page_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return clean(main.get_text(" ", strip=True))

    def _detail_text_index(self, rows: list[dict[str, str]], crawl_root: Path) -> dict[str, str]:
        output: dict[str, str] = {}
        html_by_url: dict[str, str] = {}
        for row in rows:
            url = clean(row.get("final_url"))
            snapshot = clean(row.get("snapshot_path"))
            if not url or not snapshot:
                continue
            path = crawl_root / snapshot
            if path.exists():
                page_html = self._read_snapshot(path)
                key = url.rstrip("/")
                html_by_url[key] = page_html
                output[key] = self._page_text(page_html)
        external_available = any((urlparse(url).hostname or "").casefold() != "dst.gov.in" for url in output)
        if not external_available:
            return output
        for url, page_html in html_by_url.items():
            if (urlparse(url).hostname or "").casefold() != "dst.gov.in" or "/callforproposals" not in urlparse(url).path:
                continue
            soup = BeautifulSoup(page_html, "html.parser")
            main = soup.find("main") or soup.find("article") or soup.body or soup
            linked_text: list[str] = []
            for anchor in main.find_all("a", href=True):
                target = urljoin(url, anchor["href"]).split("#", 1)[0].rstrip("/")
                if target != url and target in output and trusted_url(target, self.profile.official_domains):
                    linked_text.append(output[target])
            if linked_text:
                output[url] = clean(f"{output[url]} {' '.join(linked_text)}")
        return output

    @staticmethod
    def _headers(table: Any) -> list[str]:
        first_row = table.find("tr")
        return [low(cell.get_text(" ", strip=True)) for cell in first_row.find_all(["th", "td"])] if first_row else []

    def extract(self, crawled_pages_csv: Path, crawl_root: Path) -> list[ExtractedCall]:
        with crawled_pages_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            pages = list(csv.DictReader(handle))
        detail_text = self._detail_text_index(pages, crawl_root)
        extracted: dict[str, ExtractedCall] = {}
        for page in pages:
            source_url = clean(page.get("final_url"))
            path = urlparse(source_url).path.rstrip("/")
            if path not in {"/call-for-proposals", "/archive-call-for-proposals"}:
                continue
            snapshot = crawl_root / clean(page.get("snapshot_path"))
            if not snapshot.exists():
                continue
            soup = BeautifulSoup(self._read_snapshot(snapshot), "html.parser")
            for table in soup.find_all("table"):
                headers = self._headers(table)
                if "title" not in headers or not ({"start date", "end date"} & set(headers)):
                    continue
                for row_number, tr in enumerate(table.find_all("tr")[1:], start=1):
                    cells = tr.find_all("td")
                    if not cells:
                        continue
                    values = {headers[index]: clean(cell.get_text(" ", strip=True)) for index, cell in enumerate(cells) if index < len(headers)}
                    title = values.get("title", "")
                    if not title:
                        continue
                    title_cell = cells[headers.index("title")]
                    detail_anchor = title_cell.find("a", href=True)
                    detail_url = urljoin(source_url, detail_anchor["href"]) if detail_anchor else ""
                    links = [urljoin(source_url, anchor["href"]) for anchor in tr.find_all("a", href=True)]
                    official_links = [url for url in links if trusted_url(url, self.profile.official_domains)]
                    attachment_url = next((url for url in official_links if url != detail_url), "")
                    opening = values.get("start date", values.get("opening date", ""))
                    closing = values.get("end date", values.get("closing date", ""))
                    status, status_reason = calculate_status(opening, closing, self.today)
                    page_detail = detail_text.get(detail_url.rstrip("/"), "") if detail_url else ""
                    parent_id, parent_resolution, parent_reason = self.parents.resolve(title, page_detail)
                    relevance, relevance_reason = self.relevance.classify(title, page_detail, parent_id)
                    layer, layer_reason = infer_applicant_layer(title, page_detail)
                    if relevance == "STARTUP_RELEVANT" and layer == "INTERMEDIARY_IMPLEMENTER":
                        relevance = "STARTUP_ECOSYSTEM_CALL"
                        relevance_reason = f"{layer_reason} This is related to startup support but is not a direct founder opportunity."
                    sector_scope, primary_sector, secondary_sectors, sector_reason = self.sectors.classify(title, page_detail)
                    call_id = stable_id("dst_call", detail_url or source_url, title, opening, closing)
                    record = {
                        "call_id": call_id,
                        "department_code": "DST",
                        "call_title": title,
                        "record_role": "CALL_INSTANCE",
                        "call_type": infer_call_type(title),
                        "applicant_layer": layer,
                        "applicant_layer_reason": layer_reason,
                        "parent_master_id": parent_id,
                        "parent_resolution": parent_resolution,
                        "parent_resolution_reason": parent_reason,
                        "opening_date": opening,
                        "closing_date": closing,
                        "application_status": status,
                        "status_reason": status_reason,
                        "startup_relevance": relevance,
                        "startup_relevance_reason": relevance_reason,
                        "sector_scope": sector_scope,
                        "primary_sector": primary_sector,
                        "secondary_sectors": secondary_sectors,
                        "sector_reason": sector_reason,
                        "sector_review_required": str(sector_scope == "UNKNOWN").lower(),
                        "detail_url": detail_url,
                        "attachment_url": attachment_url,
                        "source_container_url": source_url,
                        "source_container_role": "CALL_INDEX_CONTAINER",
                        "source_row_number": str(row_number),
                        "source_fetched_at": clean(page.get("fetched_at")),
                    }
                    evidence = [
                        {"field_name": "call_title", "source_url": source_url, "evidence_text": title},
                        {"field_name": "opening_date", "source_url": source_url, "evidence_text": opening},
                        {"field_name": "closing_date", "source_url": source_url, "evidence_text": closing},
                    ]
                    if page_detail:
                        evidence.append({"field_name": "detail_text", "source_url": detail_url, "evidence_text": page_detail[:1500]})
                    extracted[call_id] = ExtractedCall(record, evidence)

        page_by_url = {clean(page.get("final_url")).rstrip("/"): page for page in pages}
        entity_by_code = self.profile.entity_by_code
        for monitor in self.profile.payload.get("monitored_call_pages", []):
            page_url = clean(monitor.get("page_url")).rstrip("/")
            page = page_by_url.get(page_url)
            if not page:
                continue
            snapshot = crawl_root / clean(page.get("snapshot_path"))
            if not snapshot.exists():
                continue
            page_html = self._read_snapshot(snapshot)
            soup = BeautifulSoup(page_html, "html.parser")
            main = soup.find("main") or soup.find("article") or soup.body or soup
            required_apply_text = low(monitor.get("required_apply_text", "apply"))
            apply_anchor = next(
                (
                    anchor for anchor in main.find_all("a", href=True)
                    if required_apply_text in low(anchor.get_text(" ", strip=True))
                    and trusted_url(urljoin(page_url, anchor["href"]), self.profile.official_domains)
                ),
                None,
            )
            if not apply_anchor:
                continue
            application_url = urljoin(page_url, apply_anchor["href"])
            title = clean(monitor.get("call_title"))
            parent = entity_by_code.get(clean(monitor.get("parent_code")), {})
            page_detail = self._page_text(page_html)
            sector_scope, primary_sector, secondary_sectors, sector_reason = self.sectors.classify(title, page_detail)
            call_id = stable_id("dst_call", page_url, title)
            fetched_at = clean(page.get("fetched_at"))
            record = {
                "call_id": call_id,
                "department_code": "DST",
                "call_title": title,
                "record_role": "CALL_INSTANCE",
                "call_type": "OPEN_FUNDING_CALL",
                "applicant_layer": "DIRECT_BENEFICIARY",
                "applicant_layer_reason": "A monitored official programme page exposes a direct application route.",
                "parent_master_id": clean(parent.get("master_id")),
                "parent_resolution": "MONITORED_OFFICIAL_RELATIONSHIP",
                "parent_resolution_reason": f"Monitored source profile maps this opportunity to {clean(parent.get('canonical_name'))}.",
                "opening_date": "",
                "closing_date": "",
                "application_status": "OPEN",
                "status_basis": "EXPLICIT_OFFICIAL_APPLY_ROUTE",
                "status_evidence": f"Official page exposes {clean(apply_anchor.get_text(' ', strip=True))} linking to {application_url}.",
                "status_reason": "Open status is based on a current official application control; no closing date is published.",
                "last_verified_at": fetched_at,
                "startup_relevance": "REVIEW_REQUIRED",
                "startup_relevance_reason": "The monitored application page requires field-level beneficiary verification before automatic publication.",
                "implementing_entity": clean(monitor.get("implementing_entity")),
                "implementation_role": "SECOND_LEVEL_FUND_MANAGER",
                "sector_scope": sector_scope,
                "primary_sector": primary_sector,
                "secondary_sectors": secondary_sectors,
                "sector_reason": sector_reason,
                "sector_review_required": str(sector_scope == "UNKNOWN").lower(),
                "detail_url": page_url,
                "application_url": application_url,
                "attachment_url": "",
                "source_container_url": page_url,
                "source_container_role": "MONITORED_OFFICIAL_APPLICATION_PAGE",
                "source_row_number": "",
                "source_fetched_at": fetched_at,
            }
            evidence = [
                {"field_name": "application_status", "source_url": page_url, "evidence_text": record["status_evidence"]},
                {"field_name": "application_url", "source_url": page_url, "evidence_text": application_url},
                {"field_name": "detail_text", "source_url": page_url, "evidence_text": page_detail[:1500]},
            ]
            extracted[call_id] = ExtractedCall(record, evidence)
        return sorted(extracted.values(), key=lambda item: (item.values["closing_date"], item.values["call_title"]))
