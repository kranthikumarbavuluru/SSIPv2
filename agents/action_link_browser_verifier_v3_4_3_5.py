from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agents.action_link_agent_v3_4_3_5 import (
    EXPECTED_SOURCE_SHA256,
    load_json,
    sha256_file,
    snapshot_hashes,
)


VERSION = "3.4.3.5"
EXPECTED_SCHEME_NAMES = {"GENESIS", "SAMRIDH", "SASACT", "TIDE 2.0"}
DEFAULT_TIMEOUT_MS = 45_000
RENDER_WAIT_SECONDS = 18

ENTITY_RULES = {
    "GENESIS": {
        "short_markers": ("genesis",),
        "strong_markers": (
            "gen next support for innovative startups",
            "gen-next support for innovative startups",
            "gen next support for innovative start-ups",
            "gen-next support for innovative start-ups",
        ),
    },
    "SAMRIDH": {
        "short_markers": ("samridh",),
        "strong_markers": (
            "startup accelerator of meity for product innovation development and growth",
        ),
    },
    "SASACT": {
        "short_markers": ("sasact",),
        "strong_markers": (
            "scheme for accelerating startups around post covid technology",
            "scheme for accelerating start-ups around post-covid technology",
            "scheme for accelerating start-ups around post covid technology",
        ),
    },
    "TIDE 2.0": {
        "short_markers": ("tide 2.0", "tide 2"),
        "strong_markers": (
            "technology incubation and development of entrepreneurs",
        ),
    },
}

