from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)

WORD_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
    "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
    "twenty first": 21, "twenty second": 22, "twenty third": 23,
    "twenty fourth": 24, "twenty fifth": 25,
}

FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:sisfs|startup india seed fund(?: scheme)?)\b", "Startup India Seed Fund Scheme (SISFS)"),
    (r"\bcredit guarantee scheme for startups?\b|\bcgss\b", "Credit Guarantee Scheme for Startups (CGSS)"),
    (r"\bstartup india fund of funds(?: 2\.0)?\b|\bfund of funds 2\.0\b", "Startup India Fund of Funds"),
    (r"\bbiotechnology ignition grant\b|\bbig scheme\b|\bbig guidelines?\b", "Biotechnology Ignition Grant (BIG)"),
    (r"\bsmall business innovation research initiative\b|\bsbiri\b", "Small Business Innovation Research Initiative (SBIRI)"),
    (r"\bbiotechnology industry partnership programme\b|\bbipp\b", "Biotechnology Industry Partnership Programme (BIPP)"),
    (r"\bcontract research and services scheme\b|\bcrss?\b", "Contract Research and Services Scheme (CRS)"),
    (r"\bpromoting academic research conversion to enterprise\b|\bpace scheme\b", "Promoting Academic Research Conversion to Enterprise (PACE)"),
    (r"\be-?yuva\b|\beyuva\b", "E-YUVA"),
    (r"\bbionest\b", "BioNEST"),
    (r"\bsparsh\b", "SPARSH"),
    (r"\bamrit team grants?\b", "AMRIT Team Grants"),
    (r"\bnational green hydrogen mission\b|\bnghm\b", "National Green Hydrogen Mission"),
    (r"\bwaste to energy\b", "Waste to Energy – Innovation Clean Technologies Scale-up"),
    (r"\bnational biopharma mission\b", "National Biopharma Mission"),
    (r"\bindustry innovation programme on medical electronics\b|\biipme\b", "Industry Innovation Programme on Medical Electronics (IIPME)"),
    (r"\bamrit grand challenge jancare\b|\bjancare\b", "AMRIT Grand Challenge – JanCare"),
    (r"\bgrand challenges india\b|\bgci\b", "Grand Challenges India (GCI)"),
    (r"\bbio-?ai\b|\bbioe3\b|मूलांकुर", "Bio-AI / BioE3 Mulankur Hubs"),
    (r"\binspire scheme\b", "INSPIRE Scheme"),
    (r"\bmega facilities for basic research\b", "Mega Facilities for Basic Research Scheme"),
    (r"\bnational science and technology entrepreneurship development board\b|\bnstedb\b", "National Science & Technology Entrepreneurship Development Board (NSTEDB)"),
    (r"\bnidhi-?eir\b", "NIDHI-EIR"),
    (r"\bindo-japan cooperative science programme\b|\bijcsp\b", "Indo-Japan Cooperative Science Programme (IJCSP)"),
    (r"\bindia-austria science and technology cooperation\b", "India-Austria Science & Technology Cooperation"),
    (r"\bwater technology initiative\b|\bwti-\d{4}\b", "Water Technology Initiative (WTI)"),
    (r"\bicps programme\b", "Interdisciplinary Cyber Physical Systems (ICPS) Programme"),
    (r"\bwise-kiran\b", "WISE-KIRAN"),
    (r"\bnational startup awards?\b|\bnsa\s*5(?:\.0)?\b", "National Startup Awards"),
    (r"\bnational geospatial programme\b|\bngp-dst\b|\bnrdms\b", "National Geospatial Programme"),
    (r"\bncstc\b", "National Council for Science & Technology Communication (NCSTC)"),
)

CATEGORY_PRIORITY = {
    "SCHEME": 100,
    "PROGRAMME": 95,
    "FELLOWSHIP": 85,
    "CALL": 75,
    "DIRECTORY_PAGE": 55,
    "GUIDELINE": 45,
    "POLICY": 35,
    "REFERENCE_DIRECTORY": 30,
    "REFERENCE_DOCUMENT": 25,
    "RESULT_LIST": 10,
    "AWARD": 5,
    "ARCHIVE_INDEX": 0,
    "OTHER": 0,
}

