from __future__ import annotations

from copy import deepcopy

from .dpiit_identity_rules_v3_4_1_0_1 import CANONICAL_DEPARTMENT


VERSION = "3.4.1.0.1"
MINISTRY = "Ministry of Commerce and Industry"
VERIFIED_DATE = "2026-07-12"

SOURCE_FIELDS = [
    "source_id", "source_name", "official_domain", "official_url", "source_type",
    "owning_ministry", "owning_department", "platform_host", "implementing_agency",
    "authority_status", "priority", "allowed_for_discovery", "ownership_evidence_url",
    "notes", "last_verified_date",
]


def _source(source_id: str, name: str, domain: str, url: str, source_type: str,
            *, host: str, agency: str = "", owner: str = CANONICAL_DEPARTMENT,
            evidence: str = "https://www.dpiit.gov.in/offerings/schemes-and-services/details/startup-india-initiative-MTMzYDNtQWa",
            priority: int = 90, notes: str = "") -> dict[str, str]:
    return {
        "source_id": source_id,
        "source_name": name,
        "official_domain": domain,
        "official_url": url,
        "source_type": source_type,
        "owning_ministry": MINISTRY,
        "owning_department": owner,
        "platform_host": host,
        "implementing_agency": agency,
        "authority_status": "OFFICIAL_PRIMARY",
        "priority": str(priority),
        "allowed_for_discovery": "1",
        "ownership_evidence_url": evidence,
        "notes": notes,
        "last_verified_date": VERIFIED_DATE,
    }


