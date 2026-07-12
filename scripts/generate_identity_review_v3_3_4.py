from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.catalogue_populations import (
    split_catalogue_populations,
)
from ssip_dashboard.config import DashboardConfig


OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "audit"
    / "v3_3_4_semantic_cleanup"
)

NOISE_FILE = OUTPUT_DIR / "noise_candidates.csv"

REVIEW_FILE = (
    OUTPUT_DIR
    / "current_public_identity_review_v3_3_4.csv"
)


GENERIC_NAME_PATTERN = re.compile(
    r"(?:"
    r"\.html?$"
    r"|\.xml$"
    r"|^schemes?$"
    r"|^programmes?$"
    r"|^funding$"
    r"|^government\s+schemes?$"
    r"|^incubation\s+support$"
    r"|^incubator\s+framework$"
    r"|^international$"
    r"|^international\s+bridges$"
    r"|^income\s+tax\s+exemption\s+notifications$"
    r"|^search$"
    r"|^directory$"
    r"|^resources?$"
    r"|^downloads?$"
    r"|^sitemap"
    r")",
    re.IGNORECASE,
)


NOISE_URL_PATTERN = re.compile(
    r"(?:"
    r"sitemap"
    r"|market_research_reports"
    r"|incubator_page_content"
    r"|compendium_of_good_practices"
    r"|/search\.html"
    r"|/resources/government-schemes"
    r"|/funding\.html"
    r"|/incubator-framework\.html"
    r")",
    re.IGNORECASE,
)


def value(record, field: str):
    result = getattr(record, field, "")
    return result if result is not None else ""


def text(record, field: str) -> str:
    return str(value(record, field)).strip()


def has_content(record, field: str) -> bool:
    result = value(record, field)

    if isinstance(result, (list, tuple, set)):
        return any(str(item).strip() for item in result)

    return bool(str(result).strip())


def authority(record) -> str:
    return (
        text(record, "department")
        or text(record, "implementing_agency")
        or text(record, "ministry")
        or text(record, "source")
    )


def official_url(record) -> str:
    return (
        text(record, "official_page_url")
        or text(record, "final_url")
    )


def load_noise_ids() -> set[str]:
    noise_ids: set[str] = set()

    if not NOISE_FILE.exists():
        return noise_ids

    with NOISE_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        for row in csv.DictReader(handle):
            master_id = str(
                row.get("master_id") or ""
            ).strip()

            if master_id:
                noise_ids.add(master_id)

    return noise_ids


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    noise_ids = load_noise_ids()

    config = DashboardConfig.from_env()
    bundle = load_catalogue(config)

    populations = split_catalogue_populations(
        bundle.records
    )

    main_records = populations.main_scheme_records

    review_rows: list[dict[str, object]] = []

    for record in main_records:
        master_id = text(record, "master_id")
        scheme_name = text(record, "scheme_name")
        url = official_url(record)

        evidence_score = 0
        evidence_score += int(bool(url))
        evidence_score += int(bool(authority(record)))
        evidence_score += int(
            has_content(record, "objectives")
        )
        evidence_score += int(
            has_content(record, "eligibility")
        )
        evidence_score += int(
            has_content(record, "benefits")
        )

        reasons: list[str] = []

        if master_id in noise_ids:
            recommendation = "EVIDENCE_ONLY"
            reasons.append(
                "Matched the semantic noise audit."
            )

        elif GENERIC_NAME_PATTERN.search(scheme_name):
            recommendation = "NEEDS_CORE_PAGE"
            reasons.append(
                "Generic or filename-derived scheme name."
            )

        elif NOISE_URL_PATTERN.search(url):
            recommendation = "EVIDENCE_ONLY"
            reasons.append(
                "URL points to a directory, report, guide, "
                "search page or generic information page."
            )

        elif not url:
            recommendation = "NEEDS_CORE_PAGE"
            reasons.append(
                "Official scheme page is missing."
            )

        elif evidence_score >= 4:
            recommendation = "REVIEW_LIKELY_SCHEME"
            reasons.append(
                "Strong structured scheme-identity evidence."
            )

        else:
            recommendation = "NEEDS_CORE_PAGE"
            reasons.append(
                "Insufficient structured identity evidence."
            )

        review_rows.append(
            {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": text(record, "source"),
                "ministry": text(record, "ministry"),
                "department": text(record, "department"),
                "implementing_agency": text(
                    record,
                    "implementing_agency",
                ),
                "record_kind": text(
                    record,
                    "record_kind",
                ),
                "programme_status": text(
                    record,
                    "programme_status",
                ),
                "application_status": text(
                    record,
                    "application_status",
                ),
                "official_page_url": url,
                "application_url": text(
                    record,
                    "application_url",
                ),
                "objectives_present": has_content(
                    record,
                    "objectives",
                ),
                "eligibility_present": has_content(
                    record,
                    "eligibility",
                ),
                "benefits_present": has_content(
                    record,
                    "benefits",
                ),
                "identity_evidence_score": evidence_score,
                "automatic_recommendation": recommendation,
                "automatic_reason": " | ".join(reasons),

                # Complete these four columns manually:
                "manual_identity_decision": "",
                "manual_availability_decision": "",
                "verified_core_scheme_url": "",
                "reviewer_notes": "",
            }
        )

    fieldnames = [
        "master_id",
        "scheme_name",
        "source",
        "ministry",
        "department",
        "implementing_agency",
        "record_kind",
        "programme_status",
        "application_status",
        "official_page_url",
        "application_url",
        "objectives_present",
        "eligibility_present",
        "benefits_present",
        "identity_evidence_score",
        "automatic_recommendation",
        "automatic_reason",
        "manual_identity_decision",
        "manual_availability_decision",
        "verified_core_scheme_url",
        "reviewer_notes",
    ]

    with REVIEW_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(review_rows)

    recommendations = Counter(
        str(row["automatic_recommendation"])
        for row in review_rows
    )

    print("=" * 72)
    print("SSIP v3.3.4 CURRENT PUBLIC IDENTITY REVIEW")
    print("=" * 72)
    print(
        f"Loaded catalogue rows: {len(bundle.records)}"
    )
    print(
        f"Current main candidates: {len(main_records)}"
    )
    print(
        f"Noise master IDs loaded: {len(noise_ids)}"
    )
    print()

    for label, count in sorted(
        recommendations.items()
    ):
        print(f"{label}: {count}")

    print()
    print("Review file created:")
    print(REVIEW_FILE)
    print()
    print("Database writes performed: 0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
