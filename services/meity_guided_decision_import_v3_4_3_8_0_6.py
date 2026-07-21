from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.6"


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def truthy(value: Any) -> bool:
    return clean(value).casefold() in {"1", "true", "yes", "y"}


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
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


def parse_selected_child_ids(value: str) -> list[str]:
    return [
        clean(item)
        for item in clean(value).split(";")
        if clean(item)
    ]


def allowed_decisions(bundle: dict[str, Any]) -> set[str]:
    return {
        clean(item)
        for item in clean(bundle.get("allowed_decisions")).split(";")
        if clean(item)
    }


def decision_plan_id(
    worksheet_signature: str,
    bundle_id: str,
    decision_code: str,
) -> str:
    payload = {
        "worksheet_signature": worksheet_signature,
        "bundle_id": bundle_id,
        "decision_code": decision_code,
    }
    return "meitydecision_" + hashlib.sha256(
        stable_json(payload).encode("utf-8")
    ).hexdigest()[:20]


@dataclass(frozen=True)
class DecisionImportPaths:
    project_root: Path
    source_dir: Path
    output_dir: Path
    config_path: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "DecisionImportPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_4",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_6",
            config_path=(
                root
                / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
            ),
            database_path=root / "database/ssip_staging_v1.db",
        )


class GuidedDecisionImporter:
    def __init__(
        self,
        paths: DecisionImportPaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config

    def _load_manifest(self) -> dict[str, Any]:
        path = (
            self.paths.source_dir
            / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
        )
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _load_bundles(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv"
        )

    def _load_children(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
        )

    def validate_and_plan(
        self,
        worksheet_path: Path,
        strict: bool = True,
    ) -> dict[str, Any]:
        worksheet_path = worksheet_path.resolve()
        rows = read_csv(worksheet_path)

        required_headers = [
            clean(value)
            for value in self.config.get("required_headers", [])
        ]
        actual_headers = list(rows[0].keys()) if rows else []
        missing_headers = [
            header for header in required_headers if header not in actual_headers
        ]

        file_hash = hashlib.sha256(worksheet_path.read_bytes()).hexdigest()
        source_manifest = self._load_manifest()
        bundles = self._load_bundles()
        children = self._load_children()

        bundle_by_id = {
            clean(row.get("bundle_id")): row
            for row in bundles
            if clean(row.get("bundle_id"))
        }
        child_ids_by_bundle: dict[str, set[str]] = {}
        child_rows_by_bundle: dict[str, list[dict[str, str]]] = {}
        for child in children:
            bundle_id = clean(child.get("bundle_id"))
            child_id = clean(child.get("child_id"))
            child_ids_by_bundle.setdefault(bundle_id, set())
            if child_id:
                child_ids_by_bundle[bundle_id].add(child_id)
            child_rows_by_bundle.setdefault(bundle_id, []).append(child)

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen_bundle_ids: set[str] = set()
        decision_to_action = self.config.get(
            "decision_to_bridge_action",
            {},
        )
        positive_decisions = set(
            self.config.get("positive_decisions", [])
        )
        note_required_decisions = set(
            self.config.get("note_required_decisions", [])
        )
        current_call_decision = clean(
            self.config.get("current_call_decision")
        )

        if missing_headers:
            rejected.append(
                {
                    "worksheet_row": 0,
                    "bundle_id": "",
                    "admin_decision": "",
                    "rejection_codes": (
                        "MISSING_REQUIRED_HEADERS:"
                        + ",".join(missing_headers)
                    ),
                    "rejection_detail": (
                        "The worksheet does not match the guided-review export."
                    ),
                }
            )

        for row_number, row in enumerate(rows, start=2):
            bundle_id = clean(row.get("bundle_id"))
            decision = clean(row.get("admin_decision"))
            signature = clean(row.get("link_integrity_signature"))
            selected_ids = parse_selected_child_ids(
                row.get("selected_child_ids", "")
            )
            note = clean(row.get("admin_note"))
            errors: list[str] = []

            if not bundle_id:
                errors.append("BUNDLE_ID_MISSING")
            elif bundle_id in seen_bundle_ids:
                errors.append("DUPLICATE_BUNDLE_DECISION")
            seen_bundle_ids.add(bundle_id)

            bundle = bundle_by_id.get(bundle_id)
            if bundle is None:
                errors.append("UNKNOWN_BUNDLE_ID")
            else:
                if signature != clean(
                    bundle.get("link_integrity_signature")
                ):
                    errors.append("STALE_OR_TAMPERED_LINK_SIGNATURE")

                allowed = allowed_decisions(bundle)
                if decision not in allowed:
                    errors.append("DECISION_NOT_ALLOWED_FOR_BUNDLE")

                valid_child_ids = child_ids_by_bundle.get(bundle_id, set())
                unknown_selected = [
                    child_id
                    for child_id in selected_ids
                    if child_id not in valid_child_ids
                ]
                if unknown_selected:
                    errors.append(
                        "UNKNOWN_SELECTED_CHILD:"
                        + ",".join(unknown_selected)
                    )

                requires_selection = truthy(
                    bundle.get("requires_child_selection")
                )
                if requires_selection and not selected_ids:
                    errors.append("CHILD_SELECTION_REQUIRED")

                requires_note = (
                    truthy(bundle.get("requires_admin_note"))
                    or decision in note_required_decisions
                )
                if requires_note and not note:
                    errors.append("ADMIN_NOTE_REQUIRED")

                if decision in positive_decisions and not truthy(
                    bundle.get("safe_positive_decision_allowed")
                ):
                    errors.append("POSITIVE_DECISION_BLOCKED_BY_LINK_SAFETY")

                if (
                    decision == current_call_decision
                    and not truthy(
                        bundle.get(
                            "current_application_integrity_complete"
                        )
                    )
                ):
                    errors.append(
                        "CURRENT_APPLICATION_INTEGRITY_INCOMPLETE"
                    )

            if decision in {"", "PENDING"}:
                errors.append("NO_COMPLETED_DECISION")

            if decision not in decision_to_action:
                errors.append("UNKNOWN_DECISION_CODE")

            if errors:
                rejected.append(
                    {
                        "worksheet_row": row_number,
                        "bundle_id": bundle_id,
                        "admin_decision": decision,
                        "rejection_codes": ";".join(
                            dict.fromkeys(errors)
                        ),
                        "rejection_detail": (
                            "The row cannot enter the governed Admin bridge."
                        ),
                    }
                )
                continue

            bridge_action = clean(decision_to_action[decision])
            attached_children = child_rows_by_bundle.get(bundle_id, [])
            selected_children = (
                [
                    child
                    for child in attached_children
                    if clean(child.get("child_id")) in set(selected_ids)
                ]
                if selected_ids
                else attached_children
            )

            accepted.append(
                {
                    "worksheet_row": row_number,
                    "decision_plan_id": decision_plan_id(
                        file_hash,
                        bundle_id,
                        decision,
                    ),
                    "bundle_id": bundle_id,
                    "bundle_title": clean(
                        row.get("bundle_title")
                        or bundle.get("bundle_title")
                    ),
                    "link_integrity_signature": signature,
                    "admin_decision": decision,
                    "admin_decision_label": clean(
                        row.get("admin_decision_label")
                    ),
                    "admin_note": note,
                    "selected_child_ids": ";".join(
                        clean(child.get("child_id"))
                        for child in selected_children
                        if clean(child.get("child_id"))
                    ),
                    "selected_child_count": len(selected_children),
                    "bridge_action": bridge_action,
                    "database_action": "NONE",
                    "publication_action": "NONE",
                    "source_manifest_signature": clean(
                        source_manifest.get("link_integrity_signature")
                    ),
                }
            )

        if strict and rejected:
            plan_status = "BLOCKED"
        elif accepted:
            plan_status = "READY_FOR_REVIEW"
        else:
            plan_status = "EMPTY"

        counts_by_decision: dict[str, int] = {}
        counts_by_action: dict[str, int] = {}
        for item in accepted:
            counts_by_decision[item["admin_decision"]] = (
                counts_by_decision.get(item["admin_decision"], 0) + 1
            )
            counts_by_action[item["bridge_action"]] = (
                counts_by_action.get(item["bridge_action"], 0) + 1
            )

        plan_signature_payload = {
            "version": VERSION,
            "source_link_integrity_signature": source_manifest.get(
                "link_integrity_signature",
                "",
            ),
            "worksheet_sha256": file_hash,
            "accepted": accepted,
            "rejected": rejected,
            "strict": strict,
        }
        plan_signature = hashlib.sha256(
            stable_json(plan_signature_payload).encode("utf-8")
        ).hexdigest()

        summary = {
            "version": VERSION,
            "generated_at": utc_now(),
            "worksheet_path": str(worksheet_path),
            "worksheet_sha256": file_hash,
            "worksheet_row_count": len(rows),
            "accepted_decision_count": len(accepted),
            "rejected_decision_count": len(rejected),
            "missing_required_headers": missing_headers,
            "plan_status": plan_status,
            "strict_mode": strict,
            "counts_by_decision": dict(sorted(counts_by_decision.items())),
            "counts_by_bridge_action": dict(sorted(counts_by_action.items())),
            "source_link_integrity_signature": source_manifest.get(
                "link_integrity_signature",
                "",
            ),
            "decision_plan_signature": plan_signature,
            "database_write_performed": False,
            "publication_performed": False,
            "admin_bridge_applied": False,
        }

        output_dir = self.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        accepted_fields = [
            "worksheet_row",
            "decision_plan_id",
            "bundle_id",
            "bundle_title",
            "link_integrity_signature",
            "admin_decision",
            "admin_decision_label",
            "admin_note",
            "selected_child_ids",
            "selected_child_count",
            "bridge_action",
            "database_action",
            "publication_action",
            "source_manifest_signature",
        ]
        rejected_fields = [
            "worksheet_row",
            "bundle_id",
            "admin_decision",
            "rejection_codes",
            "rejection_detail",
        ]

        write_csv(
            output_dir
            / "meity_validated_admin_decisions_v3_4_3_8_0_6.csv",
            accepted,
            accepted_fields,
        )
        write_csv(
            output_dir
            / "meity_rejected_decision_rows_v3_4_3_8_0_6.csv",
            rejected,
            rejected_fields,
        )
        write_csv(
            output_dir
            / "meity_admin_bridge_preview_v3_4_3_8_0_6.csv",
            accepted,
            accepted_fields,
        )
        (
            output_dir
            / "meity_decision_import_summary_v3_4_3_8_0_6.json"
        ).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (
            output_dir
            / "meity_signed_admin_bridge_plan_v3_4_3_8_0_6.json"
        ).write_text(
            json.dumps(
                {
                    "summary": summary,
                    "accepted_decisions": accepted,
                    "rejected_decisions": rejected,
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


def run_decision_import(
    project_root: Path,
    worksheet_path: Path,
    strict: bool = True,
) -> dict[str, Any]:
    paths = DecisionImportPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return GuidedDecisionImporter(paths, config).validate_and_plan(
        worksheet_path,
        strict=strict,
    )
