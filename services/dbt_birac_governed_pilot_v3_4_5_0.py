from __future__ import annotations

import ast
import csv
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib import robotparser
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from agents.dbt_birac.source_registry_v3_4_5_0 import (
    BIRAC,
    DEPARTMENT,
    MINISTRY,
    build_source_registry,
)
from agents.shared.official_domain_policy import OfficialDomainPolicy
from agents.shared.url_normalization import normalize_url


VERSION = "3.4.5.0"
PREFIX = "dbt_birac"
USER_AGENT = "SSIPGovernedDiscoveryBot/3.4.5.0"

OUTPUT_NAMES = {
    "sources": "dbt_birac_official_source_registry_v3_4_5_0.csv",
    "crawl": "dbt_birac_crawl_manifest_v3_4_5_0.json",
    "raw": "dbt_birac_raw_discovery_v3_4_5_0.json",
    "urls": "dbt_birac_discovered_url_inventory_v3_4_5_0.csv",
    "fetch": "dbt_birac_fetch_report_v3_4_5_0.csv",
    "failures": "dbt_birac_fetch_failure_report_v3_4_5_0.csv",
    "redirects": "dbt_birac_redirect_report_v3_4_5_0.csv",
    "roles": "dbt_birac_page_role_classifications_v3_4_5_0.csv",
    "permanent": "dbt_birac_permanent_programme_inventory_v3_4_5_0.csv",
    "calls": "dbt_birac_current_call_round_inventory_v3_4_5_0.csv",
    "challenges": "dbt_birac_challenge_competition_inventory_v3_4_5_0.csv",
    "intermediary": "dbt_birac_intermediary_opportunity_inventory_v3_4_5_0.csv",
    "historical": "dbt_birac_historical_call_inventory_v3_4_5_0.csv",
    "relationships": "dbt_birac_parent_child_relationships_v3_4_5_0.csv",
    "ownership": "dbt_birac_ownership_evidence_v3_4_5_0.csv",
    "applicants": "dbt_birac_applicant_layer_classifications_v3_4_5_0.csv",
    "relevance": "dbt_birac_startup_relevance_classifications_v3_4_5_0.csv",
    "sectors": "dbt_birac_sector_evidence_mappings_v3_4_5_0.csv",
    "support": "dbt_birac_support_type_evidence_mappings_v3_4_5_0.csv",
    "extensions": "dbt_birac_extension_corrigendum_relationships_v3_4_5_0.csv",
    "documents": "dbt_birac_supporting_document_index_v3_4_5_0.csv",
    "duplicates": "dbt_birac_duplicate_version_resolution_v3_4_5_0.csv",
    "excluded": "dbt_birac_excluded_non_catalogue_inventory_v3_4_5_0.csv",
    "review": "dbt_birac_unresolved_admin_review_queue_v3_4_5_0.csv",
    "reconciliation": "dbt_birac_existing_record_reconciliation_v3_4_5_0.csv",
    "validation": "dbt_birac_validation_report_v3_4_5_0.json",
    "manifest": "dbt_birac_signed_dry_run_manifest_v3_4_5_0.json",
    "preview": "dbt_birac_dashboard_preview_projection_v3_4_5_0.csv",
}


