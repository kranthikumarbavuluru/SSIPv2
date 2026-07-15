from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.3"
SOURCE_VERSION = "3.4.3.8.0.2"

LANE_BATCH = "BATCH_CONFIRMATION"
LANE_DEEP = "DEEP_REVIEW"

SAFE_CURRENT_ACTION = "VERIFY_CURRENT_CALL_EVIDENCE"
SAFE_HISTORICAL_ACTION = "CONFIRM_HISTORICAL_CLASSIFICATION"
SAFE_PROGRAMME_ACTION = "CONFIRM_CANONICAL_PROGRAMME_FAMILY"
SAFE_NEW_PROGRAMME_ACTION = "REVIEW_NEW_PROGRAMME_IDENTITY"
SAFE_CALL_ACTION = "CONFIRM_CALL_IDENTITY_AND_PARENT"
SAFE_IDENTITY_ACTION = "REVIEW_IDENTITY_OR_ROLE"

TEMPORAL_CURRENT = "CURRENT_STATUS_EVIDENCE_COMPLETE"
TEMPORAL_HISTORICAL = "HISTORICAL_BY_TITLE_OR_DEADLINE"
TEMPORAL_UNVERIFIED = "CURRENT_STATUS_NOT_PROVEN"
TEMPORAL_NOT_APPLICABLE = "NOT_APPLICABLE"

PARENT_DIRECT = "DIRECT_PARENT_EVIDENCE"
PARENT_ALIAS = "TITLE_OR_URL_ALIAS_MATCH"
PARENT_UNRESOLVED = "UNRESOLVED"
PARENT_CONFLICT = "CONFLICTING_PARENT_EVIDENCE"
PARENT_NOT_APPLICABLE = "NOT_APPLICABLE"

PERMANENT_TYPES = {
    "PERMANENT_SCHEME",
    "PERMANENT_PROGRAMME",
    "ACCELERATOR_PROGRAMME",
    "GRANT_PROGRAMME",
    "INCUBATION_PROGRAMME",
    "ECOSYSTEM_PROGRAMME",
    "IMPLEMENTATION_PROGRAMME",
}


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


def parse_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def title_years(value: str) -> list[int]:
    return sorted(
        {
            int(match)
            for match in re.findall(r"\b(20\d{2})\b", clean(value))
        }
    )


def official_url(url: str, domains: Iterable[str]) -> bool:
    try:
        host = urllib.parse.urlsplit(clean(url)).hostname or ""
    except ValueError:
        return False
    host = host.casefold()
    return any(
        host == domain.casefold()
        or host.endswith("." + domain.casefold())
        for domain in domains
    )


def evidence_text(row: dict[str, Any]) -> str:
    return clean(
        " ".join(
            clean(row.get(key))
            for key in (
                "canonical_name",
                "original_canonical_name",
                "source_titles",
                "evidence_excerpt",
                "status_evidence",
                "quality_flags",
                "official_page_url",
                "application_url",
            )
        )
    )


