from __future__ import annotations

from typing import Any

from agents.shared.validation_core import stable_id

from .dpiit_canonical_identity_resolver_v3_4_1_0_2 import ENTITY_FIELDS
from .dpiit_ownership_service_rules_v3_4_1_0_3 import (
    AS_OF, DEPARTMENT, EVIDENCE_RECORDS, LINEAGE_RULE, MINISTRY, OWNERSHIP_RULES,
    SERVICE_BOUNDARY_RULE, VERSION,
)


OWNERSHIP_FIELDS = [
    "decision_id", "review_id", "candidate_id", "candidate_name", "decision",
    "ownership_status", "owning_department", "content_authority", "entity_boundary",
    "final_page_role", "evidence_url", "evidence_basis", "confidence",
    "resolution_status", "publication_status",
]
SERVICE_DECISION_FIELDS = [
    "decision_id", "review_id", "candidate_id", "combined_page_name", "decision",
    "recognition_master_id", "recognition_service_name", "tax_service_master_id",
    "tax_service_name", "relationship_type", "evidence_urls", "evidence_basis",
    "resolution_status", "publication_status",
]
SERVICE_RELATIONSHIP_FIELDS = [
    "relationship_id", "source_master_id", "target_master_id", "relationship_type",
    "evidence_url", "status", "reasons",
]
LINEAGE_FIELDS = [
    "decision_id", "review_id", "candidate_id", "current_master_id", "current_name",
    "predecessor_name", "predecessor_master_id", "relationship_type", "decision",
    "merge_allowed", "evidence_url", "evidence_basis", "resolution_status",
    "publication_status",
]
RESOLUTION_FIELDS = [
    "resolution_id", "review_id", "candidate_id", "candidate_name", "review_type",
    "decision_class", "decision", "resolution_status", "evidence_url",
    "remaining_action", "publication_status",
]
EVIDENCE_FIELDS = [
    "evidence_id", "evidence_code", "official_url", "authority_type", "evidence_summary",
    "verification_date", "evidence_status",
]


