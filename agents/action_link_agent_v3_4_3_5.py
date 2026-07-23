from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import re
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit


VERSION = "3.4.3.5"
EXPECTED_SOURCE_SHA256 = "ef43bd7e27df2ead5fe88ab8bf2751a80eac6c4e13e8894173a6625b57650a8c"
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>'\"|]+")
TRAILING_URL_PUNCTUATION = ".,;:!?)]}>"

INVENTORY_COLUMNS = [
    "inventory_id",
    "source_row_number",
    "master_id",
    "canonical_name",
    "record_type",
    "source_name",
    "department",
    "ministry",
    "scope_match_reason",
    "source_field_names",
    "source_strength",
    "original_url",
    "normalized_url",
    "url_scheme",
    "url_domain",
    "url_path",
    "file_extension",
    "has_query",
    "fragment_removed",
    "url_occurrence_count",
    "inventory_status",
    "classification_status",
    "network_status",
    "candidate_sha256",
    "inventoried_at_utc",
]

QUARANTINE_COLUMNS = INVENTORY_COLUMNS + [
    "quarantine_reason",
    "quarantine_detail",
]

FIELD_ALIASES = {
    "master_id": ("master_id", "scheme_id", "programme_id", "record_id", "id"),
    "canonical_name": (
        "canonical_name",
        "scheme_name",
        "programme_name",
        "program_name",
        "title",
        "name",
    ),
    "record_type": ("record_type", "master_type", "entity_type", "programme_type", "type"),
    "source_name": ("source", "source_name", "source_authority", "authority", "portal"),
    "department": ("department", "department_name", "owner_department"),
    "ministry": ("ministry", "ministry_name", "owner_ministry"),
}

MEITY_SCOPE_MARKERS = (
    "meity",
    "ministry of electronics and information technology",
    "ministry of electronics & information technology",
    "meity startup hub",
    "msh.meity.gov.in",
    "software technology parks of india",
    "centre for development of advanced computing",
    "center for development of advanced computing",
)

KNOWN_MEITY_NAME_MARKERS = (
    "sasact",
    "genesis",
    "samridh",
    "tide 2.0",
    "tide 2",
    "sitaa",
)

NON_SCHEME_UTILITY_NAMES = {
    "sitemap.xml",
    "sitemap 0.xml",
    "myscheme",
    "about",
    "accessibility statement",
    "contact",
    "dashboard",
    "disclaimer",
    "screen reader",
    "terms conditions",
    "terms and conditions",
    "privacy policy",
    "copyright policy",
    "hyperlinking policy",
    "help",
    "faq",
}

FORBIDDEN_FIELD_TOKENS = (
    "sector_reason",
    "llm",
    "model_endpoint",
    "api_endpoint",
    "chat_completion",
    "prompt",
    "embedding",
    "debug",
    "trace",
)

PRIMARY_URL_FIELD_TOKENS = (
    "official_page_url",
    "application_url",
    "apply_url",
    "application_link",
    "apply_link",
    "portal_url",
    "guideline_url",
    "manual_url",
    "notification_url",
    "contact_url",
    "call_url",
    "scheme_url",
    "programme_url",
    "program_url",
    "final_url",
    "source_url",
)

SECONDARY_URL_FIELD_TOKENS = (
    "evidence",
    "url",
    "link",
    "page",
    "portal",
    "guideline",
    "manual",
    "notification",
    "application",
    "apply",
    "contact",
)

ENTITY_HINTS = {
    "samridh": ("samridh",),
    "tide 2.0": ("tide", "tide 2.0", "tide%202.0", "tide_2.0"),
    "sasact": ("sasact",),
    "genesis": ("genesis",),
    "sitaa": ("sitaa",),
}

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def read_candidate_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(50_000_000)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No CSV header found in {path}")
        rows = [
            {str(key): (value or "") for key, value in row.items()}
            for row in reader
        ]
        return list(reader.fieldnames), rows


def first_value(row: dict[str, str], logical_name: str) -> str:
    aliases = FIELD_ALIASES[logical_name]
    casefold_map = {key.casefold(): key for key in row}
    for alias in aliases:
        actual_key = casefold_map.get(alias.casefold())
        if actual_key:
            value = str(row.get(actual_key, "")).strip()
            if value:
                return value
    return ""


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def row_is_non_scheme_utility(row: dict[str, str]) -> bool:
    canonical_name = normalize_name(first_value(row, "canonical_name"))
    if canonical_name in NON_SCHEME_UTILITY_NAMES:
        return True
    if canonical_name.startswith("sitemap") and canonical_name.endswith(".xml"):
        return True
    return False


