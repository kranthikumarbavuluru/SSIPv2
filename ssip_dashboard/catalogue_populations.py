from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse


MAIN_SCHEME_RECORD_KINDS = {
    "SCHEME",
    "PROGRAMME",
    "SCHEME_OR_PROGRAMME",
    "GRANT",
    "FUND",
    "CREDIT_SUPPORT",
    "CREDIT_GUARANTEE",
    "SUBSIDY",
    "INCENTIVE",
    "FELLOWSHIP",
    "INCUBATION_SUPPORT",
    "ACCELERATOR_SUPPORT",
    "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT",
    "PROCUREMENT_SUPPORT",
    "INDIRECT_FINANCIAL_SUPPORT",
    "UMBRELLA_PROGRAMME",
    "GOVERNMENT_SERVICE",
    "ECOSYSTEM_OPPORTUNITY",
}
EVIDENCE_ONLY_RECORD_KINDS = {
    "GUIDELINE",
    "MANUAL",
    "REPORT",
    "MARKET_RESEARCH_REPORT",
    "WHITEPAPER",
    "BROCHURE",
    "FAQ",
    "DIRECTORY_PAGE",
    "INDEX_PAGE",
    "SITEMAP",
    "NEWS_PAGE",
    "RESULT_PAGE",
    "APPLICATION_FORM",
    "APPLICATION_PORTAL",
    "POLICY_PAGE",
    "ARCHIVE_PAGE",
    "SUPPORTING_PDF",
}
EVIDENCE_SIGNALS = {
    "annual report",
    "ecosystem report",
    "market research",
    "whitepaper",
    "handbook",
    "playbook",
    "manual",
    "guideline",
    "guidelines",
    "brochure",
    "faq",
    "sitemap",
    "directory",
    "index",
    "result",
    "awardees",
    "application form",
    "downloadable document",
    "certificate",
    "scope",
    "nabl accreditation",
    "startup landscape report",
    "trendbook",
}
GENERIC_NAMES = {
    "scheme",
    "schemes",
    "programme",
    "programmes",
    "program",
    "programs",
    "guideline",
    "guidelines",
    "report",
    "reports",
    "sitemap",
    "sitemap.xml",
    "search",
    "dashboard",
    "contact",
    "about",
    "disclaimer",
    "terms conditions",
    "accessibility statement",
    "screen reader",
}
SUPPORT_TYPE_MAP = {
    "GRANT": "GRANT",
    "FUND": "FUND",
    "SEED": "SEED_FUNDING",
    "SEED FUND": "SEED_FUNDING",
    "CREDIT_SUPPORT": "CREDIT_OR_LOAN",
    "CREDIT": "CREDIT_OR_LOAN",
    "LOAN": "CREDIT_OR_LOAN",
    "CREDIT_GUARANTEE": "CREDIT_GUARANTEE",
    "GUARANTEE": "CREDIT_GUARANTEE",
    "SUBSIDY": "SUBSIDY_OR_INCENTIVE",
    "INCENTIVE": "SUBSIDY_OR_INCENTIVE",
    "FELLOWSHIP": "FELLOWSHIP_OR_SCHOLARSHIP",
    "SCHOLARSHIP": "FELLOWSHIP_OR_SCHOLARSHIP",
    "INCUBATION_SUPPORT": "INCUBATION_OR_ACCELERATION",
    "ACCELERATOR_SUPPORT": "INCUBATION_OR_ACCELERATION",
    "INCUBATION": "INCUBATION_OR_ACCELERATION",
    "ACCELERATION": "INCUBATION_OR_ACCELERATION",
    "INFRASTRUCTURE_SUPPORT": "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT": "RESEARCH_SUPPORT",
    "PROCUREMENT_SUPPORT": "PROCUREMENT_OR_MARKET_ACCESS",
    "MARKET": "PROCUREMENT_OR_MARKET_ACCESS",
    "CHALLENGE": "CHALLENGE_SUPPORT",
    "INDIRECT_FINANCIAL_SUPPORT": "INDIRECT_FINANCIAL_SUPPORT",
}


@dataclass(frozen=True)
class CataloguePopulations:
    main_scheme_records: list[Any]
    application_call_records: list[Any]
    archived_scheme_records: list[Any]
    verification_required_scheme_records: list[Any]
    evidence_only_records: list[Any]
    excluded_records: list[Any]


def value(record: Any, field: str) -> str:
    if isinstance(record, dict):
        return str(record.get(field, "") or "").strip()
    return str(getattr(record, field, "") or "").strip()


def values(record: Any, field: str) -> list[str]:
    raw = record.get(field, []) if isinstance(record, dict) else getattr(record, field, [])
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item or "").strip()]
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r";|\|", text) if part.strip()]


