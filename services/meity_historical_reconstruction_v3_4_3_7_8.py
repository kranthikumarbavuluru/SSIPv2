from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.7.8"
SOURCE = "MeitY Startup Hub"
MINISTRY = "Ministry of Electronics and Information Technology (MeitY)"

EXPECTED_WITHDRAWN_IDS = (
    "meitycall_a95e53af41b5c53999cf",
    "meitycall_98f3c3720f15dae91ade",
    "meitycall_cbb7e8cd8fe24b00afd9",
    "meitycall_533fd1397d9885d223d2",
    "meitycall_37a5f7055e19110989f3",
    "meitycall_056b139f54fba2e7a8b3",
    "meitycall_a4a05a783de6e3478e54",
    "meitycall_b2b15a80eaf08c64193e",
    "meitycall_c53a5b2578e3b03d7291",
    "meitycall_0c7011d0b31e008b13b8",
    "meitycall_11ee67b180d2f208f8ef",
    "meitycall_ba1e7d64714d21401ed3",
    "meitycall_8d44c653724d98cb049d",
    "meitycall_f76675fa4a424f58ed0b",
    "meitycall_2f886d6194cb0b281a16",
    "meitycall_f6f817622dfc3035cf72",
)

ARCHIVE_RULES = {
    "meitycall_533fd1397d9885d223d2": {
        "canonical_title": (
            "DRISHTI – SSB Grand Challenge on Strengthening "
            "Border Security"
        ),
        "historical_year": "",
        "programme_type": "GRAND_CHALLENGE",
        "sector": "Defence & Border Security",
        "applicant_layer": "STARTUP",
        "historical_basis": (
            "The official page states that MeitY and SSB had "
            "undertaken the DRISHTI Grand Challenge and describes "
            "the intended use of startup-developed solutions."
        ),
        "qualification_markers": (
            "had undertaken a grand challenge",
            "solutions developed by the start-ups",
        ),
    },
    "meitycall_a4a05a783de6e3478e54": {
        "canonical_title": "Google Appscale Academy 2023",
        "historical_year": "2023",
        "programme_type": "ACCELERATOR_COHORT",
        "sector": "Digital Products & Mobile Applications",
        "applicant_layer": "STARTUP",
        "historical_basis": (
            "The official page identifies the Class of 2023, states "
            "that the programme was executed, and records 100 startups "
            "selected from more than 950 applications."
        ),
        "qualification_markers": (
            "class of 2023",
            "was executed",
            "100 startups selected",
        ),
    },
    "meitycall_b2b15a80eaf08c64193e": {
        "canonical_title": (
            "IHMCL Barrier-less Free-flow Tolling and Intelligent "
            "Traffic Management Hackathon"
        ),
        "historical_year": "",
        "programme_type": "HACKATHON",
        "sector": "Mobility & Intelligent Transport Systems",
        "applicant_layer": "STARTUP",
        "historical_basis": (
            "The official page states that IHMCL and MeitY Startup "
            "Hub organized a hackathon with Indian startups for smart "
            "tolling and traffic-management solutions."
        ),
        "qualification_markers": (
            "organized a hackathon",
            "with indian start-ups",
        ),
    },
}

REVIEW_RULES = {
    "meitycall_a95e53af41b5c53999cf": {
        "proposed_title": "BHUMI – BSF Border Security Hackathon",
        "reason": (
            "A distinct hackathon identity is present, but the page "
            "uses prospective language and provides no verified dated "
            "completion or application window."
        ),
        "required_action": (
            "Locate dated official announcement, result or closure "
            "evidence before historical qualification."
        ),
    },
    "meitycall_0c7011d0b31e008b13b8": {
        "proposed_title": (
            "CREST Semiconductor Accelerator for Early-Stage Startups"
        ),
        "reason": (
            "The official page describes a launched accelerator, but "
            "the specific cohort window and historical closure are not "
            "yet evidenced."
        ),
        "required_action": (
            "Recover cohort dates, selection result and applicant-layer "
            "evidence."
        ),
    },
    "meitycall_2f886d6194cb0b281a16": {
        "proposed_title": "XR Startup Program",
        "reason": (
            "A startup accelerator programme identity is established, "
            "but no dated application call or completed cohort instance "
            "is currently separated from the permanent programme page."
        ),
        "required_action": (
            "Discover and link individual accelerator or grand-challenge "
            "cohort windows."
        ),
    },
    "meitycall_f6f817622dfc3035cf72": {
        "proposed_title": "SAMRIDH Cohort 2",
        "reason": (
            "The evidence is an encoded PDF filename rather than a "
            "curated call record, and its dates have not been extracted."
        ),
        "required_action": (
            "Extract the official PDF, recover the canonical call title, "
            "dates and applicant layer, then create a separate call "
            "instance linked to SAMRIDH."
        ),
    },
}