SOURCES = [
    _source("DPIIT-SRC-001", "DPIIT Schemes and Services", "dpiit.gov.in", "https://www.dpiit.gov.in/offerings", "OFFICIAL_SOURCE_DIRECTORY", host="DPIIT", priority=100),
    _source("DPIIT-SRC-002", "DPIIT Orders and Notices", "dpiit.gov.in", "https://www.dpiit.gov.in/documents/orders-and-notices", "NOTIFICATION_DIRECTORY", host="DPIIT", priority=98),
    _source("DPIIT-SRC-003", "DPIIT Gazette Notifications", "dpiit.gov.in", "https://www.dpiit.gov.in/documents/gazettes-notifications", "GAZETTE_DIRECTORY", host="DPIIT", priority=100),
    _source("DPIIT-SRC-004", "Startup India Portal", "startupindia.gov.in", "https://www.startupindia.gov.in/", "OFFICIAL_SOURCE_DIRECTORY", host="Startup India", priority=98, notes="Hosting alone does not prove DPIIT ownership of child pages."),
    _source("DPIIT-SRC-005", "Central Government Schemes for Startups", "startupindia.gov.in", "https://www.startupindia.gov.in/content/sih/en/government-schemes.html", "OFFICIAL_SOURCE_DIRECTORY", host="Startup India", owner="", evidence="", priority=96, notes="Cross-department directory; candidate ownership must be separately proven."),
    _source("DPIIT-SRC-006", "Startup India Programs and Challenges", "startupindia.gov.in", "https://www.startupindia.gov.in/content/sih/en/ams-application/application-listing.html", "OFFICIAL_SOURCE_DIRECTORY", host="Startup India", owner="", evidence="", priority=96, notes="Contains government and corporate hosts; ownership is candidate-specific."),
    _source("DPIIT-SRC-007", "Startup India Seed Fund Scheme", "seedfund.startupindia.gov.in", "https://seedfund.startupindia.gov.in/", "PROGRAMME_PORTAL", host="Startup India Seed Fund Scheme", agency="Invest India", priority=100),
    _source("DPIIT-SRC-008", "DPIIT Startup Recognition", "startupindia.gov.in", "https://www.startupindia.gov.in/content/sih/en/startupgov/startup_recognition_page.html", "APPLICATION_PORTAL", host="Startup India", priority=100, notes="Recognition service; not a funding scheme."),
    _source("DPIIT-SRC-009", "Startup India Fund of Funds 2.0", "startupindia.gov.in", "https://www.startupindia.gov.in/content/dam/startupindia/Startup-India-Fund-of-Funds-2.0-Scheme.pdf", "GUIDELINE_DIRECTORY", host="Startup India", agency="SIDBI", priority=100),
    _source("DPIIT-SRC-010", "Credit Guarantee Scheme for Startups", "startupindia.gov.in", "https://www.startupindia.gov.in/content/sih/en/credit-guarantee-scheme-for-startups.html", "PROGRAMME_PORTAL", host="Startup India", agency="National Credit Guarantee Trustee Company", priority=100),
    _source("DPIIT-SRC-011", "NCGTC CGSS Evidence", "ncgtc.in", "https://www.ncgtc.in/content/products/0/20250519/FAQ_CGSS_2025_2026_37fd554fb8.pdf", "IMPLEMENTING_AGENCY_PORTAL", host="NCGTC", agency="National Credit Guarantee Trustee Company", priority=96),
    _source("DPIIT-SRC-012", "Startup Intellectual Property Protection", "dpiit.gov.in", "https://www.dpiit.gov.in/offerings/schemes-and-services/details/sipp-gTM1UDNtQWa", "PROGRAMME_PORTAL", host="DPIIT", agency="Office of the Controller General of Patents, Designs and Trade Marks", priority=100),
    _source("DPIIT-SRC-013", "National Startup Awards", "startupindia.gov.in", "https://www.startupindia.gov.in/content/sih/en/nsa-landing.html", "PROGRAMME_PORTAL", host="Startup India", priority=100),
    _source("DPIIT-SRC-014", "Bharat Startup Grand Challenge", "startupindia.gov.in", "https://www.startupindia.gov.in/content/sih/en/bharat-startup-grand-challenge.html", "PROGRAMME_PORTAL", host="Startup India", agency="Invest India", priority=100),
    _source("DPIIT-SRC-015", "BHASKAR", "startupindia.gov.in", "https://www.startupindia.gov.in/bhaskar/about", "PROGRAMME_PORTAL", host="Startup India", agency="Invest India", priority=98),
    _source("DPIIT-SRC-016", "MAARG", "maarg.startupindia.gov.in", "https://maarg.startupindia.gov.in/", "PROGRAMME_PORTAL", host="MAARG", agency="Invest India", priority=98),
    _source("DPIIT-SRC-017", "Startup India Investor Connect", "investorconnect.startupindia.gov.in", "https://investorconnect.startupindia.gov.in/", "PROGRAMME_PORTAL", host="Startup India Investor Connect", agency="Invest India", priority=98),
    _source("DPIIT-SRC-018", "DPIIT Startup India Initiative", "dpiit.gov.in", "https://www.dpiit.gov.in/offerings/schemes-and-services/details/startup-india-initiative-MTMzYDNtQWa", "DEPARTMENT_PORTAL", host="DPIIT", priority=100),
    _source("DPIIT-SRC-019", "Startup India Recognition Application via NSWS", "nsws.gov.in", "https://www.nsws.gov.in/", "APPLICATION_PORTAL", host="National Single Window System", priority=90),
    _source("DPIIT-SRC-020", "eGazette Directory", "egazette.nic.in", "https://egazette.nic.in/", "GAZETTE_DIRECTORY", host="eGazette", owner="", evidence="", priority=85, notes="Supporting evidence; ownership must be proven from the issuing notification."),
]