def detect_meity_scope(row: dict[str, str]) -> tuple[bool, str]:
    canonical_name = normalize_name(first_value(row, "canonical_name"))
    for marker in KNOWN_MEITY_NAME_MARKERS:
        if marker in canonical_name:
            return True, f"KNOWN_MEITY_ENTITY:{marker}"

    explicit_url_values = []
    for field_name, value in row.items():
        field_key = field_name.casefold()
        if "official_page_url" in field_key or "scheme_url" in field_key:
            explicit_url_values.append(str(value))
    explicit_blob = " | ".join(explicit_url_values).casefold()
    if "msh.meity.gov.in" in explicit_blob:
        return True, "OFFICIAL_MEITY_SCHEME_URL"

    identity_field_tokens = (
        "source",
        "department",
        "ministry",
        "authority",
        "owner",
        "agency",
        "organisation",
        "organization",
        "portal",
    )
    identity_values = [
        str(value)
        for key, value in row.items()
        if any(token in key.casefold() for token in identity_field_tokens)
    ]
    identity_blob = " | ".join(identity_values).casefold()
    record_type = normalize_name(first_value(row, "record_type"))

    scheme_like = (
        not record_type
        or any(
            token in record_type
            for token in ("scheme", "programme", "program", "call", "challenge", "cohort")
        )
    )
    if scheme_like:
        for marker in MEITY_SCOPE_MARKERS:
            if marker in identity_blob:
                return True, f"IDENTITY_FIELD:{marker}"

    return False, ""


def extract_urls(value: str) -> list[str]:
    found: list[str] = []
    for match in URL_RE.finditer(value or ""):
        url = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
        if url:
            found.append(url)
    return found


def normalize_url(raw_url: str) -> tuple[str, dict[str, Any]]:
    candidate = raw_url.strip()
    if candidate.casefold().startswith("www."):
        candidate = "https://" + candidate

    split = urlsplit(candidate)
    scheme = split.scheme.casefold()
    hostname = (split.hostname or "").casefold()
    port = split.port
    netloc = hostname
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"

    path = split.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    normalized = urlunsplit((scheme, netloc, path, split.query, ""))
    extension = Path(unquote(path)).suffix.casefold()

    metadata = {
        "url_scheme": scheme,
        "url_domain": hostname,
        "url_path": path,
        "file_extension": extension,
        "has_query": bool(split.query),
        "fragment_removed": bool(split.fragment),
    }
    return normalized, metadata


def is_local_or_private_host(hostname: str) -> bool:
    host = hostname.strip().casefold()
    if host in {"localhost", "0.0.0.0", "::1"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
    )


def field_source_strength(field_name: str) -> str:
    key = field_name.casefold()
    if any(token in key for token in FORBIDDEN_FIELD_TOKENS):
        return "FORBIDDEN"
    if any(token in key for token in PRIMARY_URL_FIELD_TOKENS):
        return "PRIMARY"
    if any(token in key for token in SECONDARY_URL_FIELD_TOKENS):
        return "SECONDARY_EVIDENCE"
    return "IGNORE"


def canonical_entity_key(canonical_name: str) -> str:
    name = normalize_name(canonical_name)
    for entity_key in ENTITY_HINTS:
        if entity_key in name:
            return entity_key
    return ""


def entity_keys_in_url(normalized_url: str) -> set[str]:
    haystack = unquote(normalized_url).casefold()
    matched: set[str] = set()
    for entity_key, hints in ENTITY_HINTS.items():
        if any(hint in haystack for hint in hints):
            matched.add(entity_key)
    return matched


