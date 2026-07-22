from __future__ import annotations

from dataclasses import dataclass, field
import ast
import json
import math
import re
from typing import Any

import pandas as pd

from .config import CatalogueMode, DashboardConfig
from .data_access import read_dashboard_tables, read_normalization_plan
from .msme_supplement import load_active_msme_supplement, load_active_mymsme_supplement
from .media_supplement import load_active_media_publication


URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+", re.IGNORECASE)


@dataclass
class CatalogueRecord:
    master_id: str
    scheme_name: str
    source: str = ""
    ministry: str = ""
    department: str = ""
    implementing_agency: str = ""
    parent_master_id: str = ""
    parent_scheme_name: str = ""
    applicant_layer: str = ""
    implementation_role: str = ""
    status_basis: str = ""
    status_evidence: str = ""
    last_verified_at: str = ""
    record_kind: str = ""
    programme_status: str = ""
    application_status: str = ""
    geographic_scope: str = ""
    catalogue_inclusion: str = ""
    catalogue_section: str = ""
    publication_status: str = ""
    is_public: int = 0
    current_location: str = ""
    current_review_status: str = ""
    current_decision: str = ""
    official_page_url: str = ""
    application_url: str = ""
    opening_date: str = ""
    closing_date: str = ""
    validation_score: float | None = None
    currency: str = "INR"
    funding_minimum: int | None = None
    funding_maximum: int | None = None
    funding_amount_status: str = "NOT_STATED"
    funding_amount_optional: bool = True
    funding_evidence: Any = None
    beneficiary_support_minimum: int | None = None
    beneficiary_support_maximum: int | None = None
    intermediary_support_maximum: int | None = None
    scheme_corpus: int | None = None
    objectives: list[str] = field(default_factory=list)
    eligibility: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    application_process: list[str] = field(default_factory=list)
    required_documents: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    scheme_types: list[str] = field(default_factory=list)
    target_beneficiaries: list[str] = field(default_factory=list)
    startup_stage: list[str] = field(default_factory=list)
    guideline_urls: list[str] = field(default_factory=list)
    reference_urls: list[str] = field(default_factory=list)
    verified_public_actions: list[dict[str, Any]] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    decision_reasons: list[str] = field(default_factory=list)
    last_updated: str = ""
    search_blob: str = ""


@dataclass
class CatalogueBundle:
    records: list[CatalogueRecord]
    mode: CatalogueMode
    metadata: dict[str, Any]


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"none", "nan", "nat", "null"}


def first_value(*values: Any) -> Any:
    for value in values:
        if not is_blank(value):
            return value
    return None


def as_text(value: Any) -> str:
    if is_blank(value):
        return ""
    return str(value).strip()


def as_int(value: Any) -> int | None:
    if is_blank(value):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None