EXCLUSION_RULES = {
    "meitycall_98f3c3720f15dae91ade": (
        "EVENT_OR_DELEGATION",
        "Brussels page describes an international delegation and ecosystem engagement.",
    ),
    "meitycall_cbb7e8cd8fe24b00afd9": (
        "NAVIGATION_OR_DIRECTORY",
        "Challenges is a listing page and not an individual call identity.",
    ),
    "meitycall_37a5f7055e19110989f3": (
        "NAVIGATION_OR_DIRECTORY",
        "Event Partner is an events listing rather than a call.",
    ),
    "meitycall_056b139f54fba2e7a8b3": (
        "EVENT_OR_CONFERENCE",
        "G20 DIA overview is a summit overview, not an application call.",
    ),
    "meitycall_c53a5b2578e3b03d7291": (
        "PERMANENT_PARTNERSHIP_PROGRAMME",
        "MathWorks page describes an ongoing partnership benefit without a dated call instance.",
    ),
    "meitycall_11ee67b180d2f208f8ef": (
        "ORGANISATION_PROFILE",
        "Organisation profile is not a call or programme instance.",
    ),
    "meitycall_ba1e7d64714d21401ed3": (
        "PRESS_RELEASE_LISTING",
        "Press Release All is a news listing and only a discovery source.",
    ),
    "meitycall_8d44c653724d98cb049d": (
        "EVENT_OR_CONFERENCE",
        "The Summit is a conference page rather than an application call.",
    ),
    "meitycall_f76675fa4a424f58ed0b": (
        "EVENT_OR_CONFERENCE",
        "VivaTech 2022 describes participation in an event, not a call.",
    ),
}

ARCHIVE_FIELDS = (
    "historical_id",
    "source_master_id",
    "canonical_title",
    "source",
    "ministry",
    "implementing_agency",
    "official_page_url",
    "historical_status",
    "historical_year",
    "programme_type",
    "sector",
    "applicant_layer",
    "startup_relevance",
    "parent_master_id",
    "parent_scheme_name",
    "parent_resolution",
    "historical_basis",
    "evidence_excerpt",
    "date_confidence",
    "application_url",
    "apply_action_allowed",
    "qualification_status",
    "quality_flags",
    "evidence_hash",
)

REVIEW_FIELDS = (
    "source_master_id",
    "current_title",
    "proposed_title",
    "official_page_url",
    "review_reason",
    "required_action",
    "admin_review_required",
    "publication_eligible",
    "evidence_excerpt",
)

EXCLUSION_FIELDS = (
    "source_master_id",
    "current_title",
    "official_page_url",
    "exclusion_class",
    "exclusion_reason",
    "public_call_eligible",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


@dataclass(frozen=True)
class ReconstructionPaths:
    project_root: Path
    candidate_path: Path
    withdrawal_queue_path: Path
    database_path: Path
    output_dir: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "ReconstructionPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            candidate_path=(
                root
                / "data/departments/meity/v3_4_3_7_5"
                / "meity_call_candidates_v3_4_3_7_5.csv"
            ),
            withdrawal_queue_path=(
                root
                / "data/departments/meity/v3_4_3_7_7"
                / "meity_reclassification_queue_v3_4_3_7_7.csv"
            ),
            database_path=root / "database/ssip_staging_v1.db",
            output_dir=(
                root
                / "data/departments/meity/v3_4_3_7_8"
            ),
        )