MASTER_ELIGIBLE_CATEGORIES = {"SCHEME", "PROGRAMME", "FELLOWSHIP", "CALL"}
SUPPORTING_CATEGORIES = {"GUIDELINE", "POLICY", "REFERENCE_DOCUMENT", "REFERENCE_DIRECTORY", "RESULT_LIST"}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_for_match(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(value: str) -> str:
    text = normalize_for_match(value)
    text = re.sub(r"\b(?:scheme|programme|program)\b", " ", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text or "unresolved"


def canonicalize_url(url: str) -> str:
    raw = clean_text(url)
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = "https" if parts.scheme.lower() in {"http", "https"} else parts.scheme.lower()
    host = parts.netloc.lower()
    path = re.sub(r"/+", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")

    kept_query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in {"fbclid", "gclid", "ref", "source"}:
            continue
        kept_query.append((key, value))

    return urlunsplit((scheme, host, path, urlencode(sorted(kept_query)), ""))


def record_text(record: dict[str, Any]) -> str:
    return clean_text(" ".join([
        record.get("title", ""),
        record.get("description", ""),
        record.get("anchor_text", ""),
        record.get("url", ""),
    ]))


def extract_dates(text: str) -> list[date]:
    value = clean_text(text)
    found: set[date] = set()

    day_month_year = re.compile(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\s*,?\s*(20\d{{2}})\b",
        re.IGNORECASE,
    )
    for day_text, month_text, year_text in day_month_year.findall(value):
        try:
            found.add(date(int(year_text), MONTHS[month_text.lower()], int(day_text)))
        except ValueError:
            pass

    month_day_year = re.compile(
        rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(20\d{{2}})\b",
        re.IGNORECASE,
    )
    for month_text, day_text, year_text in month_day_year.findall(value):
        try:
            found.add(date(int(year_text), MONTHS[month_text.lower()], int(day_text)))
        except ValueError:
            pass

    numeric_date = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")
    for day_text, month_text, year_text in numeric_date.findall(value):
        try:
            found.add(date(int(year_text), int(month_text), int(day_text)))
        except ValueError:
            pass

    return sorted(found)


def extract_call_sequence(text: str) -> int | None:
    normalized = normalize_for_match(text)
    numeric = re.search(r"\b(\d{1,3})(?:st|nd|rd|th)?\s+(?:special\s+|challenge\s+|national\s+)?call\b", normalized)
    if numeric:
        return int(numeric.group(1))
    for word, number in sorted(WORD_ORDINALS.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(word)}\s+call\b", normalized):
            return number
    return None


def classify_category(record: dict[str, Any]) -> tuple[str, float, list[str]]:
    text = normalize_for_match(record_text(record))
    url = clean_text(record.get("url"))
    title = normalize_for_match(record.get("title"))

    if "archive call for proposals" in text or "/archive-call-for-proposals" in url:
        return "ARCHIVE_INDEX", 0.99, ["archive marker"]

    if re.search(
        r"\b(results?|projects supported|list of (?:recommended |screened |various )?proposals|"
        r"list of projects|selected proposals|awardees)\b",
        text,
    ):
        return "RESULT_LIST", 0.96, ["result/list marker"]

    if re.search(r"\b(national startup awards?|startup awards?)\b", text):
        if "result" in text:
            return "RESULT_LIST", 0.98, ["award result marker"]
        return "AWARD", 0.96, ["award marker"]

    if (
        re.search(r"\bgovernment schemes for startups\b|\bschemes programmes\b|\bincubator schemes\b", text)
        or re.search(r"/(?:schemes-programmes|government-schemes|incubator-schemes)(?:\.html)?$", url, re.IGNORECASE)
        or re.search(r"/cfp\.php$", url, re.IGNORECASE)
        or (
            title in {
                "call for proposals department of science and technology",
                "birac call for proposal",
            }
            and int(record.get("depth") or 0) <= 1
        )
    ):
        return "DIRECTORY_PAGE", 0.95, ["directory/index marker"]

    if re.search(r"\b(playbook|compendium)\b", text):
        return "REFERENCE_DIRECTORY", 0.95, ["playbook/compendium marker"]

    if record.get("content_kind") == "document" and re.search(
        r"\b(guidelines?|user guide|conditions attached|instructions?|framework ip|"
        r"om on revision|clarifications?|implementation of the recommendations)\b",
        text,
    ):
        return "GUIDELINE", 0.96, ["guideline marker"]

    if re.search(
        r"\b(call for proposals?|request for proposals?|invitation of proposals?|open call|"
        r"(?:\d+(?:st|nd|rd|th)?\s+)?call for)\b",
        text,
    ):
        return "CALL", 0.96, ["call marker"]

    if re.search(r"\bfellowship\b", text):
        return "FELLOWSHIP", 0.93, ["fellowship marker"]

    if re.search(r"\b(policy|action plan|official notifications?|recognition)\b", text):
        return "POLICY", 0.88, ["policy/notification marker"]

    if re.search(r"\bscheme\b", text):
        return "SCHEME", 0.88, ["scheme marker"]

    if re.search(r"\b(programme|program|mission|board)\b", text):
        return "PROGRAMME", 0.78, ["programme marker"]

    if record.get("content_kind") == "document":
        return "REFERENCE_DOCUMENT", 0.50, ["document fallback"]

    return "OTHER", 0.35, ["no strong marker"]


def infer_programme_family(record: dict[str, Any]) -> tuple[str | None, float, str]:
    normalized = normalize_for_match(record_text(record))

    for pattern, family_name in FAMILY_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return family_name, 0.98, "known-pattern"

    if re.search(r"\bseed fund\b", normalized):
        if record.get("source") == "Startup India":
            return "Startup India Seed Fund Scheme (SISFS)", 0.92, "source-context"
        if record.get("source") == "BIRAC":
            return "BIRAC Seed Fund", 0.82, "source-context"

    original = clean_text(f"{record.get('anchor_text', '')} {record.get('title', '')}")
    generic_patterns = (
        r"\bunder\s+(?:the\s+)?(.{3,100}?)\s+(?:scheme|programme|program|mission)\b",
        r"\b(?:under\s+the\s+scheme\s+)[\"“]?(.{3,100}?)[\"”]?(?:\s*\||$)",
    )

    for pattern in generic_patterns:
        match = re.search(pattern, original, re.IGNORECASE)
        if not match:
            continue
        candidate = clean_text(match.group(1)).strip(" -:;,.()\"“”")
        candidate = re.sub(r"^(?:a|an|the)\s+", "", candidate, flags=re.IGNORECASE)
        if (
            4 <= len(candidate) <= 100
            and not re.search(r"\bcall for proposal\b", candidate, re.IGNORECASE)
            and candidate.lower() not in {"the", "scheme", "programme", "program"}
        ):
            return candidate, 0.62, "generic-under-pattern"

    return None, 0.0, "none"


def infer_lifecycle(
    record: dict[str, Any],
    category: str,
    as_of_date: date,
) -> tuple[str, str | None, float]:
    text = record_text(record)
    normalized = normalize_for_match(text)
    dates = extract_dates(text)
    deadline = max(dates) if dates else None
    years = [int(year) for year in re.findall(r"\b(20\d{2})\b", text)]
    latest_year = max(years) if years else None
    parent_url = normalize_for_match(record.get("parent_url"))

    if category == "ARCHIVE_INDEX":
        return "ARCHIVED", deadline.isoformat() if deadline else None, 0.99

    if category == "CALL":
        if "archive" in parent_url:
            return "CLOSED", deadline.isoformat() if deadline else None, 0.98
        if deadline:
            if deadline < as_of_date:
                return "CLOSED", deadline.isoformat(), 0.95
            return "ACTIVE", deadline.isoformat(), 0.97
        if re.search(r"\b(open call|currently open|last date|deadline|extended till)\b", normalized):
            if latest_year is None or latest_year >= as_of_date.year:
                return "ACTIVE_OR_UNVERIFIED", None, 0.66
        if latest_year and latest_year < as_of_date.year:
            return "CLOSED", None, 0.82
        if latest_year and latest_year >= as_of_date.year:
            return "CURRENT_YEAR_UNVERIFIED", None, 0.62
        if int(record.get("depth") or 99) <= 1 and "archive" not in parent_url:
            return "ACTIVE_OR_UNVERIFIED", None, 0.52
        return "UNKNOWN", None, 0.35

    if category in {"SCHEME", "PROGRAMME", "FELLOWSHIP"}:
        if re.search(r"\b(discontinued|closed|withdrawn|archived|expired)\b", normalized):
            return "INACTIVE", deadline.isoformat() if deadline else None, 0.85
        if latest_year and latest_year < as_of_date.year and category == "FELLOWSHIP":
            return "HISTORICAL_OR_EXPIRED", deadline.isoformat() if deadline else None, 0.78
        return "CURRENT_UNVERIFIED", deadline.isoformat() if deadline else None, 0.56

    if category in {"POLICY", "GUIDELINE", "REFERENCE_DIRECTORY", "REFERENCE_DOCUMENT"}:
        return "REFERENCE", deadline.isoformat() if deadline else None, 0.70

    if category == "RESULT_LIST":
        return "HISTORICAL_RESULT", deadline.isoformat() if deadline else None, 0.90

    return "NOT_APPLICABLE", deadline.isoformat() if deadline else None, 0.80


def infer_dashboard_relevance(
    record: dict[str, Any],
    category: str,
) -> tuple[str, int, list[str]]:
    direct_text = normalize_for_match(" ".join([
        record.get("title", ""),
        record.get("anchor_text", ""),
        record.get("description", ""),
        record.get("url", ""),
    ]))
    reasons = " ".join(record.get("relevance_reasons") or []).lower()

    score = 0
    signals: list[str] = []
    direct_patterns = (
        (r"\bstartup\b|\bstart-up\b", 5, "startup"),
        (r"\bentrepreneur(?:ship)?\b", 4, "entrepreneur"),
        (r"\bincubat", 4, "incubation"),
        (r"\bseed fund\b", 5, "seed-fund"),
        (r"\bcredit guarantee\b", 5, "credit-guarantee"),
        (r"\bfund of funds\b", 5, "fund-of-funds"),
        (r"\binnovator\b|\binnovation\b", 3, "innovation"),
        (r"\bindustry\b", 2, "industry"),
        (r"\btechnology\b", 1, "technology"),
        (r"\bresearcher\b|\bresearch institution\b", 1, "research"),
    )

    for pattern, weight, label in direct_patterns:
        if re.search(pattern, direct_text):
            score += weight
            signals.append(label)

    weak_reason_signals = (
        ("body:audience:startup", 2, "body-startup"),
        ("body:audience:start-up", 2, "body-start-up"),
        ("body:audience:entrepreneur", 1, "body-entrepreneur"),
        ("body:audience:innovator", 1, "body-innovator"),
        ("body:audience:innovation", 1, "body-innovation"),
        ("body:audience:industry", 1, "body-industry"),
    )
    for token, weight, label in weak_reason_signals:
        if token in reasons:
            score += weight
            signals.append(label)

    if record.get("source") == "Startup India":
        score += 2
        signals.append("startup-india-source")
    elif record.get("source") == "BIRAC":
        score += 1
        signals.append("birac-source")

    if category in {"RESULT_LIST", "ARCHIVE_INDEX"}:
        score -= 4
    elif category in {"POLICY", "AWARD"}:
        score -= 2
    elif category == "FELLOWSHIP":
        score -= 1

    if score >= 8:
        level = "HIGH"
    elif score >= 4:
        level = "MEDIUM"
    elif score >= 1:
        level = "LOW"
    else:
        level = "OUT_OF_SCOPE_OR_UNCLEAR"

    return level, score, signals


def clean_call_subject(record: dict[str, Any]) -> str:
    text = clean_text(record.get("anchor_text") or record.get("title") or "")
    text = re.sub(r"\.{3,}$", "", text)
    text = re.sub(r"\s*\|\s*Department Of Science.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:BIRAC|DBT-?BIRAC|GCI-?BIRAC)\s+(?:announces?|announced)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:\d+(?:st|nd|rd|th)\s+)?(?:special\s+|challenge\s+|national\s+|open\s+)?"
        r"call\s+for\s+proposals?\s+(?:on\s+|under\s+)?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.split(
        r"\b(?:last date|deadline|extended till|call extended|1st\s+jan|15th\s+feb|31st\s+march)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = text.strip(" -:;,.\"“”")
    return text[:180] or "Unresolved call"


def deduplicate_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_url: dict[str, dict[str, Any]] = {}
    for record in records:
        key = canonicalize_url(record.get("url", ""))
        if not key:
            continue
        existing = best_by_url.get(key)
        if existing is None or float(record.get("relevance_score") or 0) > float(existing.get("relevance_score") or 0):
            best_by_url[key] = dict(record)
    return list(best_by_url.values())


@dataclass
class ClassificationRunResult:
    classified_candidates: list[dict[str, Any]]
    scheme_master_candidates: list[dict[str, Any]]
    summary: dict[str, Any]


class CandidateClassifierV1:
    """Classify discovered URLs and consolidate repeated calls into scheme families.

    The classifier is deterministic and does not require an AI API. It preserves all
    original discovery fields, adds explainable classifications, and creates a compact
    set of master scheme/programme candidates for the extraction stage.
    """

    def __init__(self, as_of_date: date | None = None) -> None:
        self.as_of_date = as_of_date or date.today()

    def classify(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduplicated = deduplicate_records(records)
        classified: list[dict[str, Any]] = []

        for record in deduplicated:
            item = dict(record)
            item["canonical_url"] = canonicalize_url(record.get("url", ""))

            category, category_confidence, category_reasons = classify_category(record)
            family, family_confidence, family_method = infer_programme_family(record)
            lifecycle, deadline, lifecycle_confidence = infer_lifecycle(
                record,
                category,
                self.as_of_date,
            )
            relevance, relevance_score, relevance_signals = infer_dashboard_relevance(
                record,
                category,
            )

            item.update({
                "classification": category,
                "classification_confidence": round(category_confidence, 3),
                "classification_reasons": category_reasons,
                "programme_family": family,
                "programme_family_confidence": round(family_confidence, 3),
                "programme_family_method": family_method,
                "call_sequence": extract_call_sequence(record_text(record)),
                "lifecycle_status": lifecycle,
                "deadline": deadline,
                "lifecycle_confidence": round(lifecycle_confidence, 3),
                "dashboard_relevance": relevance,
                "dashboard_relevance_score": relevance_score,
                "dashboard_relevance_signals": relevance_signals,
                "classified_at": datetime.now(timezone.utc).isoformat(),
                "classifier_version": "1.0.0",
            })
            classified.append(item)

        self._inherit_family_from_parent(classified)
        self._infer_historical_call_sequences(classified)
        self._assign_review_decisions(classified)

        classified.sort(
            key=lambda item: (
                item.get("source", ""),
                -CATEGORY_PRIORITY.get(item.get("classification", "OTHER"), 0),
                -float(item.get("relevance_score") or 0),
                item.get("title", ""),
            )
        )
        return classified

    def _inherit_family_from_parent(self, records: list[dict[str, Any]]) -> None:
        by_url = {record.get("canonical_url"): record for record in records}
        for record in records:
            if record.get("programme_family") or not record.get("parent_url"):
                continue
            parent = by_url.get(canonicalize_url(record.get("parent_url", "")))
            if not parent or not parent.get("programme_family"):
                continue
            if record.get("classification") not in SUPPORTING_CATEGORIES | {"CALL"}:
                continue
            record["programme_family"] = parent["programme_family"]
            record["programme_family_confidence"] = round(
                max(0.55, float(parent.get("programme_family_confidence") or 0) - 0.10),
                3,
            )
            record["programme_family_method"] = "inherited-from-parent"

    def _infer_historical_call_sequences(self, records: list[dict[str, Any]]) -> None:
        grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            if record.get("classification") != "CALL" or not record.get("programme_family"):
                continue
            grouped[(record.get("source", ""), record["programme_family"])].append(record)

        for family_records in grouped.values():
            dated_sequences = [
                int(record["call_sequence"])
                for record in family_records
                if record.get("call_sequence") is not None
                and record.get("deadline")
            ]
            if not dated_sequences:
                continue
            latest_dated_sequence = max(dated_sequences)
            for record in family_records:
                sequence = record.get("call_sequence")
                if (
                    sequence is not None
                    and int(sequence) < latest_dated_sequence
                    and record.get("lifecycle_status") == "UNKNOWN"
                ):
                    record["lifecycle_status"] = "CLOSED"
                    record["lifecycle_confidence"] = 0.82
                    record["lifecycle_inference"] = (
                        "Earlier numbered call than a later dated call in the same programme family"
                    )

    def _assign_review_decisions(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            category = record.get("classification")
            lifecycle = record.get("lifecycle_status")
            relevance = record.get("dashboard_relevance")

            if category in {"ARCHIVE_INDEX", "RESULT_LIST", "AWARD"}:
                decision = "EXCLUDE_FROM_SCHEME_MASTER"
            elif category in SUPPORTING_CATEGORIES:
                decision = "ATTACH_AS_SUPPORTING_EVIDENCE"
            elif category == "DIRECTORY_PAGE":
                decision = "USE_FOR_FURTHER_DISCOVERY"
            elif category == "CALL" and lifecycle == "CLOSED":
                decision = "HISTORICAL_CALL"
            elif category == "CALL" and lifecycle in {
                "ACTIVE", "ACTIVE_OR_UNVERIFIED", "CURRENT_YEAR_UNVERIFIED"
            }:
                decision = "PRIORITY_REVIEW"
            elif category in {"SCHEME", "PROGRAMME"} and relevance in {"HIGH", "MEDIUM"}:
                decision = "PRIORITY_REVIEW"
            elif category == "FELLOWSHIP" and relevance in {"HIGH", "MEDIUM"}:
                decision = "REVIEW_IF_IN_SCOPE"
            else:
                decision = "MANUAL_REVIEW"

            record["review_decision"] = decision

    def consolidate(self, classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        for record in classified:
            category = record.get("classification")
            family = record.get("programme_family")

            if family:
                group_name = family
            elif category == "CALL" and record.get("lifecycle_status") in {
                "ACTIVE", "ACTIVE_OR_UNVERIFIED", "CURRENT_YEAR_UNVERIFIED"
            }:
                group_name = clean_call_subject(record)
            elif category in {"SCHEME", "PROGRAMME", "FELLOWSHIP"}:
                group_name = clean_text(record.get("title")) or clean_call_subject(record)
            else:
                continue

            grouped[(record.get("source", "Unknown"), slugify(group_name))].append(record)

        masters: list[dict[str, Any]] = []
        for (source, group_key), members in grouped.items():
            canonical_name = self._choose_canonical_name(members)
            active_calls = self._deduplicate_call_members([
                member for member in members
                if member.get("classification") == "CALL"
                and member.get("lifecycle_status") in {
                    "ACTIVE", "ACTIVE_OR_UNVERIFIED", "CURRENT_YEAR_UNVERIFIED"
                }
            ])
            closed_calls = [
                member for member in members
                if member.get("classification") == "CALL"
                and member.get("lifecycle_status") == "CLOSED"
            ]
            supporting = [
                member for member in members
                if member.get("classification") in SUPPORTING_CATEGORIES
            ]
            core_pages = [
                member for member in members
                if member.get("classification") in {"SCHEME", "PROGRAMME", "FELLOWSHIP"}
            ]

            known_family_evidence = (
                max(float(member.get("programme_family_confidence") or 0) for member in members) >= 0.80
                and any(
                    member.get("classification") in {"CALL", "SCHEME", "PROGRAMME", "FELLOWSHIP"}
                    or (
                        member.get("source") == "BIRAC"
                        and member.get("classification") == "RESULT_LIST"
                        and "projects supported" in normalize_for_match(member.get("title"))
                    )
                    for member in members
                )
            )

            if not core_pages and not active_calls and not known_family_evidence:
                continue

            # Historical, low-relevance fellowships should not become dashboard masters.
            if (
                core_pages
                and all(page.get("classification") == "FELLOWSHIP" for page in core_pages)
                and not active_calls
                and all(page.get("dashboard_relevance") in {"LOW", "OUT_OF_SCOPE_OR_UNCLEAR"} for page in core_pages)
            ):
                continue

            primary = self._choose_primary_record(core_pages or active_calls or members)
            best_relevance = max(float(member.get("relevance_score") or 0) for member in members)
            relevance_levels = [member.get("dashboard_relevance") for member in members]
            family_confidence = max(float(member.get("programme_family_confidence") or 0) for member in members)

            if core_pages and any(page.get("classification") in {"SCHEME", "PROGRAMME"} for page in core_pages):
                master_type = "SCHEME_OR_PROGRAMME"
            elif core_pages and all(page.get("classification") == "FELLOWSHIP" for page in core_pages):
                master_type = "FELLOWSHIP"
            elif active_calls:
                master_type = "ACTIVE_CALL_FAMILY"
            else:
                master_type = "PROGRAMME_FAMILY_FROM_HISTORICAL_EVIDENCE"

            if core_pages and ("HIGH" in relevance_levels or "MEDIUM" in relevance_levels):
                readiness = "READY_FOR_EXTRACTION"
            elif core_pages:
                readiness = "NEEDS_SCOPE_REVIEW"
            elif active_calls:
                readiness = "NEEDS_CONTENT_EXTRACTION_AND_REVIEW"
            elif known_family_evidence:
                readiness = "NEEDS_OFFICIAL_SCHEME_PAGE_DISCOVERY"
            else:
                readiness = "NEEDS_MANUAL_REVIEW"

            current_status = (
                "ACTIVE_CALL_OPEN" if active_calls
                else "SCHEME_INFORMATION_AVAILABLE" if core_pages
                else "HISTORICAL_EVIDENCE_ONLY" if known_family_evidence
                else "UNKNOWN"
            )

            master_id = hashlib.sha256(f"{source}|{group_key}".encode("utf-8")).hexdigest()[:20]
            masters.append({
                "master_id": master_id,
                "canonical_name": canonical_name,
                "source": source,
                "master_type": master_type,
                "current_status": current_status,
                "readiness": readiness,
                "official_page_url": primary.get("url") if core_pages else None,
                "official_page_title": primary.get("title") if core_pages else None,
                "best_available_url": primary.get("url"),
                "best_available_title": primary.get("title"),
                "best_relevance_score": round(best_relevance, 3),
                "programme_family_confidence": round(family_confidence, 3),
                "source_records_count": len(members),
                "core_page_count": len(core_pages),
                "active_call_count": len(active_calls),
                "closed_call_count": len(closed_calls),
                "supporting_document_count": len(supporting),
                "active_calls": [self._compact_member(member) for member in active_calls],
                "supporting_documents": [self._compact_member(member) for member in supporting],
                "core_pages": [self._compact_member(member) for member in core_pages],
                "all_member_urls": sorted({member.get("url") for member in members if member.get("url")}),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "classifier_version": "1.0.0",
            })

        masters.sort(
            key=lambda item: (
                0 if item["current_status"] == "ACTIVE_CALL_OPEN" else 1,
                0 if item["readiness"] == "READY_FOR_EXTRACTION" else 1,
                -float(item["best_relevance_score"]),
                item["source"],
                item["canonical_name"],
            )
        )
        return masters

    def _choose_canonical_name(self, members: list[dict[str, Any]]) -> str:
        family_candidates = [
            (float(member.get("programme_family_confidence") or 0), member.get("programme_family"))
            for member in members
            if member.get("programme_family")
        ]
        if family_candidates:
            family_candidates.sort(reverse=True)
            return clean_text(family_candidates[0][1])

        core = [member for member in members if member.get("classification") in {"SCHEME", "PROGRAMME", "FELLOWSHIP"}]
        if core:
            return clean_text(self._choose_primary_record(core).get("title"))
        return clean_call_subject(self._choose_primary_record(members))

    def _choose_primary_record(self, members: list[dict[str, Any]]) -> dict[str, Any]:
        def key(record: dict[str, Any]) -> tuple[int, int, float, int]:
            category_score = CATEGORY_PRIORITY.get(record.get("classification", "OTHER"), 0)
            lifecycle_score = {
                "ACTIVE": 25,
                "ACTIVE_OR_UNVERIFIED": 20,
                "CURRENT_YEAR_UNVERIFIED": 15,
                "CURRENT_UNVERIFIED": 12,
                "REFERENCE": 5,
                "CLOSED": 0,
            }.get(record.get("lifecycle_status"), 0)
            relevance = float(record.get("relevance_score") or 0)
            html_score = 1 if record.get("content_kind") == "html" else 0
            return category_score, lifecycle_score, relevance, html_score

        return max(members, key=key)

    def _deduplicate_call_members(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for call in calls:
            if call.get("programme_family") and call.get("deadline"):
                signature = "|".join([
                    slugify(clean_text(call.get("programme_family"))),
                    clean_text(call.get("deadline")),
                ])
            else:
                signature = "|".join([
                    slugify(clean_call_subject(call)),
                    clean_text(call.get("deadline")),
                    clean_text(call.get("programme_family")),
                ])
            existing = best.get(signature)
            if existing is None or float(call.get("relevance_score") or 0) > float(existing.get("relevance_score") or 0):
                best[signature] = call
        return sorted(
            best.values(),
            key=lambda item: (item.get("deadline") or "9999-12-31", -float(item.get("relevance_score") or 0)),
        )

    @staticmethod
    def _compact_member(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": record.get("url"),
            "title": record.get("title"),
            "anchor_text": record.get("anchor_text"),
            "classification": record.get("classification"),
            "lifecycle_status": record.get("lifecycle_status"),
            "deadline": record.get("deadline"),
            "relevance_score": record.get("relevance_score"),
            "dashboard_relevance": record.get("dashboard_relevance"),
        }

    def build_summary(
        self,
        input_count: int,
        classified: list[dict[str, Any]],
        masters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "input_record_count": input_count,
            "deduplicated_record_count": len(classified),
            "master_candidate_count": len(masters),
            "records_by_source": dict(Counter(record.get("source", "Unknown") for record in classified)),
            "records_by_classification": dict(Counter(record.get("classification", "OTHER") for record in classified)),
            "records_by_lifecycle": dict(Counter(record.get("lifecycle_status", "UNKNOWN") for record in classified)),
            "records_by_review_decision": dict(Counter(record.get("review_decision", "UNKNOWN") for record in classified)),
            "records_by_dashboard_relevance": dict(Counter(record.get("dashboard_relevance", "UNKNOWN") for record in classified)),
            "masters_by_source": dict(Counter(master.get("source", "Unknown") for master in masters)),
            "masters_by_status": dict(Counter(master.get("current_status", "UNKNOWN") for master in masters)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classifier_version": "1.0.0",
        }

    def run(self, input_path: str | Path, output_dir: str | Path) -> ClassificationRunResult:
        input_file = Path(input_path)
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)

        with input_file.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            raise ValueError("Discovery results must be a JSON array of candidate records.")

        classified = self.classify(records)
        masters = self.consolidate(classified)
        summary = self.build_summary(len(records), classified, masters)

        outputs = {
            "classified_candidates_v1.json": classified,
            "scheme_master_candidates_v1.json": masters,
            "classification_summary_v1.json": summary,
        }
        for filename, payload in outputs.items():
            with (destination / filename).open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)

        logger.info(
            "Classification complete | Input: %s | Classified: %s | Masters: %s",
            len(records),
            len(classified),
            len(masters),
        )
        return ClassificationRunResult(classified, masters, summary)