def as_float(value: Any) -> float | None:
    if is_blank(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def safe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if is_blank(value):
        return None
    text = str(value).strip()
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return None


def text_item(value: Any) -> str:
    if is_blank(value):
        return ""
    if isinstance(value, dict):
        preferred = first_value(
            value.get("value"),
            value.get("name"),
            value.get("title"),
            value.get("label"),
            value.get("description"),
            value.get("text"),
            value.get("url"),
        )
        if not is_blank(preferred):
            return as_text(preferred)
        parts = [f"{key}: {item}" for key, item in value.items() if not is_blank(item)]
        return "; ".join(parts)
    return as_text(value)


def dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = as_text(item).strip(" -*\t")
        key = text.casefold()
        if key and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def to_list(value: Any) -> list[str]:
    if is_blank(value):
        return []
    parsed = safe_json(value)
    if isinstance(parsed, list):
        return dedupe([text_item(item) for item in parsed])
    if isinstance(parsed, dict):
        return dedupe([text_item(parsed)])
    text = as_text(value)
    if text.startswith("[") and text.endswith("]"):
        parsed = safe_json(text)
        if isinstance(parsed, list):
            return to_list(parsed)
    pieces = re.split(r"\s*[|;\n]\s*", text)
    return dedupe([piece for piece in pieces if piece.strip()])


def collect_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            urls.extend(collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(collect_urls(item))
    elif not is_blank(value):
        urls.extend(URL_RE.findall(str(value)))
    return dedupe([url.rstrip(".,;") for url in urls])


def safe_url(value: Any) -> str:
    if is_blank(value):
        return ""
    match = URL_RE.search(str(value))
    return match.group(0).rstrip(".,;") if match else ""


def deep_find(value: Any, names: list[str]) -> Any:
    wanted = {name.casefold() for name in names}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in wanted and not is_blank(item):
                return item
        for item in value.values():
            found = deep_find(item, names)
            if not is_blank(found):
                return found
    if isinstance(value, list):
        for item in value:
            found = deep_find(item, names)
            if not is_blank(found):
                return found
    return None


def frame_by_master_id(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "master_id" not in frame.columns:
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict(orient="records"):
        master_id = as_text(row.get("master_id"))
        if master_id:
            output[master_id] = row
    return output


def attributes_by_master_id(frame: pd.DataFrame) -> dict[str, dict[str, list[str]]]:
    output: dict[str, dict[str, list[str]]] = {}
    if frame.empty or "master_id" not in frame.columns:
        return output
    for row in frame.to_dict(orient="records"):
        master_id = as_text(row.get("master_id"))
        group = as_text(row.get("attribute_group") or row.get("attribute_name"))
        value = as_text(row.get("value") or row.get("attribute_value"))
        if master_id and group and value:
            output.setdefault(master_id, {}).setdefault(group.casefold(), []).append(value)
    for master_id, groups in output.items():
        for group, values in groups.items():
            groups[group] = dedupe(values)
    return output


def values_for(
    attributes: dict[str, dict[str, list[str]]],
    master_id: str,
    groups: list[str],
) -> list[str]:
    wanted = {group.casefold() for group in groups}
    values: list[str] = []
    for group, items in attributes.get(master_id, {}).items():
        if group in wanted:
            values.extend(items)
    return dedupe(values)


def contacts_by_master_id(frame: pd.DataFrame) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    if frame.empty or "master_id" not in frame.columns:
        return output
    for row in frame.to_dict(orient="records"):
        master_id = as_text(row.get("master_id"))
        contact = as_text(row.get("contact_value") or row.get("contact"))
        contact_type = as_text(row.get("contact_type"))
        if master_id and contact:
            label = f"{contact_type}: {contact}" if contact_type else contact
            output.setdefault(master_id, []).append(label)
    return {key: dedupe(values) for key, values in output.items()}


def source_urls_by_master_id(frame: pd.DataFrame) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    if frame.empty or "master_id" not in frame.columns:
        return output
    for row in frame.to_dict(orient="records"):
        master_id = as_text(row.get("master_id"))
        if master_id:
            output.setdefault(master_id, []).extend(collect_urls(row))
    return {key: dedupe(values) for key, values in output.items()}


def review_record_allowed(plan_row: dict[str, Any]) -> bool:
    inclusion = as_text(plan_row.get("catalogue_inclusion")).upper()
    section = as_text(plan_row.get("catalogue_section")).upper()
    return (
        inclusion in {"ARCHIVED", "PENDING_REVALIDATION"}
        or "HISTORICAL" in section
        or "CLOSED" in section
    )


def explicit_preview_record_allowed(plan_row: dict[str, Any]) -> bool:
    inclusion = as_text(plan_row.get("catalogue_inclusion")).upper()
    decision = as_text(plan_row.get("current_decision")).upper()
    return inclusion == "INCLUDED" and decision != "REJECTED"


def payload_from_rows(*rows: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for row in rows:
        for key in ("raw_record_json", "validated_record_json"):
            parsed = safe_json(row.get(key))
            if isinstance(parsed, dict):
                payload.update({k: v for k, v in parsed.items() if k not in payload or is_blank(payload[k])})
    nested = deep_find(payload, ["validated_record", "record", "scheme_record", "data"])
    if isinstance(nested, dict):
        payload.update({k: v for k, v in nested.items() if k not in payload or is_blank(payload[k])})
    return payload


def parse_verified_public_actions(
    raw_value: Any,
    schema_version: Any = "",
) -> list[dict[str, Any]]:
    # Return only governed, verified, non-application scheme-detail actions.
    if as_text(schema_version) != "3.4.3.5" or is_blank(raw_value):
        return []

    parsed = safe_json(raw_value)
    if not isinstance(parsed, list):
        return []

    verified: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for item in parsed:
        if not isinstance(item, dict):
            continue

        action_type = as_text(item.get("action_type")).upper()
        link_role = as_text(item.get("link_role")).upper()
        verification_status = as_text(
            item.get("verification_status")
        ).upper()
        is_active = str(item.get("is_active", "")).strip().lower() in {
            "true",
            "1",
            "yes",
        }
        is_time_bound = str(
            item.get("is_time_bound", "")
        ).strip().lower() in {
            "true",
            "1",
            "yes",
        }
        resolved_url = safe_url(item.get("resolved_url"))

        if action_type != "SCHEME_DETAILS":
            continue
        if link_role != "SCHEME_MASTER":
            continue
        if verification_status != "VERIFIED_INFORMATION_PAGE":
            continue
        if not is_active or is_time_bound or not resolved_url:
            continue

        normalized_url = resolved_url.casefold().rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        verified.append(
            {
                "action_id": as_text(item.get("action_id")),
                "action_type": "SCHEME_DETAILS",
                "link_role": "SCHEME_MASTER",
                "label": "Scheme Details",
                "resolved_url": resolved_url,
                "verification_status": "VERIFIED_INFORMATION_PAGE",
                "confidence": as_float(item.get("confidence")),
                "is_active": True,
                "is_time_bound": False,
                "deadline_status": as_text(
                    item.get("deadline_status")
                )
                or "NOT_APPLICABLE",
                "last_verified_at": as_text(
                    item.get("last_verified_at")
                ),
                "verification_source": as_text(
                    item.get("verification_source")
                ),
            }
        )

    return verified


def build_record(
    master_id: str,
    *,
    plan_row: dict[str, Any],
    data_row: dict[str, Any],
    review_row: dict[str, Any],
    rejected_row: dict[str, Any],
    attributes: dict[str, dict[str, list[str]]],
    contacts: dict[str, list[str]],
    source_urls: dict[str, list[str]],
) -> CatalogueRecord:
    payload = payload_from_rows(data_row, review_row, rejected_row)

    def direct(*names: str) -> Any:
        candidates: list[Any] = []
        for name in names:
            candidates.extend(
                [
                    plan_row.get(name),
                    data_row.get(name),
                    review_row.get(name),
                    rejected_row.get(name),
                    payload.get(name),
                ]
            )
        candidates.append(deep_find(payload, list(names)))
        return first_value(*candidates)

    objective_values = to_list(deep_find(payload, ["objectives", "objective", "purpose", "description", "overview"]))
    eligibility_values = to_list(deep_find(payload, ["eligibility", "eligibility_criteria", "who_can_apply"]))
    benefits_values = to_list(deep_find(payload, ["benefits", "support", "assistance", "financial_assistance"]))
    process_values = to_list(deep_find(payload, ["application_process", "how_to_apply", "application_steps"]))
    document_values = to_list(deep_find(payload, ["required_documents", "documents_required", "documents"]))
    warning_values = to_list(first_value(plan_row.get("warnings"), review_row.get("warnings_json"), payload.get("validation_warnings"), payload.get("quality_flags")))

    guideline_urls = dedupe(
        collect_urls(deep_find(payload, ["guideline_urls", "guidelines", "manual_urls", "scheme_guidelines"]))
        + values_for(attributes, master_id, ["guideline_urls"])
    )
    all_urls = dedupe(
        [
            url
            for url in [
                safe_url(direct("official_page_url", "final_url", "best_available_url")),
                safe_url(direct("application_url", "apply_url")),
            ]
            if url
        ]
        + guideline_urls
        + source_urls.get(master_id, [])
        + collect_urls(deep_find(payload, ["source_evidence", "sources", "references"]))
    )
    guideline_urls = dedupe(guideline_urls + [url for url in all_urls if ".pdf" in url.casefold()])

    record = CatalogueRecord(
        master_id=master_id,
        scheme_name=as_text(first_value(direct("scheme_name", "canonical_name", "title"), f"Unnamed record {master_id}")),
        source=as_text(direct("source")),
        ministry=as_text(direct("ministry")),
        department=as_text(direct("department")),
        implementing_agency=as_text(direct("implementing_agency")),
        parent_master_id=as_text(direct("parent_master_id")),
        parent_scheme_name=as_text(direct("parent_scheme_name")),
        applicant_layer=as_text(direct("applicant_layer")),
        implementation_role=as_text(direct("implementation_role")),
        status_basis=as_text(direct("status_basis")),
        status_evidence=as_text(direct("status_evidence")),
        last_verified_at=as_text(direct("last_verified_at")),
        record_kind=as_text(first_value(plan_row.get("normalized_record_kind"), direct("record_kind"))),
        programme_status=as_text(direct("programme_status")),
        application_status=as_text(direct("application_status", "scheme_status")),
        geographic_scope=as_text(direct("geographic_scope")),
        catalogue_inclusion=as_text(first_value(plan_row.get("catalogue_inclusion"), "INCLUDED")),
        catalogue_section=as_text(first_value(plan_row.get("catalogue_section"), "SCHEMES_AND_PROGRAMMES")),
        publication_status=as_text(first_value(data_row.get("publication_status"), plan_row.get("current_publication_status"))),
        is_public=as_int(first_value(data_row.get("is_public"), plan_row.get("current_is_public"))) or 0,
        current_location=as_text(plan_row.get("current_location")),
        current_review_status=as_text(first_value(plan_row.get("current_review_status"), review_row.get("review_status"))),
        current_decision=as_text(first_value(plan_row.get("current_decision"), review_row.get("decision"), rejected_row.get("decision"))),
        official_page_url=safe_url(direct("official_page_url", "final_url", "best_available_url")),
        application_url=safe_url(direct("application_url", "apply_url")),
        opening_date=as_text(direct("opening_date")),
        closing_date=as_text(direct("closing_date", "deadline")),
        validation_score=as_float(direct("validation_score", "confidence")),
        currency=as_text(first_value(direct("currency"), "INR")),
        funding_minimum=as_int(direct("funding_minimum", "funding_min")),
        funding_maximum=as_int(direct("funding_maximum", "funding_max")),
        beneficiary_support_minimum=as_int(direct("beneficiary_support_minimum")),
        beneficiary_support_maximum=as_int(direct("beneficiary_support_maximum")),
        intermediary_support_maximum=as_int(direct("intermediary_support_maximum")),
        scheme_corpus=as_int(direct("scheme_corpus")),
        objectives=dedupe(objective_values + values_for(attributes, master_id, ["objectives"])),
        eligibility=dedupe(eligibility_values + values_for(attributes, master_id, ["eligibility"])),
        benefits=dedupe(benefits_values + values_for(attributes, master_id, ["benefits"])),
        application_process=dedupe(process_values + values_for(attributes, master_id, ["application_process"])),
        required_documents=dedupe(document_values + values_for(attributes, master_id, ["required_documents"])),
        sectors=dedupe(to_list(deep_find(payload, ["sector", "sectors"])) + values_for(attributes, master_id, ["sector"])),
        scheme_types=dedupe(to_list(deep_find(payload, ["scheme_type", "grant_type", "support_type"])) + values_for(attributes, master_id, ["scheme_type"])),
        target_beneficiaries=dedupe(to_list(deep_find(payload, ["target_beneficiaries", "beneficiaries", "applicant_type"])) + values_for(attributes, master_id, ["target_beneficiaries"])),
        startup_stage=dedupe(to_list(deep_find(payload, ["startup_stage", "startup_stages"])) + values_for(attributes, master_id, ["startup_stage"])),
        guideline_urls=guideline_urls,
        reference_urls=all_urls,
        verified_public_actions=parse_verified_public_actions(
            plan_row.get("verified_public_actions_json"),
            plan_row.get("verified_public_action_schema_version"),
        ),
        contacts=dedupe(to_list(deep_find(payload, ["contact_details", "contacts", "contact"])) + contacts.get(master_id, [])),
        warnings=warning_values,
        recommended_actions=to_list(first_value(plan_row.get("recommended_actions"), review_row.get("recommended_actions_json"), payload.get("recommended_actions"))),
        decision_reasons=to_list(first_value(plan_row.get("decision_reasons"), review_row.get("decision_reasons_json"), rejected_row.get("rejection_reasons_json"))),
        last_updated=as_text(first_value(data_row.get("updated_at"), data_row.get("last_loaded_at"), review_row.get("updated_at"), rejected_row.get("updated_at"), payload.get("validation_timestamp"))),
    )
    if not record.application_status:
        if "CLOSED" in record.catalogue_section.upper():
            record.application_status = "CLOSED"
        elif "VERIFICATION" in record.catalogue_section.upper() or record.catalogue_inclusion.upper() == "PENDING_REVALIDATION":
            record.application_status = "STATUS_UNVERIFIED"

    searchable = [
        record.scheme_name,
        record.source,
        record.ministry,
        record.department,
        record.implementing_agency,
        record.record_kind,
        record.application_status,
        record.programme_status,
        record.geographic_scope,
        record.catalogue_section,
        *record.objectives,
        *record.eligibility,
        *record.benefits,
        *record.sectors,
        *record.scheme_types,
        *record.target_beneficiaries,
        *record.startup_stage,
    ]
    record.search_blob = " ".join(value for value in searchable if value).casefold()
    return record


def _identity_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", as_text(value).casefold())
    ignored = {
        "and", "the", "for", "of", "under", "scheme", "schemes", "programme",
        "programmes", "program", "programs", "fund", "funding", "official", "nidhi",
    }
    return {
        token[:-1] if token.endswith("s") and len(token) > 4 else token
        for token in tokens
        if token not in ignored
    }


def _record_population(record: CatalogueRecord) -> str:
    return "CALL" if record.record_kind.upper() in {"APPLICATION_CALL", "CHALLENGE"} else "SCHEME"


def _same_catalogue_identity(left: CatalogueRecord, right: CatalogueRecord) -> bool:
    """Detect a published record that supersedes an older preview identity."""
    if _record_population(left) != _record_population(right):
        return False
    left_tokens = _identity_tokens(left.scheme_name)
    right_tokens = _identity_tokens(right.scheme_name)
    if left_tokens and left_tokens == right_tokens:
        return True
    left_url = as_text(left.official_page_url).casefold().rstrip("/")
    right_url = as_text(right.official_page_url).casefold().rstrip("/")
    if not left_url or left_url != right_url:
        return False
    url_tail = left_url.rsplit("/", 1)[-1]
    if url_tail and "." not in url_tail and url_tail not in {
        "scheme", "schemes", "programme", "programmes", "schemes-programmes",
        "funding", "program", "programs",
    }:
        return True
    # Shared directory pages can legitimately describe several programmes.
    # Require at least one distinctive name token before treating a URL match
    # as the same identity.
    return bool(left_tokens & right_tokens)


def load_catalogue(config: DashboardConfig) -> CatalogueBundle:
    if getattr(config, "preview_path_configured", False) and not config.normalization_path.exists():
        raise FileNotFoundError(f"Configured catalogue preview file not found: {config.normalization_path}")
    tables = read_dashboard_tables(
        config.database_path,
        timeout_seconds=config.sqlite_timeout_seconds,
    )
    plan = read_normalization_plan(config.normalization_path)

    staging_by_id = frame_by_master_id(tables["scheme_staging"])
    public_by_id = frame_by_master_id(tables["public_schemes"])
    review_by_id = frame_by_master_id(tables["admin_review_queue"])
    rejected_by_id = frame_by_master_id(tables["rejected_scheme_records"])
    attributes = attributes_by_master_id(tables["scheme_attributes"])
    contacts = contacts_by_master_id(tables["scheme_contacts"])
    source_urls = source_urls_by_master_id(tables["scheme_sources"])

    records: list[CatalogueRecord] = []
    included_ids: set[str] = set()
    published_appended_count = 0
    published_merged_count = 0

    if config.mode == CatalogueMode.PUBLISHED_ONLY:
        for master_id, row in public_by_id.items():
            plan_row = {}
            if not plan.empty and "master_id" in plan.columns:
                matches = plan[plan["master_id"].astype(str) == master_id]
                if not matches.empty:
                    plan_row = matches.iloc[0].to_dict()
            records.append(
                build_record(
                    master_id,
                    plan_row=plan_row,
                    data_row=row,
                    review_row=review_by_id.get(master_id, {}),
                    rejected_row=rejected_by_id.get(master_id, {}),
                    attributes=attributes,
                    contacts=contacts,
                    source_urls=source_urls,
                )
            )
            included_ids.add(master_id)
    else:
        if plan.empty:
            plan = tables["scheme_staging"].copy()
            plan["master_id"] = plan.get("master_id", "")
            plan["catalogue_inclusion"] = "INCLUDED"
            plan["catalogue_section"] = "SCHEMES_AND_PROGRAMMES"
            plan["normalized_record_kind"] = plan.get("record_kind", "SCHEME_OR_PROGRAMME")
            plan["current_location"] = "SCHEME_STAGING"

        for plan_row in plan.to_dict(orient="records"):
            master_id = as_text(plan_row.get("master_id"))
            if not master_id:
                continue
            data_row = staging_by_id.get(master_id, {})
            review_row = review_by_id.get(master_id, {})
            rejected_row = rejected_by_id.get(master_id, {})
            is_review_only = not data_row
            is_explicit_preview_file = "catalogue_preview" in {part.lower() for part in config.normalization_path.parts}
            is_rejected = as_text(
                first_value(plan_row.get("current_decision"), review_row.get("decision"), rejected_row.get("decision"))
            ).upper() == "REJECTED"
            is_rejected_or_review_only = is_review_only or is_rejected
            if is_rejected_or_review_only and not review_record_allowed(plan_row):
                if is_explicit_preview_file and is_review_only and not is_rejected and explicit_preview_record_allowed(plan_row):
                    pass
                else:
                    continue
            records.append(
                build_record(
                    master_id,
                    plan_row=plan_row,
                    data_row=data_row,
                    review_row=review_row,
                    rejected_row=rejected_row,
                    attributes=attributes,
                    contacts=contacts,
                    source_urls=source_urls,
                )
            )
            included_ids.add(master_id)

        # A configured preview CSV supplies curated normalization metadata, but
        # it must not hide records that have subsequently completed the explicit
        # publication workflow. Published records supersede semantic preview
        # duplicates even when an older import assigned a different master ID;
        # never append merely staged or review-only records.
        for master_id, row in public_by_id.items():
            if master_id in included_ids:
                continue
            record_kind = as_text(row.get("record_kind")) or "SCHEME_OR_PROGRAMME"
            plan_row = {
                "master_id": master_id,
                "catalogue_inclusion": "INCLUDED",
                "catalogue_section": (
                    "APPLICATION_CALLS"
                    if record_kind.upper() in {"APPLICATION_CALL", "CHALLENGE"}
                    else "SCHEMES_AND_PROGRAMMES"
                ),
                "normalized_record_kind": record_kind,
                "current_location": "PUBLIC_SCHEMES",
                "current_review_status": "APPROVED",
                "current_decision": "APPROVED_FOR_DATABASE",
                "current_publication_status": "PUBLISHED",
                "current_is_public": "1",
            }
            published_record = build_record(
                master_id,
                plan_row=plan_row,
                data_row=row,
                review_row=review_by_id.get(master_id, {}),
                rejected_row=rejected_by_id.get(master_id, {}),
                attributes=attributes,
                contacts=contacts,
                source_urls=source_urls,
            )
            matching_indexes = [
                index for index, existing in enumerate(records)
                if _same_catalogue_identity(existing, published_record)
            ]
            if matching_indexes:
                records[matching_indexes[0]] = published_record
                for index in reversed(matching_indexes[1:]):
                    del records[index]
                published_merged_count += 1
            else:
                records.append(published_record)
                published_appended_count += 1
            included_ids.add(master_id)

    msme_supplement = load_active_msme_supplement(config.project_root)
    mymsme_supplement = load_active_mymsme_supplement(config.project_root)
    media_publication = load_active_media_publication(config.project_root)
    existing_ids = {record.master_id for record in records}
    supplemental_count = 0
    media_supplement_count = 0
    for payload in (*msme_supplement.records, *mymsme_supplement.records):
        master_id = str(payload.get("master_id", ""))
        if master_id in existing_ids:
            continue
        records.append(CatalogueRecord(**payload))
        existing_ids.add(master_id)
        supplemental_count += 1
    for payload in media_publication.records:
        master_id = str(payload.get("master_id", ""))
        if master_id in existing_ids:
            continue
        records.append(CatalogueRecord(**payload))
        existing_ids.add(master_id)
        media_supplement_count += 1

    records = sorted(records, key=lambda item: (item.catalogue_section, item.scheme_name))
    metadata = {
        "mode": config.mode.value,
        "database_path": str(config.database_path),
        "normalization_path": str(config.normalization_path),
        "normalization_available": config.normalization_path.exists(),
        "staging_count": len(tables["scheme_staging"]),
        "public_count": len(tables["public_schemes"]),
        "review_count": len(tables["admin_review_queue"]),
        "rejected_count": len(tables["rejected_scheme_records"]),
        "record_count": len(records),
        "published_appended_count": published_appended_count,
        "published_merged_count": published_merged_count,
        "msme_supplement_count": supplemental_count,
        "msme_supplement_run_id": msme_supplement.manifest.get("run_id", ""),
        "msme_mymsme_supplement_count": len(mymsme_supplement.records),
        "msme_mymsme_supplement_run_id": mymsme_supplement.manifest.get("run_id", ""),
        "media_publication_count": media_supplement_count,
        "media_publication_run_id": media_publication.manifest.get("run_id", ""),
    }
    return CatalogueBundle(records=records, mode=config.mode, metadata=metadata)