class MeitYHistoricalReconstruction:
    def __init__(self, paths: ReconstructionPaths) -> None:
        self.paths = paths

    def _load_candidates(self) -> dict[str, dict[str, str]]:
        if not self.paths.candidate_path.exists():
            raise FileNotFoundError(
                f"MeitY candidate file not found: {self.paths.candidate_path}"
            )
        with self.paths.candidate_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            rows = list(csv.DictReader(handle))
        output = {
            clean(row.get("master_id")): {
                key: clean(value)
                for key, value in row.items()
            }
            for row in rows
            if clean(row.get("master_id"))
        }
        missing = sorted(set(EXPECTED_WITHDRAWN_IDS) - set(output))
        if missing:
            raise RuntimeError(
                "Candidate evidence is missing frozen IDs: "
                + ", ".join(missing)
            )
        return output

    def _verify_withdrawal_state(self) -> dict[str, int]:
        connection = sqlite3.connect(
            f"file:{self.paths.database_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            placeholders = ",".join(
                "?" for _ in EXPECTED_WITHDRAWN_IDS
            )
            rows = connection.execute(
                f"""
                SELECT master_id,publication_status,is_public
                FROM scheme_staging
                WHERE master_id IN ({placeholders})
                """,
                EXPECTED_WITHDRAWN_IDS,
            ).fetchall()
            public_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM public_schemes"
                ).fetchone()[0]
            )
        finally:
            connection.close()

        if len(rows) != len(EXPECTED_WITHDRAWN_IDS):
            raise RuntimeError(
                "The frozen MeitY withdrawal population is incomplete."
            )
        invalid = [
            str(row["master_id"])
            for row in rows
            if (
                clean(row["publication_status"]).upper() != "UNPUBLISHED"
                or int(row["is_public"] or 0) != 0
            )
        ]
        if invalid:
            raise RuntimeError(
                "Historical reconstruction requires withdrawn records. "
                "Still-public or invalid records: "
                + ", ".join(invalid)
            )
        return {
            "withdrawn_target_count": len(rows),
            "current_public_count": public_count,
        }

    def _archive_row(
        self,
        master_id: str,
        source: dict[str, str],
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        excerpt = clean(source.get("evidence_excerpt"))[:900]
        excerpt_key = excerpt.casefold()
        missing_markers = [
            marker
            for marker in rule["qualification_markers"]
            if marker not in excerpt_key
        ]
        if missing_markers:
            raise RuntimeError(
                f"Historical qualification markers missing for {master_id}: "
                + ", ".join(missing_markers)
            )

        canonical_title = clean(rule["canonical_title"])
        evidence_payload = {
            "source_master_id": master_id,
            "canonical_title": canonical_title,
            "official_page_url": source.get("official_source_url"),
            "historical_year": rule["historical_year"],
            "historical_basis": rule["historical_basis"],
            "evidence_excerpt": excerpt,
        }
        evidence_hash = hashlib.sha256(
            stable_json(evidence_payload).encode("utf-8")
        ).hexdigest()
        return {
            "historical_id": "meityhist_" + evidence_hash[:20],
            "source_master_id": master_id,
            "canonical_title": canonical_title,
            "source": SOURCE,
            "ministry": MINISTRY,
            "implementing_agency": SOURCE,
            "official_page_url": source.get("official_source_url"),
            "historical_status": "HISTORICAL_CLOSED",
            "historical_year": rule["historical_year"],
            "programme_type": rule["programme_type"],
            "sector": rule["sector"],
            "applicant_layer": rule["applicant_layer"],
            "startup_relevance": "STARTUP_DIRECT",
            "parent_master_id": "",
            "parent_scheme_name": "",
            "parent_resolution": "STANDALONE_OFFICIAL_HISTORICAL_CALL",
            "historical_basis": rule["historical_basis"],
            "evidence_excerpt": excerpt,
            "date_confidence": (
                "YEAR_EXPLICIT"
                if rule["historical_year"]
                else "YEAR_NOT_RECORDED"
            ),
            "application_url": "",
            "apply_action_allowed": "False",
            "qualification_status": "QUALIFIED_HISTORICAL_ARCHIVE",
            "quality_flags": (
                "NO_ACTIVE_APPLY_ACTION"
                + (
                    ""
                    if rule["historical_year"]
                    else ";EXACT_DATES_NOT_RECORDED"
                )
            ),
            "evidence_hash": evidence_hash,
        }

    def build(self) -> dict[str, Any]:
        candidates = self._load_candidates()
        database_state = self._verify_withdrawal_state()

        archive_rows = [
            self._archive_row(
                master_id,
                candidates[master_id],
                rule,
            )
            for master_id, rule in ARCHIVE_RULES.items()
        ]

        review_rows: list[dict[str, Any]] = []
        for master_id, rule in REVIEW_RULES.items():
            source = candidates[master_id]
            review_rows.append(
                {
                    "source_master_id": master_id,
                    "current_title": source.get("canonical_name"),
                    "proposed_title": rule["proposed_title"],
                    "official_page_url": source.get(
                        "official_source_url"
                    ),
                    "review_reason": rule["reason"],
                    "required_action": rule["required_action"],
                    "admin_review_required": "True",
                    "publication_eligible": "False",
                    "evidence_excerpt": clean(
                        source.get("evidence_excerpt")
                    )[:900],
                }
            )

        exclusion_rows: list[dict[str, Any]] = []
        for master_id, (category, reason) in EXCLUSION_RULES.items():
            source = candidates[master_id]
            exclusion_rows.append(
                {
                    "source_master_id": master_id,
                    "current_title": source.get("canonical_name"),
                    "official_page_url": source.get(
                        "official_source_url"
                    ),
                    "exclusion_class": category,
                    "exclusion_reason": reason,
                    "public_call_eligible": "False",
                }
            )

        classified_ids = {
            *ARCHIVE_RULES,
            *REVIEW_RULES,
            *EXCLUSION_RULES,
        }
        if classified_ids != set(EXPECTED_WITHDRAWN_IDS):
            missing = sorted(
                set(EXPECTED_WITHDRAWN_IDS) - classified_ids
            )
            extras = sorted(
                classified_ids - set(EXPECTED_WITHDRAWN_IDS)
            )
            raise RuntimeError(
                "Classification partition mismatch. "
                f"Missing={missing}; extras={extras}"
            )

        archive_rows.sort(
            key=lambda row: (
                row["historical_year"] or "0000",
                row["canonical_title"].casefold(),
            ),
            reverse=True,
        )
        review_rows.sort(
            key=lambda row: row["proposed_title"].casefold()
        )
        exclusion_rows.sort(
            key=lambda row: row["current_title"].casefold()
        )

        signature_payload = {
            "version": VERSION,
            "archive": archive_rows,
            "review": review_rows,
            "excluded": exclusion_rows,
            "withdrawn_target_count": database_state[
                "withdrawn_target_count"
            ],
        }
        signature = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()

        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        archive_path = (
            self.paths.output_dir
            / "meity_historical_archive_v3_4_3_7_8.csv"
        )
        review_path = (
            self.paths.output_dir
            / "meity_historical_review_queue_v3_4_3_7_8.csv"
        )
        exclusion_path = (
            self.paths.output_dir
            / "meity_historical_exclusions_v3_4_3_7_8.csv"
        )
        manifest_path = (
            self.paths.output_dir
            / "meity_historical_archive_manifest_v3_4_3_7_8.json"
        )

        write_csv(archive_path, archive_rows, ARCHIVE_FIELDS)
        write_csv(review_path, review_rows, REVIEW_FIELDS)
        write_csv(
            exclusion_path,
            exclusion_rows,
            EXCLUSION_FIELDS,
        )

        year_counts: dict[str, int] = {}
        for row in archive_rows:
            key = row["historical_year"] or "Unknown"
            year_counts[key] = year_counts.get(key, 0) + 1

        manifest = {
            "version": VERSION,
            "phase": (
                "MeitY Historical Call Reconstruction and Archive"
            ),
            "generated_at": utc_now(),
            "signature": signature,
            "withdrawn_target_count": database_state[
                "withdrawn_target_count"
            ],
            "current_public_count": database_state[
                "current_public_count"
            ],
            "qualified_historical_calls": len(archive_rows),
            "historical_review_queue_count": len(review_rows),
            "excluded_non_call_count": len(exclusion_rows),
            "startup_direct_count": sum(
                row["startup_relevance"] == "STARTUP_DIRECT"
                for row in archive_rows
            ),
            "year_evidenced_count": sum(
                bool(row["historical_year"])
                for row in archive_rows
            ),
            "year_counts": year_counts,
            "apply_actions_allowed": 0,
            "database_modified": False,
            "publication_performed": False,
            "archive_path": str(
                archive_path.relative_to(self.paths.project_root)
            ),
            "review_queue_path": str(
                review_path.relative_to(self.paths.project_root)
            ),
            "exclusions_path": str(
                exclusion_path.relative_to(self.paths.project_root)
            ),
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        manifest["manifest_path"] = str(
            manifest_path.relative_to(self.paths.project_root)
        )
        return manifest
