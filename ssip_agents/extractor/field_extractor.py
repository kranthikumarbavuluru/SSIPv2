from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from dateutil import parser as date_parser

from .models import SourceDocument
from .utils import normalize_space, sentence_chunks, short_quote, unique_preserve, utc_now_iso


MONEY_RE = re.compile(
    r"(?P<prefix>₹|rs\.?|inr|rupees?)\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>crores?|cr|lakhs?|lacs?|million|billion|thousand|k)?",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([A-Z0-9._%+-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*"
    r"([A-Z0-9.-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*"
    r"([A-Z0-9.-]+)\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?91[\s-]?)?(?:0[\s-]?)?"
    r"(?:\d[\s-]?){9,11}(?!\d)"
)

DATE_PATTERNS = [
    re.compile(
        r"\b(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?[\s./-]+"
        r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"[\s,./-]+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"\s+(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?(?:,)?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.]\d{4}\b"),
    re.compile(r"\b\d{4}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b"),
]

SECTION_TERMS: dict[str, tuple[str, ...]] = {
    "overview": ("overview", "about the scheme", "introduction", "background"),
    "objectives": ("objective", "objectives", "aim", "purpose"),
    "eligibility": (
        "eligibility", "eligible", "who can apply", "applicant eligibility",
        "eligibility criteria", "target applicants",
    ),
    "benefits": (
        "benefits", "benefit", "financial assistance", "financial support",
        "funding support", "grant support", "support provided", "assistance",
    ),
    "application_process": (
        "how to apply", "application process", "application procedure",
        "registration process", "apply online", "submission process",
    ),
    "required_documents": (
        "documents required", "required documents", "documents to be submitted",
        "enclosures", "supporting documents", "document checklist",
    ),
    "selection_process": (
        "selection process", "evaluation process", "selection criteria",
        "screening process", "assessment process",
    ),
    "important_dates": (
        "important dates", "last date", "deadline", "closing date",
        "opening date", "application dates",
    ),
    "contact": ("contact", "contact details", "helpdesk", "queries"),
}


TARGET_BENEFICIARIES = {
    "Startups": ("startup", "start-up", "start ups"),
    "Innovators": ("innovator", "innovators"),
    "Entrepreneurs": ("entrepreneur", "entrepreneurs", "entrepreneurship"),
    "MSMEs": ("msme", "micro small and medium enterprise", "small business"),
    "Researchers": ("researcher", "researchers", "scientist", "scientists"),
    "Students": ("student", "students", "fellow", "fellows"),
    "Incubators": ("incubator", "incubators", "incubation centre", "incubation center"),
    "Academic institutions": (
        "academic institution", "academic institutions", "university",
        "universities", "college", "institutes",
    ),
    "Research institutions": ("research institution", "research institutions", "r&d institution"),
    "Women entrepreneurs": ("women entrepreneur", "women-led", "woman entrepreneur"),
    "Industry": ("industry", "industries", "industrial enterprise"),
}

STARTUP_STAGES = {
    "Ideation": ("idea stage", "ideation", "technology idea"),
    "Proof of Concept": ("proof of concept", "poc"),
    "Prototype": ("prototype", "prototyping"),
    "Validation": ("validation", "validate the technology"),
    "Early Stage": ("early stage", "early-stage"),
    "Commercialisation": ("commercialisation", "commercialization", "market launch"),
    "Growth": ("growth stage", "scale up", "scale-up", "scaling"),
}

SECTORS = {
    "Biotechnology": ("biotechnology", "biotech", "biopharma", "bio-manufacturing", "biomanufacturing"),
    "Healthcare": ("healthcare", "health care", "medical", "diagnostic", "vaccine"),
    "Agriculture": ("agriculture", "agri", "farming", "food processing"),
    "Clean Technology": ("clean technology", "cleantech", "waste to energy", "green technology"),
    "Energy": ("energy", "solar", "hydrogen"),
    "Quantum Technology": ("quantum technology", "quantum"),
    "Critical Minerals": ("critical minerals",),
    "Water": ("water technology", "water solutions"),
    "Geospatial": ("geospatial",),
    "Digital Technology": ("digital technology", "information technology", "software", "electronics"),
    "Deep Technology": ("deeptech", "deep tech"),
}

SCHEME_TYPES = {
    "Grant": ("grant", "grants", "grant-in-aid"),
    "Loan": ("loan", "soft loan", "debt"),
    "Credit Guarantee": ("credit guarantee", "guarantee cover"),
    "Equity / Fund": ("equity", "fund of funds", "venture fund", "seed fund"),
    "Fellowship": ("fellowship", "fellow"),
    "Incubation Support": ("incubation", "incubator", "bionest"),
    "Challenge / Call": ("challenge", "call for proposal", "call for proposals"),
    "Recognition / Certification": ("recognition", "certification"),
    "Tax / Regulatory Support": ("tax exemption", "regulatory support", "self-certification"),
}

STATE_NAMES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
)


class EvidenceFirstFieldExtractor:
    def __init__(
        self,
        *,
        source_authorities: dict[str, dict[str, Any]] | None = None,
        as_of_date: date | None = None,
    ) -> None:
        self.source_authorities = source_authorities or {}
        self.as_of_date = as_of_date or date.today()

    @staticmethod
    def _combined_text(documents: list[SourceDocument]) -> str:
        return normalize_space(
            " ".join(
                [doc.title for doc in documents]
                + [doc.text for doc in documents]
            )
        )

    @staticmethod
    def _evidence(
        *,
        field: str,
        value: Any,
        url: str,
        quote: str,
        method: str,
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "field": field,
            "value": value,
            "source_url": url,
            "quote": short_quote(quote),
            "method": method,
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
        }

    def _section_matches(
        self,
        documents: list[SourceDocument],
        section_key: str,
        max_items: int = 12,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        terms = SECTION_TERMS[section_key]
        items: list[str] = []
        evidence: list[dict[str, Any]] = []

        for doc in documents:
            for heading, values in doc.sections.items():
                heading_lower = heading.casefold()
                if not any(term in heading_lower for term in terms):
                    continue

                for value in values:
                    cleaned = normalize_space(value)
                    if len(cleaned) < 6:
                        continue
                    items.append(cleaned)
                    evidence.append(
                        self._evidence(
                            field=section_key,
                            value=cleaned,
                            url=doc.url,
                            quote=f"{heading}: {cleaned}",
                            method="section-heading",
                            confidence=0.9,
                        )
                    )
                    if len(items) >= max_items:
                        return unique_preserve(items), evidence[:max_items]

        if items:
            return unique_preserve(items), evidence[:max_items]

        # Fallback: sentence-level context search.
        for doc in documents:
            for sentence in sentence_chunks(doc.text):
                lower = sentence.casefold()
                if any(term in lower for term in terms):
                    items.append(sentence)
                    evidence.append(
                        self._evidence(
                            field=section_key,
                            value=sentence,
                            url=doc.url,
                            quote=sentence,
                            method="keyword-context",
                            confidence=0.68,
                        )
                    )
                    if len(items) >= max_items:
                        return unique_preserve(items), evidence[:max_items]

        return unique_preserve(items), evidence[:max_items]

    @staticmethod
    def _clean_list_items(values: Iterable[str], max_items: int = 12) -> list[str]:
        output: list[str] = []
        for value in values:
            chunks = re.split(r"(?:\s*[•▪●]\s*|\s*;\s*|\s+\d+[.)]\s+)", value)
            for chunk in chunks:
                cleaned = normalize_space(chunk).strip(" -–—:;")
                if 12 <= len(cleaned) <= 800:
                    output.append(cleaned)
                    if len(output) >= max_items:
                        return unique_preserve(output)
        return unique_preserve(output)

    @staticmethod
    def _money_multiplier(unit: str | None) -> float:
        if not unit:
            return 1.0
        unit = unit.casefold()
        if unit in {"crore", "crores", "cr"}:
            return 10_000_000.0
        if unit in {"lakh", "lakhs", "lac", "lacs"}:
            return 100_000.0
        if unit == "million":
            return 1_000_000.0
        if unit == "billion":
            return 1_000_000_000.0
        if unit in {"thousand", "k"}:
            return 1_000.0
        return 1.0

    def _extract_funding(
        self,
        documents: list[SourceDocument],
        benefits: list[str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()

        source_texts: list[tuple[str, str]] = []
        for doc in documents:
            source_texts.append((doc.url, doc.text))
        for benefit in benefits:
            source_texts.append(("", benefit))

        for url, text in source_texts:
            for match in MONEY_RE.finditer(text):
                raw = normalize_space(match.group(0))
                try:
                    number = float(match.group("number").replace(",", ""))
                except ValueError:
                    continue
                amount = int(round(number * self._money_multiplier(match.group("unit"))))
                if amount <= 0:
                    continue

                context_start = max(0, match.start() - 100)
                context_end = min(len(text), match.end() + 180)
                context = normalize_space(text[context_start:context_end])
                key = (amount, context.casefold()[:120])
                if key in seen:
                    continue
                seen.add(key)

                candidates.append(
                    {
                        "amount": amount,
                        "currency": "INR",
                        "display_text": raw,
                        "context": short_quote(context, 320),
                        "source_url": url,
                    }
                )
                evidence.append(
                    self._evidence(
                        field="funding_amount",
                        value=amount,
                        url=url,
                        quote=context,
                        method="money-pattern",
                        confidence=0.88,
                    )
                )

        amounts = [item["amount"] for item in candidates]
        combined = self._combined_text(documents).casefold()
        funding_types = [
            scheme_type
            for scheme_type, markers in SCHEME_TYPES.items()
            if any(marker in combined for marker in markers)
        ]

        return (
            {
                "minimum": min(amounts) if amounts else None,
                "maximum": max(amounts) if amounts else None,
                "currency": "INR",
                "funding_types": funding_types,
                "amount_mentions": candidates[:20],
            },
            evidence[:20],
        )

    def _extract_categories(
        self,
        text: str,
        mapping: dict[str, tuple[str, ...]],
    ) -> list[str]:
        lower = text.casefold()
        return [
            label
            for label, markers in mapping.items()
            if any(marker in lower for marker in markers)
        ]

    def _extract_dates(
        self,
        documents: list[SourceDocument],
        master: dict[str, Any],
    ) -> tuple[str | None, str | None, list[dict[str, Any]]]:
        opening_candidates: list[tuple[date, str, str]] = []
        closing_candidates: list[tuple[date, str, str]] = []
        evidence: list[dict[str, Any]] = []

        def add_date(raw: str, context: str, url: str) -> None:
            cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE)
            try:
                parsed = date_parser.parse(cleaned, dayfirst=True, fuzzy=True).date()
            except (ValueError, OverflowError):
                return

            context_lower = context.casefold()
            if any(marker in context_lower for marker in ("last date", "deadline", "closing date", "close by", "submission by")):
                closing_candidates.append((parsed, url, context))
            elif any(marker in context_lower for marker in ("opening date", "opens on", "application opens", "start date")):
                opening_candidates.append((parsed, url, context))

        for call in master.get("active_calls") or []:
            deadline = call.get("deadline")
            if deadline:
                try:
                    parsed = datetime.fromisoformat(str(deadline)).date()
                    closing_candidates.append(
                        (parsed, str(call.get("url", "")), str(call.get("title", "")))
                    )
                except ValueError:
                    pass

        for doc in documents:
            for sentence in sentence_chunks(doc.text, min_chars=10):
                if not any(
                    marker in sentence.casefold()
                    for marker in (
                        "last date", "deadline", "closing date", "opening date",
                        "opens on", "application opens", "submission by",
                    )
                ):
                    continue
                for pattern in DATE_PATTERNS:
                    for match in pattern.finditer(sentence):
                        add_date(match.group(0), sentence, doc.url)

        opening = max((item[0] for item in opening_candidates), default=None)
        closing = max((item[0] for item in closing_candidates), default=None)

        if opening_candidates:
            latest = max(opening_candidates, key=lambda item: item[0])
            evidence.append(
                self._evidence(
                    field="opening_date",
                    value=opening.isoformat() if opening else None,
                    url=latest[1],
                    quote=latest[2],
                    method="date-context",
                    confidence=0.84,
                )
            )

        if closing_candidates:
            latest = max(closing_candidates, key=lambda item: item[0])
            evidence.append(
                self._evidence(
                    field="closing_date",
                    value=closing.isoformat() if closing else None,
                    url=latest[1],
                    quote=latest[2],
                    method="deadline-context",
                    confidence=0.9,
                )
            )

        return (
            opening.isoformat() if opening else None,
            closing.isoformat() if closing else None,
            evidence,
        )

    def _extract_contacts(
        self,
        documents: list[SourceDocument],
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        contacts: list[dict[str, str]] = []
        evidence: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for doc in documents:
            text = doc.text

            for match in EMAIL_RE.finditer(text):
                email = match.group(0)
                key = ("email", email.casefold())
                if key not in seen:
                    seen.add(key)
                    contacts.append({"type": "email", "value": email})
                    evidence.append(
                        self._evidence(
                            field="contact_details",
                            value=email,
                            url=doc.url,
                            quote=text[max(0, match.start() - 80): match.end() + 80],
                            method="email-pattern",
                            confidence=0.95,
                        )
                    )

            for match in OBFUSCATED_EMAIL_RE.finditer(text):
                email = f"{match.group(1)}.{match.group(2)}@{match.group(3)}"
                key = ("email", email.casefold())
                if key not in seen:
                    seen.add(key)
                    contacts.append({"type": "email", "value": email})
                    evidence.append(
                        self._evidence(
                            field="contact_details",
                            value=email,
                            url=doc.url,
                            quote=match.group(0),
                            method="obfuscated-email-pattern",
                            confidence=0.8,
                        )
                    )

            for match in PHONE_RE.finditer(text):
                raw = normalize_space(match.group(0))
                digits = re.sub(r"\D", "", raw)
                if not (10 <= len(digits) <= 12):
                    continue
                key = ("phone", digits)
                if key not in seen:
                    seen.add(key)
                    contacts.append({"type": "phone", "value": raw})
                    evidence.append(
                        self._evidence(
                            field="contact_details",
                            value=raw,
                            url=doc.url,
                            quote=text[max(0, match.start() - 60): match.end() + 60],
                            method="phone-pattern",
                            confidence=0.78,
                        )
                    )

        return contacts[:15], evidence[:15]

    def _extract_application_url(
        self,
        documents: list[SourceDocument],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        scored: list[tuple[int, str, str, str]] = []
        for doc in documents:
            for link in doc.links:
                url = normalize_space(link.get("url"))
                anchor = normalize_space(link.get("text"))
                if not url:
                    continue

                haystack = f"{anchor} {url}".casefold()
                score = 0
                for marker, weight in (
                    ("apply now", 10),
                    ("apply online", 10),
                    ("application portal", 9),
                    ("register", 7),
                    ("application", 6),
                    ("apply", 6),
                    ("submission", 4),
                    ("login", 2),
                ):
                    if marker in haystack:
                        score += weight

                if any(
                    bad in haystack
                    for bad in ("guideline", ".pdf", "privacy", "terms", "result", "archive")
                ):
                    score -= 8

                if score > 0:
                    scored.append((score, url, anchor, doc.url))

        if not scored:
            return None, []

        scored.sort(key=lambda item: (-item[0], len(item[1])))
        score, url, anchor, source_url = scored[0]
        return (
            url,
            [
                self._evidence(
                    field="application_url",
                    value=url,
                    url=source_url,
                    quote=anchor or url,
                    method="application-link-ranking",
                    confidence=min(0.95, 0.55 + score / 20),
                )
            ],
        )

    def _extract_geographic_scope(
        self,
        combined_text: str,
        source: str,
    ) -> tuple[str, list[str]]:
        lower = combined_text.casefold()
        matched_states = [
            state for state in STATE_NAMES if state.casefold() in lower
        ]

        if matched_states:
            return "State / UT specific", matched_states

        if any(marker in lower for marker in ("across india", "all india", "pan india", "throughout india")):
            return "National (India)", []

        if source in {"Startup India", "DST", "BIRAC", "MeitY Startup Hub"}:
            return "National (India) - inferred from national authority", []

        return "Not clearly stated", []

    @staticmethod
    def _extract_short_name(name: str, documents: list[SourceDocument]) -> str:
        match = re.search(r"\(([A-Z][A-Z0-9-]{1,12})\)", name)
        if match:
            return match.group(1)

        known_acronyms = (
            "SISFS", "CGSS", "BIG", "BIPP", "SBIRI", "CRS",
            "PACE", "E-YUVA", "BioNEST", "NSTEDB", "INSPIRE", "IJCSP",
            "SAMRIDH", "TIDE 2.0", "TIDE", "SASACT", "GENESIS", "SITAA",
        )
        haystack = " ".join([name] + [doc.title for doc in documents])
        for acronym in known_acronyms:
            if acronym.casefold() in haystack.casefold():
                return acronym
        return ""

    def _scheme_status(
        self,
        master: dict[str, Any],
        closing_date: str | None,
    ) -> str:
        if closing_date:
            try:
                closing = datetime.fromisoformat(closing_date).date()
                if closing >= self.as_of_date:
                    return "OPEN_FOR_APPLICATIONS"
                return "CLOSED_OR_DEADLINE_PASSED"
            except ValueError:
                pass

        current_status = str(master.get("current_status", ""))
        if current_status == "ACTIVE_CALL_OPEN":
            return "OPEN_STATUS_REQUIRES_DEADLINE_VERIFICATION"
        if current_status == "SCHEME_INFORMATION_AVAILABLE":
            return "SCHEME_INFORMATION_AVAILABLE_STATUS_UNVERIFIED"
        if current_status == "HISTORICAL_EVIDENCE_ONLY":
            return "HISTORICAL_OR_CURRENT_STATUS_UNVERIFIED"
        return "STATUS_UNVERIFIED"

    def extract(
        self,
        *,
        master: dict[str, Any],
        documents: list[SourceDocument],
    ) -> dict[str, Any]:
        scheme_name = normalize_space(master.get("canonical_name")) or "Unnamed scheme"
        source = normalize_space(master.get("source"))
        authority = dict(self.source_authorities.get(source) or {})
        combined_text = self._combined_text(documents)

        eligibility_raw, eligibility_evidence = self._section_matches(documents, "eligibility")
        benefits_raw, benefits_evidence = self._section_matches(documents, "benefits")
        application_raw, application_evidence = self._section_matches(documents, "application_process")
        documents_raw, documents_evidence = self._section_matches(documents, "required_documents")
        objectives_raw, objectives_evidence = self._section_matches(documents, "objectives")
        selection_raw, selection_evidence = self._section_matches(documents, "selection_process")

        eligibility = self._clean_list_items(eligibility_raw)
        benefits = self._clean_list_items(benefits_raw)
        application_process = self._clean_list_items(application_raw)
        required_documents = self._clean_list_items(documents_raw)
        objectives = self._clean_list_items(objectives_raw, max_items=8)
        selection_process = self._clean_list_items(selection_raw, max_items=8)

        funding_amount, funding_evidence = self._extract_funding(documents, benefits)
        opening_date, closing_date, date_evidence = self._extract_dates(documents, master)
        contacts, contact_evidence = self._extract_contacts(documents)
        application_url, application_url_evidence = self._extract_application_url(documents)

        target_beneficiaries = self._extract_categories(combined_text, TARGET_BENEFICIARIES)
        startup_stage = self._extract_categories(combined_text, STARTUP_STAGES)
        sectors = self._extract_categories(combined_text, SECTORS)
        scheme_types = self._extract_categories(combined_text, SCHEME_TYPES)
        geographic_scope, states = self._extract_geographic_scope(combined_text, source)

        official_url = (
            normalize_space(master.get("official_page_url"))
            or normalize_space(master.get("best_available_url"))
            or (documents[0].url if documents else "")
        )

        guideline_urls = unique_preserve(
            item.get("url", "")
            for item in (master.get("supporting_documents") or [])
            if str(item.get("classification", "")).upper() in {"GUIDELINE", "POLICY"}
        )

        evidence_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in (
            eligibility_evidence
            + benefits_evidence
            + application_evidence
            + documents_evidence
            + objectives_evidence
            + selection_evidence
            + funding_evidence
            + date_evidence
            + contact_evidence
            + application_url_evidence
        ):
            evidence_map[item["field"]].append(item)

        evidence_map["scheme_name"].append(
            self._evidence(
                field="scheme_name",
                value=scheme_name,
                url=official_url,
                quote=scheme_name,
                method="master-candidate",
                confidence=0.98,
            )
        )

        for field_name in ("ministry", "department", "implementing_agency"):
            value = normalize_space(authority.get(field_name))
            if value:
                evidence_map[field_name].append(
                    self._evidence(
                        field=field_name,
                        value=value,
                        url=normalize_space(authority.get("official_url")) or official_url,
                        quote=normalize_space(authority.get("evidence_note")) or f"Configured authority for {source}",
                        method="source-authority-config",
                        confidence=float(authority.get("confidence", 0.82)),
                    )
                )

        essential_checks = {
            "scheme_name": bool(scheme_name),
            "official_page_url": bool(official_url),
            "eligibility": bool(eligibility),
            "benefits": bool(benefits),
            "application_process": bool(application_process or application_url),
            "implementing_agency": bool(authority.get("implementing_agency") or source),
            "funding": bool(funding_amount["amount_mentions"] or scheme_types),
            "source_documents": bool(documents),
        }

        extraction_confidence = sum(essential_checks.values()) / len(essential_checks)
        quality_flags: list[str] = []
        if not eligibility:
            quality_flags.append("ELIGIBILITY_NOT_FOUND")
        if not benefits:
            quality_flags.append("BENEFITS_NOT_FOUND")
        if not application_process and not application_url:
            quality_flags.append("APPLICATION_PROCESS_NOT_FOUND")
        if not required_documents:
            quality_flags.append("REQUIRED_DOCUMENTS_NOT_FOUND")
        if not funding_amount["amount_mentions"]:
            quality_flags.append("EXPLICIT_FUNDING_AMOUNT_NOT_FOUND")
        if not closing_date and master.get("current_status") == "ACTIVE_CALL_OPEN":
            quality_flags.append("ACTIVE_CALL_DEADLINE_NOT_VERIFIED")
        if not documents:
            quality_flags.append("NO_SOURCE_DOCUMENTS_FETCHED")

        source_evidence = [
            {
                "url": doc.url,
                "title": doc.title,
                "content_kind": doc.kind,
                "source_hash": doc.source_hash,
                "fetched_at": doc.fetched_at,
                "rendered_with_browser": bool(doc.metadata.get("rendered_with_browser")),
                "text_length": len(doc.text),
            }
            for doc in documents
        ]

        return {
            "master_id": master.get("master_id"),
            "scheme_name": scheme_name,
            "short_name": self._extract_short_name(scheme_name, documents),
            "source": source,
            "ministry": normalize_space(authority.get("ministry")),
            "department": normalize_space(authority.get("department")),
            "implementing_agency": normalize_space(authority.get("implementing_agency")) or source,
            "scheme_type": scheme_types,
            "target_beneficiaries": target_beneficiaries,
            "startup_stage": startup_stage,
            "sector": sectors,
            "geographic_scope": geographic_scope,
            "states_or_uts": states,
            "objectives": objectives,
            "eligibility": eligibility,
            "benefits": benefits,
            "funding_amount": funding_amount,
            "application_process": application_process,
            "selection_process": selection_process,
            "required_documents": required_documents,
            "application_url": application_url,
            "official_page_url": official_url,
            "guideline_urls": guideline_urls,
            "opening_date": opening_date,
            "closing_date": closing_date,
            "scheme_status": self._scheme_status(master, closing_date),
            "contact_details": contacts,
            "source_evidence": source_evidence,
            "field_evidence": dict(evidence_map),
            "quality_flags": quality_flags,
            "extraction_confidence": round(extraction_confidence, 3),
            "master_readiness": master.get("readiness"),
            "master_current_status": master.get("current_status"),
            "extracted_at": utc_now_iso(),
            "extractor_version": "1.0.0",
        }
