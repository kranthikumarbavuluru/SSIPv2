from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

VERSION = "3.4.3.2"
PHASE = "MeitY Candidate Normalization, Identity Deduplication and Classification Triage"

GENERIC_TITLES = {
    "",
    "meitystartuphub",
    "meity startup hub",
    "ministry of electronics and information technology",
    "official sitemap",
    "official json endpoint",
}

KNOWN_NAMES = {
    "/schemes/samridh": "SAMRIDH",
    "/schemes/tide": "TIDE 2.0",
    "/schemes/sasact": "SASACT",
    "/schemes/genesis": "GENESIS",
    "/programs/incubator": "MeitY Startup Hub Incubator Network",
    "/program/coe": "MeitY Centres of Excellence",
    "/program/mshcorporate/sbi": "SBI Corporate Partnership",
    "/program/mshcorporate/tally": "Tally Corporate Partnership",
    "/program/mshcorporate/razorpaypartnership": "Razorpay Corporate Partnership",
    "/program/mshcorporate/mathworks": "MathWorks Corporate Partnership",
    "/program/mshcorporate/micron": "Micron Corporate Partnership",
    "/program/mshcorporate/samsung": "Samsung Corporate Partnership",
    "/program/mshcorporate/googleappscale": "Google Appscale Academy Partnership",
    "/program/mshcorporate/bhumi": "Bhumi Corporate Partnership",
    "/program/mshcorporate/drishti": "Drishti Corporate Partnership",
    "/program/mshcorporate/ihmcl": "IHMCL Corporate Partnership",
    "/program/mshcorporate/xr-startup-program": "XR Startup Program Partnership",
    "/program/mshinternational/iftech": "IFTech International Programme",
    "/program/mshinternational/brussels": "Brussels International Delegation",
    "/program/mshinternational/vivatech2023": "VivaTech 2023 Delegation",
    "/program/mshinternational/vivatech": "VivaTech International Programme",
}

SCHEME_PATHS = {
    "/schemes/samridh",
    "/schemes/tide",
    "/schemes/sasact",
    "/schemes/genesis",
}

CALL_FALSE_POSITIVE_PATHS = {
    "/",
    "/about/organisationprofile",
    "/media/press-release-all",
    "/event-partner",
    "/g20dia/g20diaoverview",
    "/g20dia/exhibition",
    "/g20dia/the-summit",
}

EXPECTED_EXISTING_IDS = {
    "147173e17ea741687247": "SAMRIDH",
    "6af79cf6c8a213dddce8": "TIDE 2.0",
}


def root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def path_of(url: str) -> str:
    return urlparse(url).path.rstrip("/").casefold() or "/"


def slug_name(path: str) -> str:
    slug = unquote(path.rstrip("/").rsplit("/", 1)[-1])
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", slug)
    return " ".join(word.upper() if len(word) <= 4 else word.title() for word in slug.split())


def canonical_name(row: dict[str, str]) -> str:
    url_path = path_of(row.get("canonical_url", ""))
    if url_path in KNOWN_NAMES:
        return KNOWN_NAMES[url_path]

    for key in ("heading", "title"):
        value = text(row.get(key, ""))
        if value.casefold() not in GENERIC_TITLES:
            return value

    return slug_name(url_path)


def normalize_identity_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    ignored = {"scheme", "programme", "program", "partnership", "the", "of", "for", "and"}
    return " ".join(token for token in normalized.split() if token not in ignored)


def classify_master(row: dict[str, str]) -> tuple[str, str, str]:
    url = row.get("canonical_url", "")
    path = path_of(url)

    if path in SCHEME_PATHS:
        return (
            "VERIFIED_PERMANENT_SCHEME",
            "OFFICIAL_MSH_SCHEME_DETAIL_PATH",
            "PROCEED_TO_GOVERNED_EXTRACTION",
        )

    if "/program/mshcorporate/" in path:
        return (
            "CORPORATE_PARTNERSHIP",
            "MSH_CORPORATE_PARTNERSHIP_PATH",
            "EXCLUDE_FROM_SCHEME_MASTER_PIPELINE",
        )

    if "/program/mshinternational/" in path:
        return (
            "INTERNATIONAL_EVENT_OR_DELEGATION",
            "MSH_INTERNATIONAL_PROGRAMME_PATH",
            "SEPARATE_EVENT_OR_ECOSYSTEM_PIPELINE",
        )

    if path in {"/programs/incubator", "/program/coe"}:
        return (
            "INCUBATOR_OR_ECOSYSTEM_RESOURCE",
            "MSH_INCUBATOR_OR_COE_RESOURCE_PATH",
            "SEPARATE_ECOSYSTEM_RESOURCE_PIPELINE",
        )

    return (
        "MANUAL_REVIEW",
        "UNRESOLVED_PROGRAMME_IDENTITY",
        "REVIEW_BEFORE_MASTER_CREATION",
    )


