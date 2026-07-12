import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path


VERSION = "2.8.1"

DB_PATH = Path(r"database\ssip_staging_v1.db")
OUTPUT_DIR = Path(
    r"data\audit\v2_8_1_catalogue_normalization"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_json_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    text = str(value).strip()

    if not text:
        return []

    try:
        parsed = json.loads(text)

        if isinstance(parsed, list):
            return parsed

        return [parsed]
    except (json.JSONDecodeError, TypeError):
        return [text]


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = []
    seen = set()

    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def infer_record_kind(record):
    existing = str(
        record.get("record_kind") or ""
    ).strip().upper()

    if existing:
        return existing, "EXISTING_VALUE"

    programme_status = str(
        record.get("programme_status") or ""
    ).upper()

    scheme_name = str(
        record.get("scheme_name") or ""
    ).upper()

    if "UMBRELLA_PROGRAMME" in programme_status:
        return (
            "UMBRELLA_PROGRAMME",
            "INFERRED_FROM_PROGRAMME_STATUS",
        )

    if "CALL_" in programme_status:
        return (
            "APPLICATION_CALL",
            "INFERRED_FROM_PROGRAMME_STATUS",
        )

    if "SCHEME_INFORMATION" in programme_status:
        return (
            "SCHEME_OR_PROGRAMME",
            "INFERRED_FROM_PROGRAMME_STATUS",
        )

    call_terms = (
        "CHALLENGE",
        "APPLICATIONS INVITED",
        "REQUEST FOR PROPOSAL",
        "CALL FOR",
    )

    if any(term in scheme_name for term in call_terms):
        return (
            "APPLICATION_CALL",
            "INFERRED_FROM_SCHEME_NAME",
        )

    if "SCHEME" in scheme_name:
        return (
            "SCHEME_OR_PROGRAMME",
            "INFERRED_FROM_SCHEME_NAME",
        )

    return "UNCLASSIFIED", "REQUIRES_MANUAL_REVIEW"


def classify_staged(record, normalized_kind):
    application_status = str(
        record.get("application_status") or ""
    ).upper()

    programme_status = str(
        record.get("programme_status") or ""
    ).upper()

    if normalized_kind == "UMBRELLA_PROGRAMME":
        return {
            "catalogue_inclusion": "INCLUDED",
            "catalogue_section": "UMBRELLA_PROGRAMMES",
            "normalization_disposition": (
                "KEEP_AS_UMBRELLA_PROGRAMME"
            ),
            "publication_recommendation": (
                "ELIGIBLE_AFTER_CONTENT_REVIEW"
            ),
        }

    if normalized_kind == "APPLICATION_CALL":
        if application_status == "OPEN":
            return {
                "catalogue_inclusion": "INCLUDED",
                "catalogue_section": (
                    "CURRENT_OPPORTUNITIES"
                ),
                "normalization_disposition": (
                    "KEEP_AS_CURRENT_OPPORTUNITY"
                ),
                "publication_recommendation": (
                    "VERIFY_URL_AND_DEADLINE_BEFORE_PUBLICATION"
                ),
            }

        if application_status == "CLOSED":
            return {
                "catalogue_inclusion": "ARCHIVED",
                "catalogue_section": (
                    "CLOSED_OPPORTUNITIES"
                ),
                "normalization_disposition": (
                    "KEEP_AS_CLOSED_OPPORTUNITY"
                ),
                "publication_recommendation": (
                    "PUBLIC_ARCHIVE_AFTER_CONTENT_REVIEW"
                ),
            }

        if application_status == "DEADLINE_UNVERIFIED":
            return {
                "catalogue_inclusion": (
                    "PENDING_REVALIDATION"
                ),
                "catalogue_section": (
                    "OPPORTUNITIES_REQUIRING_VERIFICATION"
                ),
                "normalization_disposition": (
                    "VERIFY_CURRENT_DEADLINE"
                ),
                "publication_recommendation": (
                    "DO_NOT_MARK_OPEN_UNTIL_VERIFIED"
                ),
            }

        return {
            "catalogue_inclusion": "INCLUDED",
            "catalogue_section": "OPPORTUNITIES",
            "normalization_disposition": (
                "KEEP_AS_APPLICATION_CALL"
            ),
            "publication_recommendation": (
                "REVIEW_APPLICATION_STATUS"
            ),
        }

    if normalized_kind == "SCHEME_OR_PROGRAMME":
        if application_status == "CLOSED":
            return {
                "catalogue_inclusion": "INCLUDED",
                "catalogue_section": (
                    "SCHEMES_AND_PROGRAMMES"
                ),
                "normalization_disposition": (
                    "KEEP_SCHEME_WITH_CLOSED_STATUS"
                ),
                "publication_recommendation": (
                    "PUBLIC_CATALOGUE_CLOSED"
                ),
            }

        return {
            "catalogue_inclusion": "INCLUDED",
            "catalogue_section": (
                "SCHEMES_AND_PROGRAMMES"
            ),
            "normalization_disposition": (
                "KEEP_AS_SCHEME_OR_PROGRAMME"
            ),
            "publication_recommendation": (
                "ELIGIBLE_AFTER_CONTENT_REVIEW"
            ),
        }

    if "SCHEME_INFORMATION" in programme_status:
        return {
            "catalogue_inclusion": (
                "PENDING_REVALIDATION"
            ),
            "catalogue_section": (
                "SCHEMES_AND_PROGRAMMES"
            ),
            "normalization_disposition": (
                "NORMALIZE_MISSING_RECORD_KIND"
            ),
            "publication_recommendation": (
                "REVIEW_RECORD_KIND_BEFORE_PUBLICATION"
            ),
        }

    return {
        "catalogue_inclusion": "PENDING_REVALIDATION",
        "catalogue_section": "UNCLASSIFIED",
        "normalization_disposition": (
            "MANUAL_CLASSIFICATION_REQUIRED"
        ),
        "publication_recommendation": (
            "DO_NOT_AUTO_PUBLISH"
        ),
    }


def classify_rejected(record, normalized_kind):
    reasons = [
        str(item).strip()
        for item in parse_json_list(
            record.get("decision_reasons_json")
        )
    ]

    reason_text = " | ".join(reasons).lower()
    scheme_name = str(
        record.get("scheme_name") or ""
    ).lower()

    if "fund of funds" in scheme_name:
        return {
            "catalogue_inclusion": (
                "PENDING_REVALIDATION"
            ),
            "catalogue_section": (
                "INDIRECT_FINANCIAL_SUPPORT"
            ),
            "normalization_disposition": (
                "REVALIDATE_AS_INDIRECT_SUPPORT"
            ),
            "publication_recommendation": (
                "VERIFY_OFFICIAL_GUIDELINES_AND_SUPPORT_MODEL"
            ),
        }

    if "old scheme" in reason_text:
        section = "HISTORICAL_PROGRAMMES"

        if normalized_kind == "APPLICATION_CALL":
            section = "CLOSED_OPPORTUNITIES"

        return {
            "catalogue_inclusion": "ARCHIVED",
            "catalogue_section": section,
            "normalization_disposition": (
                "REVALIDATE_AS_HISTORICAL_RECORD"
            ),
            "publication_recommendation": (
                "PUBLIC_ARCHIVE_AFTER_EVIDENCE_REPAIR"
            ),
        }

    if "closed" in reason_text:
        section = "SCHEMES_AND_PROGRAMMES"

        if normalized_kind == "APPLICATION_CALL":
            section = "CLOSED_OPPORTUNITIES"

        return {
            "catalogue_inclusion": "INCLUDED",
            "catalogue_section": section,
            "normalization_disposition": (
                "REVALIDATE_AS_CLOSED_CATALOGUE_RECORD"
            ),
            "publication_recommendation": (
                "PUBLIC_CATALOGUE_CLOSED_AFTER_REVALIDATION"
            ),
        }

    return {
        "catalogue_inclusion": "PENDING_REVALIDATION",
        "catalogue_section": "MANUAL_REVIEW",
        "normalization_disposition": (
            "MANUAL_REVALIDATION_REQUIRED"
        ),
        "publication_recommendation": (
            "DO_NOT_AUTO_PUBLISH"
        ),
    }


if not DB_PATH.exists():
    raise SystemExit(
        f"Database not found: {DB_PATH}"
    )

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cursor = con.cursor()


def read_table(table_name):
    exists = cursor.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    if not exists:
        return []

    return [
        dict(row)
        for row in cursor.execute(
            f'SELECT * FROM "{table_name}"'
        ).fetchall()
    ]


staging_rows = read_table("scheme_staging")
review_rows = read_table("admin_review_queue")

staging_by_id = {
    str(row["master_id"]): row
    for row in staging_rows
    if row.get("master_id")
}

review_by_id = {
    str(row["master_id"]): row
    for row in review_rows
    if row.get("master_id")
}

all_master_ids = sorted(
    set(staging_by_id) | set(review_by_id)
)

normalization_rows = []

for master_id in all_master_ids:
    staged = staging_by_id.get(master_id)
    reviewed = review_by_id.get(master_id)

    combined = {}

    if reviewed:
        combined.update(reviewed)

    if staged:
        combined.update(staged)

    normalized_kind, kind_basis = infer_record_kind(
        combined
    )

    if staged:
        classification = classify_staged(
            combined,
            normalized_kind,
        )
        current_location = "SCHEME_STAGING"
    else:
        classification = classify_rejected(
            combined,
            normalized_kind,
        )
        current_location = "REVIEW_ONLY"

    warnings = parse_json_list(
        reviewed.get("warnings_json")
        if reviewed
        else None
    )

    reasons = parse_json_list(
        reviewed.get("decision_reasons_json")
        if reviewed
        else None
    )

    recommended_actions = parse_json_list(
        reviewed.get("recommended_actions_json")
        if reviewed
        else None
    )

    issues = []

    if staged and staged.get("is_public") is None:
        issues.append("IS_PUBLIC_NULL")

    if staged and not reviewed:
        issues.append(
            "STAGED_WITHOUT_CURRENT_REVIEW_LINEAGE"
        )

    if not combined.get("record_kind"):
        issues.append("RECORD_KIND_MISSING")

    if not combined.get("official_page_url"):
        issues.append("OFFICIAL_PAGE_URL_MISSING")

    if not combined.get("application_url"):
        issues.append("APPLICATION_URL_MISSING")

    issues.extend(str(item) for item in warnings)

    normalization_rows.append(
        {
            "master_id": master_id,
            "source": combined.get("source"),
            "scheme_name": combined.get("scheme_name"),
            "current_location": current_location,
            "current_review_status": (
                reviewed.get("review_status")
                if reviewed
                else None
            ),
            "current_decision": (
                reviewed.get("decision")
                if reviewed
                else None
            ),
            "current_publication_status": (
                staged.get("publication_status")
                if staged
                else None
            ),
            "current_is_public": (
                staged.get("is_public")
                if staged
                else None
            ),
            "current_record_kind": (
                combined.get("record_kind")
            ),
            "normalized_record_kind": normalized_kind,
            "record_kind_basis": kind_basis,
            "programme_status": combined.get(
                "programme_status"
            ),
            "application_status": combined.get(
                "application_status"
            ),
            "catalogue_inclusion": classification[
                "catalogue_inclusion"
            ],
            "catalogue_section": classification[
                "catalogue_section"
            ],
            "normalization_disposition": classification[
                "normalization_disposition"
            ],
            "publication_recommendation": classification[
                "publication_recommendation"
            ],
            "official_page_url": combined.get(
                "official_page_url"
            ),
            "application_url": combined.get(
                "application_url"
            ),
            "decision_reasons": json.dumps(
                reasons,
                ensure_ascii=False,
            ),
            "warnings": json.dumps(
                warnings,
                ensure_ascii=False,
            ),
            "recommended_actions": json.dumps(
                recommended_actions,
                ensure_ascii=False,
            ),
            "normalization_issues": json.dumps(
                sorted(set(issues)),
                ensure_ascii=False,
            ),
        }
    )

write_csv(
    OUTPUT_DIR
    / "catalogue_normalization_plan_v2_8_1.csv",
    normalization_rows,
)

legacy_staged = [
    row
    for row in normalization_rows
    if (
        row["current_location"] == "SCHEME_STAGING"
        and not row["current_review_status"]
    )
]

write_csv(
    OUTPUT_DIR
    / "legacy_staged_records_v2_8_1.csv",
    legacy_staged,
)

revalidation_backlog = [
    row
    for row in normalization_rows
    if row["catalogue_inclusion"]
    in {
        "PENDING_REVALIDATION",
        "ARCHIVED",
    }
]

write_csv(
    OUTPUT_DIR
    / "catalogue_revalidation_backlog_v2_8_1.csv",
    revalidation_backlog,
)

catalogue_candidates = [
    row
    for row in normalization_rows
    if row["catalogue_inclusion"] == "INCLUDED"
]

write_csv(
    OUTPUT_DIR
    / "catalogue_inclusion_candidates_v2_8_1.csv",
    catalogue_candidates,
)

summary = {
    "normalization_version": VERSION,
    "database": str(DB_PATH),
    "total_unique_records": len(normalization_rows),
    "by_current_location": dict(
        sorted(
            Counter(
                row["current_location"]
                for row in normalization_rows
            ).items()
        )
    ),
    "by_catalogue_inclusion": dict(
        sorted(
            Counter(
                row["catalogue_inclusion"]
                for row in normalization_rows
            ).items()
        )
    ),
    "by_catalogue_section": dict(
        sorted(
            Counter(
                row["catalogue_section"]
                for row in normalization_rows
            ).items()
        )
    ),
    "by_normalized_record_kind": dict(
        sorted(
            Counter(
                row["normalized_record_kind"]
                for row in normalization_rows
            ).items()
        )
    ),
    "by_normalization_disposition": dict(
        sorted(
            Counter(
                row["normalization_disposition"]
                for row in normalization_rows
            ).items()
        )
    ),
    "legacy_staged_record_count": len(
        legacy_staged
    ),
    "revalidation_backlog_count": len(
        revalidation_backlog
    ),
    "catalogue_inclusion_candidate_count": len(
        catalogue_candidates
    ),
    "database_modified": False,
}

with (
    OUTPUT_DIR
    / "catalogue_normalization_summary_v2_8_1.json"
).open("w", encoding="utf-8") as file:
    json.dump(
        summary,
        file,
        indent=2,
        ensure_ascii=False,
    )

print("=" * 76)
print("SSIP v2.8.1 CATALOGUE NORMALIZATION PLAN")
print("=" * 76)
print(json.dumps(summary, indent=2, ensure_ascii=False))

print()
print("RECORD PLAN")
print("-" * 76)

for row in normalization_rows:
    print(
        f'{row["scheme_name"]} | '
        f'{row["normalized_record_kind"]} | '
        f'{row["catalogue_inclusion"]} | '
        f'{row["catalogue_section"]} | '
        f'{row["normalization_disposition"]}'
    )

print()
print("FILES CREATED")

for path in sorted(OUTPUT_DIR.iterdir()):
    print(path)

con.close()
