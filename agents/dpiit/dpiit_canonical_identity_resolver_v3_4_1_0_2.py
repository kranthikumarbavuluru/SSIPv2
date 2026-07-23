from __future__ import annotations

import re
from typing import Any

from agents.shared.validation_core import stable_id

from .dpiit_canonical_identity_rules_v3_4_1_0_2 import (
    AS_OF, CHILD_RELATIONSHIP_TYPES, DEPARTMENT, IDENTITY_RULES, MINISTRY, VERSION,
)


ENTITY_FIELDS = [
    "master_id", "canonical_name", "official_abbreviation", "entity_type",
    "owning_ministry", "owning_department", "implementing_agency",
    "official_master_url", "source_candidate_id", "identity_status",
    "identity_confidence", "identity_evidence", "identity_rule_version",
    "last_verified_date", "publication_status",
]
ALIAS_FIELDS = [
    "alias_id", "master_id", "alias_text", "alias_type", "alias_status",
    "source_candidate_id", "evidence_url", "notes",
]
RELATIONSHIP_FIELDS = [
    "relationship_id", "parent_master_id", "child_candidate_id", "child_name",
    "child_role", "relationship_type", "evidence_url", "confidence", "status", "reasons",
]
EVIDENCE_FIELDS = [
    "evidence_id", "master_id", "candidate_id", "evidence_role", "page_role",
    "evidence_url", "page_title", "ownership_status", "evidence_status", "notes",
]
REVIEW_FIELDS = [
    "review_id", "candidate_id", "candidate_name", "review_type", "proposed_master_id",
    "proposed_canonical_name", "source_url", "page_role", "ownership_status",
    "review_reasons", "publication_status",
]
AUDIT_FIELDS = [
    "audit_id", "master_id", "canonical_name", "entity_type", "source_candidate_id",
    "source_url", "decision", "decision_reasons", "identity_rule_version",
]
REJECTION_FIELDS = [
    "rejection_id", "candidate_id", "candidate_name", "source_url", "page_role",
    "rejection_reason", "retained_for_audit",
]


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _entity(rule: dict[str, Any], candidate: dict[str, str]) -> dict[str, str]:
    master_id = stable_id("dpiit_master", rule["entity_type"], rule["master_url"])
    return {
        "master_id": master_id,
        "canonical_name": rule["canonical_name"],
        "official_abbreviation": rule.get("abbreviation", ""),
        "entity_type": rule["entity_type"],
        "owning_ministry": MINISTRY,
        "owning_department": DEPARTMENT,
        "implementing_agency": rule.get("implementing_agency", ""),
        "official_master_url": rule["master_url"],
        "source_candidate_id": candidate["candidate_id"],
        "identity_status": "LOCKED_VERIFIED_OFFICIAL_IDENTITY",
        "identity_confidence": "0.98",
        "identity_evidence": rule["evidence"],
        "identity_rule_version": VERSION,
        "last_verified_date": AS_OF,
        "publication_status": "NOT_PUBLISHED",
    }


