from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.2"
SOURCE_VERSION = "3.4.3.8.0.1"

LANE_AUTO = "AUTO_RESOLVED"
LANE_BATCH = "BATCH_CONFIRMATION"
LANE_DEEP = "DEEP_REVIEW"

ACTION_CONFIRM_PROGRAMME = "CONFIRM_PROGRAMME_FAMILY"
ACTION_CONFIRM_EXISTING_PROGRAMME = "CONFIRM_EXISTING_PROGRAMME_FAMILY"
ACTION_REVIEW_NEW_PROGRAMME = "REVIEW_NEW_PROGRAMME_FAMILY"
ACTION_CONFIRM_CALL_GROUP = "CONFIRM_CALL_OR_CHALLENGE_GROUP"
ACTION_REVIEW_CURRENT_CALL = "REVIEW_CURRENT_CALL"
ACTION_CONFIRM_HISTORICAL = "CONFIRM_HISTORICAL_GROUP"
ACTION_EXCLUDE_EVENT = "EXCLUDE_NON_CATALOGUE_EVENT_GROUP"
ACTION_ACCEPT_DOCUMENT_LINKS = "ACCEPT_SUPPORTING_DOCUMENT_LINKS"
ACTION_ACCEPT_EXCLUSIONS = "ACCEPT_AUTOMATIC_EXCLUSIONS"
ACTION_REVIEW_IDENTITY = "REVIEW_IDENTITY_OR_ROLE"
ACTION_MIXED_LOW_RISK = "REVIEW_LOW_RISK_GROUP"

POTENTIAL_OPEN_STATUSES = {"OPEN", "UPCOMING"}
PUBLICATION_BLOCKED = False
APPLY_BLOCKED = False


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def normalize(value: str) -> str:
    decoded = urllib.parse.unquote(clean(value))
    return clean(re.sub(r"[^a-z0-9]+", " ", decoded.casefold()))


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return clean(value).casefold() in {"1", "true", "yes", "y"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=field_list,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in field_list})


def row_weight(row: dict[str, Any]) -> int:
    value = parse_int(row.get("source_candidate_count"), 0)
    return value if value > 0 else 1


def child_identifier(row: dict[str, Any], category: str) -> str:
    payload = {
        "category": category,
        "canonical_name": clean(row.get("canonical_name")),
        "original_canonical_name": clean(row.get("original_canonical_name")),
        "source_candidate_id": clean(row.get("source_candidate_id")),
        "source_candidate_ids": clean(row.get("source_candidate_ids")),
        "official_page_url": clean(row.get("official_page_url")),
        "entity_type": clean(row.get("entity_type")),
        "disposition": clean(row.get("disposition")),
    }
    return "meitychild_" + hashlib.sha256(
        stable_json(payload).encode("utf-8")
    ).hexdigest()[:20]


def stable_bundle_id(
    lane: str,
    action: str,
    title: str,
    child_ids: Iterable[str],
) -> str:
    payload = {
        "lane": lane,
        "action": action,
        "title": title,
        "children": sorted(set(child_ids)),
    }
    return "meitybundle_" + hashlib.sha256(
        stable_json(payload).encode("utf-8")
    ).hexdigest()[:20]


def infer_family(
    row: dict[str, Any],
    config: dict[str, Any],
) -> str:
    existing = clean(
        row.get("parent_scheme_name")
        or row.get("identity_family")
        or row.get("canonical_name")
        or row.get("original_canonical_name")
    )
    blob = normalize(
        " ".join(
            clean(row.get(key))
            for key in (
                "canonical_name",
                "original_canonical_name",
                "source_titles",
                "evidence_excerpt",
                "status_evidence",
                "official_page_url",
            )
        )
    )
    for family, keywords in config.get("family_keywords", {}).items():
        for keyword in keywords:
            key = normalize(keyword)
            if key and key in blob:
                return family
    return existing


