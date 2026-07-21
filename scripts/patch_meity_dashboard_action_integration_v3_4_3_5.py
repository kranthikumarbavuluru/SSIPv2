from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "3.4.3.5"

CATALOGUE_BASELINE_SHA256 = (
    "fc6917a3567586986bf864e8f9023310c9850828cf92c135a4cc4c6565b4f15a"
)
APP_BASELINE_SHA256 = (
    "1db5b66ffc049cc521615e9595042e02a277ad6f14d77ec84f5c8c9e880e9bb0"
)
SOURCE_CATALOGUE_SHA256 = (
    "ef43bd7e27df2ead5fe88ab8bf2751a80eac6c4e13e8894173a6625b57650a8c"
)
ACTIONS_SHA256 = (
    "28f6174ebf4313394f205682dc1735451f14f060f346264c84d857d6cee0836e"
)

EXPECTED_SCHEMES = {"GENESIS", "SAMRIDH", "SASACT", "TIDE 2.0"}

CATALOGUE_MARKERS = (
    "verified_public_actions: list[dict[str, Any]]",
    "def parse_verified_public_actions(",
    "verified_public_actions=parse_verified_public_actions(",
)

APP_MARKERS = (
    "def verified_scheme_details_action(",
    "governed_details = verified_scheme_details_action(record)",
    ">Scheme Details",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_hashes(root: Path, patterns: tuple[str, ...]) -> dict[str, str]:
    output: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                output[path.relative_to(root).as_posix()] = sha256_file(path)
    return output


def read_source(path: Path) -> tuple[str, str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if text.count("\r\n") >= max(1, text.count("\n") // 2) else "\n"
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, newline, has_bom


def write_source(path: Path, text: str, newline: str, has_bom: bool) -> None:
    rendered = text.replace("\n", newline)
    encoded = rendered.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded
    path.write_bytes(encoded)


def replace_exact_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}.")
    return text.replace(old, new, 1)


def replace_regex_once(
    text: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}.")
    return updated


def replace_in_region(
    text: str,
    start_marker: str,
    end_marker: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found.")
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError(f"{label}: end marker not found.")
    region = text[start:end]
    patched = replace_regex_once(region, pattern, replacement, label)
    return text[:start] + patched + text[end:]


CATALOGUE_PARSER = r'''
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
'''

APP_HELPER = r'''
def verified_scheme_details_action(
    record: CatalogueRecord,
) -> dict[str, str] | None:
    # Return the first governed Scheme Details action, if present.
    for action in getattr(record, "verified_public_actions", []) or []:
        if not isinstance(action, dict):
            continue
        if str(action.get("action_type", "")).upper() != "SCHEME_DETAILS":
            continue
        if str(action.get("link_role", "")).upper() != "SCHEME_MASTER":
            continue
        if str(action.get("verification_status", "")).upper() != (
            "VERIFIED_INFORMATION_PAGE"
        ):
            continue
        if action.get("is_active") is not True:
            continue
        if action.get("is_time_bound") is not False:
            continue
        resolved_url = str(action.get("resolved_url", "") or "").strip()
        if not resolved_url.startswith(("https://", "http://")):
            continue
        return {
            "label": "Scheme Details",
            "resolved_url": resolved_url,
        }
    return None
'''

CARD_ACTIONS = r'''    actions: list[str] = []
    governed_details = verified_scheme_details_action(record)
    if record.application_url:
        actions.append(
            f'<a class="public-action public-action-primary" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.application_url)}">Apply now</a>'
        )
    if include_details_link and record.master_id:
        actions.append(
            f'<a class="public-action public-action-secondary" target="_top" '
            f'href="{html.escape(record_details_href(record), quote=True)}">View details</a>'
        )
    if governed_details:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{html.escape(governed_details["resolved_url"], quote=True)}">Scheme Details <span aria-hidden="true">&#8599;</span></a>'
        )
    elif record.official_page_url:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">&#8599;</span></a>'
        )
'''

PROFILE_ACTIONS = r'''    actions: list[str] = []
    governed_details = verified_scheme_details_action(record)
    if record.application_url:
        actions.append(
            f'<a class="public-action public-action-primary" target="_blank" rel="noopener" '
            f'href="{esc(record.application_url)}">Apply now</a>'
        )
    if governed_details:
        actions.append(
            f'<a class="public-action public-action-secondary" target="_blank" rel="noopener" '
            f'href="{html.escape(governed_details["resolved_url"], quote=True)}">Scheme Details &#8599;</a>'
        )
    elif record.official_page_url:
        actions.append(
            f'<a class="public-action public-action-secondary" target="_blank" rel="noopener" '
            f'href="{esc(record.official_page_url)}">Official page &#8599;</a>'
        )
    if record.guideline_urls:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener" '
            f'href="{esc(record.guideline_urls[0])}">Guideline &#8599;</a>'
        )

'''

DETAIL_LINKS = r'''    detail_links: list[tuple[str, str]] = []
    governed_details = verified_scheme_details_action(record)
    governed_url = (
        governed_details["resolved_url"]
        if governed_details
        else ""
    )
    if governed_url:
        detail_links.append(("Scheme Details", governed_url))
    if record.official_page_url and (
        record.official_page_url.casefold().rstrip("/")
        != governed_url.casefold().rstrip("/")
    ):
        detail_links.append(
            ("Official scheme page", record.official_page_url)
        )
    if record.application_url:
        detail_links.append(
            ("Application portal", record.application_url)
        )
    detail_links.extend(
        (f"Guideline or manual {index}", url)
        for index, url in enumerate(
            record.guideline_urls or [],
            start=1,
        )
    )
    detail_links.extend(
        (f"Official reference {index}", url)
        for index, url in enumerate(
            record.reference_urls or [],
            start=1,
        )
    )

    deduped_detail_links: list[tuple[str, str]] = []
    seen_detail_urls: set[str] = set()
    for label, url in detail_links:
        normalized_url = str(url or "").strip().casefold().rstrip("/")
        if not normalized_url or normalized_url in seen_detail_urls:
            continue
        seen_detail_urls.add(normalized_url)
        deduped_detail_links.append((label, url))
    detail_links = deduped_detail_links
'''


def patch_catalogue(path: Path) -> bool:
    text, newline, has_bom = read_source(path)
    if all(marker in text for marker in CATALOGUE_MARKERS):
        return False

    actual_hash = sha256_file(path)
    if actual_hash != CATALOGUE_BASELINE_SHA256:
        raise RuntimeError(
            "catalogue.py hash mismatch. "
            f"Expected {CATALOGUE_BASELINE_SHA256}, found {actual_hash}."
        )

    text = replace_exact_once(
        text,
        '    reference_urls: list[str] = field(default_factory=list)\n'
        '    contacts: list[str] = field(default_factory=list)\n',
        '    reference_urls: list[str] = field(default_factory=list)\n'
        '    verified_public_actions: list[dict[str, Any]] = field(default_factory=list)\n'
        '    contacts: list[str] = field(default_factory=list)\n',
        "CatalogueRecord field insertion",
    )

    text = replace_exact_once(
        text,
        "\n\ndef build_record(\n",
        "\n" + CATALOGUE_PARSER.rstrip() + "\n\n\ndef build_record(\n",
        "catalogue parser insertion",
    )

    text = replace_exact_once(
        text,
        "        reference_urls=all_urls,\n"
        "        contacts=dedupe(",
        "        reference_urls=all_urls,\n"
        "        verified_public_actions=parse_verified_public_actions(\n"
        "            plan_row.get(\"verified_public_actions_json\"),\n"
        "            plan_row.get(\"verified_public_action_schema_version\"),\n"
        "        ),\n"
        "        contacts=dedupe(",
        "catalogue constructor integration",
    )

    if not all(marker in text for marker in CATALOGUE_MARKERS):
        raise RuntimeError("catalogue.py patch markers are incomplete.")

    write_source(path, text, newline, has_bom)
    return True


def patch_app(path: Path) -> bool:
    text, newline, has_bom = read_source(path)
    if all(marker in text for marker in APP_MARKERS):
        return False

    actual_hash = sha256_file(path)
    if actual_hash != APP_BASELINE_SHA256:
        raise RuntimeError(
            "public_dashboard_app_v2_9.py hash mismatch. "
            f"Expected {APP_BASELINE_SHA256}, found {actual_hash}."
        )

    text = replace_exact_once(
        text,
        "\n\ndef public_record_card(\n",
        "\n" + APP_HELPER.rstrip() + "\n\n\ndef public_record_card(\n",
        "dashboard helper insertion",
    )

    text = replace_in_region(
        text,
        "def public_record_card(",
        "\ndef ",
        r'    actions: list\[str\] = \[\]\n'
        r'    if record\.application_url:\n'
        r'.*?'
        r'(?=    if record\.guideline_urls:)',
        CARD_ACTIONS,
        "scheme-card governed actions",
    )

    text = replace_in_region(
        text,
        "def render_scheme_details(",
        "\ndef main(",
        r'    actions: list\[str\] = \[\]\n'
        r'    if record\.application_url:\n'
        r'.*?'
        r'(?=    verified_on = )',
        PROFILE_ACTIONS,
        "scheme-profile governed actions",
    )

    text = replace_in_region(
        text,
        "def render_scheme_details(",
        "\ndef main(",
        r'    detail_links: list\[tuple\[str, str\]\] = \[\]\n'
        r'.*?'
        r'(?=    if detail_links:)',
        DETAIL_LINKS,
        "scheme-profile governed resource links",
    )

    if not all(marker in text for marker in APP_MARKERS):
        raise RuntimeError("Dashboard app patch markers are incomplete.")

    write_source(path, text, newline, has_bom)
    return True


def run_runtime_validation(root: Path) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import csv
    from dataclasses import replace

    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig

    v3434 = (
        root
        / "data/catalogue_preview/v3_4_3_4/"
        "catalogue_preview_v3_4_3_4.csv"
    )
    v3435 = (
        root
        / "data/catalogue_preview/v3_4_3_5/"
        "catalogue_preview_v3_4_3_5.csv"
    )
    actions_path = (
        root
        / "data/departments/meity/v3_4_3_5/"
        "meity_verified_public_actions_v3_4_3_5.csv"
    )

    base = DashboardConfig.from_env(root)
    config_3434 = replace(
        base,
        normalization_path=v3434.resolve(),
        preview_path_configured=True,
    )
    config_3435 = replace(
        base,
        normalization_path=v3435.resolve(),
        preview_path_configured=True,
    )

    bundle_3434 = load_catalogue(config_3434)
    bundle_3435 = load_catalogue(config_3435)
    pop_3434 = split_catalogue_populations(bundle_3434.records)
    pop_3435 = split_catalogue_populations(bundle_3435.records)

    with actions_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        action_rows = list(csv.DictReader(handle))

    targets = {row["master_id"]: row for row in action_rows}
    records_3435 = {
        record.master_id: record
        for record in bundle_3435.records
    }

    target_details: list[dict[str, Any]] = []
    for master_id, expected in sorted(targets.items()):
        record = records_3435.get(master_id)
        if record is None:
            raise RuntimeError(
                f"Target missing from loaded preview: {master_id}"
            )
        actions = record.verified_public_actions
        target_details.append(
            {
                "master_id": master_id,
                "scheme_name": record.scheme_name,
                "action_count": len(actions),
                "action_type": (
                    actions[0]["action_type"] if actions else ""
                ),
                "action_url": (
                    actions[0]["resolved_url"] if actions else ""
                ),
                "expected_url": expected["resolved_url"],
                "application_url": record.application_url,
            }
        )

    checks = {
        "v3434_loaded_records_168": len(bundle_3434.records) == 168,
        "v3435_loaded_records_168": len(bundle_3435.records) == 168,
        "main_scheme_population_unchanged": (
            len(pop_3434.main_scheme_records)
            == len(pop_3435.main_scheme_records)
            == 55
        ),
        "application_call_population_unchanged": (
            len(pop_3434.application_call_records)
            == len(pop_3435.application_call_records)
            == 38
        ),
        "exactly_four_targets": len(target_details) == 4,
        "expected_scheme_names": (
            {item["scheme_name"] for item in target_details}
            == EXPECTED_SCHEMES
        ),
        "one_governed_action_each": all(
            item["action_count"] == 1
            for item in target_details
        ),
        "all_scheme_details": all(
            item["action_type"] == "SCHEME_DETAILS"
            for item in target_details
        ),
        "all_action_urls_match": all(
            item["action_url"] == item["expected_url"]
            for item in target_details
        ),
        "all_application_urls_blank": all(
            not item["application_url"]
            for item in target_details
        ),
        "v3434_has_no_governed_actions": all(
            not record.verified_public_actions
            for record in bundle_3434.records
        ),
    }

    return {
        "checks": checks,
        "targets": target_details,
        "passed": all(checks.values()),
    }


def run(root: Path) -> dict[str, Any]:
    catalogue_path = root / "ssip_dashboard/catalogue.py"
    app_path = root / "apps/public_dashboard_app_v2_9.py"
    source_catalogue = (
        root
        / "data/catalogue_preview/v3_4_3_4/"
        "catalogue_preview_v3_4_3_4.csv"
    )
    actions_path = (
        root
        / "data/departments/meity/v3_4_3_5/"
        "meity_verified_public_actions_v3_4_3_5.csv"
    )
    preview_path = (
        root
        / "data/catalogue_preview/v3_4_3_5/"
        "catalogue_preview_v3_4_3_5.csv"
    )
    output_dir = root / "data/departments/meity/v3_4_3_5"
    summary_path = (
        output_dir
        / "meity_dashboard_action_integration_summary_v3_4_3_5.json"
    )

    for required in (
        catalogue_path,
        app_path,
        source_catalogue,
        actions_path,
        preview_path,
    ):
        if not required.exists():
            raise FileNotFoundError(required)

    if sha256_file(source_catalogue) != SOURCE_CATALOGUE_SHA256:
        raise RuntimeError("Frozen v3.4.3.4 catalogue hash mismatch.")
    if sha256_file(actions_path) != ACTIONS_SHA256:
        raise RuntimeError("Verified public actions hash mismatch.")

    database_before = snapshot_hashes(
        root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    publication_before = snapshot_hashes(
        root,
        ("publication/**/*", "data/publication/**/*"),
    )
    source_hash_before = sha256_file(source_catalogue)
    actions_hash_before = sha256_file(actions_path)
    preview_hash_before = sha256_file(preview_path)

    catalogue_pre_hash = sha256_file(catalogue_path)
    app_pre_hash = sha256_file(app_path)

    already_patched = (
        all(marker in read_source(catalogue_path)[0] for marker in CATALOGUE_MARKERS)
        and all(marker in read_source(app_path)[0] for marker in APP_MARKERS)
    )

    backup_location = ""
    if not already_patched:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = (
            root
            / "backups"
            / f"before_v3_4_3_5_dashboard_action_integration_{stamp}"
        )
        for path in (catalogue_path, app_path):
            destination = backup_root / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        backup_location = backup_root.relative_to(root).as_posix()

    catalogue_modified = patch_catalogue(catalogue_path)
    app_modified = patch_app(app_path)

    py_compile.compile(str(catalogue_path), doraise=True)
    py_compile.compile(str(app_path), doraise=True)

    runtime = run_runtime_validation(root)
    if not runtime["passed"]:
        raise RuntimeError(
            f"Runtime integration validation failed: {runtime}"
        )

    database_after = snapshot_hashes(
        root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    publication_after = snapshot_hashes(
        root,
        ("publication/**/*", "data/publication/**/*"),
    )

    safety = {
        "frozen_source_catalogue_unchanged": (
            source_hash_before == sha256_file(source_catalogue)
        ),
        "verified_actions_unchanged": (
            actions_hash_before == sha256_file(actions_path)
        ),
        "preview_catalogue_unchanged": (
            preview_hash_before == sha256_file(preview_path)
        ),
        "database_files_unchanged": database_before == database_after,
        "publication_files_unchanged": publication_before == publication_after,
    }

    summary: dict[str, Any] = {
        "version": VERSION,
        "stage": "DASHBOARD_GOVERNED_ACTION_INTEGRATION",
        "execution_mode": "PREVIEW_ONLY",
        "release_readiness_status": "PASS",
        "catalogue_loader_modified": catalogue_modified,
        "dashboard_app_modified": app_modified,
        "already_patched_before_run": already_patched,
        "verified_scheme_details_actions": 4,
        "apply_now_actions_added": 0,
        "open_call_actions_added": 0,
        "loaded_records": 168,
        "main_scheme_records": 55,
        "application_call_records": 38,
        "backup_location": backup_location,
        "catalogue_pre_sha256": catalogue_pre_hash,
        "catalogue_post_sha256": sha256_file(catalogue_path),
        "app_pre_sha256": app_pre_hash,
        "app_post_sha256": sha256_file(app_path),
        "runtime_validation": runtime,
        "safety": safety,
        "publication_performed": False,
        "database_writes": 0,
        "generated_at_utc": utc_now_iso(),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if not all(safety.values()):
        raise RuntimeError(f"Safety validation failed: {safety}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Patch the SSIP dashboard loader and renderer for governed "
            "v3.4.3.5 Scheme Details actions."
        )
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="SSIP project root.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Apply idempotently and validate the integration.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the governed preview-only integration.",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    summary = run(root)

    if args.self_test:
        print(
            "MeitY v3.4.3.5 dashboard action integration "
            "self-test: PASS"
        )
        return 0

    print("SSIP MeitY v3.4.3.5 dashboard action integration")
    print("----------------------------------------------------")
    print(
        f"Release readiness status:       "
        f"{summary['release_readiness_status']}"
    )
    print(
        f"Catalogue loader modified:      "
        f"{summary['catalogue_loader_modified']}"
    )
    print(
        f"Dashboard app modified:         "
        f"{summary['dashboard_app_modified']}"
    )
    print(
        f"Verified Scheme Details:        "
        f"{summary['verified_scheme_details_actions']}"
    )
    print(
        f"Apply Now actions added:        "
        f"{summary['apply_now_actions_added']}"
    )
    print(
        f"Open-call actions added:        "
        f"{summary['open_call_actions_added']}"
    )
    print(
        f"Loaded records:                 "
        f"{summary['loaded_records']}"
    )
    print(
        f"Main scheme records:            "
        f"{summary['main_scheme_records']}"
    )
    print(
        f"Application-call records:       "
        f"{summary['application_call_records']}"
    )
    print(
        f"Database modified:              "
        f"{not summary['safety']['database_files_unchanged']}"
    )
    print(
        f"Publication performed:          "
        f"{summary['publication_performed']}"
    )
    if summary["backup_location"]:
        print(f"Backup:                         {summary['backup_location']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