def stable_inventory_id(
    source_row_number: int,
    master_id: str,
    normalized_url: str,
) -> str:
    material = f"{VERSION}|{source_row_number}|{master_id}|{normalized_url}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def base_inventory_record(
    *,
    row_number: int,
    row: dict[str, str],
    match_reason: str,
    source_hash: str,
    inventoried_at: str,
    original_url: str,
    normalized_url: str,
    metadata: dict[str, Any],
    field_names: list[str],
    source_strength: str,
    occurrences: int,
) -> dict[str, Any]:
    master_id = first_value(row, "master_id") or f"source_row_{row_number}"
    canonical_name = first_value(row, "canonical_name") or "(unnamed record)"
    return {
        "inventory_id": stable_inventory_id(row_number, master_id, normalized_url),
        "source_row_number": row_number,
        "master_id": master_id,
        "canonical_name": canonical_name,
        "record_type": first_value(row, "record_type"),
        "source_name": first_value(row, "source_name"),
        "department": first_value(row, "department"),
        "ministry": first_value(row, "ministry"),
        "scope_match_reason": match_reason,
        "source_field_names": ";".join(dict.fromkeys(field_names)),
        "source_strength": source_strength,
        "original_url": original_url,
        "normalized_url": normalized_url,
        "url_scheme": metadata.get("url_scheme", ""),
        "url_domain": metadata.get("url_domain", ""),
        "url_path": metadata.get("url_path", ""),
        "file_extension": metadata.get("file_extension", ""),
        "has_query": str(bool(metadata.get("has_query", False))),
        "fragment_removed": str(bool(metadata.get("fragment_removed", False))),
        "url_occurrence_count": occurrences,
        "inventory_status": "URL_DISCOVERED",
        "classification_status": "NOT_CLASSIFIED",
        "network_status": "NOT_REQUESTED",
        "candidate_sha256": source_hash,
        "inventoried_at_utc": inventoried_at,
    }