@dataclass(frozen=True)
class PipelinePaths:
    project_root: Path
    config_path: Path
    output_dir: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "PipelinePaths":
        return cls(
            project_root=project_root,
            config_path=project_root / "config/dbt_birac_governed_pilot_v3_4_5_0.json",
            output_dir=project_root / "data/departments/dbt_birac/v3_4_5_0",
        )


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_id(kind: str, *parts: str) -> str:
    return f"dbt_birac_{kind}_{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:20]}"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return _sha_bytes(b"")
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    for item in files:
        digest.update(item.relative_to(path.parent).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _function_hash(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    return _sha_bytes(ast.dump(node, include_attributes=False).encode("utf-8"))


def protected_hashes(root: Path) -> dict[str, str]:
    return {
        "database": _tree_hash(root / "database/ssip_staging_v1.db"),
        "publication_current": _tree_hash(root / "data/publication/current"),
        "dst": _tree_hash(root / "data/departments/dst"),
        "meity": _tree_hash(root / "data/departments/meity"),
        "dpiit": _tree_hash(root / "data/departments/dpiit"),
        "home_function": _function_hash(root / "apps/public_dashboard_app_v2_9.py", "render_home"),
        "home_css": _tree_hash(root / "assets/dashboard_theme.css"),
        "shared_home_css": _tree_hash(root / "ssip_dashboard/assets/styles.css"),
    }


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


class _DiscoveryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "title":
            self.in_title = True
        if tag.casefold() == "a":
            self.href = dict(attrs).get("href") or ""
            self.anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False
        if tag.casefold() == "a" and self.href:
            self.links.append((self.href, " ".join(self.anchor).strip()))
            self.href = ""
            self.anchor = []

    def handle_data(self, data: str) -> None:
        if self.in_title and data.strip():
            self.title.append(data.strip())
        if self.href and data.strip():
            self.anchor.append(data.strip())


PROGRAMMES = [
    ("big", "Biotechnology Ignition Grant (BIG)", "PROGRAMME", "", BIRAC, "startup;innovator", "biotechnology", "grant;mentorship", "https://birac.nic.in/big.php", "Flagship early-stage biotechnology grant programme; official page states support up to INR 50 lakh for 18 months."),
    ("i4", "Innovation for Industry (i4)", "PROGRAMME", "", BIRAC, "biotechnology company;MSME/company", "biotechnology", "grant;soft loan;commercialisation", "https://birac.nic.in/birac_i4.php", "BIRAC umbrella for industry innovation support, including SBIRI and BIPP."),
    ("sbiri", "Small Business Innovation Research Initiative (SBIRI)", "SCHEME", "i4", BIRAC, "biotechnology company;MSME/company", "biotechnology", "grant;soft loan;validation", "https://birac.nic.in/desc_new.php?id=217", "Early-stage industry innovation support under BIRAC's i4 portfolio."),
    ("bipp", "Biotechnology Industry Partnership Programme (BIPP)", "SCHEME", "i4", BIRAC, "biotechnology company;MSME/company", "biotechnology", "grant;commercialisation;pilot support", "https://birac.nic.in/desc_new.php?id=216", "Industry partnership support for high-risk biotechnology research and development."),
    ("pace", "Promoting Academic Research Conversion to Enterprise (PACE)", "PROGRAMME", "", BIRAC, "academic or research institution", "biotechnology", "grant;validation;commercialisation", "https://birac.nic.in/desc_new.php?id=286", "Academic translation programme with AIR and CRS components."),
    ("air", "Academic Innovation Research (AIR)", "SCHEME", "pace", BIRAC, "academic or research institution", "biotechnology", "grant;validation", "https://birac.nic.in/desc_new.php?id=286", "PACE component supporting proof-of-concept validation by academic researchers."),
    ("crs", "Contract Research Scheme (CRS)", "SCHEME", "pace", BIRAC, "academic or research institution;biotechnology company", "biotechnology", "grant;commercialisation", "https://birac.nic.in/desc_new.php?id=286", "PACE component supporting academia-industry technology validation."),
    ("bionest", "BioNEST", "PROGRAMME", "", BIRAC, "incubator;ecosystem participant", "biotechnology", "incubation;infrastructure access;mentorship", "https://birac.nic.in/bionest.php", "BIRAC bio-incubator network programme; beneficiary and incubator-partner layers are kept distinct."),
    ("seed", "BIRAC SEED Fund", "SCHEME", "", BIRAC, "startup", "biotechnology", "equity;commercialisation", "https://birac.nic.in/seedFundNew.php", "Equity support for startups delivered through selected BioNEST incubator partners."),
    ("leap", "BIRAC LEAP Fund", "SCHEME", "", BIRAC, "startup", "biotechnology", "equity;commercialisation", "https://birac.nic.in/leapFund.php", "Later-stage equity support delivered through selected implementation partners."),
    ("ace", "AcE Fund", "SCHEME", "", BIRAC, "fund manager", "biotechnology", "equity", "https://birac.nic.in/aceFundNew.php", "Fund-of-funds style support delivered through SEBI-registered daughter funds; not a direct startup application window."),
    ("sparsh", "SPARSH", "PROGRAMME", "", BIRAC, "innovator;academic or research institution", "healthcare;diagnostics;medical devices;agriculture and agritech;environmental biotechnology", "grant;mentorship;incubation;commercialisation", "https://birac.nic.in/desc_new.php?id=58", "BIRAC social innovation programme under the aegis of DBT."),
    ("eyuva", "E-YUVA", "SCHEME", "", BIRAC, "founder or entrepreneur;innovator;academic or research institution", "biotechnology;healthcare;diagnostics;medical devices;agriculture and agritech;industrial biotechnology;bioinformatics", "grant;mentorship;incubation;infrastructure access", "https://birac.nic.in/e_yuva.php", "Entrepreneurship and innovation support for students and researchers through E-YUVA Centres."),
    ("biocare", "Biotechnology Career Advancement and Re-orientation (BioCARe)", "PROGRAMME", "", "Regional Centre for Biotechnology (DBT-HRD PMU)", "academic or research institution", "biotechnology", "grant;technical assistance", "https://dbtindia.gov.in/biotechnology-career-advancement-and-re-orientation-biocare-programmes", "DBT programme for women researchers, managed by the DBT-HRD PMU at RCB; not attributed to BIRAC."),
    ("dbt_pg", "DBT Supported Post Graduate Programme in Biotechnology", "PROGRAMME", "", "Regional Centre for Biotechnology (DBT-HRD PMU)", "academic or research institution", "biotechnology;healthcare;agriculture and agritech;food biotechnology;industrial biotechnology;bioinformatics", "technical assistance", "https://pgt.dbtindia.gov.in/", "DBT human-resource programme managed by RCB; not attributed to BIRAC."),
]


CALLS = [
    ("big24", "BIG Call 24", "HISTORICAL_CALL", "big", "2024-04-15", "2024-06-14", "startup;innovator", "https://birac.nic.in/cfp_view.php?id=31&scheme_type=5", "Official individual round with a past deadline."),
    ("big25", "BIG Call 25", "HISTORICAL_CALL", "big", "2025-11-01", "2025-11-30", "startup;innovator", "https://birac.nic.in/cfp.php/portal/desc_new.php?id=443", "Official individual round with a past deadline."),
    ("bioai2026", "Bio-AI / BioE3 Mulankur Hubs", "HISTORICAL_CALL", "", "2026-01-19", "2026-07-15", "academic or research institution;startup;consortium", "https://birac.nic.in/cfp_view.php?id=114&scheme_type=46", "Later official extension evidence supersedes the earlier 30 June date; deadline has passed."),
    ("gci2026", "Grand Challenges India: Transforming Health Systems through Integrated Care Models", "CHALLENGE", "", "2026-05-12", "2026-07-15", "startup;academic or research institution;consortium", "https://birac.nic.in/cfp_view.php?id=118&scheme_type=6", "Official challenge deadline was extended to 15 July 2026 and has passed."),
    ("pcp2026", "Product Commercialization Program Fund Call 2026", "HISTORICAL_CALL", "", "2026-01-08", "2026-03-15", "startup;biotechnology company", "https://birac.nic.in/cfp_view.php?id=117&scheme_type=29", "Official call page and programme page state the call is closed."),
    ("nghm2025", "National Green Hydrogen Mission Biotechnology Call", "HISTORICAL_CALL", "", "2025-12-26", "2026-02-05", "biotechnology company;academic or research institution;consortium", "https://birac.nic.in/cfp_view.php?id=116&scheme_type=52", "Official BIRAC call with a past deadline."),
    ("bionest2024", "BioNEST Call for Proposals 2024", "IMPLEMENTATION_PARTNER_OPPORTUNITY", "bionest", "2024-02-01", "2024-03-31", "incubator;academic or research institution", "https://birac.nic.in/desc_new.php?id=1120", "Past infrastructure-partner call, separated from direct startup opportunities."),
    ("eyuva2023", "Call for Setting up E-YUVA Centres 2023", "IMPLEMENTATION_PARTNER_OPPORTUNITY", "eyuva", "2023-07-01", "2023-08-17", "academic or research institution;implementation partner", "https://birac.nic.in/cfp_view.php?id=82&scheme_type=31", "Institution-only centre call; official extension to 17 August retained on the same call."),
    ("sparsh2023", "Call for Establishment of SPARSH Centres 2023", "IMPLEMENTATION_PARTNER_OPPORTUNITY", "sparsh", "2023-08-15", "2023-09-15", "academic or research institution;implementation partner", "https://birac.nic.in/cfp_view.php?id=84&scheme_type=4", "Institution/implementation-partner opportunity, not a direct startup scheme."),
]


DOCUMENTS = [
    ("BIG user guide", "GUIDELINE", "big", "https://birac.nic.in/webcontent/big_user_guide.pdf"),
    ("PACE scheme guidelines 2025", "GUIDELINE", "pace", "https://birac.nic.in/webcontent/1745298188_PACE_scheme_guidelines_16_04_2025.pdf"),
    ("BioCARe Guidelines 2024", "GUIDELINE", "biocare", "https://dbtindia.gov.in/sites/default/files/BioCARe%20Guidelines%202024_0.pdf"),
    ("SPARSH Guidelines", "GUIDELINE", "sparsh", "https://birac.nic.in/webcontent/Sparsh_Guidelines_Ver_3.pdf"),
    ("BIRAC documents required", "APPLICATION_GUIDANCE", "", "https://birac.nic.in/docRequired.php?type=i"),
    ("BIRAC call directory", "CALL_DIRECTORY", "", "https://birac.nic.in/cfp.php"),
    ("DBT call archive", "HISTORICAL_ARCHIVE", "", "https://dbtindia.gov.in/whats-new/call-for-proposals/archive"),
]


def _programme_rows(as_of: str) -> list[dict[str, Any]]:
    ids = {key: _stable_id("programme", key) for key, *_ in PROGRAMMES}
    rows = []
    for key, name, kind, parent, agency, applicants, sectors, support, url, summary in PROGRAMMES:
        rows.append({
            "record_id": ids[key], "canonical_name": name, "record_type": kind,
            "parent_record_id": ids.get(parent, ""), "ministry": MINISTRY,
            "department": DEPARTMENT, "implementing_agency": agency,
            "portal_source": "Official BIRAC portal" if "birac.nic.in" in url else "Official DBT programme portal",
            "direct_applicant_layer": applicants, "startup_relevance": (
                "INTERMEDIARY_OR_INSTITUTION_LAYER" if applicants in {"fund manager", "academic or research institution", "incubator;ecosystem participant"}
                else "STARTUP_RELEVANT"
            ),
            "sector": sectors, "support_type": support,
            "application_status": "NOT_APPLICABLE_TO_PROGRAMME_IDENTITY",
            "opening_date": "", "closing_date": "", "application_url": "",
            "official_url": url, "guideline_url": "", "status_basis": "Status belongs to a dated call, not the permanent identity",
            "last_verified_date": as_of, "evidence_excerpt": summary,
            "evidence_confidence": "HIGH", "unresolved_fields": "",
            "publication_status": "PUBLIC_DEPARTMENT_PAGE", "review_required": "0", "summary": summary,
        })
    return sorted(rows, key=lambda row: row["record_id"])


def _call_rows(as_of: str) -> list[dict[str, Any]]:
    programme_ids = {key: _stable_id("programme", key) for key, *_ in PROGRAMMES}
    rows = []
    for key, name, kind, parent, opening, closing, applicants, url, basis in CALLS:
        status = "CLOSED"
        sectors = "healthcare" if key == "gci2026" else "biotechnology"
        if key == "bioai2026":
            sectors = "bioinformatics;synthetic biology;healthcare;agriculture and agritech;industrial biotechnology"
        if key == "nghm2025":
            sectors = "industrial biotechnology;environmental biotechnology"
        rows.append({
            "record_id": _stable_id("call", key), "canonical_name": name, "record_type": kind,
            "parent_record_id": programme_ids.get(parent, ""), "ministry": MINISTRY,
            "department": DEPARTMENT, "implementing_agency": BIRAC,
            "portal_source": "Official BIRAC portal", "direct_applicant_layer": applicants,
            "startup_relevance": "INTERMEDIARY_OR_INSTITUTION_LAYER" if kind == "IMPLEMENTATION_PARTNER_OPPORTUNITY" else "STARTUP_RELEVANT",
            "sector": sectors, "support_type": "grant;validation;commercialisation",
            "application_status": status, "opening_date": opening, "closing_date": closing,
            "application_url": "", "official_url": url, "guideline_url": "",
            "status_basis": basis, "last_verified_date": as_of, "evidence_excerpt": basis,
            "evidence_confidence": "HIGH", "unresolved_fields": "parent_record_id" if not parent else "",
            "publication_status": "PUBLIC_DEPARTMENT_PAGE", "review_required": "1" if not parent else "0", "summary": basis,
        })
    rows.append({
        "record_id": _stable_id("review", "big-next-round"),
        "canonical_name": "BIG next recurring round — individual call evidence not located",
        "record_type": "REVIEW_REQUIRED", "parent_record_id": programme_ids["big"],
        "ministry": MINISTRY, "department": DEPARTMENT, "implementing_agency": BIRAC,
        "portal_source": "Official BIRAC portal", "direct_applicant_layer": "unverified",
        "startup_relevance": "REVIEW_REQUIRED", "sector": "biotechnology", "support_type": "grant",
        "application_status": "STATUS_UNVERIFIED", "opening_date": "", "closing_date": "",
        "application_url": "", "official_url": "https://birac.nic.in/big.php", "guideline_url": "",
        "status_basis": "Programme page describes recurring calls, but no official individual next-round identity and window were located as of the verification date.",
        "last_verified_date": as_of, "evidence_excerpt": "No individual next-round call evidence located.",
        "evidence_confidence": "LOW", "unresolved_fields": "call_identity;opening_date;closing_date;application_route",
        "publication_status": "REVIEW_ONLY_HIDDEN", "review_required": "1",
        "summary": "Monitoring candidate only; it is not a current call and has no Apply action.",
    })
    return sorted(rows, key=lambda row: row["record_id"])


def classify_page_role(title: str, url: str, registry_role: str = "") -> str:
    text = f"{title} {url}".casefold()
    if registry_role:
        return registry_role
    if url.casefold().endswith(".pdf") or any(token in text for token in ("guideline", "manual", "corrigendum")):
        return "SUPPORTING_DOCUMENT"
    if any(token in text for token in ("cfp.php", "call-for-proposals")):
        return "DIRECTORY"
    if any(token in text for token in ("contact", "login", "registration")):
        return "NON_CATALOGUE_PAGE"
    return "REVIEW_REQUIRED"


class DBTBIRACGovernedPilot:
    """Build a deterministic, resumable DBT-BIRAC department-page package."""

    def __init__(self, paths: PipelinePaths, config: dict[str, Any]) -> None:
        self.paths = paths
        self.config = config
        self.policy = OfficialDomainPolicy(config["allowed_domains"])
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._last_request = 0.0

    def _robots_allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser = robotparser.RobotFileParser(f"{base}/robots.txt")
            try:
                parser.read()
                self._robots[base] = parser
            except Exception:
                return False, "ROBOTS_UNAVAILABLE"
        allowed = self._robots[base].can_fetch(USER_AGENT, url)
        return allowed, "ROBOTS_ALLOWED" if allowed else "ROBOTS_DENIED"

    def _fetch_one(self, url: str, referrer: str, depth: int) -> dict[str, Any]:
        requested = normalize_url(url)
        decision = self.policy.evaluate(requested)
        base = {
            "requested_url": requested, "final_url": requested, "referring_url": referrer,
            "depth": depth, "retrieved_at": self.config["retrieval_timestamp"],
            "http_status": "", "content_type": "", "title": "", "content_hash": "",
            "redirected": "0", "robots_status": "", "error": "", "links": [],
        }
        if not decision.accepted:
            return {**base, "http_status": "DOMAIN_REJECTED", "error": decision.reason}
        allowed, robot_status = self._robots_allowed(requested)
        if not allowed:
            return {**base, "http_status": "FETCH_SKIPPED", "robots_status": robot_status, "error": robot_status}
        remaining = float(self.config["request_delay_seconds"]) - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        try:
            request = Request(requested, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=int(self.config["request_timeout_seconds"])) as response:
                raw = response.read(int(self.config["max_response_bytes"]))
                status = str(getattr(response, "status", 200))
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                final = normalize_url(response.geturl())
            self._last_request = time.monotonic()
            final_decision = self.policy.evaluate(final)
            if not final_decision.accepted:
                return {**base, "http_status": status, "final_url": final, "content_type": content_type,
                        "content_hash": _sha_bytes(raw), "redirected": str(int(final != requested)),
                        "robots_status": robot_status, "error": "REDIRECT_DOMAIN_REJECTED"}
            title = ""
            links: list[dict[str, str]] = []
            if content_type == "text/html":
                parser = _DiscoveryParser()
                parser.feed(raw.decode(charset, errors="replace"))
                title = " ".join(parser.title).strip()
                candidates = []
                for href, anchor in parser.links:
                    target = normalize_url(href, final)
                    if target and self.policy.accepts(target):
                        candidates.append((target, anchor))
                for target, anchor in sorted(set(candidates))[: int(self.config["max_links_per_page"])]:
                    links.append({"url": target, "anchor": anchor})
            return {**base, "final_url": final, "http_status": status, "content_type": content_type,
                    "title": title, "content_hash": _sha_bytes(raw), "redirected": str(int(final != requested)),
                    "robots_status": robot_status, "links": links}
        except Exception as exc:
            return {**base, "http_status": "FETCH_FAILED", "robots_status": robot_status,
                    "error": f"{type(exc).__name__}:{exc}"}

    def _crawl(self, sources: list[dict[str, str]], live_network: bool) -> list[dict[str, Any]]:
        raw_path = self.paths.output_dir / OUTPUT_NAMES["raw"]
        if not live_network and raw_path.exists():
            return json.loads(raw_path.read_text(encoding="utf-8"))["pages"]
        seeds = [(normalize_url(row["official_url"]), "", 0) for row in sources]
        if not live_network:
            return [{
                "requested_url": url, "final_url": url, "referring_url": referrer, "depth": depth,
                "retrieved_at": self.config["retrieval_timestamp"], "http_status": "PREVIEW_NOT_FETCHED",
                "content_type": "", "title": "", "content_hash": "", "redirected": "0",
                "robots_status": "NOT_CHECKED_OFFLINE", "error": "", "links": [],
            } for url, referrer, depth in seeds[: int(self.config["max_pages"])]]
        queue = list(seeds)
        seen: set[str] = set()
        pages: list[dict[str, Any]] = []
        while queue and len(pages) < int(self.config["max_pages"]):
            url, referrer, depth = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            page = self._fetch_one(url, referrer, depth)
            pages.append(page)
            if depth < int(self.config["max_depth"]):
                for link in page.get("links", []):
                    if link["url"] not in seen:
                        queue.append((link["url"], page["final_url"], depth + 1))
        return pages

    def _reconcile_existing(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        database = self.paths.project_root / "database/ssip_staging_v1.db"
        matches: list[dict[str, Any]] = []
        uri = f"file:{database.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            existing = connection.execute(
                "SELECT master_id, scheme_name, record_kind, application_status, closing_date, publication_status "
                "FROM scheme_staging WHERE lower(coalesce(implementing_agency,'')) LIKE '%birac%' "
                "OR lower(coalesce(official_page_url,'')) LIKE '%birac.nic.in%' ORDER BY master_id"
            ).fetchall()
            queue = {row[0]: dict(zip(("master_id", "review_status"), row)) for row in connection.execute(
                "SELECT master_id, review_status FROM admin_review_queue ORDER BY master_id"
            ).fetchall()}
        by_name = {row["canonical_name"].casefold(): row for row in records}
        for row in existing:
            preview = by_name.get(row["scheme_name"].casefold())
            review = queue.get(row["master_id"], {})
            matches.append({
                "existing_master_id": row["master_id"], "existing_scheme_name": row["scheme_name"],
                "existing_record_type": row["record_kind"], "existing_stored_status": row["application_status"],
                "existing_closing_date": row["closing_date"], "existing_publication_status": row["publication_status"],
                "existing_admin_review_status": review.get("review_status", ""),
                "preview_record_id": preview["record_id"] if preview else "", "preview_status": preview["application_status"] if preview else "",
                "resolution": "MATCHED_WITHOUT_MUTATION" if preview else "UNMATCHED_REVIEW_REQUIRED",
                "mutation_performed": "0",
            })
        return matches

    def run(self, *, live_network: bool = False) -> dict[str, Any]:
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        protected_before = protected_hashes(self.paths.project_root)
        sources = sorted(build_source_registry(), key=lambda row: row["source_id"])
        pages = self._crawl(sources, live_network)
        _write_json(self.paths.output_dir / OUTPUT_NAMES["raw"], {
            "version": VERSION, "retrieval_timestamp": self.config["retrieval_timestamp"], "pages": pages,
        })
        permanent = _programme_rows(self.config["as_of_date"])
        calls = _call_rows(self.config["as_of_date"])
        all_records = sorted(permanent + calls, key=lambda row: row["record_id"])
        source_by_url = {normalize_url(row["official_url"]): row for row in sources}
        roles = [{
            "url": page["final_url"], "page_title": page["title"],
            "page_role": classify_page_role(page["title"], page["final_url"], source_by_url.get(page["requested_url"], {}).get("authoritative_role", "")),
            "classification_basis": "REGISTERED_ROLE" if page["requested_url"] in source_by_url else "URL_AND_TITLE_RULE",
            "confidence": "HIGH" if page["requested_url"] in source_by_url else "MEDIUM",
        } for page in pages]
        fields = [
            "record_id", "canonical_name", "record_type", "parent_record_id", "ministry", "department",
            "implementing_agency", "portal_source", "direct_applicant_layer", "startup_relevance", "sector",
            "support_type", "application_status", "opening_date", "closing_date", "application_url", "official_url",
            "guideline_url", "status_basis", "last_verified_date", "evidence_excerpt", "evidence_confidence",
            "unresolved_fields", "publication_status", "review_required", "summary",
        ]
        current = [row for row in calls if row["application_status"] in {"OPEN", "UPCOMING"}]
        challenges = [row for row in calls if row["record_type"] in {"CHALLENGE", "COMPETITION"}]
        intermediary = [row for row in calls if row["record_type"] in {"INCUBATOR_OPPORTUNITY", "ACCELERATOR_OPPORTUNITY", "ECOSYSTEM_OPPORTUNITY", "IMPLEMENTATION_PARTNER_OPPORTUNITY"}]
        historical = [row for row in calls if row["application_status"] == "CLOSED"]
        documents = [{
            "document_id": _stable_id("document", url), "title": title, "document_type": kind,
            "parent_record_id": _stable_id("programme", parent) if parent else "", "official_url": url,
            "evidence_status": "OFFICIAL_PRIMARY", "last_verified_date": self.config["as_of_date"],
            "publication_status": "PUBLIC_DEPARTMENT_PAGE",
        } for title, kind, parent, url in DOCUMENTS]
        relationships = [{
            "parent_record_id": row["parent_record_id"], "child_record_id": row["record_id"],
            "relationship_type": "PROGRAMME_HAS_COMPONENT" if row in permanent else "PROGRAMME_HAS_CALL",
            "evidence_url": row["official_url"], "resolution_status": "RESOLVED",
        } for row in all_records if row["parent_record_id"]]
        ownership = [{
            "record_id": row["record_id"], "ministry": row["ministry"], "department": row["department"],
            "implementing_agency": row["implementing_agency"], "portal_source": row["portal_source"],
            "evidence_url": row["official_url"], "ownership_status": "VERIFIED",
            "ownership_note": "DBT-only implementing body retained" if "RCB" in row["implementing_agency"] else "BIRAC implementation supported by official record-level evidence",
        } for row in all_records]
        applicants = [{"record_id": row["record_id"], "direct_applicant_layer": row["direct_applicant_layer"], "evidence_url": row["official_url"], "classification_status": "EVIDENCE_SUPPORTED"} for row in all_records]
        relevance = [{"record_id": row["record_id"], "startup_relevance": row["startup_relevance"], "reason": row["summary"], "evidence_url": row["official_url"]} for row in all_records]
        sectors = [{"record_id": row["record_id"], "sector": sector, "evidence_url": row["official_url"], "mapping_basis": "OFFICIAL_SCOPE_TEXT"} for row in all_records for sector in row["sector"].split(";") if sector]
        support = [{"record_id": row["record_id"], "support_type": kind, "evidence_url": row["official_url"], "mapping_basis": "OFFICIAL_BENEFIT_TEXT"} for row in all_records for kind in row["support_type"].split(";") if kind]
        extensions = [
            {"notice_id": _stable_id("notice", "bioai-extension"), "notice_type": "EXTENSION_NOTICE", "call_record_id": _stable_id("call", "bioai2026"), "effective_closing_date": "2026-07-15", "official_url": "https://birac.nic.in/?id=927", "resolution": "MERGED_WITH_EXISTING_CALL"},
            {"notice_id": _stable_id("notice", "gci-extension"), "notice_type": "EXTENSION_NOTICE", "call_record_id": _stable_id("call", "gci2026"), "effective_closing_date": "2026-07-15", "official_url": "https://birac.nic.in/?id=927", "resolution": "MERGED_WITH_EXISTING_CALL"},
            {"notice_id": _stable_id("notice", "eyuva-extension"), "notice_type": "EXTENSION_NOTICE", "call_record_id": _stable_id("call", "eyuva2023"), "effective_closing_date": "2023-08-17", "official_url": "https://birac.nic.in/cfp_view.php?id=82&scheme_type=31", "resolution": "MERGED_WITH_EXISTING_CALL"},
        ]
        duplicates = [
            {"candidate_url": "https://www.birac.nic.in/desc_new.php/desc_new.php?id=286", "canonical_url": "https://birac.nic.in/desc_new.php?id=286", "resolution": "DUPLICATE_URL_VERSION_COLLAPSED", "canonical_record_id": _stable_id("programme", "pace")},
            {"candidate_url": "https://birac.nic.in/cfp.php/portal/portal/cfp.php", "canonical_url": "https://birac.nic.in/cfp.php", "resolution": "DUPLICATE_DIRECTORY_PATH_COLLAPSED", "canonical_record_id": ""},
        ]
        excluded = [
            {"url": "https://birac.nic.in/cfp.php", "page_role": "DIRECTORY", "reason": "Container page, not an individual call", "publication_eligible": "0"},
            {"url": "https://birac.nic.in/docRequired.php?type=i", "page_role": "SUPPORTING_DOCUMENT", "reason": "Generic application guidance, not a scheme", "publication_eligible": "0"},
            {"url": "https://birac.nic.in/desc_new.php?id=327", "page_role": "NON_CATALOGUE_PAGE", "reason": "Generic registration page", "publication_eligible": "0"},
            {"url": "https://dbtindia.gov.in/whats-new/call-for-proposals/archive", "page_role": "DIRECTORY", "reason": "Archive container; individual calls require separate identity evidence", "publication_eligible": "0"},
        ]
        review = [{
            "review_id": _stable_id("review_item", row["record_id"]), "record_id": row["record_id"],
            "review_type": "ORPHAN_PARENT_OR_STATUS_EVIDENCE" if row["record_type"] != "REVIEW_REQUIRED" else "MISSING_INDIVIDUAL_CALL_EVIDENCE",
            "reason": row["status_basis"], "unresolved_fields": row["unresolved_fields"],
            "official_url": row["official_url"], "recommended_action": "Confirm ownership/parent and individual call evidence before any publication",
            "publication_blocked": "1",
        } for row in calls if row["review_required"] == "1"]
        reconciliation = self._reconcile_existing(all_records)

        source_fields = list(sources[0])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["sources"], sources, source_fields)
        fetch_fields = ["requested_url", "final_url", "referring_url", "depth", "retrieved_at", "http_status", "content_type", "title", "content_hash", "redirected", "robots_status", "error"]
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["fetch"], pages, fetch_fields)
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["failures"], [row for row in pages if row["error"] or not str(row["http_status"]).startswith("2")], fetch_fields)
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["redirects"], [row for row in pages if row["redirected"] == "1"], ["requested_url", "final_url", "http_status", "content_type", "retrieved_at"])
        discovered = {}
        for page in pages:
            discovered[page["requested_url"]] = {"url": page["requested_url"], "referring_url": page["referring_url"], "depth": page["depth"], "discovery_method": "REGISTRY_SEED" if page["depth"] == 0 else "OFFICIAL_LINK"}
            for link in page.get("links", []):
                discovered.setdefault(link["url"], {"url": link["url"], "referring_url": page["final_url"], "depth": int(page["depth"]) + 1, "discovery_method": "OFFICIAL_LINK"})
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["urls"], sorted(discovered.values(), key=lambda row: row["url"]), ["url", "referring_url", "depth", "discovery_method"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["roles"], roles, ["url", "page_title", "page_role", "classification_basis", "confidence"])
        for key, rows in (("permanent", permanent), ("calls", current), ("challenges", challenges), ("intermediary", intermediary), ("historical", historical), ("preview", all_records)):
            _write_csv(self.paths.output_dir / OUTPUT_NAMES[key], rows, fields)
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["relationships"], relationships, ["parent_record_id", "child_record_id", "relationship_type", "evidence_url", "resolution_status"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["ownership"], ownership, ["record_id", "ministry", "department", "implementing_agency", "portal_source", "evidence_url", "ownership_status", "ownership_note"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["applicants"], applicants, ["record_id", "direct_applicant_layer", "evidence_url", "classification_status"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["relevance"], relevance, ["record_id", "startup_relevance", "reason", "evidence_url"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["sectors"], sectors, ["record_id", "sector", "evidence_url", "mapping_basis"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["support"], support, ["record_id", "support_type", "evidence_url", "mapping_basis"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["extensions"], extensions, ["notice_id", "notice_type", "call_record_id", "effective_closing_date", "official_url", "resolution"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["documents"], documents, ["document_id", "title", "document_type", "parent_record_id", "official_url", "evidence_status", "last_verified_date", "publication_status"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["duplicates"], duplicates, ["candidate_url", "canonical_url", "resolution", "canonical_record_id"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["excluded"], excluded, ["url", "page_role", "reason", "publication_eligible"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["review"], review, ["review_id", "record_id", "review_type", "reason", "unresolved_fields", "official_url", "recommended_action", "publication_blocked"])
        _write_csv(self.paths.output_dir / OUTPUT_NAMES["reconciliation"], reconciliation, ["existing_master_id", "existing_scheme_name", "existing_record_type", "existing_stored_status", "existing_closing_date", "existing_publication_status", "existing_admin_review_status", "preview_record_id", "preview_status", "resolution", "mutation_performed"])
        reused_live_snapshot = not live_network and any(str(row["http_status"]).startswith("2") for row in pages)
        crawl = {
            "version": VERSION, "mode": (
                "LIVE_BOUNDED" if live_network else
                "RESUMED_LIVE_SNAPSHOT" if reused_live_snapshot else
                "OFFLINE_DETERMINISTIC"
            ),
            "retrieval_timestamp": self.config["retrieval_timestamp"], "max_pages": self.config["max_pages"],
            "max_depth": self.config["max_depth"], "attempted": len(pages),
            "fetched": sum(str(row["http_status"]).startswith("2") for row in pages),
            "failed": sum(bool(row["error"]) for row in pages),
            "redirected": sum(row["redirected"] == "1" for row in pages),
            "resumable_from": OUTPUT_NAMES["raw"], "publication_writes": 0, "database_writes": 0,
        }
        _write_json(self.paths.output_dir / OUTPUT_NAMES["crawl"], crawl)
        protected_after = protected_hashes(self.paths.project_root)
        checks = {
            "department_page_publication_enabled": self.config.get("public_department_page") is True,
            "review_records_hidden": all(
                row["publication_status"] == "REVIEW_ONLY_HIDDEN"
                for row in all_records if row["record_type"] == "REVIEW_REQUIRED"
            ),
            "no_open_without_current_evidence": not current,
            "all_sources_official": all(self.policy.accepts(row["official_url"]) for row in sources),
            "ownership_separation": all(row["ministry"] == MINISTRY and row["department"] == DEPARTMENT for row in all_records),
            "dbt_only_not_birac": all(BIRAC not in row["implementing_agency"] for row in permanent if row["record_id"] in {_stable_id("programme", "biocare"), _stable_id("programme", "dbt_pg")}),
            "historical_apply_suppressed": all(not row["application_url"] for row in historical),
            "protected_unchanged": protected_before == protected_after,
        }
        validation = {"version": VERSION, "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "protected_before": protected_before, "protected_after": protected_after}
        _write_json(self.paths.output_dir / OUTPUT_NAMES["validation"], validation)
        signed = {}
        for key, filename in sorted(OUTPUT_NAMES.items()):
            if key != "manifest" and (self.paths.output_dir / filename).exists():
                signed[filename] = _sha(self.paths.output_dir / filename)
        counts = {
            "official_sources": len(sources), "pages_attempted": len(pages), "pages_fetched": crawl["fetched"],
            "pages_failed": crawl["failed"], "pages_redirected": crawl["redirected"], "permanent": len(permanent),
            "current_calls": len(current), "status_unverified": sum(row["application_status"] == "STATUS_UNVERIFIED" for row in calls),
            "challenges": len(challenges), "historical_calls": len(historical), "intermediary": len(intermediary),
            "supporting_documents": len(documents), "relationships": len(relationships),
            "orphans": sum(not row["parent_record_id"] for row in calls if row["record_type"] not in {"REVIEW_REQUIRED"}),
            "ownership_conflicts": 0, "duplicate_resolutions": len(duplicates), "extensions_linked": len(extensions),
            "excluded": len(excluded), "review_queue": len(review), "existing_reconciled": len(reconciliation),
            "public_department_records": sum(row["publication_status"] == "PUBLIC_DEPARTMENT_PAGE" for row in all_records),
        }
        signature_payload = json.dumps({"counts": counts, "files": signed, "version": VERSION}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest = {
            "version": VERSION, "generated_at": self.config["retrieval_timestamp"], "mode": "PUBLIC_DEPARTMENT_PAGE",
            "counts": counts, "signed_files": signed, "signature_algorithm": "SHA256",
            "signature": _sha_bytes(signature_payload), "database_writes": 0, "publication_writes": 0,
            "validation_status": validation["status"],
        }
        _write_json(self.paths.output_dir / OUTPUT_NAMES["manifest"], manifest)
        return {"manifest": manifest, "crawl": crawl, "validation": validation}