def obvious_non_catalogue(
    row: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    entity_type = clean(row.get("entity_type"))
    if entity_type in set(config.get("auto_resolve_entity_types", [])):
        return True
    title = normalize(
        clean(row.get("canonical_name"))
        or clean(row.get("original_canonical_name"))
    )
    if any(
        normalize(marker) in title
        for marker in config.get("auto_resolve_title_markers", [])
        if normalize(marker)
    ):
        return True
    return False


def risk_score(row: dict[str, Any]) -> int:
    score = 0
    status = clean(
        row.get("application_status")
        or row.get("programme_status")
    )
    if status in POTENTIAL_OPEN_STATUSES:
        score += 50
    if clean(row.get("application_url")):
        score += 25
    if clean(row.get("closing_date")):
        score += 15
    if clean(row.get("opening_date")):
        score += 10
    if clean(row.get("parent_resolution")) in {
        "UNRESOLVED",
        "PARENT_REQUIRES_ADMIN_VERIFICATION",
        "RELATED_CALL_REQUIRES_ADMIN_VERIFICATION",
    }:
        score += 15
    if (
        clean(row.get("source_entity_type"))
        and clean(row.get("source_entity_type"))
        != clean(row.get("entity_type"))
    ):
        score += 10
    if clean(row.get("existing_master_id")):
        score += 4
    if parse_bool(row.get("existing_public_record")):
        score += 5
    return score


def priority_from_risk(score: int) -> str:
    if score >= 45:
        return "CRITICAL"
    if score >= 25:
        return "HIGH"
    if score >= 12:
        return "MEDIUM"
    return "LOW"


@dataclass(frozen=True)
class CompressionPaths:
    project_root: Path
    source_dir: Path
    output_dir: Path
    config_path: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "CompressionPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_1",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_2",
            config_path=(
                root / "config/meity_review_compression_v3_4_3_8_0_2.json"
            ),
            database_path=root / "database/ssip_staging_v1.db",
        )