def classify_call(row: dict[str, str]) -> tuple[str, str, str]:
    path = path_of(row.get("canonical_url", ""))

    if path in CALL_FALSE_POSITIVE_PATHS:
        return (
            "NON_CATALOGUE",
            "GENERIC_HOME_OR_EVENT_INFORMATION_PAGE_FALSE_POSITIVE",
            "EXCLUDE_FROM_CALL_PIPELINE",
        )

    if any(token in path for token in ("/challenge/", "/challenges/", "/cohort/", "/call/", "/eoi/", "/rfp/")):
        return (
            "CALL_OR_COHORT_INSTANCE",
            "EXPLICIT_CALL_OR_CHALLENGE_PATH",
            "PROCEED_TO_CALL_STATUS_VALIDATION",
        )

    return (
        "MANUAL_REVIEW",
        "CALL_SIGNAL_WITHOUT_EXPLICIT_CALL_DETAIL_PATH",
        "REVIEW_PARENT_AND_STATUS",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        test_rows = [
            {"canonical_url": "https://msh.meity.gov.in/schemes/samridh"},
            {"canonical_url": "https://msh.meity.gov.in/program/mshcorporate/SBI"},
            {"canonical_url": "https://msh.meity.gov.in/program/mshinternational/vivatech"},
        ]
        expected = [
            "VERIFIED_PERMANENT_SCHEME",
            "CORPORATE_PARTNERSHIP",
            "INTERNATIONAL_EVENT_OR_DELEGATION",
        ]
        actual = [classify_master(row)[0] for row in test_rows]
        if actual != expected:
            raise AssertionError(f"expected={expected} actual={actual}")
        if canonical_name(test_rows[0]) != "SAMRIDH":
            raise AssertionError("Canonical name derivation failed.")
        print("MeitY v3.4.3.2 triage self-test: PASS")
        return 0

    root = root_dir()
    source_dir = root / "data" / "departments" / "meity" / "v3_4_3_1"
    out_dir = root / "data" / "departments" / "meity" / "v3_4_3_2"
    audit_dir = root / "data" / "audit"

    paths = {
        "schemes": source_dir / "meity_scheme_master_candidates_v3_4_3_1.csv",
        "programmes": source_dir / "meity_programme_master_candidates_v3_4_3_1.csv",
        "calls": source_dir / "meity_call_instances_v3_4_3_1.csv",
        "reviews": source_dir / "meity_manual_review_queue_v3_4_3_1.csv",
        "pages": source_dir / "meity_discovered_pages_v3_4_3_1.csv",
        "summary": source_dir / "meity_discovery_summary_v3_4_3_1.json",
    }

    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise RuntimeError("Missing v3.4.3.1 inputs:\n" + "\n".join(missing))

    source_hashes = {key: sha256(path) for key, path in paths.items()}

    _, scheme_rows = read_csv(paths["schemes"])
    _, programme_rows = read_csv(paths["programmes"])
    _, call_rows = read_csv(paths["calls"])
    _, review_rows = read_csv(paths["reviews"])
    _, page_rows = read_csv(paths["pages"])

    master_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    triage_review_rows: list[dict[str, object]] = []

    for row in scheme_rows + programme_rows:
        name = canonical_name(row)
        classification, reason, action = classify_master(row)
        existing_id = text(row.get("existing_master_id", ""))
        candidate_id = text(row.get("candidate_id", ""))

        identity_decision = (
            "EXISTING_MASTER_ID_RETAINED"
            if existing_id
            else (
                "NEW_PERMANENT_IDENTITY_CANDIDATE"
                if classification == "VERIFIED_PERMANENT_SCHEME"
                else "NO_SCHEME_MASTER_ID_TO_CREATE"
            )
        )

        normalized = {
            "candidate_id": candidate_id,
            "existing_master_id": existing_id,
            "canonical_name": name,
            "normalized_identity_name": normalize_identity_name(name),
            "canonical_url": row.get("canonical_url", ""),
            "source_classification": row.get("classification", ""),
            "triage_classification": classification,
            "identity_decision": identity_decision,
            "triage_reason": reason,
            "recommended_action": action,
            "confidence": row.get("confidence", ""),
            "status_hint": row.get("status_hint", ""),
            "parent_hint": row.get("parent_hint", ""),
            "publication_status": "NOT_PUBLISHED",
        }
        master_rows.append(normalized)

        if classification == "VERIFIED_PERMANENT_SCHEME":
            identity_rows.append(
                {
                    "candidate_id": candidate_id,
                    "master_id": existing_id,
                    "canonical_name": name,
                    "canonical_url": row.get("canonical_url", ""),
                    "identity_decision": identity_decision,
                    "record_kind": "SCHEME",
                    "existing_identity": "true" if existing_id else "false",
                    "requires_identity_validation": "false" if existing_id else "true",
                    "publication_status": "NOT_PUBLISHED",
                }
            )

        if classification == "MANUAL_REVIEW":
            triage_review_rows.append(
                {
                    "review_id": "meity_triage_" + hashlib.sha256(
                        text(row.get("canonical_url", "")).encode("utf-8")
                    ).hexdigest()[:16],
                    "candidate_id": candidate_id,
                    "canonical_name": name,
                    "canonical_url": row.get("canonical_url", ""),
                    "review_type": "MASTER_IDENTITY_CLASSIFICATION",
                    "review_reason": reason,
                    "review_status": "OPEN",
                    "publication_status": "NOT_PUBLISHED",
                }
            )

    call_triage_rows: list[dict[str, object]] = []
    for row in call_rows:
        classification, reason, action = classify_call(row)
        name = canonical_name(row)
        call_triage_rows.append(
            {
                "candidate_id": row.get("candidate_id", ""),
                "canonical_name": name,
                "canonical_url": row.get("canonical_url", ""),
                "parent_hint": row.get("parent_hint", ""),
                "status_hint": row.get("status_hint", ""),
                "source_classification": row.get("classification", ""),
                "triage_classification": classification,
                "triage_reason": reason,
                "recommended_action": action,
                "confidence": row.get("confidence", ""),
                "publication_status": "NOT_PUBLISHED",
            }
        )
        if classification == "MANUAL_REVIEW":
            triage_review_rows.append(
                {
                    "review_id": "meity_triage_" + hashlib.sha256(
                        text(row.get("canonical_url", "")).encode("utf-8")
                    ).hexdigest()[:16],
                    "candidate_id": row.get("candidate_id", ""),
                    "canonical_name": name,
                    "canonical_url": row.get("canonical_url", ""),
                    "review_type": "CALL_INSTANCE_CLASSIFICATION",
                    "review_reason": reason,
                    "review_status": "OPEN",
                    "publication_status": "NOT_PUBLISHED",
                }
            )

    page_by_url = {text(row.get("canonical_url", "")): row for row in page_rows}
    fetch_error_rows: list[dict[str, object]] = []
    for row in review_rows:
        if "FETCH_ERROR" not in text(row.get("review_reasons", "")):
            continue
        url = text(row.get("canonical_url", ""))
        source = page_by_url.get(url, {})
        fetch_error_rows.append(
            {
                "review_id": row.get("review_id", ""),
                "candidate_id": row.get("candidate_id", ""),
                "canonical_url": url,
                "http_status": source.get("status_code", ""),
                "error": source.get("error", ""),
                "error_classification": (
                    "BROKEN_OR_PLACEHOLDER_EVIDENCE_URL"
                    if "/selectedfile_path" in url or "/whatsnew-docs/" in url
                    else "OFFICIAL_URL_FETCH_ERROR"
                ),
                "master_identity_impact": "NONE",
                "recommended_action": "RETRY_OR_RECONSTRUCT_EVIDENCE_URL",
                "publication_status": "NOT_PUBLISHED",
            }
        )

    duplicate_groups: dict[str, list[dict[str, object]]] = {}
    for row in identity_rows:
        key = text(row["normalized_identity_name"])
        duplicate_groups.setdefault(key, []).append(row)
    duplicate_identity_groups = {
        key: rows for key, rows in duplicate_groups.items() if len(rows) > 1
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    master_fields = [
        "candidate_id", "existing_master_id", "canonical_name",
        "normalized_identity_name", "canonical_url", "source_classification",
        "triage_classification", "identity_decision", "triage_reason",
        "recommended_action", "confidence", "status_hint", "parent_hint",
        "publication_status",
    ]
    write_csv(
        out_dir / "meity_normalized_master_triage_v3_4_3_2.csv",
        master_rows,
        master_fields,
    )

    identity_fields = [
        "candidate_id", "master_id", "canonical_name", "canonical_url",
        "identity_decision", "record_kind", "existing_identity",
        "requires_identity_validation", "publication_status",
    ]
    write_csv(
        out_dir / "meity_candidate_identity_register_v3_4_3_2.csv",
        identity_rows,
        identity_fields,
    )

    call_fields = [
        "candidate_id", "canonical_name", "canonical_url", "parent_hint",
        "status_hint", "source_classification", "triage_classification",
        "triage_reason", "recommended_action", "confidence",
        "publication_status",
    ]
    write_csv(
        out_dir / "meity_call_triage_v3_4_3_2.csv",
        call_triage_rows,
        call_fields,
    )

    fetch_fields = [
        "review_id", "candidate_id", "canonical_url", "http_status", "error",
        "error_classification", "master_identity_impact",
        "recommended_action", "publication_status",
    ]
    write_csv(
        out_dir / "meity_fetch_error_queue_v3_4_3_2.csv",
        fetch_error_rows,
        fetch_fields,
    )

    review_fields = [
        "review_id", "candidate_id", "canonical_name", "canonical_url",
        "review_type", "review_reason", "review_status", "publication_status",
    ]
    write_csv(
        out_dir / "meity_triage_review_queue_v3_4_3_2.csv",
        triage_review_rows,
        review_fields,
    )

    master_counts = Counter(text(row["triage_classification"]) for row in master_rows)
    call_counts = Counter(text(row["triage_classification"]) for row in call_triage_rows)

    existing_identity_map = {
        text(row["master_id"]): text(row["canonical_name"])
        for row in identity_rows
        if text(row["master_id"])
    }

    checks = [
        {
            "name": "input_master_candidates_21",
            "passed": len(master_rows) == 21,
            "details": f"actual={len(master_rows)}",
        },
        {
            "name": "verified_permanent_schemes_4",
            "passed": master_counts["VERIFIED_PERMANENT_SCHEME"] == 4,
            "details": f"actual={master_counts['VERIFIED_PERMANENT_SCHEME']}",
        },
        {
            "name": "existing_ids_preserved",
            "passed": existing_identity_map == EXPECTED_EXISTING_IDS,
            "details": json.dumps(existing_identity_map, sort_keys=True),
        },
        {
            "name": "new_scheme_candidates_require_identity_validation",
            "passed": all(
                row["requires_identity_validation"] == "true"
                for row in identity_rows
                if not text(row["master_id"])
            ),
            "details": "SASACT and GENESIS must not receive permanent IDs automatically.",
        },
        {
            "name": "generic_titles_replaced",
            "passed": all(
                text(row["canonical_name"]).casefold() not in GENERIC_TITLES
                for row in master_rows
            ),
            "details": "No normalized candidate may retain MeityStartupHub as its name.",
        },
        {
            "name": "no_duplicate_verified_identity_names",
            "passed": len(duplicate_identity_groups) == 0,
            "details": f"duplicate_groups={len(duplicate_identity_groups)}",
        },
        {
            "name": "fetch_errors_quarantined",
            "passed": len(fetch_error_rows) == 23,
            "details": f"actual={len(fetch_error_rows)}",
        },
        {
            "name": "all_outputs_not_published",
            "passed": all(
                row.get("publication_status") == "NOT_PUBLISHED"
                for collection in (
                    master_rows, identity_rows, call_triage_rows,
                    fetch_error_rows, triage_review_rows,
                )
                for row in collection
            ),
            "details": "All triage outputs must remain preview-only.",
        },
    ]

    source_unchanged = {
        key: sha256(path) == source_hashes[key]
        for key, path in paths.items()
    }
    checks.append(
        {
            "name": "v3_4_3_1_inputs_unchanged",
            "passed": all(source_unchanged.values()),
            "details": json.dumps(source_unchanged, sort_keys=True),
        }
    )

    failed = [check for check in checks if not check["passed"]]
    status = "PASS" if not failed else "FAIL"

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "validation_status": status,
        "completed_at": now_iso(),
        "counts": {
            "input_scheme_candidates": len(scheme_rows),
            "input_programme_candidates": len(programme_rows),
            "normalized_master_candidates": len(master_rows),
            "verified_permanent_schemes": master_counts["VERIFIED_PERMANENT_SCHEME"],
            "corporate_partnerships": master_counts["CORPORATE_PARTNERSHIP"],
            "international_events_or_delegations": master_counts[
                "INTERNATIONAL_EVENT_OR_DELEGATION"
            ],
            "incubator_or_ecosystem_resources": master_counts[
                "INCUBATOR_OR_ECOSYSTEM_RESOURCE"
            ],
            "master_manual_review": master_counts["MANUAL_REVIEW"],
            "input_call_candidates": len(call_rows),
            "verified_call_or_cohort_instances": call_counts[
                "CALL_OR_COHORT_INSTANCE"
            ],
            "call_false_positives_excluded": call_counts["NON_CATALOGUE"],
            "call_manual_review": call_counts["MANUAL_REVIEW"],
            "fetch_errors_quarantined": len(fetch_error_rows),
            "triage_review_rows": len(triage_review_rows),
            "existing_identity_matches": len(existing_identity_map),
            "new_permanent_identity_candidates": sum(
                row["identity_decision"] == "NEW_PERMANENT_IDENTITY_CANDIDATE"
                for row in identity_rows
            ),
        },
        "master_classification_counts": dict(sorted(master_counts.items())),
        "call_classification_counts": dict(sorted(call_counts.items())),
        "checks": checks,
        "failed_checks": [check["name"] for check in failed],
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    }
    write_json(
        out_dir / "meity_triage_summary_v3_4_3_2.json",
        summary,
    )
    write_json(
        out_dir / "meity_triage_validation_v3_4_3_2.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "validation_status": status,
            "checks": checks,
            "failed_checks": [check["name"] for check in failed],
            "source_hashes": source_hashes,
            "source_unchanged": source_unchanged,
        },
    )

    generated = sorted(path for path in out_dir.iterdir() if path.is_file())
    write_json(
        out_dir / "meity_triage_manifest_v3_4_3_2.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "generated_at": now_iso(),
            "validation_status": status,
            "outputs": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in generated
            ],
            "publication_status": "NOT_PUBLISHED",
        },
    )

    write_json(
        audit_dir / "meity_v3_4_3_2_triage_postchange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "source_unchanged": source_unchanged,
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
    )

    print()
    print("SSIP MeitY v3.4.3.2 candidate triage")
    print("--------------------------------------------")
    print(f"Validation status:                  {status}")
    print(f"Normalized master candidates:       {len(master_rows)}")
    print(
        "Verified permanent schemes:        "
        f"{master_counts['VERIFIED_PERMANENT_SCHEME']}"
    )
    print(
        "Corporate partnerships excluded:   "
        f"{master_counts['CORPORATE_PARTNERSHIP']}"
    )
    print(
        "International/event records:       "
        f"{master_counts['INTERNATIONAL_EVENT_OR_DELEGATION']}"
    )
    print(
        "Ecosystem/incubator resources:      "
        f"{master_counts['INCUBATOR_OR_ECOSYSTEM_RESOURCE']}"
    )
    print(f"Call candidates triaged:            {len(call_triage_rows)}")
    print(f"Fetch errors quarantined:           {len(fetch_error_rows)}")
    print(f"Triage review rows:                 {len(triage_review_rows)}")
    print(f"Existing scheme IDs retained:       {len(existing_identity_map)}")
    print(
        "New scheme identity candidates:     "
        f"{sum(row['identity_decision'] == 'NEW_PERMANENT_IDENTITY_CANDIDATE' for row in identity_rows)}"
    )
    print("Publication performed:              No")
    print()
    print("Output directory:")
    print(out_dir)

    if failed:
        print()
        print("Failed checks:")
        for check in failed:
            print(f"- {check['name']}: {check['details']}")

    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