def build_inventory(
    source_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    source_hash = sha256_file(source_path)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "Safety failure: v3.4.3.4 source SHA-256 does not match the frozen baseline. "
            f"Expected {EXPECTED_SOURCE_SHA256}, got {source_hash}."
        )

    source_columns, source_rows = read_candidate_rows(source_path)
    inventoried_at = utc_now_iso()

    scoped_rows: list[tuple[int, dict[str, str], str]] = []
    excluded_utility_rows = 0
    excluded_out_of_scope_rows = 0

    for row_number, row in enumerate(source_rows, start=1):
        if row_is_non_scheme_utility(row):
            excluded_utility_rows += 1
            continue
        is_meity, match_reason = detect_meity_scope(row)
        if is_meity:
            scoped_rows.append((row_number, row, match_reason))
        else:
            excluded_out_of_scope_rows += 1

    raw_records: list[dict[str, Any]] = []
    matched_names: list[str] = []

    for row_number, row, match_reason in scoped_rows:
        canonical_name = first_value(row, "canonical_name") or "(unnamed record)"
        matched_names.append(canonical_name)

        grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for field_name, raw_value in row.items():
            strength = field_source_strength(field_name)
            if strength == "IGNORE":
                continue

            for raw_url in extract_urls(str(raw_value or "")):
                normalized_url, metadata = normalize_url(raw_url)
                if normalized_url not in grouped:
                    grouped[normalized_url] = {
                        "original_url": raw_url,
                        "field_names": [],
                        "strengths": [],
                        "occurrences": 0,
                        "metadata": metadata,
                    }
                grouped[normalized_url]["field_names"].append(field_name)
                grouped[normalized_url]["strengths"].append(strength)
                grouped[normalized_url]["occurrences"] += 1

        for normalized_url, grouped_value in grouped.items():
            strengths = grouped_value["strengths"]
            source_strength = (
                "FORBIDDEN"
                if all(item == "FORBIDDEN" for item in strengths)
                else "PRIMARY"
                if "PRIMARY" in strengths
                else "SECONDARY_EVIDENCE"
            )
            raw_records.append(
                base_inventory_record(
                    row_number=row_number,
                    row=row,
                    match_reason=match_reason,
                    source_hash=source_hash,
                    inventoried_at=inventoried_at,
                    original_url=grouped_value["original_url"],
                    normalized_url=normalized_url,
                    metadata=grouped_value["metadata"],
                    field_names=grouped_value["field_names"],
                    source_strength=source_strength,
                    occurrences=grouped_value["occurrences"],
                )
            )

    url_to_entities: dict[str, set[str]] = defaultdict(set)
    for record in raw_records:
        url_to_entities[record["normalized_url"]].add(
            normalize_name(record["canonical_name"])
        )

    clean_inventory: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []

    for record in raw_records:
        reason = ""
        detail = ""
        hostname = str(record["url_domain"])
        normalized_url = str(record["normalized_url"])
        own_entity = canonical_entity_key(str(record["canonical_name"]))
        url_entities = entity_keys_in_url(normalized_url)
        shared_entities = url_to_entities[normalized_url]

        if record["source_strength"] == "FORBIDDEN":
            reason = "NON_PUBLIC_TECHNICAL_FIELD"
            detail = (
                "The URL was found only in a model, prompt, debug, or reasoning field."
            )
        elif is_local_or_private_host(hostname):
            reason = "LOCAL_OR_PRIVATE_ENDPOINT"
            detail = "Loopback, private-network, or local-development URLs are never public actions."
        elif "/v1/chat/completions" in str(record["url_path"]).casefold():
            reason = "MODEL_API_ENDPOINT"
            detail = "LLM completion endpoints are implementation metadata, not scheme links."
        elif own_entity and url_entities and own_entity not in url_entities:
            reason = "CROSS_ENTITY_EVIDENCE"
            detail = (
                f"The URL identifies {sorted(url_entities)}, but the catalogue row is "
                f"{record['canonical_name']}."
            )
        elif (
            len(shared_entities) > 1
            and record["file_extension"] in DOCUMENT_EXTENSIONS
            and not url_entities
        ):
            reason = "SHARED_AMBIGUOUS_DOCUMENT"
            detail = (
                "The same generic document URL is attached to multiple canonical schemes "
                "without entity-specific evidence."
            )

        if reason:
            quarantined = dict(record)
            quarantined["inventory_status"] = "QUARANTINED"
            quarantined["quarantine_reason"] = reason
            quarantined["quarantine_detail"] = detail
            quarantine.append(quarantined)
        else:
            clean_inventory.append(record)

    unique_clean_urls = {
        str(item["normalized_url"])
        for item in clean_inventory
        if item["normalized_url"]
    }
    matched_blob = " | ".join(matched_names).casefold()
    required_visibility = {
        "SASACT": "sasact" in matched_blob,
        "GENESIS": "genesis" in matched_blob,
    }

    quarantine_counts: dict[str, int] = {}
    for item in quarantine:
        key = str(item["quarantine_reason"])
        quarantine_counts[key] = quarantine_counts.get(key, 0) + 1

    summary = {
        "version": VERSION,
        "stage": "HYGIENE_INVENTORY_ONLY",
        "execution_mode": "PREVIEW_ONLY",
        "source_path": source_path.as_posix(),
        "source_sha256": source_hash,
        "source_row_count": len(source_rows),
        "source_columns": source_columns,
        "detected_meity_row_count": len(scoped_rows),
        "excluded_non_scheme_utility_row_count": excluded_utility_rows,
        "excluded_out_of_scope_row_count": excluded_out_of_scope_rows,
        "inventory_row_count": len(clean_inventory),
        "quarantined_inventory_row_count": len(quarantine),
        "raw_url_record_count_before_hygiene": len(raw_records),
        "unique_normalized_url_count": len(unique_clean_urls),
        "required_entities_visible": required_visibility,
        "quarantine_counts": quarantine_counts,
        "classification_performed": False,
        "network_requests": 0,
        "database_writes": 0,
        "dashboard_code_changes": 0,
        "publication_performed": False,
        "inventoried_at_utc": inventoried_at,
    }
    return clean_inventory, quarantine, summary


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def snapshot_hashes(root: Path, patterns: tuple[str, ...]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                snapshot[path.relative_to(root).as_posix()] = sha256_file(path)
    return snapshot


def run_inventory(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "config" / "action_link_rules_v3_4_3_5.json"
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
    output_dir = project_root / Path(config["output"]["directory"])
    inventory_path = output_dir / "meity_action_link_inventory_v3_4_3_5.csv"
    quarantine_path = output_dir / "meity_action_link_inventory_quarantine_v3_4_3_5.csv"
    summary_path = output_dir / "meity_action_link_inventory_summary_v3_4_3_5.json"

    source_hash_before = sha256_file(source_path)
    database_before = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_before = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_current = project_root / "publication" / "current"
    publication_existed_before = publication_current.exists()

    inventory, quarantine, summary = build_inventory(source_path)
    write_csv(inventory_path, inventory, INVENTORY_COLUMNS)
    write_csv(quarantine_path, quarantine, QUARANTINE_COLUMNS)

    summary["inventory_path"] = inventory_path.relative_to(project_root).as_posix()
    summary["quarantine_path"] = quarantine_path.relative_to(project_root).as_posix()
    summary["inventory_sha256"] = sha256_file(inventory_path)
    summary["quarantine_sha256"] = sha256_file(quarantine_path)
    write_json(summary_path, summary)

    source_hash_after = sha256_file(source_path)
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
