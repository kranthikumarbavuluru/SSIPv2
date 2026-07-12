from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)

VALIDATOR_VERSION = "1.0.0"

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

DATE_CONTEXT_TERMS = (
    "deadline",
    "closing date",
    "last date",
    "last submission date",
    "last date to apply",
    "applications close",
    "application closes",
    "apply by",
    "submission date",
)

NOISE_MARKERS = (
    "annual reports",
    "compliance",
    " rti ",
    "dbt-birac mou",
    "tenders",
    "vacancy",
    "what's new",
    "official website",
    "last updated",
    "copyright",
    "supported projects",
    "contact us",
    "about us",
)

GENERIC_APPLICATION_PATHS = (
    "/announcement/applications-invited-throughout-year",
    "/bhaskar/register",
)

CENTRAL_SOURCES = {"BIRAC", "DST", "Startup India"}

BILATERAL_COUNTRY_NAMES = (
    "Austria",
    "Japan",
    "United States",
    "U.S.",
    "USA",
    "Germany",
    "France",
    "Australia",
    "Israel",
    "Canada",
    "United Kingdom",
    "UK",
    "Korea",
    "Singapore",
)


@dataclass
class ValidationRunResult:
    approved_records: list[dict[str, Any]]
    review_queue: list[dict[str, Any]]
    rejected_records: list[dict[str, Any]]
    audit_records: list[dict[str, Any]]
    summary: dict[str, Any]