CANDIDATE_SEEDS = [
    {"source_id": "DPIIT-SRC-001", "url": "https://www.dpiit.gov.in/offerings", "title": "Schemes and Services", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-002", "url": "https://www.dpiit.gov.in/documents/orders-and-notices", "title": "Orders and Notices", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-003", "url": "https://www.dpiit.gov.in/documents/gazettes-notifications?page=1", "title": "Gazettes Notifications", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-004", "url": "https://www.startupindia.gov.in/", "title": "Startup India", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-005", "url": "https://www.startupindia.gov.in/content/sih/en/government-schemes.html", "title": "Government Schemes for Startups", "ownership_proven": False},
    {"source_id": "DPIIT-SRC-006", "url": "https://www.startupindia.gov.in/content/sih/en/ams-application/application-listing.html", "title": "Startup India Programs", "ownership_proven": False},
    {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/", "title": "Startup India Seed Fund Scheme", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/faq", "title": "SISFS Frequently Asked Questions", "ownership_proven": True, "parent_name": "Startup India Seed Fund Scheme"},
    {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/?utm_source=test&src_trk=abc", "title": "Startup India Seed Fund Scheme", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/startup/login", "title": "SISFS Startup Application Login", "ownership_proven": True, "parent_name": "Startup India Seed Fund Scheme"},
    {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/final-notice-2026", "title": "Final Notice: last date for startups to apply under SISFS – 31 May 2026", "ownership_proven": True, "parent_name": "Startup India Seed Fund Scheme"},
    {"source_id": "DPIIT-SRC-008", "url": "https://www.startupindia.gov.in/content/sih/en/startupgov/startup_recognition_page.html", "title": "DPIIT Startup Recognition and Tax Exemption", "ownership_proven": True, "service_review": True},
    {"source_id": "DPIIT-SRC-009", "url": "https://www.startupindia.gov.in/content/dam/startupindia/Startup-India-Fund-of-Funds-2.0-Scheme.pdf", "title": "Startup India Fund of Funds 2.0 Scheme", "ownership_proven": True, "parent_name": "Fund of Funds for Startups"},
    {"source_id": "DPIIT-SRC-010", "url": "https://www.startupindia.gov.in/content/sih/en/credit-guarantee-scheme-for-startups.html", "title": "Credit Guarantee Scheme for Startups", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-011", "url": "https://www.ncgtc.in/content/products/0/20250519/FAQ_CGSS_2025_2026_37fd554fb8.pdf", "title": "Frequently Asked Questions – Credit Guarantee Scheme for Startups", "ownership_proven": True, "parent_name": "Credit Guarantee Scheme for Startups"},
    {"source_id": "DPIIT-SRC-012", "url": "https://www.dpiit.gov.in/offerings/schemes-and-services/details/sipp-gTM1UDNtQWa", "title": "Scheme for Facilitating Startups Intellectual Property Protection (SIPP)", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-013", "url": "https://www.startupindia.gov.in/content/sih/en/nsa-landing.html", "title": "National Startup Awards", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-013", "url": "https://www.startupindia.gov.in/content/sih/en/nsa2025.html", "title": "National Startup Awards 5.0", "ownership_proven": True, "parent_name": "National Startup Awards"},
    {"source_id": "DPIIT-SRC-013", "url": "https://www.startupindia.gov.in/content/dam/invest-india/Templates/public/National%20Startup%20Awards%202023_Guidelines.pdf", "title": "National Startup Awards 2023 Guidelines", "ownership_proven": True, "parent_name": "National Startup Awards"},
    {"source_id": "DPIIT-SRC-014", "url": "https://www.startupindia.gov.in/content/sih/en/bharat-startup-grand-challenge.html", "title": "Bharat Startup Grand Challenge", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-014", "url": "https://www.startupindia.gov.in/content/sih/en/bharat-startup-grand-challenge/gaming-for-good.html", "title": "Gaming for Good – Bharat Startup Grand Challenge", "ownership_proven": True, "parent_name": "Bharat Startup Grand Challenge"},
    {"source_id": "DPIIT-SRC-015", "url": "https://www.startupindia.gov.in/bhaskar/about", "title": "BHASKAR – Bharat Startup Knowledge Access Registry", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-016", "url": "https://maarg.startupindia.gov.in/", "title": "MAARG – Startup India National Mentorship Platform", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-017", "url": "https://investorconnect.startupindia.gov.in/", "title": "Startup India Investor Connect", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-018", "url": "https://www.dpiit.gov.in/offerings/schemes-and-services/details/startup-india-initiative-MTMzYDNtQWa", "title": "Startup India Initiative and Related Schemes", "ownership_proven": True},
    {"source_id": "DPIIT-SRC-019", "url": "https://www.nsws.gov.in/portal/scheme/dpiit-startup-recognition", "title": "Apply for DPIIT Startup Recognition", "ownership_proven": True, "parent_name": "DPIIT Startup Recognition"},
    {"source_id": "DPIIT-SRC-020", "url": "https://egazette.nic.in/WriteReadData/2026/270965.pdf", "title": "Gazette Notification G.S.R. 108(E) – Startup Definition", "ownership_proven": False},
    {"source_id": "DPIIT-SRC-005", "url": "https://www.startupindia.gov.in/content/sih/en/archive-notice.html", "title": "Archived Page", "ownership_proven": False},
    {"source_id": "DPIIT-SRC-006", "url": "https://www.startupindia.gov.in/content/sih/en/contact-us.html", "title": "Contact Us", "ownership_proven": False},
]


def build_source_registry() -> list[dict[str, str]]:
    return deepcopy(sorted(SOURCES, key=lambda row: row["source_id"]))


def seed_candidates() -> list[dict[str, object]]:
    return deepcopy(CANDIDATE_SEEDS)