RESULT_COLUMNS = [
    "verification_id",
    "classification_id",
    "inventory_id",
    "master_id",
    "canonical_name",
    "requested_url",
    "final_url",
    "http_status",
    "final_domain",
    "browser_engine",
    "browser_executable",
    "playwright_version",
    "page_title",
    "heading_text",
    "visible_text_length",
    "strong_marker_evidence",
    "heading_marker_evidence",
    "verification_status",
    "confidence",
    "eligible_for_public_button",
    "network_status",
    "render_wait_seconds",
    "error_type",
    "error_detail",
    "verified_at_utc",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"[^a-z0-9.+&/\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_id(prefix: str, *parts: str) -> str:
    material = "|".join([VERSION, prefix, *parts])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def read_csv(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(50_000_000)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key): (value or "") for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=RESULT_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def discover_browser_executable() -> tuple[str, str]:
    candidates = [
        (
            "Google Chrome",
            Path(os.environ.get("ProgramFiles", ""))
            / "Google/Chrome/Application/chrome.exe",
        ),
        (
            "Google Chrome",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Google/Chrome/Application/chrome.exe",
        ),
        (
            "Google Chrome",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google/Chrome/Application/chrome.exe",
        ),
        (
            "Microsoft Edge",
            Path(os.environ.get("ProgramFiles", ""))
            / "Microsoft/Edge/Application/msedge.exe",
        ),
        (
            "Microsoft Edge",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Microsoft/Edge/Application/msedge.exe",
        ),
        (
            "Microsoft Edge",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Microsoft/Edge/Application/msedge.exe",
        ),
    ]

    for name, path in candidates:
        if str(path) and path.is_file():
            return name, str(path)
    return "Playwright Chromium", ""


def domain_is_official(domain: str, config: dict[str, Any]) -> bool:
    host = normalize_text(domain).strip(".")
    policy = config["official_domain_policy"]

    exact = {
        normalize_text(item).strip(".")
        for item in policy.get("trusted_exact_domains", [])
    }
    if host in exact:
        return True

    for suffix in policy.get("permitted_domain_suffixes", []):
        clean = normalize_text(suffix).strip(".")
        if host == clean or host.endswith("." + clean):
            return True
    return False


def select_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected = [
        row
        for row in rows
        if row.get("proposed_action_type") == "SCHEME_DETAILS"
        and row.get("link_role") == "SCHEME_MASTER"
        and row.get("official_domain_policy_result") == "PASS"
        and row.get("normalized_url", "").startswith("https://")
        and not row.get("file_extension", "")
    ]
    return sorted(selected, key=lambda item: item.get("canonical_name", ""))


def load_inputs(
    project_root: Path,
) -> tuple[dict[str, Any], Path, Path, list[dict[str, str]]]:
    config_path = project_root / "config/action_link_rules_v3_4_3_5.json"
    config = load_json(config_path)

    if config.get("schema_version") != VERSION:
        raise RuntimeError("Configuration version mismatch.")
    if config.get("execution_mode") != "PREVIEW_ONLY":
        raise RuntimeError("Configuration is not PREVIEW_ONLY.")
    if config.get("output", {}).get("publication_allowed") is not False:
        raise RuntimeError("Publication must remain disabled.")
    if config.get("output", {}).get("database_writes_allowed") is not False:
        raise RuntimeError("Database writes must remain disabled.")

    source_path = project_root / Path(config["source"]["catalogue_path"])
    if sha256_file(source_path) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Frozen v3.4.3.4 source candidate hash mismatch.")

    output_dir = project_root / Path(config["output"]["directory"])
    classification_path = (
        output_dir / "meity_action_link_offline_classification_v3_4_3_5.csv"
    )
    classification_summary_path = (
        output_dir
        / "meity_action_link_offline_classification_summary_v3_4_3_5.json"
    )

    if not classification_path.exists():
        raise FileNotFoundError(f"Missing classification: {classification_path}")
    if not classification_summary_path.exists():
        raise FileNotFoundError(
            f"Missing classification summary: {classification_summary_path}"
        )

    summary = load_json(classification_summary_path)
    if summary.get("stage") != "OFFLINE_CLASSIFICATION_ONLY":
        raise RuntimeError("Offline classification stage is not current.")
    if summary.get("network_requests") != 0:
        raise RuntimeError("Offline classification unexpectedly used the network.")
    if not all(summary.get("safety", {}).values()):
        raise RuntimeError("Offline classification safety checks did not pass.")

    return config, source_path, classification_path, read_csv(classification_path)


def validate_candidates(selected: list[dict[str, str]]) -> dict[str, Any]:
    names = {row.get("canonical_name", "") for row in selected}
    urls = [row.get("normalized_url", "") for row in selected]

    checks = {
        "exactly_four_candidates": len(selected) == 4,
        "expected_names_only": names == EXPECTED_SCHEME_NAMES,
        "all_https": all(url.startswith("https://") for url in urls),
        "all_meity_scheme_routes": all(
            (urlsplit(url).hostname or "").casefold() == "msh.meity.gov.in"
            and urlsplit(url).path.casefold().startswith("/schemes/")
            for url in urls
        ),
        "no_documents": all(not Path(urlsplit(url).path).suffix for url in urls),
        "no_apply_actions": all(
            row.get("proposed_action_type") != "APPLY_NOW" for row in selected
        ),
    }
    return {
        "selected_names": sorted(names),
        "selected_urls": urls,
        "checks": checks,
        "passed": all(checks.values()),
    }


def marker_evidence(
    canonical_name: str,
    title: str,
    headings: list[str],
    visible_text: str,
) -> tuple[list[str], list[str]]:
    rules = ENTITY_RULES[canonical_name]
    normalized_title = normalize_text(title)
    normalized_headings = normalize_text(" | ".join(headings))
    normalized_body = normalize_text(visible_text)

    strong: list[str] = []
    for marker in rules["strong_markers"]:
        normalized_marker = normalize_text(marker)
        if normalized_marker and normalized_marker in normalized_body:
            strong.append(f"visible_text:{marker}")

    heading: list[str] = []
    for marker in rules["short_markers"]:
        normalized_marker = normalize_text(marker)
        if not normalized_marker:
            continue
        if normalized_marker in normalized_title:
            heading.append(f"title:{marker}")
        if normalized_marker in normalized_headings:
            heading.append(f"heading:{marker}")

    return list(dict.fromkeys(strong)), list(dict.fromkeys(heading))


def render_and_verify(
    browser: Any,
    row: dict[str, str],
    config: dict[str, Any],
    browser_engine: str,
    browser_executable: str,
    playwright_version: str,
    timeout_ms: int,
) -> dict[str, Any]:
    canonical_name = row["canonical_name"]
    requested_url = row["normalized_url"]
    verified_at = utc_now_iso()

    context = browser.new_context(
        locale="en-IN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36 "
            "SSIP-RenderedVerifier/3.4.3.5"
        ),
        viewport={"width": 1440, "height": 1000},
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    try:
        response = page.goto(
            requested_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass

        deadline = time.monotonic() + RENDER_WAIT_SECONDS
        title = ""
        headings: list[str] = []
        visible_text = ""
        strong: list[str] = []
        heading: list[str] = []

        while time.monotonic() < deadline:
            try:
                title = page.title()
                headings = page.locator(
                    "h1, h2, h3, [role='heading']"
                ).all_inner_texts()
                visible_text = page.locator("body").inner_text()
                strong, heading = marker_evidence(
                    canonical_name,
                    title,
                    headings,
                    visible_text,
                )
                if strong or heading:
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)

        final_url = page.url
        final_domain = (urlsplit(final_url).hostname or "").casefold()
        official = domain_is_official(final_domain, config)
        http_status = response.status if response else ""

        verification_status = "UNVERIFIED"
        confidence = 0.55
        eligible = False

        if not official:
            verification_status = "REJECTED_NON_OFFICIAL"
            confidence = 0.00
        elif isinstance(http_status, int) and http_status in {401, 403, 429}:
            verification_status = "ACCESS_BLOCKED"
            confidence = 0.00
        elif isinstance(http_status, int) and http_status in {404, 410}:
            verification_status = "BROKEN_LINK"
            confidence = 0.00
        elif strong:
            verification_status = "VERIFIED_INFORMATION_PAGE"
            confidence = 0.98
            eligible = True
        elif heading:
            verification_status = "VERIFIED_INFORMATION_PAGE"
            confidence = 0.93
            eligible = True

        return {
            "verification_id": stable_id(
                "browser-verification",
                row.get("classification_id", ""),
                requested_url,
            ),
            "classification_id": row.get("classification_id", ""),
            "inventory_id": row.get("inventory_id", ""),
            "master_id": row.get("master_id", ""),
            "canonical_name": canonical_name,
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": http_status,
            "final_domain": final_domain,
            "browser_engine": browser_engine,
            "browser_executable": browser_executable,
            "playwright_version": playwright_version,
            "page_title": title,
            "heading_text": " | ".join(headings)[:4000],
            "visible_text_length": len(visible_text),
            "strong_marker_evidence": " | ".join(strong),
            "heading_marker_evidence": " | ".join(heading),
            "verification_status": verification_status,
            "confidence": f"{confidence:.2f}",
            "eligible_for_public_button": str(eligible),
            "network_status": "COMPLETED",
            "render_wait_seconds": RENDER_WAIT_SECONDS,
            "error_type": "",
            "error_detail": "",
            "verified_at_utc": verified_at,
        }

    except Exception as exc:
        return {
            "verification_id": stable_id(
                "browser-verification",
                row.get("classification_id", ""),
                requested_url,
            ),
            "classification_id": row.get("classification_id", ""),
            "inventory_id": row.get("inventory_id", ""),
            "master_id": row.get("master_id", ""),
            "canonical_name": canonical_name,
            "requested_url": requested_url,
            "final_url": page.url,
            "http_status": "",
            "final_domain": (urlsplit(page.url).hostname or "").casefold(),
            "browser_engine": browser_engine,
            "browser_executable": browser_executable,
            "playwright_version": playwright_version,
            "page_title": "",
            "heading_text": "",
            "visible_text_length": 0,
            "strong_marker_evidence": "",
            "heading_marker_evidence": "",
            "verification_status": "UNVERIFIED",
            "confidence": "0.00",
            "eligible_for_public_button": "False",
            "network_status": "BROWSER_ERROR",
            "render_wait_seconds": RENDER_WAIT_SECONDS,
            "error_type": type(exc).__name__,
            "error_detail": str(exc)[:1500],
            "verified_at_utc": verified_at,
        }
    finally:
        context.close()


def run_self_test(project_root: Path) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    _, _, _, rows = load_inputs(project_root)
    selected = select_candidates(rows)
    candidate_test = validate_candidates(selected)
    if not candidate_test["passed"]:
        raise RuntimeError(f"Candidate preflight failed: {candidate_test}")

    browser_name, executable = discover_browser_executable()
    playwright_version = importlib.metadata.version("playwright")

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {
            "headless": True,
            "args": ["--disable-gpu", "--no-first-run"],
        }
        if executable:
            launch_kwargs["executable_path"] = executable
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page()
        page.goto("about:blank")
        title = page.title()
        browser.close()

    checks = {
        "candidate_preflight": candidate_test["passed"],
        "playwright_imported": True,
        "browser_launched": True,
        "about_blank_loaded": title == "",
        "network_requests_zero": True,
    }
    return {
        "version": VERSION,
        "stage": "BROWSER_RENDERER_PREFLIGHT",
        "browser_name": browser_name,
        "browser_executable": executable,
        "playwright_version": playwright_version,
        "candidate_test": candidate_test,
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_browser_verification(
    project_root: Path,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    config, source_path, classification_path, rows = load_inputs(project_root)
    selected = select_candidates(rows)
    candidate_test = validate_candidates(selected)
    if not candidate_test["passed"]:
        raise RuntimeError(f"Candidate preflight failed: {candidate_test}")

    output_dir = project_root / Path(config["output"]["directory"])
    inventory_path = output_dir / "meity_action_link_inventory_v3_4_3_5.csv"
    quarantine_path = (
        output_dir / "meity_action_link_inventory_quarantine_v3_4_3_5.csv"
    )
    result_path = (
        output_dir / "meity_scheme_page_browser_verification_v3_4_3_5.csv"
    )
    summary_path = (
        output_dir
        / "meity_scheme_page_browser_verification_summary_v3_4_3_5.json"
    )

    source_hash_before = sha256_file(source_path)
    classification_hash_before = sha256_file(classification_path)
    inventory_hash_before = sha256_file(inventory_path)
    quarantine_hash_before = sha256_file(quarantine_path)

    database_before = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_before = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_current = project_root / "publication/current"
    publication_existed_before = publication_current.exists()

    browser_name, executable = discover_browser_executable()
    playwright_version = importlib.metadata.version("playwright")

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {
            "headless": True,
            "args": [
                "--disable-gpu",
                "--no-first-run",
                "--disable-background-networking",
            ],
        }
        if executable:
            launch_kwargs["executable_path"] = executable

        browser = playwright.chromium.launch(**launch_kwargs)
        try:
            results = [
                render_and_verify(
                    browser,
                    row,
                    config,
                    browser_name,
                    executable,
                    playwright_version,
                    timeout_ms,
                )
                for row in selected
            ]
        finally:
            browser.close()

    write_csv(result_path, results)

    status_counts: dict[str, int] = {}
    for item in results:
        status = str(item["verification_status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    verified_count = status_counts.get("VERIFIED_INFORMATION_PAGE", 0)
    eligible_count = sum(
        item["eligible_for_public_button"] == "True" for item in results
    )

    readiness = (
        "PASS"
        if verified_count == len(results) == 4
        else "PASS_WITH_REVIEW"
        if results
        else "FAIL"
    )

    summary: dict[str, Any] = {
        "version": VERSION,
        "stage": "BROWSER_RENDERED_SCHEME_PAGE_VERIFICATION",
        "execution_mode": "PREVIEW_ONLY",
        "release_readiness_status": readiness,
        "verification_policy": (
            "VISIBLE_RENDERED_DOM_STRONG_MARKER_OR_TITLE_HEADING_MARKER"
        ),
        "selected_candidate_count": len(selected),
        "browser_render_attempts": len(selected),
        "result_row_count": len(results),
        "verification_status_counts": status_counts,
        "verified_information_page_count": verified_count,
        "scheme_details_button_candidate_count": eligible_count,
        "review_required_count": len(results) - verified_count,
        "apply_now_button_count": 0,
        "open_call_button_count": 0,
        "pdf_requests": 0,
        "quarantined_link_requests": 0,
        "database_writes": 0,
        "dashboard_code_changes": 0,
        "publication_performed": False,
        "browser_name": browser_name,
        "browser_executable": executable,
        "playwright_version": playwright_version,
        "timeout_ms": timeout_ms,
        "render_wait_seconds": RENDER_WAIT_SECONDS,
        "result_path": result_path.relative_to(project_root).as_posix(),
        "source_sha256": source_hash_before,
        "classification_sha256": classification_hash_before,
        "inventory_sha256": inventory_hash_before,
        "quarantine_sha256": quarantine_hash_before,
        "result_sha256": sha256_file(result_path),
        "candidate_test": candidate_test,
        "verified_at_utc": utc_now_iso(),
    }
    write_json(summary_path, summary)

    source_hash_after = sha256_file(source_path)
    classification_hash_after = sha256_file(classification_path)
    inventory_hash_after = sha256_file(inventory_path)
    quarantine_hash_after = sha256_file(quarantine_path)
    database_after = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_after = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_exists_after = publication_current.exists()

    safety = {
        "source_candidate_unchanged": source_hash_before == source_hash_after,
        "offline_classification_unchanged": (
            classification_hash_before == classification_hash_after
        ),
        "clean_inventory_unchanged": inventory_hash_before == inventory_hash_after,
        "quarantine_inventory_unchanged": (
            quarantine_hash_before == quarantine_hash_after
        ),
        "database_files_unchanged": database_before == database_after,
        "dashboard_python_files_unchanged": dashboard_before == dashboard_after,
        "publication_current_unchanged": (
            publication_existed_before == publication_exists_after
        ),
    }
    summary["safety"] = safety
    write_json(summary_path, summary)

    if not all(safety.values()):
        raise RuntimeError(f"Safety validation failed: {safety}")

    return summary