class SchemeValidationAgentV1:
    """Evidence-aware validation and normalization for extracted scheme records.

    This validator is intentionally deterministic. It does not fabricate missing fields.
    It corrects common extraction errors, preserves field-level audit information, and
    routes uncertain records to an admin review queue.
    """

    def __init__(
        self,
        *,
        as_of_date: date | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        env_as_of = os.getenv("SSIP_VALIDATION_AS_OF", "").strip()
        if as_of_date is None and env_as_of:
            as_of_date = date.fromisoformat(env_as_of)
        self.as_of_date = as_of_date or date.today()
        self.config = self._load_config(config_path)

    def run(
        self,
        *,
        input_path: str | Path,
        failure_path: str | Path | None = None,
        output_dir: str | Path,
        limit: int | None = None,
    ) -> ValidationRunResult:
        input_path = Path(input_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        records = self._load_json_list(input_path)
        failures = self._load_json_list(Path(failure_path)) if failure_path else []

        if limit is None:
            env_limit = os.getenv("SSIP_VALIDATION_LIMIT", "").strip()
            if env_limit:
                limit = max(0, int(env_limit))
        if limit:
            records = records[:limit]

        audit_records: list[dict[str, Any]] = []
        approved: list[dict[str, Any]] = []
        review_queue: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for record in records:
            validated = self.validate_record(record)
            audit_records.append(validated)
            decision = validated["validation"]["decision"]
            if decision == "APPROVED_FOR_DATABASE":
                approved.append(validated)
            elif decision in {"NEEDS_ADMIN_REVIEW", "NEEDS_MORE_EVIDENCE"}:
                review_queue.append(self._to_review_item(validated))
            else:
                rejected.append(validated)

        summary = self._build_summary(
            input_path=input_path,
            input_count=len(records),
            original_failure_count=len(failures),
            approved=approved,
            review_queue=review_queue,
            rejected=rejected,
            audit_records=audit_records,
        )

        self._write_json(output_dir / "validated_scheme_records_v1.json", approved)
        self._write_json(output_dir / "admin_review_queue_v1.json", review_queue)
        self._write_json(output_dir / "rejected_scheme_records_v1.json", rejected)
        self._write_json(output_dir / "validation_audit_v1.json", audit_records)
        self._write_json(output_dir / "validation_summary_v1.json", summary)

        return ValidationRunResult(
            approved_records=approved,
            review_queue=review_queue,
            rejected_records=rejected,
            audit_records=audit_records,
            summary=summary,
        )

    def validate_record(self, source_record: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(source_record)
        corrections: list[dict[str, Any]] = []
        warnings: list[str] = []
        critical_flags: list[str] = []

        record_kind = self._infer_record_kind(record)

        for field in ("objectives", "eligibility", "benefits", "application_process", "selection_process", "required_documents"):
            before = list(record.get(field) or [])
            after = self._clean_text_list(before, field=field)
            record[field] = after
            if after != before:
                corrections.append(self._correction(field, before, after, "Removed navigation, footer, fragments, duplicates, or misclassified text."))

        geographic_scope, states = self._validate_geography(record)
        if geographic_scope != record.get("geographic_scope") or states != (record.get("states_or_uts") or []):
            corrections.append(
                self._correction(
                    "geographic_scope",
                    {"scope": record.get("geographic_scope"), "states_or_uts": record.get("states_or_uts") or []},
                    {"scope": geographic_scope, "states_or_uts": states},
                    "Central-government pages often contain state names in navigation or contact addresses; geography was normalized from programme context.",
                )
            )
        record["geographic_scope"] = geographic_scope
        record["states_or_uts"] = states

        validated_contacts, removed_contacts = self._validate_contacts(record)
        if removed_contacts or validated_contacts != (record.get("contact_details") or []):
            corrections.append(
                self._correction(
                    "contact_details",
                    record.get("contact_details") or [],
                    validated_contacts,
                    "Rejected date-like phone numbers and restored complete official email domains where supported by evidence.",
                )
            )
        record["contact_details"] = validated_contacts
        if removed_contacts:
            warnings.append("INVALID_CONTACTS_REMOVED")

        funding = self._validate_funding(record)
        if funding != record.get("funding_amount"):
            corrections.append(
                self._correction(
                    "funding_amount",
                    record.get("funding_amount"),
                    funding,
                    "Classified monetary evidence by role and removed section numbers, counts, examples, corpus values, and eligibility thresholds from direct-benefit limits.",
                )
            )
        record["funding_amount"] = funding

        validated_types = self._validate_scheme_types(record, record_kind)
        if validated_types != (record.get("scheme_type") or []):
            corrections.append(
                self._correction(
                    "scheme_type",
                    record.get("scheme_type") or [],
                    validated_types,
                    "Scheme type was re-derived from the scheme name and validated content instead of page navigation menus.",
                )
            )
        record["scheme_type"] = validated_types

        validated_application_url, application_url_status = self._validate_application_url(record)
        if validated_application_url != record.get("application_url"):
            corrections.append(
                self._correction(
                    "application_url",
                    record.get("application_url"),
                    validated_application_url,
                    "Generic registration or announcement links were not accepted as scheme-specific application links.",
                )
            )
        record["application_url"] = validated_application_url
        record["application_url_status"] = application_url_status

        deadline, deadline_evidence = self._resolve_deadline(record)
        original_deadline = record.get("closing_date")
        if deadline != original_deadline:
            corrections.append(
                self._correction(
                    "closing_date",
                    original_deadline,
                    deadline,
                    "Deadline was resolved from explicit deadline/application context and separated from selection or administrative milestone dates.",
                )
            )
        record["closing_date"] = deadline
        record["deadline_evidence"] = deadline_evidence

        programme_status, application_status = self._validate_status(
            record=record,
            record_kind=record_kind,
            deadline=deadline,
        )
        record["record_kind"] = record_kind
        record["programme_status"] = programme_status
        record["application_status"] = application_status

        missing = self._missing_core_fields(record, record_kind)
        warnings.extend(missing)

        evidence_flags = self._evidence_quality_flags(record)
        warnings.extend(evidence_flags)

        if not self._is_official_url(record.get("official_page_url"), record.get("source")):
            critical_flags.append("OFFICIAL_SOURCE_NOT_VERIFIED")
        if not record.get("scheme_name"):
            critical_flags.append("SCHEME_NAME_MISSING")
        if record_kind == "APPLICATION_CALL" and application_status == "DEADLINE_UNVERIFIED":
            warnings.append("ACTIVE_CALL_DEADLINE_UNVERIFIED")
        if record.get("application_url_status") == "GENERIC_OR_UNVERIFIED" and record_kind == "APPLICATION_CALL":
            warnings.append("APPLICATION_LINK_REQUIRES_REVIEW")

        warnings = sorted(set(warnings))
        critical_flags = sorted(set(critical_flags))
        validation_score = self._calculate_score(record, record_kind, warnings, critical_flags)
        decision, decision_reasons = self._make_decision(record, validation_score, warnings, critical_flags)

        record["validation"] = {
            "decision": decision,
            "decision_reasons": decision_reasons,
            "validation_score": round(validation_score, 3),
            "warnings": warnings,
            "critical_flags": critical_flags,
            "corrections": corrections,
            "as_of_date": self.as_of_date.isoformat(),
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "validator_version": VALIDATOR_VERSION,
            "record_hash": self._stable_hash(record),
        }
        return record

    def _load_config(self, config_path: str | Path | None) -> dict[str, Any]:
        defaults = {
            "approval_score": 0.82,
            "review_score": 0.62,
            "minimum_text_length": 24,
            "trusted_domains": {
                "BIRAC": ["birac.nic.in", "www.birac.nic.in"],
                "DST": ["dst.gov.in", "www.dst.gov.in"],
                "Startup India": [
                    "startupindia.gov.in",
                    "www.startupindia.gov.in",
                    "seedfund.startupindia.gov.in",
                    "seedfundapi.startupindia.gov.in",
                ],
            },
        }
        if config_path is None:
            return defaults
        path = Path(config_path)
        if not path.exists():
            return defaults
        loaded = json.loads(path.read_text(encoding="utf-8"))
        defaults.update(loaded)
        return defaults

    @staticmethod
    def _load_json_list(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list in {path}")
        return data

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _correction(field: str, before: Any, after: Any, reason: str) -> dict[str, Any]:
        return {"field": field, "before": before, "after": after, "reason": reason}

    def _infer_record_kind(self, record: dict[str, Any]) -> str:
        name = (record.get("scheme_name") or "").lower()
        master_status = record.get("master_current_status") or ""
        if master_status == "ACTIVE_CALL_OPEN" or any(term in name for term in ("call for", "partnerships to drive innovation", "cooperation")):
            return "APPLICATION_CALL"
        if any(term in name for term in ("board", "umbrella", "nstedb")):
            return "UMBRELLA_PROGRAMME"
        return "SCHEME_OR_PROGRAMME"

    def _clean_text_list(self, values: Iterable[Any], *, field: str) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            if not isinstance(raw, str):
                continue
            text = re.sub(r"\s+", " ", raw).strip(" \t\r\n•-;:")
            if self._is_noise_text(text, field=field):
                continue
            key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
            if not key or key in seen:
                continue
            if any(key in existing or existing in key for existing in seen if len(existing) > 35 and len(key) > 35):
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned

    def _is_noise_text(self, text: str, *, field: str) -> bool:
        minimum_length = int(self.config.get("minimum_text_length", 24))
        if len(text) < minimum_length:
            return True
        lower = f" {text.lower()} "
        marker_count = sum(1 for marker in NOISE_MARKERS if marker in lower)
        if marker_count >= 3:
            return True
        if re.fullmatch(r"page\s+\d+\s+of\s+\d+", text, flags=re.I):
            return True
        if text.lower().startswith(("click here to register annual reports", "click here to register/apply view")):
            return True
        if field == "benefits" and re.match(r"^(no\.|total corpus allocated|investment agreements signed|total investments raised)", text, flags=re.I):
            return True
        if field == "benefits" and text[:1].islower() and len(text) < 140:
            return True
        if field == "benefits" and any(term in lower for term in ("ministry of commerce and industry", "department for promotion of industry", "gazette : extraordinary", "भारत का", "राजपत्र")):
            return True
        if field == "objectives" and any(term in lower for term in ("invocation of guarantee", "claim settlement", "lock-in period", "committee will comprise", "representative of department")):
            return True
        if field == "eligibility" and any(term in lower for term in (
            "this notification shall supersede",
            "the requirement",
            "capital inadequacy",
            "come into effect from",
            "monitoring processes",
            "composition of investment committee",
            "composition of inv estment committee",
            "implementation of the scheme will",
            "will seek proposals from aifs",
            "will consider the proposals",
            "representation from the industry",
            "shall also be the implementing agency",
            "shall also be the implementing agency",
            "out of these, one lakh ideas",
            "covers eligibility criteria",
            "selected to implement the proposed scheme",
            "constituted by dpiit",
            "which would include",
        )):
            return True
        if field == "eligibility" and text[:1].islower() and not re.search(r"\b(must|should|eligible|shall|required|recognized|recognised|registered|minimum|at least)\b", lower):
            return True
        if field == "eligibility" and text[:1] in "‘’\"'" and not re.search(r"\b(must|should|eligible|shall|required|recognized|recognised|registered|minimum|at least)\b", lower):
            return True
        if field == "eligibility" and re.match(r"^[ab]\.\s", text, flags=re.I) and not re.search(r"\b(must|should|eligible|shall|required)\b", lower):
            return True
        if text.count("|") >= 3:
            return True
        return False

    def _validate_geography(self, record: dict[str, Any]) -> tuple[str, list[str]]:
        name = record.get("scheme_name") or ""
        lower = name.lower()
        for country in BILATERAL_COUNTRY_NAMES:
            if country.lower() in lower and any(term in lower for term in ("cooperation", "partnership", "joint", "indo-", "india-")):
                return f"International bilateral programme involving India and {country}", []
        if record.get("source") in CENTRAL_SOURCES:
            return "National (India)", []
        return record.get("geographic_scope") or "Unknown", list(record.get("states_or_uts") or [])

    def _validate_contacts(self, record: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        contacts = record.get("contact_details") or []
        evidence_text = json.dumps(record.get("field_evidence", {}).get("contact_details", []), ensure_ascii=False).lower()
        accepted: list[dict[str, str]] = []
        removed: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for contact in contacts:
            kind = str(contact.get("type") or "").lower()
            value = str(contact.get("value") or "").strip()
            if kind == "email":
                if value.endswith("@nic") and "[at]nic[dot]in" in evidence_text:
                    value += ".in"
                elif value.endswith("@gov") and "[at]gov[dot]in" in evidence_text:
                    value += ".in"
                if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
                    removed.append(contact)
                    continue
            elif kind == "phone":
                if re.search(r"\b20\d{2}\b", value) or re.search(r"\d{1,2}-\d{1,2}-20\d{2}", value):
                    removed.append(contact)
                    continue
                digits = re.sub(r"\D", "", value)
                if len(digits) < 10 or len(digits) > 12:
                    removed.append(contact)
                    continue
                if digits.startswith("91") and len(digits) == 12:
                    value = "+91-" + digits[2:]
                elif len(digits) == 10:
                    value = digits
                else:
                    value = digits
            else:
                removed.append(contact)
                continue
            key = (kind, value.lower())
            if key not in seen:
                seen.add(key)
                accepted.append({"type": kind, "value": value})
        return accepted, removed

    def _validate_funding(self, record: dict[str, Any]) -> dict[str, Any]:
        original = record.get("funding_amount") or {}
        raw_mentions = list(original.get("amount_mentions") or [])
        classified: list[dict[str, Any]] = []
        seen: set[tuple[int, str, str]] = set()

        for mention in raw_mentions:
            context = re.sub(r"\s+", " ", str(mention.get("context") or "")).strip()
            source_url = str(mention.get("source_url") or "")
            parsed_amounts = self._extract_explicit_money(context)
            if not parsed_amounts:
                continue
            for amount, display in parsed_amounts:
                if amount < 1000 and not re.search(r"crore|cr\.?|lakh|lac|million|billion", display, flags=re.I):
                    continue
                role = self._classify_money_role(context)
                if role in {"FALSE_POSITIVE_COUNT", "SECTION_NUMBER", "EXAMPLE_ONLY", "PERFORMANCE_METRIC"}:
                    continue
                key = (amount, role, source_url)
                if key in seen:
                    continue
                seen.add(key)
                classified.append(
                    {
                        "amount": amount,
                        "currency": "INR",
                        "display_text": display,
                        "role": role,
                        "context": context,
                        "source_url": source_url,
                    }
                )

        beneficiary = [m["amount"] for m in classified if m["role"] == "BENEFICIARY_LIMIT"]
        intermediary = [m["amount"] for m in classified if m["role"] == "INTERMEDIARY_LIMIT"]
        corpus = [m["amount"] for m in classified if m["role"] == "SCHEME_CORPUS"]

        minimum: int | None = None
        maximum: int | None = None
        if beneficiary:
            maximum = max(beneficiary)
            if len(set(beneficiary)) > 1:
                minimum = min(beneficiary)

        return {
            "minimum": minimum,
            "maximum": maximum,
            "currency": "INR",
            "funding_types": self._funding_types_from_mentions(record, classified),
            "amount_mentions": classified,
            "beneficiary_support": {
                "minimum": minimum,
                "maximum": maximum,
            },
            "intermediary_support_maximum": max(intermediary) if intermediary else None,
            "scheme_corpus": max(corpus) if corpus else None,
        }

    @staticmethod
    def _extract_explicit_money(context: str) -> list[tuple[int, str]]:
        pattern = re.compile(
            r"(?<![A-Za-z])(?P<currency>₹|INR|Rs\.?)(?:\s*)(?P<number>\d[\d,]*(?:\.\d+)?)"
            r"(?:\s*\([^)]{0,30}\))?\s*(?P<unit>crores?|cr\.?|lakhs?|lacs?|million|billion)?",
            flags=re.I,
        )
        results: list[tuple[int, str]] = []
        for match in pattern.finditer(context):
            raw_number = match.group("number").replace(",", "")
            try:
                number = float(raw_number)
            except ValueError:
                continue
            unit = (match.group("unit") or "").lower().rstrip(".")
            multiplier = 1
            if unit.startswith("crore") or unit == "cr":
                multiplier = 10_000_000
            elif unit.startswith("lakh") or unit.startswith("lac"):
                multiplier = 100_000
            elif unit == "million":
                multiplier = 1_000_000
            elif unit == "billion":
                multiplier = 1_000_000_000
            amount = int(round(number * multiplier))
            if amount <= 0:
                continue
            display = match.group(0).strip()
            results.append((amount, display))
        return results

    @staticmethod
    def _classify_money_role(context: str) -> str:
        lower = context.lower()
        if any(term in lower for term in ("offers ", "fellowships every year", "scholarships every year", "target number")) and not any(term in lower for term in ("grant", "financial support", "assistance", "corpus", "guarantee", "investment")):
            return "FALSE_POSITIVE_COUNT"
        if re.search(r"\b(?:section|clause|guidelines?)\s+\d+(?:\.\d+)?", lower):
            return "SECTION_NUMBER"
        if any(term in lower for term in ("for example", "i.e. if", "for instance")):
            return "EXAMPLE_ONLY"
        if any(term in lower for term in ("revenue of", "net worth of startup", "performance indicator")):
            return "PERFORMANCE_METRIC"
        if any(term in lower for term in ("total corpus", "scheme corpus", "outlay of", "approved the establishment")):
            return "SCHEME_CORPUS"
        if any(term in lower for term in ("minimum networth", "minimum net worth", "should not have received more than", "eligibility")) and not any(term in lower for term in ("grant of up to", "support up to", "guarantee cover")):
            return "ELIGIBILITY_THRESHOLD"
        if any(term in lower for term in ("selected incubator", "grant assistance to incubator", "provided to a selected incubator")):
            return "INTERMEDIARY_LIMIT"
        if any(term in lower for term in (
            "per borrower",
            "guarantee cover",
            "support up to",
            "financial support of up to",
            "grant of up to",
            "up to rs",
            "up to inr",
            "investment for market entry",
            "seed fund to an eligible startup",
            "providing scholarship",
            "mentorship grant",
            "award of rs",
            "award of inr",
        )):
            return "BENEFICIARY_LIMIT"
        return "GENERAL_FINANCIAL_MENTION"

    @staticmethod
    def _funding_types_from_mentions(record: dict[str, Any], mentions: list[dict[str, Any]]) -> list[str]:
        text = " ".join(
            [record.get("scheme_name") or ""]
            + [m.get("context") or "" for m in mentions]
            + list(record.get("benefits") or [])
        ).lower()
        result: list[str] = []
        if "credit guarantee" in text or "guarantee cover" in text:
            result.append("Credit Guarantee")
        if "grant" in text or "financial support" in text or "scholarship" in text:
            result.append("Grant / Scholarship")
        if any(term in text for term in ("debt", "loan", "debenture")):
            result.append("Debt / Loan")
        if any(term in text for term in ("equity", "venture capital", "fund of funds", "aif")):
            result.append("Equity / Fund")
        if not result and mentions:
            result.append("Financial Support")
        return result

    def _validate_scheme_types(self, record: dict[str, Any], record_kind: str) -> list[str]:
        name = (record.get("scheme_name") or "").lower()
        text = " ".join(
            [name]
            + list(record.get("objectives") or [])
            + list(record.get("benefits") or [])
            + list(record.get("application_process") or [])
        ).lower()
        result: list[str] = []
        if record_kind == "APPLICATION_CALL":
            result.append("Challenge / Call")
        if "credit guarantee" in name:
            result.append("Credit Guarantee")
        elif "fund of funds" in name:
            result.append("Equity / Fund")
        elif "seed fund" in name:
            result.extend(["Seed Fund", "Grant", "Debt / Convertible Instruments"])
        elif "inspire" in name:
            result.extend(["Scholarship", "Fellowship", "Grant"])
        elif "nstedb" in name or "entrepreneurship development board" in name:
            result.extend(["Entrepreneurship Support", "Incubation Support"])
        else:
            funding_types = record.get("funding_amount", {}).get("funding_types") or []
            result.extend(funding_types)
            if "incubat" in text:
                result.append("Incubation Support")
        deduped: list[str] = []
        for item in result:
            if item and item not in deduped:
                deduped.append(item)
        return deduped

    def _validate_application_url(self, record: dict[str, Any]) -> tuple[str | None, str]:
        url = record.get("application_url")
        name = (record.get("scheme_name") or "").lower()
        if not url:
            if any(term in name for term in ("fund of funds", "credit guarantee")):
                return None, "INDIRECT_OR_INTERMEDIARY_APPLICATION"
            return None, "NOT_FOUND"
        parsed = urlparse(url)
        path = parsed.path.lower()
        if any(path.endswith(generic) or generic in path for generic in GENERIC_APPLICATION_PATHS):
            return None, "GENERIC_OR_UNVERIFIED"
        if parsed.netloc.endswith("birac.nic.in") and path.endswith("/login.php"):
            return url, "GENERAL_OFFICIAL_PORTAL"
        if self._is_official_url(url, record.get("source")):
            return url, "OFFICIAL_LINK"
        return None, "UNTRUSTED_DOMAIN"

    def _resolve_deadline(self, record: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        candidates: list[tuple[int, date, str]] = []
        nested_texts = self._iter_nested_strings(
            {
                "field_evidence": record.get("field_evidence"),
                "funding_amount": record.get("funding_amount"),
                "source_evidence": record.get("source_evidence"),
                "closing_date": record.get("closing_date"),
            }
        )
        for text in nested_texts:
            lower = text.lower()
            if not any(term in lower for term in DATE_CONTEXT_TERMS):
                continue
            for parsed_date, raw, start, end in self._extract_dates(text):
                score = 1
                before = lower[max(0, start - 120):start]
                after = lower[end:min(len(lower), end + 100)]
                window = before + " " + lower[start:end] + " " + after
                nearest_prefix = lower[max(0, start - 70):start]
                if any(term in nearest_prefix for term in ("last date to apply", "last submission date", "closing date", "deadline", "apply under")):
                    score += 8
                elif any(term in window for term in ("last date to apply", "last submission date", "closing date", "deadline")):
                    score += 4
                if "startup" in nearest_prefix and ("apply" in nearest_prefix or "application" in nearest_prefix):
                    score += 6
                if any(term in nearest_prefix for term in ("selection by", "complete 100%", "incubators to complete", "announcement date", "starting date")):
                    score -= 8
                if "selection" in window and "apply" not in nearest_prefix:
                    score -= 4
                candidates.append((score, parsed_date, text[max(0, start - 180):min(len(text), end + 180)]))

        if not candidates and record.get("closing_date"):
            try:
                parsed = date.fromisoformat(str(record["closing_date"]))
                return parsed.isoformat(), {"method": "extractor-value", "confidence": 0.7}
            except ValueError:
                pass
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        score, best_date, evidence = candidates[0]
        return best_date.isoformat(), {"method": "deadline-context-validation", "confidence": min(0.98, 0.65 + score * 0.04), "quote": evidence}

    @staticmethod
    def _extract_dates(text: str) -> list[tuple[date, str, int, int]]:
        results: list[tuple[date, str, int, int]] = []
        numeric = re.compile(r"\b([0-3]?\d)[-/]([01]?\d)[-/](20\d{2})\b")
        named = re.compile(
            r"\b([0-3]?\d)(?:\s*(?:st|nd|rd|th))?\s+"
            r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
            r"[,]?\s+(20\d{2})\b",
            flags=re.I,
        )
        for match in numeric.finditer(text):
            try:
                parsed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            except ValueError:
                continue
            results.append((parsed, match.group(0), match.start(), match.end()))
        for match in named.finditer(text):
            month = MONTHS[match.group(2).lower()]
            try:
                parsed = date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                continue
            results.append((parsed, match.group(0), match.start(), match.end()))
        return results

    def _validate_status(self, *, record: dict[str, Any], record_kind: str, deadline: str | None) -> tuple[str, str]:
        deadline_date = date.fromisoformat(deadline) if deadline else None
        name = (record.get("scheme_name") or "").lower()
        if record_kind == "APPLICATION_CALL":
            if deadline_date:
                if deadline_date >= self.as_of_date:
                    return "CALL_INFORMATION_CURRENT", "OPEN"
                return "CALL_INFORMATION_AVAILABLE", "CLOSED"
            return "CALL_INFORMATION_CURRENT", "DEADLINE_UNVERIFIED"
        if record_kind == "UMBRELLA_PROGRAMME":
            return "UMBRELLA_PROGRAMME_INFORMATION_AVAILABLE", "NOT_A_SINGLE_APPLICATION_WINDOW"
        if "fund of funds" in name:
            return "SCHEME_INFORMATION_AVAILABLE", "NOT_DIRECTLY_APPLICABLE_BY_STARTUPS"
        if "credit guarantee" in name:
            return "SCHEME_INFORMATION_AVAILABLE", "APPLY_THROUGH_MEMBER_INSTITUTION"
        if "inspire" in name:
            return "SCHEME_INFORMATION_AVAILABLE", "COMPONENT_SPECIFIC"
        if deadline_date:
            return "SCHEME_INFORMATION_AVAILABLE", "OPEN" if deadline_date >= self.as_of_date else "CLOSED"
        return "SCHEME_INFORMATION_AVAILABLE", "STATUS_UNVERIFIED"

    def _missing_core_fields(self, record: dict[str, Any], record_kind: str) -> list[str]:
        missing: list[str] = []
        if not record.get("eligibility"):
            missing.append("ELIGIBILITY_REQUIRES_EVIDENCE")
        if not record.get("benefits") and not record.get("funding_amount", {}).get("maximum") and not record.get("funding_amount", {}).get("scheme_corpus"):
            missing.append("BENEFITS_OR_FUNDING_REQUIRES_EVIDENCE")
        if not record.get("application_process") and record_kind == "APPLICATION_CALL":
            missing.append("APPLICATION_PROCESS_REQUIRES_EVIDENCE")
        if not record.get("required_documents"):
            missing.append("REQUIRED_DOCUMENTS_NOT_VERIFIED")
        if not record.get("objectives"):
            missing.append("OBJECTIVE_REQUIRES_EVIDENCE")
        return missing

    @staticmethod
    def _evidence_quality_flags(record: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        if not record.get("source_evidence"):
            flags.append("SOURCE_EVIDENCE_MISSING")
        if record.get("record_kind") == "SCHEME_OR_PROGRAMME" and len(record.get("source_evidence") or []) == 1:
            flags.append("SINGLE_SOURCE_ONLY")
        if record.get("funding_amount", {}).get("amount_mentions") and not record.get("funding_amount", {}).get("maximum") and not record.get("funding_amount", {}).get("scheme_corpus"):
            flags.append("FUNDING_MENTIONS_NOT_DIRECT_BENEFIT")
        return flags

    def _calculate_score(self, record: dict[str, Any], record_kind: str, warnings: list[str], critical_flags: list[str]) -> float:
        score = 0.0
        if self._is_official_url(record.get("official_page_url"), record.get("source")):
            score += 0.16
        if record.get("scheme_name"):
            score += 0.10
        if record.get("ministry") and record.get("department") and record.get("implementing_agency"):
            score += 0.12
        if record.get("source_evidence"):
            score += 0.10
        if record.get("objectives"):
            score += 0.08
        if record.get("eligibility"):
            score += 0.13
        if record.get("benefits") or record.get("funding_amount", {}).get("maximum") or record.get("funding_amount", {}).get("scheme_corpus"):
            score += 0.13
        if record.get("programme_status"):
            score += 0.08
        if record_kind != "APPLICATION_CALL" or record.get("application_status") in {"OPEN", "CLOSED"}:
            score += 0.05
        if record.get("application_url_status") in {"OFFICIAL_LINK", "GENERAL_OFFICIAL_PORTAL", "INDIRECT_OR_INTERMEDIARY_APPLICATION"}:
            score += 0.05
        score -= 0.025 * len(warnings)
        score -= 0.25 * len(critical_flags)
        return max(0.0, min(1.0, score))

    def _make_decision(self, record: dict[str, Any], score: float, warnings: list[str], critical_flags: list[str]) -> tuple[str, list[str]]:
        approval_score = float(self.config.get("approval_score", 0.82))
        review_score = float(self.config.get("review_score", 0.62))
        reasons: list[str] = []

        if critical_flags:
            reasons.extend(critical_flags)
            if score < 0.35:
                return "REJECTED", reasons
            return "NEEDS_MORE_EVIDENCE", reasons

        name = (record.get("scheme_name") or "").lower()
        if record.get("record_kind") == "UMBRELLA_PROGRAMME":
            reasons.append("Umbrella programme should be split into component schemes before publication.")
            return "NEEDS_ADMIN_REVIEW", reasons
        if record.get("record_kind") == "APPLICATION_CALL" and record.get("application_status") == "DEADLINE_UNVERIFIED":
            reasons.append("Current call deadline could not be verified.")
            return "NEEDS_MORE_EVIDENCE", reasons
        if "APPLICATION_PROCESS_REQUIRES_EVIDENCE" in warnings and record.get("record_kind") == "APPLICATION_CALL":
            reasons.append("Call is discoverable, but the application process is incomplete.")
            return "NEEDS_MORE_EVIDENCE", reasons
        if "ELIGIBILITY_REQUIRES_EVIDENCE" in warnings and record.get("record_kind") == "APPLICATION_CALL":
            reasons.append("Eligibility is required before the call can be published.")
            return "NEEDS_MORE_EVIDENCE", reasons
        if record.get("application_url_status") == "GENERIC_OR_UNVERIFIED" and record.get("record_kind") == "APPLICATION_CALL":
            reasons.append("A scheme-specific application link must be confirmed.")
            return "NEEDS_ADMIN_REVIEW", reasons
        if score >= approval_score:
            reasons.append("Official source, core content, lifecycle status, and financial evidence meet the publication threshold.")
            return "APPROVED_FOR_DATABASE", reasons
        if score >= review_score:
            reasons.append("Record is credible but one or more fields require admin confirmation.")
            return "NEEDS_ADMIN_REVIEW", reasons
        reasons.append("Core eligibility, benefit, application, or status evidence is incomplete.")
        if "fund of funds" in name and record.get("funding_amount", {}).get("scheme_corpus"):
            return "NEEDS_ADMIN_REVIEW", reasons
        return "NEEDS_MORE_EVIDENCE", reasons

    def _is_official_url(self, url: str | None, source: str | None) -> bool:
        if not url:
            return False
        host = (urlparse(url).hostname or "").lower()
        trusted = self.config.get("trusted_domains", {}).get(source or "", [])
        return any(host == domain or host.endswith("." + domain) for domain in trusted)

    @staticmethod
    def _iter_nested_strings(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for nested in value.values():
                yield from SchemeValidationAgentV1._iter_nested_strings(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from SchemeValidationAgentV1._iter_nested_strings(nested)

    @staticmethod
    def _stable_hash(record: dict[str, Any]) -> str:
        copy_record = copy.deepcopy(record)
        copy_record.pop("validation", None)
        payload = json.dumps(copy_record, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _to_review_item(record: dict[str, Any]) -> dict[str, Any]:
        validation = record["validation"]
        return {
            "master_id": record.get("master_id"),
            "scheme_name": record.get("scheme_name"),
            "source": record.get("source"),
            "record_kind": record.get("record_kind"),
            "programme_status": record.get("programme_status"),
            "application_status": record.get("application_status"),
            "official_page_url": record.get("official_page_url"),
            "application_url": record.get("application_url"),
            "decision": validation["decision"],
            "validation_score": validation["validation_score"],
            "decision_reasons": validation["decision_reasons"],
            "warnings": validation["warnings"],
            "critical_flags": validation["critical_flags"],
            "corrections_count": len(validation["corrections"]),
            "recommended_admin_actions": SchemeValidationAgentV1._recommended_actions(record),
            "validated_record": record,
        }

    @staticmethod
    def _recommended_actions(record: dict[str, Any]) -> list[str]:
        warnings = set(record.get("validation", {}).get("warnings", []))
        actions: list[str] = []
        if "ELIGIBILITY_REQUIRES_EVIDENCE" in warnings:
            actions.append("Confirm eligibility from the official guideline, RFP, or application portal.")
        if "BENEFITS_OR_FUNDING_REQUIRES_EVIDENCE" in warnings:
            actions.append("Confirm the exact financial/non-financial benefit and beneficiary-level limit.")
        if "APPLICATION_PROCESS_REQUIRES_EVIDENCE" in warnings:
            actions.append("Confirm the step-by-step application process and official application link.")
        if "ACTIVE_CALL_DEADLINE_UNVERIFIED" in warnings:
            actions.append("Confirm the latest closing date or extension notice.")
        if record.get("record_kind") == "UMBRELLA_PROGRAMME":
            actions.append("Create separate records for each component programme instead of publishing the umbrella page as one scheme.")
        if not actions:
            actions.append("Review corrections and approve or edit the normalized record.")
        return actions

    def _build_summary(
        self,
        *,
        input_path: Path,
        input_count: int,
        original_failure_count: int,
        approved: list[dict[str, Any]],
        review_queue: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        audit_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        decision_counts = Counter(r["validation"]["decision"] for r in audit_records)
        source_counts = Counter(r.get("source") or "UNKNOWN" for r in audit_records)
        programme_status_counts = Counter(r.get("programme_status") or "UNKNOWN" for r in audit_records)
        application_status_counts = Counter(r.get("application_status") or "UNKNOWN" for r in audit_records)
        warning_counts = Counter(w for r in audit_records for w in r["validation"]["warnings"])
        correction_count = sum(len(r["validation"]["corrections"]) for r in audit_records)
        scores = [r["validation"]["validation_score"] for r in audit_records]
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "input_record_count": input_count,
            "upstream_failure_count": original_failure_count,
            "approved_for_database_count": len(approved),
            "admin_review_queue_count": len(review_queue),
            "rejected_count": len(rejected),
            "records_by_decision": dict(decision_counts),
            "records_by_source": dict(source_counts),
            "records_by_programme_status": dict(programme_status_counts),
            "records_by_application_status": dict(application_status_counts),
            "warning_counts": dict(warning_counts),
            "total_field_corrections": correction_count,
            "average_validation_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
            "input_path": str(input_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "validator_version": VALIDATOR_VERSION,
        }