def resolve(review_rows: list[dict[str, str]], canonical_entities: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    reviews_by_candidate = {row["candidate_id"]: row for row in review_rows}
    entities_by_id = {row["master_id"]: row for row in canonical_entities}
    ownership: list[dict[str, str]] = []
    service_decisions: list[dict[str, str]] = []
    services: list[dict[str, str]] = []
    service_relationships: list[dict[str, str]] = []
    lineage: list[dict[str, str]] = []
    resolved: list[dict[str, str]] = []
    covered: set[str] = set()

    for candidate_id, rule in sorted(OWNERSHIP_RULES.items()):
        review = reviews_by_candidate[candidate_id]
        row = {
            "decision_id": stable_id("dpiit_ownership_decision", candidate_id),
            "review_id": review["review_id"], "candidate_id": candidate_id,
            "candidate_name": review["candidate_name"], "decision": rule["decision"],
            "ownership_status": rule["ownership_status"], "owning_department": rule["owning_department"],
            "content_authority": rule["content_authority"], "entity_boundary": rule["entity_boundary"],
            "final_page_role": rule["final_page_role"], "evidence_url": rule["evidence_url"],
            "evidence_basis": rule["evidence_basis"], "confidence": rule["confidence"],
            "resolution_status": "RESOLVED", "publication_status": "NOT_PUBLISHED",
        }
        ownership.append(row)
        covered.add(candidate_id)
        resolved.append({
            "resolution_id": stable_id("dpiit_review_resolution", review["review_id"]),
            "review_id": review["review_id"], "candidate_id": candidate_id,
            "candidate_name": review["candidate_name"], "review_type": review["review_type"],
            "decision_class": "OWNERSHIP_AND_PAGE_BOUNDARY", "decision": rule["decision"],
            "resolution_status": "RESOLVED", "evidence_url": rule["evidence_url"],
            "remaining_action": "NONE" if rule["entity_boundary"] != "CROSS_DEPARTMENT_SCHEME_DIRECTORY" else "VERIFY_EACH_CHILD_OWNER_SEPARATELY",
            "publication_status": "NOT_PUBLISHED",
        })

    service_rule = SERVICE_BOUNDARY_RULE
    service_review = reviews_by_candidate[service_rule["review_candidate_id"]]
    recognition = entities_by_id[service_rule["recognition_master_id"]]
    tax_master_id = stable_id("dpiit_master", "GOVERNMENT_SERVICE", service_rule["tax_service_url"])
    services.append(dict(recognition))
    services.append({
        "master_id": tax_master_id,
        "canonical_name": service_rule["tax_service_name"],
        "official_abbreviation": "80-IAC Eligibility Certification",
        "entity_type": "GOVERNMENT_SERVICE",
        "owning_ministry": MINISTRY,
        "owning_department": service_rule["tax_service_owner"],
        "implementing_agency": service_rule["tax_service_authority"],
        "official_master_url": service_rule["tax_service_url"],
        "source_candidate_id": service_review["candidate_id"],
        "identity_status": "LOCKED_VERIFIED_OFFICIAL_SERVICE_IDENTITY",
        "identity_confidence": "0.99",
        "identity_evidence": service_rule["evidence_basis"],
        "identity_rule_version": VERSION,
        "last_verified_date": AS_OF,
        "publication_status": "NOT_PUBLISHED",
    })
    service_decisions.append({
        "decision_id": stable_id("dpiit_service_boundary", service_review["candidate_id"]),
        "review_id": service_review["review_id"], "candidate_id": service_review["candidate_id"],
        "combined_page_name": service_review["candidate_name"], "decision": service_rule["decision"],
        "recognition_master_id": recognition["master_id"], "recognition_service_name": recognition["canonical_name"],
        "tax_service_master_id": tax_master_id, "tax_service_name": service_rule["tax_service_name"],
        "relationship_type": service_rule["relationship_type"],
        "evidence_urls": ";".join(service_rule["evidence_urls"]), "evidence_basis": service_rule["evidence_basis"],
        "resolution_status": "RESOLVED", "publication_status": "NOT_PUBLISHED",
    })
    service_relationships.append({
        "relationship_id": stable_id("dpiit_service_relationship", tax_master_id, recognition["master_id"]),
        "source_master_id": tax_master_id, "target_master_id": recognition["master_id"],
        "relationship_type": service_rule["relationship_type"],
        "evidence_url": service_rule["evidence_urls"][0], "status": "LOCKED_OFFICIAL_SERVICE_RELATIONSHIP",
        "reasons": "The official notification and application page require startup recognition before 80-IAC certification.",
    })
    covered.add(service_review["candidate_id"])
    resolved.append({
        "resolution_id": stable_id("dpiit_review_resolution", service_review["review_id"]),
        "review_id": service_review["review_id"], "candidate_id": service_review["candidate_id"],
        "candidate_name": service_review["candidate_name"], "review_type": service_review["review_type"],
        "decision_class": "SERVICE_BOUNDARY", "decision": service_rule["decision"],
        "resolution_status": "RESOLVED", "evidence_url": service_rule["evidence_urls"][0],
        "remaining_action": "NONE", "publication_status": "NOT_PUBLISHED",
    })

    lineage_rule = LINEAGE_RULE
    lineage_review = reviews_by_candidate[lineage_rule["review_candidate_id"]]
    lineage.append({
        "decision_id": stable_id("dpiit_lineage_decision", lineage_review["candidate_id"]),
        "review_id": lineage_review["review_id"], "candidate_id": lineage_review["candidate_id"],
        "current_master_id": lineage_rule["current_master_id"], "current_name": lineage_rule["current_name"],
        "predecessor_name": lineage_rule["predecessor_name"], "predecessor_master_id": "",
        "relationship_type": lineage_rule["relationship_type"], "decision": lineage_rule["decision"],
        "merge_allowed": lineage_rule["merge_allowed"], "evidence_url": lineage_rule["evidence_url"],
        "evidence_basis": lineage_rule["evidence_basis"], "resolution_status": "RESOLVED_WITH_EXTERNAL_REFERENCE",
        "publication_status": "NOT_PUBLISHED",
    })
    covered.add(lineage_review["candidate_id"])
    resolved.append({
        "resolution_id": stable_id("dpiit_review_resolution", lineage_review["review_id"]),
        "review_id": lineage_review["review_id"], "candidate_id": lineage_review["candidate_id"],
        "candidate_name": lineage_review["candidate_name"], "review_type": lineage_review["review_type"],
        "decision_class": "SCHEME_VERSION_LINEAGE", "decision": lineage_rule["decision"],
        "resolution_status": "RESOLVED_WITH_EXTERNAL_REFERENCE", "evidence_url": lineage_rule["evidence_url"],
        "remaining_action": "CREATE_PREDECESSOR_MASTER_ONLY_IF_LATER_OFFICIAL_INVENTORY_REQUIRES_IT",
        "publication_status": "NOT_PUBLISHED",
    })

    unresolved = [row for row in review_rows if row["candidate_id"] not in covered]
    evidence = [
        {
            "evidence_id": stable_id("dpiit_adjudication_evidence", code, url),
            "evidence_code": code, "official_url": url,
            "authority_type": "PRIMARY_OFFICIAL_SOURCE", "evidence_summary": summary,
            "verification_date": AS_OF, "evidence_status": "ACCEPTED_FOR_ADJUDICATION",
        }
        for code, url, summary in EVIDENCE_RECORDS
    ]

    def ordered(rows: list[dict[str, str]], *keys: str) -> list[dict[str, str]]:
        return sorted(rows, key=lambda row: tuple(row.get(key, "").casefold() for key in keys))

    return {
        "ownership": ordered(ownership, "candidate_name"),
        "service_decisions": ordered(service_decisions, "combined_page_name"),
        "services": ordered(services, "canonical_name"),
        "service_relationships": ordered(service_relationships, "relationship_type"),
        "lineage": ordered(lineage, "current_name"),
        "resolved": ordered(resolved, "review_type", "candidate_name"),
        "unresolved": ordered(unresolved, "review_type", "candidate_name"),
        "evidence": ordered(evidence, "evidence_code"),
    }