def kind(record: Any) -> str:
    return value(record, "normalized_record_kind") or value(record, "record_kind") or "SCHEME_OR_PROGRAMME"


def decoded_url(record: Any) -> str:
    return unquote(value(record, "official_page_url"))


def is_rejected(record: Any) -> bool:
    return value(record, "current_decision").upper() == "REJECTED"


def is_application_call(record: Any) -> bool:
    return kind(record).upper() in {
        "APPLICATION_CALL",
        "CHALLENGE",
        "HISTORICAL_CALL",
    }


def is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def raw_filename_like(name: str) -> bool:
    text = unquote(name).strip()
    return bool(
        re.search(r"\.(pdf|docx?|xlsx?)$", text, re.IGNORECASE)
        or "%" in name
        or re.match(r"^\d{4}\s+[^|]+(?:report|ecosystem|landscape|trendbook|whitepaper)", text, re.IGNORECASE)
    )


def poor_scheme_name_reason(record: Any) -> str:
    name = value(record, "scheme_name")
    normalized = re.sub(r"\s+", " ", unquote(name).strip()).casefold()
    if not normalized:
        return "MISSING_SCHEME_NAME"
    if normalized in GENERIC_NAMES:
        return "GENERIC_SCHEME_NAME"
    if raw_filename_like(name):
        return "RAW_OR_URL_ENCODED_FILENAME_AS_NAME"
    if "sitemap" in normalized or "directory" in normalized:
        return "SITEMAP_OR_DIRECTORY_TITLE"
    return ""


def evidence_signal_reason(record: Any) -> str:
    text = f"{value(record, 'scheme_name')} {decoded_url(record)} {kind(record)}".casefold()
    if kind(record).upper() in EVIDENCE_ONLY_RECORD_KINDS:
        return f"EVIDENCE_ONLY_KIND_{kind(record).upper()}"
    if is_pdf_url(decoded_url(record)):
        return "PDF_REQUIRES_FORMAL_EXCEPTION"
    for signal in EVIDENCE_SIGNALS:
        if signal in text:
            return f"EVIDENCE_SIGNAL_{signal.upper().replace(' ', '_')}"
    return ""


def formal_pdf_exception_reason(record: Any) -> str:
    if not is_pdf_url(decoded_url(record)):
        return "NOT_A_PDF"
    name_text = value(record, "scheme_name").casefold()
    if any(signal in name_text for signal in ["report", "playbook", "handbook", "manual", "guideline", "brochure", "whitepaper"]):
        return "PDF_EXCEPTION_DENIED_REPORT_OR_GUIDANCE"
    if poor_scheme_name_reason(record):
        return "PDF_EXCEPTION_DENIED_FILENAME_OR_GENERIC_NAME"
    if not (value(record, "ministry") or value(record, "department") or value(record, "implementing_agency")):
        return "PDF_EXCEPTION_DENIED_AUTHORITY_MISSING"
    if not (values(record, "eligibility") or values(record, "benefits") or value(record, "programme_status")):
        return "PDF_EXCEPTION_DENIED_CORE_FIELDS_MISSING"
    return "PDF_EXCEPTION_ALLOWED_FORMAL_SCHEME_NOTIFICATION"


def is_evidence_only(record: Any) -> tuple[bool, str]:
    signal = evidence_signal_reason(record)
    if is_pdf_url(decoded_url(record)):
        pdf_reason = formal_pdf_exception_reason(record)
        if pdf_reason.startswith("PDF_EXCEPTION_ALLOWED"):
            return False, ""
        return True, pdf_reason
    if signal:
        return True, signal
    return False, ""


def has_authority(record: Any) -> bool:
    return bool(value(record, "ministry") or value(record, "department") or value(record, "implementing_agency") or value(record, "source"))


def has_primary_source(record: Any) -> bool:
    return bool(value(record, "official_page_url"))


def is_main_scheme_record(record: Any, seen_ids: set[str] | None = None) -> tuple[bool, str]:
    master_id = value(record, "master_id")
    if not master_id:
        return False, "MISSING_MASTER_ID"
    if seen_ids is not None and master_id in seen_ids:
        return False, "DUPLICATE_MASTER_ID"
    if is_rejected(record):
        return False, "REJECTED_RECORD"
    if is_application_call(record):
        return False, "APPLICATION_CALL_SEPARATE"
    if kind(record).upper() not in MAIN_SCHEME_RECORD_KINDS:
        return False, f"INELIGIBLE_RECORD_KIND_{kind(record).upper()}"
    name_reason = poor_scheme_name_reason(record)
    if name_reason:
        return False, name_reason
    evidence_only, evidence_reason = is_evidence_only(record)
    if evidence_only:
        return False, evidence_reason
    if not has_authority(record):
        return False, "AUTHORITY_OR_IMPLEMENTING_ORGANISATION_MISSING"
    if not has_primary_source(record):
        return False, "PRIMARY_OFFICIAL_URL_MISSING"
    return True, "MAIN_SCHEME_RECORD"