def contains_marker(text: str, markers: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(clean(marker).casefold() in lowered for marker in markers)


def verification_is_fresh(
    last_verified_at: Any,
    today: date,
    freshness_days: int,
) -> bool:
    parsed = parse_datetime(last_verified_at)
    if parsed is None:
        return False
    verified_date = parsed.date()
    delta = (today - verified_date).days
    return 0 <= delta <= freshness_days


def temporal_validation(
    row: dict[str, Any],
    config: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    title = clean(row.get("canonical_name") or row.get("original_canonical_name"))
    years = title_years(title)
    opening = parse_date(row.get("opening_date"))
    closing = parse_date(row.get("closing_date"))
    application_url = clean(row.get("application_url"))
    status = clean(
        row.get("application_status")
        or row.get("programme_status")
    ).upper()
    evidence = evidence_text(row)
    explicit_open = contains_marker(
        evidence,
        config.get("explicit_open_markers", []),
    )
    reopened = contains_marker(
        evidence,
        config.get("reopen_markers", []),
    )
    official_application = official_url(
        application_url,
        config.get("official_domains", []),
    )
    last_verified_at = clean(row.get("last_verified_at"))
    fresh = verification_is_fresh(
        last_verified_at,
        today,
        parse_int(config.get("verification_freshness_days"), 45),
    )

    historical_title = any(year < today.year for year in years)
    future_deadline = bool(closing and closing >= today)
    future_opening = bool(opening and opening > today)

    current_complete = (
        status in {"OPEN", "UPCOMING"}
        and future_deadline
        and explicit_open
        and official_application
        and fresh
    )
    if historical_title and not reopened:
        current_complete = False

    flags: list[str] = []
    if years:
        flags.append("TITLE_YEAR:" + ",".join(str(year) for year in years))
    if historical_title and not reopened:
        flags.append("HISTORICAL_TITLE_WITHOUT_REOPEN_EVIDENCE")
    if status in {"OPEN", "UPCOMING"} and not future_deadline:
        flags.append("CURRENT_DEADLINE_NOT_PROVEN")
    if status in {"OPEN", "UPCOMING"} and not explicit_open:
        flags.append("EXPLICIT_OPEN_LANGUAGE_NOT_PROVEN")
    if status in {"OPEN", "UPCOMING"} and not official_application:
        flags.append("OFFICIAL_APPLICATION_ROUTE_NOT_PROVEN")
    if status in {"OPEN", "UPCOMING"} and not fresh:
        flags.append("RECENT_VERIFICATION_NOT_PROVEN")

    if current_complete:
        result = TEMPORAL_CURRENT
        safe_status = status
    elif historical_title or (closing and closing < today):
        result = TEMPORAL_HISTORICAL
        safe_status = "HISTORICAL_CLOSED"
    elif status in {"OPEN", "UPCOMING"} or future_opening or application_url:
        result = TEMPORAL_UNVERIFIED
        safe_status = "VERIFICATION_REQUIRED"
    else:
        result = TEMPORAL_NOT_APPLICABLE
        safe_status = status or "NOT_APPLICABLE"

    return {
        "temporal_validation": result,
        "safe_application_status": safe_status,
        "title_years": ";".join(str(year) for year in years),
        "historical_title": historical_title,
        "explicit_open_evidence": explicit_open,
        "reopen_evidence": reopened,
        "future_deadline_proven": future_deadline,
        "official_application_route": official_application,
        "recent_verification_proven": fresh,
        "last_verified_at": last_verified_at,
        "temporal_flags": ";".join(flags),
    }


def family_alias_matches(
    value: str,
    aliases: dict[str, list[str]],
) -> list[str]:
    key = normalize(value)
    matches: list[str] = []
    for family, values in aliases.items():
        for alias in [family, *values]:
            alias_key = normalize(alias)
            if alias_key and (
                key == alias_key
                or alias_key in key
            ):
                matches.append(family)
                break
    return sorted(set(matches))


def parent_link_repair(
    row: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    entity_type = clean(row.get("entity_type"))
    record_kind = clean(row.get("record_kind"))
    if entity_type in PERMANENT_TYPES or record_kind == "SCHEME_PROGRAMME":
        return {
            "repaired_parent_scheme_name": "",
            "repaired_parent_master_id": "",
            "parent_link_resolution": PARENT_NOT_APPLICABLE,
            "parent_link_flags": "",
            "programme_alias_matches": "",
            "standalone_call_matches": "",
        }

    title_url = clean(
        f"{row.get('canonical_name', '')} "
        f"{row.get('original_canonical_name', '')} "
        f"{row.get('official_page_url', '')}"
    )
    programme_aliases = config.get("programme_aliases", {})
    standalone_aliases = config.get("standalone_call_aliases", {})

    direct_parent = clean(row.get("parent_scheme_name"))
    direct_parent_id = clean(row.get("parent_master_id"))
    inferred = clean(row.get("inferred_family"))

    programme_matches = family_alias_matches(
        title_url,
        programme_aliases,
    )
    standalone_matches = family_alias_matches(
        title_url,
        standalone_aliases,
    )

    direct_matches = (
        family_alias_matches(direct_parent, programme_aliases)
        if direct_parent
        else []
    )

    flags: list[str] = []
    repaired_parent = ""
    repaired_parent_id = ""
    resolution = PARENT_UNRESOLVED

    if standalone_matches and not programme_matches:
        flags.append("STANDALONE_CALL_IDENTITY")
        if direct_parent or inferred:
            flags.append("INCIDENTAL_PARENT_LINK_REMOVED")
        repaired_parent = ""
        repaired_parent_id = ""
        resolution = PARENT_UNRESOLVED
    elif direct_parent and direct_matches:
        if programme_matches and direct_matches[0] not in programme_matches:
            flags.append("DIRECT_PARENT_CONFLICTS_WITH_TITLE_OR_URL")
            resolution = PARENT_CONFLICT
        else:
            repaired_parent = direct_matches[0]
            repaired_parent_id = direct_parent_id
            resolution = PARENT_DIRECT
    elif len(programme_matches) == 1:
        repaired_parent = programme_matches[0]
        repaired_parent_id = (
            direct_parent_id
            if direct_parent and normalize(direct_parent) == normalize(repaired_parent)
            else ""
        )
        resolution = PARENT_ALIAS
    elif len(programme_matches) > 1:
        flags.append("MULTIPLE_PROGRAMME_ALIAS_MATCHES")
        resolution = PARENT_CONFLICT
    else:
        if direct_parent or inferred:
            flags.append("UNSUPPORTED_PARENT_LINK_REMOVED")
        resolution = PARENT_UNRESOLVED

    if inferred and repaired_parent and normalize(inferred) != normalize(repaired_parent):
        flags.append("INFERRED_FAMILY_REPAIRED")
    if inferred and not repaired_parent:
        flags.append("INFERRED_FAMILY_CLEARED")

    return {
        "repaired_parent_scheme_name": repaired_parent,
        "repaired_parent_master_id": repaired_parent_id,
        "parent_link_resolution": resolution,
        "parent_link_flags": ";".join(flags),
        "programme_alias_matches": ";".join(programme_matches),
        "standalone_call_matches": ";".join(standalone_matches),
    }


def safe_recommended_action(
    original_action: str,
    temporal: str,
    config: dict[str, Any],
) -> str:
    mapped = clean(
        config.get("safe_action_labels", {}).get(
            clean(original_action),
            SAFE_IDENTITY_ACTION,
        )
    )
    if temporal == TEMPORAL_HISTORICAL:
        return SAFE_HISTORICAL_ACTION
    if temporal == TEMPORAL_UNVERIFIED and mapped == SAFE_CURRENT_ACTION:
        return SAFE_IDENTITY_ACTION
    return mapped


def safe_decision_options(action: str) -> list[str]:
    if action == SAFE_HISTORICAL_ACTION:
        positive = "CONFIRM_HISTORICAL"
    elif action == SAFE_PROGRAMME_ACTION:
        positive = "CONFIRM_PROGRAMME_IDENTITY"
    elif action == SAFE_NEW_PROGRAMME_ACTION:
        positive = "CONFIRM_NEW_PROGRAMME_FOR_STAGING_REVIEW"
    elif action == SAFE_CALL_ACTION:
        positive = "CONFIRM_CALL_AND_PARENT"
    elif action == SAFE_CURRENT_ACTION:
        positive = "CONFIRM_CURRENT_CALL_EVIDENCE_COMPLETE"
    else:
        positive = "CONFIRM_REVIEW_CLASSIFICATION"
    return [
        "PENDING",
        positive,
        "NEEDS_MORE_EVIDENCE",
        "DEFER",
        "REJECT_CLASSIFICATION",
    ]


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


@dataclass(frozen=True)
class SafetyPaths:
    project_root: Path
    source_dir: Path
    purified_source_dir: Path
    output_dir: Path
    config_path: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "SafetyPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_2",
            purified_source_dir=root / "data/departments/meity/v3_4_3_8_0_1",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_3",
            config_path=(
                root / "config/meity_temporal_parent_safety_v3_4_3_8_0_3.json"
            ),
            database_path=root / "database/ssip_staging_v1.db",
        )


class DecisionSafetyGate:
    def __init__(
        self,
        paths: SafetyPaths,
        config: dict[str, Any],
        today: date | None = None,
    ) -> None:
        self.paths = paths
        self.config = config
        self.today = today or date.today()

    def _load_manifest(self) -> dict[str, Any]:
        path = (
            self.paths.source_dir
            / "meity_review_compression_manifest_v3_4_3_8_0_2.json"
        )
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _load_children(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_decision_bundle_children_v3_4_3_8_0_2.csv"
        )

    def _load_bundles(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_admin_decision_bundles_v3_4_3_8_0_2.csv"
        )

    def _enrich_verification_dates(
        self,
        children: list[dict[str, str]],
    ) -> None:
        candidate_to_verified: dict[str, str] = {}
        for filename in (
            "meity_purified_programme_families_v3_4_3_8_0_1.csv",
            "meity_purified_calls_challenges_v3_4_3_8_0_1.csv",
            "meity_purified_historical_events_v3_4_3_8_0_1.csv",
            "meity_identity_role_review_v3_4_3_8_0_1.csv",
        ):
            for row in read_csv(self.paths.purified_source_dir / filename):
                candidate_id = clean(row.get("source_candidate_id"))
                last_verified = clean(row.get("last_verified_at"))
                if candidate_id and last_verified:
                    candidate_to_verified[candidate_id] = last_verified

        for child in children:
            if clean(child.get("last_verified_at")):
                continue
            candidate_id = clean(child.get("source_candidate_id"))
            if candidate_id in candidate_to_verified:
                child["last_verified_at"] = candidate_to_verified[candidate_id]

    def run(self) -> dict[str, Any]:
        source_manifest = self._load_manifest()
        source_bundles = self._load_bundles()
        source_children = self._load_children()
        self._enrich_verification_dates(source_children)

        source_bundle_map = {
            row["bundle_id"]: row
            for row in source_bundles
        }
        decision_bundle_ids = set(source_bundle_map)

        source_decision_children = [
            child
            for child in source_children
            if clean(child.get("bundle_id")) in decision_bundle_ids
        ]

        safe_children: list[dict[str, Any]] = []
        temporal_downgrades = 0
        parent_repairs = 0
        current_complete = 0
        historical_count = 0

        for child in source_decision_children:
            repaired = dict(child)
            temporal = temporal_validation(
                repaired,
                self.config,
                self.today,
            )
            parent = parent_link_repair(
                repaired,
                self.config,
            )
            repaired.update(temporal)
            repaired.update(parent)
            repaired["publication_eligible"] = False
            repaired["apply_action_allowed"] = False

            if (
                clean(child.get("bundle_action")) == "REVIEW_CURRENT_CALL"
                and temporal["temporal_validation"] != TEMPORAL_CURRENT
            ):
                temporal_downgrades += 1
            child_is_programme = (
                clean(child.get("entity_type")) in PERMANENT_TYPES
                or clean(child.get("record_kind")) == "SCHEME_PROGRAMME"
            )
            if (
                not child_is_programme
                and clean(child.get("inferred_family"))
                != clean(parent["repaired_parent_scheme_name"])
            ):
                parent_repairs += 1
            if temporal["temporal_validation"] == TEMPORAL_CURRENT:
                current_complete += 1
            if temporal["temporal_validation"] == TEMPORAL_HISTORICAL:
                historical_count += 1

            safe_children.append(repaired)

        children_by_bundle: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for child in safe_children:
            children_by_bundle[clean(child.get("bundle_id"))].append(child)

        safe_bundles: list[dict[str, Any]] = []
        for source_bundle in source_bundles:
            bundle_id = source_bundle["bundle_id"]
            children = children_by_bundle.get(bundle_id, [])
            if not children:
                continue

            temporal_states = sorted(
                {
                    clean(child.get("temporal_validation"))
                    for child in children
                    if clean(child.get("temporal_validation"))
                }
            )
            parent_states = sorted(
                {
                    clean(child.get("parent_link_resolution"))
                    for child in children
                    if clean(child.get("parent_link_resolution"))
                }
            )

            original_action = clean(source_bundle.get("recommended_action"))
            if len(children) == 1:
                temporal_state = clean(children[0].get("temporal_validation"))
            elif TEMPORAL_CURRENT in temporal_states:
                temporal_state = TEMPORAL_CURRENT
            elif TEMPORAL_HISTORICAL in temporal_states:
                temporal_state = TEMPORAL_HISTORICAL
            else:
                temporal_state = TEMPORAL_UNVERIFIED

            safe_action = safe_recommended_action(
                original_action,
                temporal_state,
                self.config,
            )

            lane = clean(source_bundle.get("lane"))
            priority = clean(source_bundle.get("priority"))
            rationale = clean(source_bundle.get("rationale"))
            title = clean(source_bundle.get("bundle_title"))

            if temporal_state == TEMPORAL_HISTORICAL:
                title = re.sub(
                    r"(?i)^Potential current call\s*—\s*",
                    "Historical/status review — ",
                    title,
                )
                rationale = (
                    "The title year or deadline indicates historical activity. "
                    "Current status is not accepted without explicit reopened "
                    "evidence, a future deadline, an official application route "
                    "and recent verification."
                )
                lane = LANE_BATCH
                priority = "MEDIUM"
            elif safe_action == SAFE_CURRENT_ACTION:
                lane = LANE_DEEP
                priority = "HIGH"
                rationale = (
                    "All current-status fields appear complete, but Admin must "
                    "verify the official deadline, application route, applicant "
                    "layer and recent verification before any later staging step."
                )
            elif original_action == "REVIEW_CURRENT_CALL":
                title = re.sub(
                    r"(?i)^Potential current call\s*—\s*",
                    "Current-status evidence review — ",
                    title,
                )
                rationale = (
                    "Current or upcoming status is not proven. Review the missing "
                    "deadline, open-language, application-route or verification "
                    "evidence. This does not approve OPEN status."
                )
                lane = LANE_DEEP
                priority = "HIGH"

            requires_child_selection = (
                lane == LANE_DEEP
                or clean(source_bundle.get("requires_individual_child_selection"))
                == "True"
            )
            requires_note = lane == LANE_DEEP

            options = safe_decision_options(safe_action)
            if "ACCEPT_RECOMMENDATION" in options:
                raise RuntimeError(
                    "Ambiguous ACCEPT_RECOMMENDATION survived decision repair."
                )

            signature_payload = {
                "bundle_id": bundle_id,
                "source_signature": source_manifest.get("signature", ""),
                "safe_action": safe_action,
                "temporal_states": temporal_states,
                "parent_states": parent_states,
                "child_signatures": [
                    {
                        "child_id": child.get("child_id", ""),
                        "temporal": child.get("temporal_validation", ""),
                        "parent": child.get("parent_link_resolution", ""),
                        "safe_status": child.get("safe_application_status", ""),
                    }
                    for child in children
                ],
            }
            bundle_signature = hashlib.sha256(
                stable_json(signature_payload).encode("utf-8")
            ).hexdigest()

            safe_bundles.append(
                {
                    **source_bundle,
                    "lane": lane,
                    "priority": priority,
                    "bundle_title": title,
                    "original_recommended_action": original_action,
                    "recommended_action": safe_action,
                    "rationale": rationale,
                    "temporal_states": ";".join(temporal_states),
                    "parent_link_states": ";".join(parent_states),
                    "requires_child_selection": requires_child_selection,
                    "requires_admin_note": requires_note,
                    "allowed_decisions": ";".join(options),
                    "bundle_signature": bundle_signature,
                    "publication_eligible": False,
                    "apply_action_allowed": False,
                    "database_action": "NONE",
                    "publication_action": "NONE",
                }
            )

        safe_bundle_ids = {bundle["bundle_id"] for bundle in safe_bundles}
        if safe_bundle_ids != decision_bundle_ids:
            missing = decision_bundle_ids - safe_bundle_ids
            extra = safe_bundle_ids - decision_bundle_ids
            raise RuntimeError(
                f"Decision bundle reconciliation failed. Missing={missing}, extra={extra}"
            )

        if any(
            "ACCEPT_RECOMMENDATION"
            in clean(bundle.get("allowed_decisions"))
            for bundle in safe_bundles
        ):
            raise RuntimeError("Ambiguous decision wording remains.")

        unsafe_current = [
            child
            for child in safe_children
            if clean(child.get("safe_application_status")) in {"OPEN", "UPCOMING"}
            and clean(child.get("temporal_validation")) != TEMPORAL_CURRENT
        ]
        if unsafe_current:
            raise RuntimeError(
                "Unsafe OPEN/UPCOMING status survived temporal safety gate."
            )

        output_dir = self.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        bundle_fields = [
            "bundle_id",
            "bundle_signature",
            "lane",
            "priority",
            "risk_score",
            "bundle_title",
            "original_recommended_action",
            "recommended_action",
            "rationale",
            "child_record_count",
            "source_evidence_weight",
            "families",
            "entity_types",
            "temporal_states",
            "parent_link_states",
            "requires_child_selection",
            "requires_admin_note",
            "allowed_decisions",
            "reversible",
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
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "source_entity_type",
            "application_status",
            "safe_application_status",
            "temporal_validation",
            "title_years",
            "historical_title",
            "explicit_open_evidence",
            "reopen_evidence",
            "future_deadline_proven",
            "official_application_route",
            "recent_verification_proven",
            "last_verified_at",
            "temporal_flags",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "inferred_family",
            "parent_scheme_name",
            "parent_master_id",
            "repaired_parent_scheme_name",
            "repaired_parent_master_id",
            "parent_link_resolution",
            "parent_link_flags",
            "programme_alias_matches",
            "standalone_call_matches",
            "parent_resolution",
            "evidence_excerpt",
            "status_evidence",
            "source_urls",
            "quality_flags",
            "publication_eligible",
            "apply_action_allowed",
        ]

        write_csv(
            output_dir / "meity_safe_admin_decision_bundles_v3_4_3_8_0_3.csv",
            safe_bundles,
            bundle_fields,
        )
        write_csv(
            output_dir / "meity_safe_decision_children_v3_4_3_8_0_3.csv",
            safe_children,
            child_fields,
        )
        write_csv(
            output_dir / "meity_temporal_downgrades_v3_4_3_8_0_3.csv",
            [
                child
                for child in safe_children
                if clean(child.get("bundle_action")) == "REVIEW_CURRENT_CALL"
                and clean(child.get("temporal_validation")) != TEMPORAL_CURRENT
            ],
            child_fields,
        )
        write_csv(
            output_dir / "meity_parent_link_repairs_v3_4_3_8_0_3.csv",
            [
                child
                for child in safe_children
                if (
                    clean(child.get("entity_type")) not in PERMANENT_TYPES
                    and clean(child.get("record_kind")) != "SCHEME_PROGRAMME"
                    and clean(child.get("inferred_family"))
                    != clean(child.get("repaired_parent_scheme_name"))
                )
            ],
            child_fields,
        )

        session_key_payload = {
            "version": VERSION,
            "source_signature": source_manifest.get("signature", ""),
            "bundle_signatures": sorted(
                bundle["bundle_signature"]
                for bundle in safe_bundles
            ),
        }
        session_state_signature = hashlib.sha256(
            stable_json(session_key_payload).encode("utf-8")
        ).hexdigest()

        summary = {
            "version": VERSION,
            "generated_at": utc_now(),
            "source_manifest_signature": source_manifest.get("signature", ""),
            "source_decision_bundle_count": len(source_bundles),
            "safe_decision_bundle_count": len(safe_bundles),
            "safe_child_count": len(safe_children),
            "temporal_downgrade_count": temporal_downgrades,
            "parent_link_repair_count": parent_repairs,
            "current_status_evidence_complete_count": current_complete,
            "historical_classification_count": historical_count,
            "unsafe_current_status_count": len(unsafe_current),
            "ambiguous_decision_label_count": 0,
            "deep_review_requires_child_selection": True,
            "deep_review_requires_admin_note": True,
            "session_state_signature": session_state_signature,
            "session_decisions_invalidated_on_signature_change": True,
            "apply_action_allowed_count": 0,
            "publication_eligible_count": 0,
            "database_write_performed": False,
            "publication_performed": False,
        }
        signature_payload = {
            "summary": summary,
            "bundles": safe_bundles,
            "children": safe_children,
        }
        summary["signature"] = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()

        (
            output_dir
            / "meity_temporal_parent_safety_manifest_v3_4_3_8_0_3.json"
        ).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return summary


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_safety_gate(
    project_root: Path,
    today: date | None = None,
) -> dict[str, Any]:
    paths = SafetyPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return DecisionSafetyGate(paths, config, today=today).run()