class ReviewCompressor:
    def __init__(
        self,
        paths: CompressionPaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config

    def _load_manifest(self) -> dict[str, Any]:
        path = (
            self.paths.source_dir
            / "meity_candidate_purification_manifest_v3_4_3_8_0_1.json"
        )
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _load_inputs(self) -> dict[str, list[dict[str, str]]]:
        files = {
            "programmes": "meity_purified_programme_families_v3_4_3_8_0_1.csv",
            "calls": "meity_purified_calls_challenges_v3_4_3_8_0_1.csv",
            "historical": "meity_purified_historical_events_v3_4_3_8_0_1.csv",
            "documents": "meity_supporting_documents_v3_4_3_8_0_1.csv",
            "excluded": "meity_excluded_error_pages_v3_4_3_8_0_1.csv",
            "identity_review": "meity_identity_role_review_v3_4_3_8_0_1.csv",
        }
        return {
            key: read_csv(self.paths.source_dir / filename)
            for key, filename in files.items()
        }

    def _child(
        self,
        row: dict[str, Any],
        category: str,
        auto_resolution: str = "",
    ) -> dict[str, Any]:
        result = dict(row)
        result["input_category"] = category
        result["child_id"] = child_identifier(row, category)
        result["source_evidence_weight"] = row_weight(row)
        result["inferred_family"] = infer_family(row, self.config)
        result["risk_score"] = risk_score(row)
        result["priority"] = priority_from_risk(result["risk_score"])
        result["auto_resolution"] = auto_resolution
        result["publication_eligible"] = False
        result["apply_action_allowed"] = False
        return result

    def _make_bundle(
        self,
        *,
        lane: str,
        action: str,
        title: str,
        children: list[dict[str, Any]],
        rationale: str,
        allow_batch_all: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not children:
            raise ValueError("A decision bundle requires at least one child.")
        child_ids = [clean(child.get("child_id")) for child in children]
        bundle_id = stable_bundle_id(lane, action, title, child_ids)
        max_risk = max(parse_int(child.get("risk_score")) for child in children)
        families = sorted(
            {
                clean(child.get("inferred_family"))
                for child in children
                if clean(child.get("inferred_family"))
            }
        )
        entity_types = sorted(
            {
                clean(child.get("entity_type"))
                for child in children
                if clean(child.get("entity_type"))
            }
        )
        evidence_weight = sum(
            parse_int(child.get("source_evidence_weight"), 1)
            for child in children
        )
        bundle = {
            "bundle_id": bundle_id,
            "lane": lane,
            "priority": priority_from_risk(max_risk),
            "risk_score": max_risk,
            "bundle_title": title,
            "recommended_action": action,
            "rationale": rationale,
            "child_record_count": len(children),
            "source_evidence_weight": evidence_weight,
            "families": ";".join(families),
            "entity_types": ";".join(entity_types),
            "allow_batch_all": allow_batch_all,
            "reversible": True,
            "requires_individual_child_selection": not allow_batch_all,
            "publication_eligible": False,
            "apply_action_allowed": False,
            "database_action": "NONE",
            "publication_action": "NONE",
        }
        attached: list[dict[str, Any]] = []
        for index, child in enumerate(children, start=1):
            item = dict(child)
            item["bundle_id"] = bundle_id
            item["bundle_lane"] = lane
            item["bundle_action"] = action
            item["bundle_title"] = title
            item["bundle_child_order"] = index
            attached.append(item)
        return bundle, attached

    def _auto_groups(
        self,
        inputs: dict[str, list[dict[str, str]]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

        for row in inputs["excluded"]:
            child = self._child(
                row,
                "excluded",
                auto_resolution="EXCLUDED_ERROR_OR_NAVIGATION",
            )
            reason = clean(row.get("decision_reason")) or "AUTOMATIC_EXCLUSION"
            groups[
                (
                    ACTION_ACCEPT_EXCLUSIONS,
                    reason,
                    clean(row.get("entity_type")) or "UNKNOWN",
                )
            ].append(child)

        for row in inputs["documents"]:
            child = self._child(
                row,
                "documents",
                auto_resolution="SUPPORTING_DOCUMENT_RETAINED",
            )
            role = clean(row.get("document_role")) or "SUPPORTING_EVIDENCE"
            family = clean(child.get("inferred_family")) or "UNLINKED_DOCUMENTS"
            groups[
                (
                    ACTION_ACCEPT_DOCUMENT_LINKS,
                    role,
                    family,
                )
            ].append(child)

        remaining_identity: list[dict[str, Any]] = []
        for row in inputs["identity_review"]:
            if obvious_non_catalogue(row, self.config):
                child = self._child(
                    row,
                    "identity_review",
                    auto_resolution="NON_CATALOGUE_EVENT_OR_EVIDENCE",
                )
                groups[
                    (
                        ACTION_EXCLUDE_EVENT,
                        clean(row.get("entity_type")) or "NON_CATALOGUE",
                        "EVENT_OR_EVIDENCE",
                    )
                ].append(child)
            else:
                remaining_identity.append(row)

        bundles: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []
        for (action, group_type, family), rows in sorted(groups.items()):
            if action == ACTION_ACCEPT_EXCLUSIONS:
                title = f"Automatic exclusions — {group_type}"
                rationale = (
                    "Error, navigation, access-denied or generic portal records "
                    "remain in the audit ledger and require no Admin decision."
                )
            elif action == ACTION_ACCEPT_DOCUMENT_LINKS:
                title = f"Supporting documents — {family} — {group_type}"
                rationale = (
                    "Documents are retained as evidence and cannot create "
                    "programme, call or Apply identities."
                )
            else:
                title = f"Non-catalogue events/evidence — {group_type}"
                rationale = (
                    "Conference, summit, expo, message, navigation and similar "
                    "records are non-catalogue evidence and are auto-resolved."
                )
            bundle, attached = self._make_bundle(
                lane=LANE_AUTO,
                action=action,
                title=title,
                children=rows,
                rationale=rationale,
                allow_batch_all=True,
            )
            bundles.append(bundle)
            children.extend(attached)
        return bundles, children, remaining_identity

    def _programme_bundles(
        self,
        rows: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        bundles: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []
        for row in rows:
            child = self._child(row, "programmes")
            name = clean(row.get("canonical_name")) or "Unnamed programme family"
            existing = bool(clean(row.get("existing_master_id")))
            if existing:
                action = ACTION_CONFIRM_EXISTING_PROGRAMME
                rationale = (
                    "Confirm the canonical family and its consolidated evidence "
                    "without creating a duplicate master identity."
                )
            else:
                action = ACTION_REVIEW_NEW_PROGRAMME
                rationale = (
                    "Review a possible new permanent MeitY programme family. "
                    "Approval remains separate from publication."
                )
            bundle, attached = self._make_bundle(
                lane=LANE_BATCH if existing else LANE_DEEP,
                action=action,
                title=f"Programme family — {name}",
                children=[child],
                rationale=rationale,
                allow_batch_all=existing,
            )
            bundles.append(bundle)
            children.extend(attached)
        return bundles, children

    def _call_bundles(
        self,
        rows: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        current_individual: list[dict[str, Any]] = []
        for row in rows:
            child = self._child(row, "calls")
            status = clean(
                row.get("application_status")
                or row.get("programme_status")
            )
            if (
                status in POTENTIAL_OPEN_STATUSES
                or clean(row.get("application_url"))
                or clean(row.get("closing_date"))
            ):
                current_individual.append(child)
            else:
                family = clean(child.get("inferred_family")) or "UNPARENTED"
                entity_type = clean(row.get("entity_type")) or "CALL"
                grouped[(family, entity_type)].append(child)

        bundles: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []

        for child in current_individual:
            name = clean(child.get("canonical_name")) or "Potential current call"
            bundle, attached = self._make_bundle(
                lane=LANE_DEEP,
                action=ACTION_REVIEW_CURRENT_CALL,
                title=f"Potential current call — {name}",
                children=[child],
                rationale=(
                    "Potential current or upcoming opportunity requires "
                    "individual deadline, applicant-layer and Apply-route review."
                ),
                allow_batch_all=False,
            )
            bundles.append(bundle)
            children.extend(attached)

        for (family, entity_type), group_rows in sorted(grouped.items()):
            title = f"Calls/challenges — {family} — {entity_type}"
            bundle, attached = self._make_bundle(
                lane=LANE_BATCH,
                action=ACTION_CONFIRM_CALL_GROUP,
                title=title,
                children=group_rows,
                rationale=(
                    "Confirm the grouped call or challenge identities and their "
                    "parent relationship. No current status is inferred."
                ),
                allow_batch_all=True,
            )
            bundles.append(bundle)
            children.extend(attached)
        return bundles, children

    def _historical_bundles(
        self,
        rows: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            child = self._child(row, "historical")
            family = clean(child.get("inferred_family")) or "UNPARENTED_HISTORICAL"
            grouped[family].append(child)

        bundles: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []
        for family, group_rows in sorted(grouped.items()):
            bundle, attached = self._make_bundle(
                lane=LANE_BATCH,
                action=ACTION_CONFIRM_HISTORICAL,
                title=f"Historical evidence — {family}",
                children=group_rows,
                rationale=(
                    "Confirm historical/result classification. These records "
                    "never expose an Apply action."
                ),
                allow_batch_all=True,
            )
            bundles.append(bundle)
            children.extend(attached)
        return bundles, children

    def _identity_bundles(
        self,
        rows: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        programmes = set(self.config.get("potential_programme_types", []))
        calls = set(self.config.get("potential_call_types", []))
        high: list[dict[str, Any]] = []
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for row in rows:
            child = self._child(row, "identity_review")
            entity_type = clean(row.get("entity_type")) or "UNKNOWN"
            score = parse_int(child.get("risk_score"))
            if entity_type in programmes or entity_type in calls or score >= 25:
                high.append(child)
            else:
                grouped[entity_type].append(child)

        bundles: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []

        for child in high:
            name = (
                clean(child.get("canonical_name"))
                or clean(child.get("original_canonical_name"))
                or "Ambiguous identity"
            )
            bundle, attached = self._make_bundle(
                lane=LANE_DEEP,
                action=ACTION_REVIEW_IDENTITY,
                title=f"Identity/role review — {name}",
                children=[child],
                rationale=(
                    "Possible scheme, programme, call or material role conflict "
                    "requires individual Admin evidence review."
                ),
                allow_batch_all=False,
            )
            bundles.append(bundle)
            children.extend(attached)

        for entity_type, group_rows in sorted(grouped.items()):
            bundle, attached = self._make_bundle(
                lane=LANE_BATCH,
                action=ACTION_REVIEW_IDENTITY,
                title=f"Low-risk identity review — {entity_type}",
                children=group_rows,
                rationale=(
                    "Review grouped low-risk evidence. Child records remain "
                    "individually selectable inside the bundle."
                ),
                allow_batch_all=False,
            )
            bundles.append(bundle)
            children.extend(attached)
        return bundles, children

    def _compress_to_limit(
        self,
        bundles: list[dict[str, Any]],
        children: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        maximum = parse_int(
            self.config.get("max_admin_decision_bundles"),
            20,
        )
        decision_bundles = [
            bundle for bundle in bundles if bundle["lane"] != LANE_AUTO
        ]
        if len(decision_bundles) <= maximum:
            return bundles, children

        protected_ids = {
            bundle["bundle_id"]
            for bundle in decision_bundles
            if (
                bundle["lane"] == LANE_DEEP
                and bundle["priority"] in {"CRITICAL", "HIGH"}
            )
            or bundle["recommended_action"] in {
                ACTION_REVIEW_CURRENT_CALL,
                ACTION_REVIEW_NEW_PROGRAMME,
            }
        }
        low_bundles = [
            bundle
            for bundle in decision_bundles
            if bundle["bundle_id"] not in protected_ids
        ]
        protected = [
            bundle
            for bundle in bundles
            if bundle["bundle_id"] in protected_ids
            or bundle["lane"] == LANE_AUTO
        ]

        child_by_bundle: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for child in children:
            child_by_bundle[clean(child.get("bundle_id"))].append(child)

        slots = max(1, maximum - len(protected_ids))
        grouping: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for bundle in low_bundles:
            key = clean(bundle.get("recommended_action")) or ACTION_MIXED_LOW_RISK
            grouping[key].append(bundle)

        merged_bundles: list[dict[str, Any]] = []
        merged_children: list[dict[str, Any]] = []
        groups = list(sorted(grouping.items()))
        if len(groups) > slots:
            groups = [
                (
                    ACTION_MIXED_LOW_RISK,
                    [
                        bundle
                        for _, grouped_bundles in groups
                        for bundle in grouped_bundles
                    ],
                )
            ]

        for action, grouped_bundles in groups:
            group_children = [
                child
                for bundle in grouped_bundles
                for child in child_by_bundle[bundle["bundle_id"]]
            ]
            title = (
                "Compressed low-risk review — "
                + (
                    action
                    if action != ACTION_MIXED_LOW_RISK
                    else "mixed classifications"
                )
            )
            bundle, attached = self._make_bundle(
                lane=LANE_BATCH,
                action=action,
                title=title,
                children=group_children,
                rationale=(
                    "Low-risk bundles were compressed to keep the Admin "
                    "workload within the governed maximum. Child-level "
                    "selection remains mandatory."
                ),
                allow_batch_all=False,
            )
            merged_bundles.append(bundle)
            merged_children.extend(attached)

        kept_children = [
            child
            for child in children
            if (
                clean(child.get("bundle_id")) in protected_ids
                or any(
                    bundle["bundle_id"] == clean(child.get("bundle_id"))
                    and bundle["lane"] == LANE_AUTO
                    for bundle in bundles
                )
            )
        ]
        return protected + merged_bundles, kept_children + merged_children

    def run(self) -> dict[str, Any]:
        source_manifest = self._load_manifest()
        inputs = self._load_inputs()

        auto_bundles, auto_children, remaining_identity = self._auto_groups(inputs)
        programme_bundles, programme_children = self._programme_bundles(
            inputs["programmes"]
        )
        call_bundles, call_children = self._call_bundles(inputs["calls"])
        historical_bundles, historical_children = self._historical_bundles(
            inputs["historical"]
        )
        identity_bundles, identity_children = self._identity_bundles(
            remaining_identity
        )

        bundles = [
            *auto_bundles,
            *programme_bundles,
            *call_bundles,
            *historical_bundles,
            *identity_bundles,
        ]
        children = [
            *auto_children,
            *programme_children,
            *call_children,
            *historical_children,
            *identity_children,
        ]
        bundles, children = self._compress_to_limit(bundles, children)

        source_rows = sum(len(rows) for rows in inputs.values())
        source_weight = sum(
            row_weight(row)
            for rows in inputs.values()
            for row in rows
        )
        child_rows = len(children)
        child_weight = sum(
            parse_int(child.get("source_evidence_weight"), 1)
            for child in children
        )
        if child_rows != source_rows:
            raise RuntimeError(
                f"Review compression row mismatch: {child_rows} != {source_rows}"
            )
        if child_weight != source_weight:
            raise RuntimeError(
                "Review compression evidence-weight mismatch: "
                f"{child_weight} != {source_weight}"
            )
        expected_weight = parse_int(source_manifest.get("source_candidate_count"))
        if expected_weight and source_weight != expected_weight:
            raise RuntimeError(
                "Purified source weight does not reconcile to source candidates: "
                f"{source_weight} != {expected_weight}"
            )

        bundle_by_id = {
            bundle["bundle_id"]: bundle
            for bundle in bundles
        }
        for child in children:
            if clean(child.get("bundle_id")) not in bundle_by_id:
                raise RuntimeError(
                    "Child record references a missing decision bundle."
                )

        auto = [bundle for bundle in bundles if bundle["lane"] == LANE_AUTO]
        batch = [bundle for bundle in bundles if bundle["lane"] == LANE_BATCH]
        deep = [bundle for bundle in bundles if bundle["lane"] == LANE_DEEP]
        decisions = [*batch, *deep]

        maximum = parse_int(
            self.config.get("max_admin_decision_bundles"),
            20,
        )
        if len(decisions) > maximum:
            raise RuntimeError(
                f"Admin decision bundle limit exceeded: {len(decisions)} > {maximum}"
            )

        max_deep = parse_int(self.config.get("max_deep_review_bundles"), 8)
        if len(deep) > max_deep:
            # This is advisory rather than destructive. The manifest records it.
            deep_limit_status = "EXCEEDED"
        else:
            deep_limit_status = "PASS"

        output_dir = self.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        bundle_fields = [
            "bundle_id",
            "lane",
            "priority",
            "risk_score",
            "bundle_title",
            "recommended_action",
            "rationale",
            "child_record_count",
            "source_evidence_weight",
            "families",
            "entity_types",
            "allow_batch_all",
            "reversible",
            "requires_individual_child_selection",
            "publication_eligible",
            "apply_action_allowed",
            "database_action",
            "publication_action",
        ]
        child_fields = [
            "bundle_id",
            "bundle_lane",
            "bundle_action",
            "bundle_title",
            "bundle_child_order",
            "child_id",
            "input_category",
            "source_evidence_weight",
            "inferred_family",
            "risk_score",
            "priority",
            "auto_resolution",
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "source_entity_type",
            "record_kind",
            "application_status",
            "programme_status",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "startup_relevance",
            "parent_master_id",
            "parent_scheme_name",
            "parent_resolution",
            "existing_master_id",
            "existing_public_record",
            "disposition",
            "decision_reason",
            "document_role",
            "source_candidate_id",
            "source_candidate_ids",
            "source_candidate_count",
            "source_evidence_id",
            "evidence_ids",
            "source_titles",
            "source_urls",
            "evidence_excerpt",
            "status_evidence",
            "quality_flags",
            "publication_eligible",
            "apply_action_allowed",
        ]

        write_csv(
            output_dir / "meity_auto_resolved_groups_v3_4_3_8_0_2.csv",
            auto,
            bundle_fields,
        )
        write_csv(
            output_dir / "meity_admin_decision_bundles_v3_4_3_8_0_2.csv",
            decisions,
            bundle_fields,
        )
        write_csv(
            output_dir / "meity_decision_bundle_children_v3_4_3_8_0_2.csv",
            children,
            child_fields,
        )
        write_csv(
            output_dir / "meity_deep_review_bundles_v3_4_3_8_0_2.csv",
            deep,
            bundle_fields,
        )

        summary = {
            "version": VERSION,
            "generated_at": utc_now(),
            "source_manifest_signature": source_manifest.get("signature", ""),
            "source_input_row_count": source_rows,
            "source_evidence_weight": source_weight,
            "auto_resolved_group_count": len(auto),
            "auto_resolved_child_count": sum(
                parse_int(bundle.get("child_record_count"))
                for bundle in auto
            ),
            "auto_resolved_evidence_weight": sum(
                parse_int(bundle.get("source_evidence_weight"))
                for bundle in auto
            ),
            "admin_decision_bundle_count": len(decisions),
            "batch_confirmation_bundle_count": len(batch),
            "deep_review_bundle_count": len(deep),
            "deep_review_limit_status": deep_limit_status,
            "max_admin_decision_bundles": maximum,
            "max_deep_review_bundles": max_deep,
            "decision_child_count": sum(
                parse_int(bundle.get("child_record_count"))
                for bundle in decisions
            ),
            "decision_evidence_weight": sum(
                parse_int(bundle.get("source_evidence_weight"))
                for bundle in decisions
            ),
            "row_reconciliation": child_rows == source_rows,
            "evidence_weight_reconciliation": child_weight == source_weight,
            "apply_action_allowed_count": 0,
            "publication_eligible_count": 0,
            "database_write_performed": False,
            "publication_performed": False,
        }
        signature_payload = {
            "summary": summary,
            "bundles": bundles,
            "children": children,
        }
        summary["signature"] = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()

        (
            output_dir / "meity_review_compression_manifest_v3_4_3_8_0_2.json"
        ).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (
            output_dir / "meity_family_review_summary_v3_4_3_8_0_2.json"
        ).write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "generated_at": summary["generated_at"],
                    "auto_resolved_groups": auto,
                    "decision_bundles": decisions,
                    "database_write_performed": False,
                    "publication_performed": False,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return summary


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_compression(project_root: Path) -> dict[str, Any]:
    paths = CompressionPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return ReviewCompressor(paths, config).run()