def resolve(candidates: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    by_url = {row["normalized_url"]: row for row in candidates}

    entities: list[dict[str, str]] = []
    aliases: list[dict[str, str]] = []
    evidence: list[dict[str, str]] = []
    relationships: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    audits: list[dict[str, str]] = []
    rejections: list[dict[str, str]] = []
    master_by_candidate: dict[str, str] = {}

    for rule in IDENTITY_RULES:
        candidate = by_url.get(rule["master_url"])
        if not candidate:
            reviews.append({
                "review_id": stable_id("dpiit_review", "missing-master", rule["master_url"]),
                "candidate_id": "", "candidate_name": rule["canonical_name"],
                "review_type": "MISSING_OFFICIAL_MASTER_EVIDENCE", "proposed_master_id": "",
                "proposed_canonical_name": rule["canonical_name"], "source_url": rule["master_url"],
                "page_role": "", "ownership_status": "", "review_reasons": "RULE_MASTER_URL_NOT_DISCOVERED",
                "publication_status": "NOT_PUBLISHED",
            })
            continue
        if candidate["ownership_status"] != "VERIFIED_DPIIT":
            reviews.append({
                "review_id": stable_id("dpiit_review", "ownership", candidate["candidate_id"]),
                "candidate_id": candidate["candidate_id"], "candidate_name": candidate["candidate_name"],
                "review_type": "OWNERSHIP_VERIFICATION", "proposed_master_id": "",
                "proposed_canonical_name": rule["canonical_name"], "source_url": candidate["normalized_url"],
                "page_role": candidate["page_role"], "ownership_status": candidate["ownership_status"],
                "review_reasons": "OWNERSHIP_NOT_VERIFIED", "publication_status": "NOT_PUBLISHED",
            })
            continue
        entity = _entity(rule, candidate)
        entities.append(entity)
        master_by_candidate[candidate["candidate_id"]] = entity["master_id"]
        evidence.append({
            "evidence_id": stable_id("dpiit_evidence", entity["master_id"], candidate["candidate_id"]),
            "master_id": entity["master_id"], "candidate_id": candidate["candidate_id"],
            "evidence_role": "CANONICAL_MASTER_EVIDENCE", "page_role": candidate["page_role"],
            "evidence_url": candidate["normalized_url"], "page_title": candidate["page_title"],
            "ownership_status": candidate["ownership_status"], "evidence_status": "ACCEPTED_OFFICIAL",
            "notes": rule["evidence"],
        })
        audits.append({
            "audit_id": stable_id("dpiit_lock_audit", entity["master_id"]),
            "master_id": entity["master_id"], "canonical_name": entity["canonical_name"],
            "entity_type": entity["entity_type"], "source_candidate_id": candidate["candidate_id"],
            "source_url": candidate["normalized_url"], "decision": "LOCK_IDENTITY",
            "decision_reasons": rule["evidence"], "identity_rule_version": VERSION,
        })
        seen_aliases: set[str] = set()
        for alias in rule.get("aliases", []):
            key = normalize_name(alias)
            if not key or key == normalize_name(rule["canonical_name"]) or key in seen_aliases:
                continue
            seen_aliases.add(key)
            alias_type = "ABBREVIATION" if alias.upper() == alias and len(alias) <= 12 else "OFFICIAL_VARIANT"
            aliases.append({
                "alias_id": stable_id("dpiit_alias", entity["master_id"], alias),
                "master_id": entity["master_id"], "alias_text": alias,
                "alias_type": alias_type, "alias_status": "LOCKED_ALIAS",
                "source_candidate_id": candidate["candidate_id"], "evidence_url": candidate["normalized_url"],
                "notes": "Governed alias; does not create a second entity.",
            })
        if rule.get("lineage_review"):
            reviews.append({
                "review_id": stable_id("dpiit_review", "lineage", entity["master_id"]),
                "candidate_id": candidate["candidate_id"], "candidate_name": candidate["candidate_name"],
                "review_type": "VERSION_AND_PREDECESSOR_LINEAGE", "proposed_master_id": entity["master_id"],
                "proposed_canonical_name": entity["canonical_name"], "source_url": candidate["normalized_url"],
                "page_role": candidate["page_role"], "ownership_status": candidate["ownership_status"],
                "review_reasons": "DO_NOT_MERGE_FOF_2_0_WITH_PREDECESSOR_WITHOUT_OFFICIAL_LINEAGE_DECISION",
                "publication_status": "NOT_PUBLISHED",
            })
        mixed_url = rule.get("mixed_service_review_url", "")
        if mixed_url and mixed_url in by_url:
            mixed = by_url[mixed_url]
            evidence.append({
                "evidence_id": stable_id("dpiit_evidence", entity["master_id"], mixed["candidate_id"]),
                "master_id": entity["master_id"], "candidate_id": mixed["candidate_id"],
                "evidence_role": "MIXED_SERVICE_PAGE", "page_role": mixed["page_role"],
                "evidence_url": mixed["normalized_url"], "page_title": mixed["page_title"],
                "ownership_status": mixed["ownership_status"], "evidence_status": "REVIEW_REQUIRED",
                "notes": "Page combines recognition and tax-exemption services; not auto-merged as one alias.",
            })
            reviews.append({
                "review_id": stable_id("dpiit_review", "mixed-service", mixed["candidate_id"]),
                "candidate_id": mixed["candidate_id"], "candidate_name": mixed["candidate_name"],
                "review_type": "MIXED_SERVICE_IDENTITY", "proposed_master_id": entity["master_id"],
                "proposed_canonical_name": entity["canonical_name"], "source_url": mixed["normalized_url"],
                "page_role": mixed["page_role"], "ownership_status": mixed["ownership_status"],
                "review_reasons": "RECOGNITION_AND_TAX_EXEMPTION_MAY_REQUIRE_SEPARATE_SERVICE_RELATIONSHIPS",
                "publication_status": "NOT_PUBLISHED",
            })

    for child in candidates:
        parent_candidate_id = child.get("parent_candidate_id", "")
        if not parent_candidate_id:
            continue
        parent_master_id = master_by_candidate.get(parent_candidate_id, "")
        relationship_type = CHILD_RELATIONSHIP_TYPES.get(child["page_role"], "")
        if not parent_master_id or not relationship_type:
            reviews.append({
                "review_id": stable_id("dpiit_review", "relationship", child["candidate_id"]),
                "candidate_id": child["candidate_id"], "candidate_name": child["candidate_name"],
                "review_type": "PARENT_CHILD_RELATIONSHIP", "proposed_master_id": parent_master_id,
                "proposed_canonical_name": "", "source_url": child["normalized_url"],
                "page_role": child["page_role"], "ownership_status": child["ownership_status"],
                "review_reasons": "PARENT_MASTER_OR_RELATIONSHIP_TYPE_UNRESOLVED",
                "publication_status": "NOT_PUBLISHED",
            })
            continue
        relationships.append({
            "relationship_id": stable_id("dpiit_relationship", parent_master_id, child["candidate_id"], relationship_type),
            "parent_master_id": parent_master_id, "child_candidate_id": child["candidate_id"],
            "child_name": child["candidate_name"], "child_role": child["page_role"],
            "relationship_type": relationship_type, "evidence_url": child["normalized_url"],
            "confidence": "0.98", "status": "LOCKED_EVIDENCE_RELATIONSHIP",
            "reasons": "Explicit v3.4.1.0.1 parent candidate mapped to locked permanent identity.",
        })
        evidence.append({
            "evidence_id": stable_id("dpiit_evidence", parent_master_id, child["candidate_id"]),
            "master_id": parent_master_id, "candidate_id": child["candidate_id"],
            "evidence_role": relationship_type, "page_role": child["page_role"],
            "evidence_url": child["normalized_url"], "page_title": child["page_title"],
            "ownership_status": child["ownership_status"], "evidence_status": "ACCEPTED_RELATED_EVIDENCE",
            "notes": "Child remains separate from permanent canonical identity.",
        })

    already_reviewed = {row["candidate_id"] for row in reviews if row["candidate_id"]}
    for candidate in candidates:
        if candidate["rejection_reason"]:
            rejections.append({
                "rejection_id": stable_id("dpiit_identity_rejection", candidate["candidate_id"]),
                "candidate_id": candidate["candidate_id"], "candidate_name": candidate["candidate_name"],
                "source_url": candidate["normalized_url"], "page_role": candidate["page_role"],
                "rejection_reason": candidate["rejection_reason"], "retained_for_audit": "1",
            })
        elif candidate["ownership_status"] == "NEEDS_VERIFICATION" and candidate["candidate_id"] not in already_reviewed:
            reviews.append({
                "review_id": stable_id("dpiit_review", "ownership", candidate["candidate_id"]),
                "candidate_id": candidate["candidate_id"], "candidate_name": candidate["candidate_name"],
                "review_type": "OWNERSHIP_VERIFICATION", "proposed_master_id": "",
                "proposed_canonical_name": "", "source_url": candidate["normalized_url"],
                "page_role": candidate["page_role"], "ownership_status": candidate["ownership_status"],
                "review_reasons": "HOSTING_PLATFORM_DOES_NOT_PROVE_DPIIT_OWNERSHIP",
                "publication_status": "NOT_PUBLISHED",
            })

    def ordered(rows: list[dict[str, str]], *keys: str) -> list[dict[str, str]]:
        return sorted(rows, key=lambda row: tuple(row.get(key, "").casefold() for key in keys))

    return {
        "entities": ordered(entities, "entity_type", "canonical_name"),
        "schemes": ordered([row for row in entities if row["entity_type"] == "SCHEME"], "canonical_name"),
        "programmes": ordered([row for row in entities if row["entity_type"] == "UMBRELLA_PROGRAMME"], "canonical_name"),
        "platforms_services": ordered([row for row in entities if row["entity_type"] in {"ECOSYSTEM_PLATFORM", "GOVERNMENT_SERVICE"}], "entity_type", "canonical_name"),
        "aliases": ordered(aliases, "master_id", "alias_text"),
        "relationships": ordered(relationships, "parent_master_id", "relationship_type", "child_name"),
        "evidence": ordered(evidence, "master_id", "evidence_role", "candidate_id"),
        "reviews": ordered(reviews, "review_type", "candidate_name"),
        "audits": ordered(audits, "entity_type", "canonical_name"),
        "rejections": ordered(rejections, "candidate_name"),
    }