def is_archived(record: Any) -> bool:
    text = f"{value(record, 'catalogue_section')} {value(record, 'application_status')}".upper()
    return "ARCHIVED" in text or "HISTORICAL" in text or "CLOSED" in text


def requires_verification(record: Any) -> bool:
    text = f"{value(record, 'catalogue_inclusion')} {value(record, 'catalogue_section')} {value(record, 'application_status')} {value(record, 'current_decision')}".upper()
    return "PENDING_REVALIDATION" in text or "VERIFICATION" in text or "NEEDS_REVIEW" in text


def split_catalogue_populations(records: list[Any]) -> CataloguePopulations:
    # Evidence-only detection deliberately runs before application-call
    # classification. This prevents a sitemap, PDF manual, report, FAQ or
    # directory incorrectly labelled APPLICATION_CALL from entering calls.
    seen_ids: set[str] = set()
    main: list[Any] = []
    calls: list[Any] = []
    archived: list[Any] = []
    verification: list[Any] = []
    evidence: list[Any] = []
    excluded: list[Any] = []

    for record in records:
        ok, reason = is_main_scheme_record(record, seen_ids)

        if ok:
            seen_ids.add(value(record, "master_id"))
            main.append(record)
            if is_archived(record):
                archived.append(record)
            if requires_verification(record):
                verification.append(record)
            continue

        evidence_only, evidence_reason = is_evidence_only(record)
        poor_name_reason = poor_scheme_name_reason(record)

        if (
            evidence_only
            or poor_name_reason
            in {
                "RAW_OR_URL_ENCODED_FILENAME_AS_NAME",
                "GENERIC_SCHEME_NAME",
                "SITEMAP_OR_DIRECTORY_TITLE",
            }
        ):
            evidence.append(record)
        elif is_application_call(record) and not is_rejected(record):
            calls.append(record)
        else:
            excluded.append(record)

    return CataloguePopulations(
        main_scheme_records=main,
        application_call_records=calls,
        archived_scheme_records=archived,
        verification_required_scheme_records=verification,
        evidence_only_records=evidence,
        excluded_records=excluded,
    )


def normalize_sector(text: str) -> str:
    """Preserve verified SSIP taxonomy values; normalize only legacy aliases."""
    value_text = str(text or "").strip().strip('[]').strip().strip('"').strip("'")
    value_text = re.sub(r"\s+", " ", value_text)
    key = value_text.casefold()
    if not key or key in {"none", "null", "unknown", "not specified", "sector not specified", "n/a", "na"}:
        return "Sector Not Specified"

    legacy_aliases = {
        "biotechnology": "Biotechnology & Life Sciences",
        "healthcare": "Healthcare & MedTech",
        "digital technology": "Digital Technology & Software",
        "it & electronics": "Electronics & Semiconductors",
        "startup / innovation": "Cross-sector Innovation & Entrepreneurship",
        "msme / entrepreneurship": "Sector Agnostic / Multi-sector",
        "science & technology": "Deep Technology",
        "agriculture": "Agriculture & AgriTech",
    }
    return legacy_aliases.get(key, value_text)
def primary_sector(record: Any) -> str:
    sectors = values(record, "sectors") or values(record, "sector")
    return normalize_sector(sectors[0]) if sectors else "Sector Not Specified"


def secondary_sectors(record: Any) -> list[str]:
    sectors = values(record, "sectors") or values(record, "sector")
    return [normalize_sector(item) for item in sectors[1:]]


def normalize_support_type(text: str) -> str:
    raw = text.strip()
    key = raw.upper().replace(" ", "_").replace("/", "_")
    for token, label in SUPPORT_TYPE_MAP.items():
        if token in key or token.casefold() in raw.casefold():
            return label
    if not raw:
        return "SUPPORT_TYPE_NOT_SPECIFIED"
    if "SCHEME" in key or "PROGRAMME" in key:
        return "OTHER_PROGRAMME_SUPPORT"
    return "OTHER_PROGRAMME_SUPPORT"


def primary_support_type(record: Any) -> str:
    support_values = values(record, "scheme_types") or [kind(record)]
    return normalize_support_type(support_values[0]) if support_values else "SUPPORT_TYPE_NOT_SPECIFIED"


def secondary_support_types(record: Any) -> list[str]:
    support_values = values(record, "scheme_types")
    return [normalize_support_type(item) for item in support_values[1:]]


def primary_sector_counts(records: list[Any]) -> Counter[str]:
    return Counter(primary_sector(record) for record in records)


def primary_support_type_counts(records: list[Any]) -> Counter[str]:
    return Counter(primary_support_type(record) for record in records)
