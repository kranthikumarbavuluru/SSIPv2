#!/usr/bin/env python3
"""SSIP v3.4.0.6 — Evidence-based sector verification agent.

Reads the current SSIP catalogue CSV, verifies or derives sectors from structured
record content and official web pages, optionally asks a local LM Studio model to
review ambiguous results, and writes an audited enriched catalogue.

Safety properties:
* Never changes master IDs, canonical names, URLs, record kinds or decisions.
* Creates a timestamped backup before --apply.
* Uses a controlled taxonomy; arbitrary LLM sector names are rejected.
* Treats broad startup/finance programmes as cross-sector instead of guessing.
* Low-confidence/conflicting classifications are retained in a review queue.
* Network and LM Studio failures do not abort deterministic classification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

VERSION = "3.4.0.6"
DEFAULT_CATALOGUE = Path("data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv")
DEFAULT_TAXONOMY = Path("config/sector_taxonomy_v3_4_0_6.json")
DEFAULT_OUTPUT_DIR = Path("data/sector_verification/v3_4_0_6")
DEFAULT_LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
USER_AGENT = "SSIP-Sector-Verification-Agent/3.4.0.6"
MAX_TEXT = 45000
MAX_RESPONSE_BYTES = 5_000_000

MAIN_RECORD_KINDS = {
    "SCHEME_OR_PROGRAMME", "SCHEME", "PROGRAMME", "GRANT", "FUND",
    "CREDIT_SUPPORT", "CREDIT_GUARANTEE", "SUBSIDY", "INCENTIVE",
    "FELLOWSHIP", "INCUBATION_SUPPORT", "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT", "PROCUREMENT_OR_MARKET_ACCESS",
}
BLANK_SECTOR_TOKENS = {
    "", "[]", "null", "none", "not recorded", "not specified",
    "sector not specified", "unknown", "n/a", "na",
}
GENERIC_SUPPORT_TERMS = {
    "fund", "funding", "grant", "loan", "credit", "incubation",
    "acceleration", "fellowship", "procurement", "market access",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm_key(value: Any) -> str:
    return normalized(value).casefold()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        temp_name = handle.name
    os.replace(temp_name, path)


def parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalized(item) for item in value if normalized(item)]
    text = normalized(value)
    if norm_key(text) in BLANK_SECTOR_TOKENS:
        return []
    for candidate in (text, html.unescape(text)):
        if candidate.startswith("[") and candidate.endswith("]"):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return [normalized(item) for item in parsed if normalized(item)]
            except json.JSONDecodeError:
                pass
    parts = re.split(r"\s*(?:;|\||\n)\s*", text)
    return [part for part in (normalized(item) for item in parts) if part]


def unique_values(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(normalized(v) for v in values if normalized(v)))


def list_json(values: Iterable[str]) -> str:
    return json.dumps(unique_values(values), ensure_ascii=False)


def list_cell(values: Iterable[str]) -> str:
    """CSV list format compatible with the existing SSIP dashboard parser."""
    return "; ".join(unique_values(values))


def record_kind(row: Mapping[str, Any]) -> str:
    return normalized(row.get("normalized_record_kind") or row.get("record_kind") or row.get("current_record_kind")).upper()


def is_visible_main_record(row: Mapping[str, Any]) -> bool:
    if norm_key(row.get("current_decision")) == "rejected":
        return False
    inclusion = norm_key(row.get("catalogue_inclusion"))
    if inclusion in {"excluded", "rejected", "evidence_only"}:
        return False
    kind = record_kind(row)
    return not kind or kind in MAIN_RECORD_KINDS


def safe_urls(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for field, role in (
        ("official_page_url", "official_page_text"),
        ("application_url", "official_page_text"),
    ):
        url = normalized(row.get(field))
        if url:
            pairs.append((url, role))
    for url in parse_list(row.get("guideline_urls")):
        pairs.append((url, "guideline_text"))
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, role in pairs:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        clean = url.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean)
            output.append((clean, role))
    return output[:3]


def strip_html(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        # Some official endpoints return XML sitemaps or feeds while declaring a
        # generic text content type. The HTML parser is sufficient for our text
        # extraction, but BeautifulSoup emits a warning to stderr. Windows
        # PowerShell can treat that harmless warning as a NativeCommandError and
        # stop the pipeline. Suppress only this exact warning.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(raw, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            node.decompose()
        return normalized(soup.get_text(" ", strip=True))[:MAX_TEXT]
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
        return normalized(html.unescape(text))[:MAX_TEXT]


def fetch_text(url: str, *, timeout: int = 25) -> tuple[str, str]:
    try:
        import requests
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.4,*/*;q=0.1"},
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        if "pdf" in content_type or urlparse(response.url).path.casefold().endswith(".pdf"):
            return "", "PDF_NOT_PARSED"
        encoding = response.encoding or "utf-8"
        raw = data.decode(encoding, errors="replace")
        return strip_html(raw), f"HTTP_{response.status_code}"
    except Exception as exc:
        return "", f"FETCH_ERROR:{type(exc).__name__}"


def field_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field, "")
    values = parse_list(value)
    if values:
        return " ".join(values)
    return normalized(value)


def structured_evidence(row: Mapping[str, Any]) -> dict[str, str]:
    fields = [
        "scheme_name", "sector", "objectives", "eligibility", "benefits",
        "target_beneficiaries", "startup_stage", "scheme_type", "status_evidence",
        "application_process", "required_documents", "source", "ministry",
        "department", "implementing_agency", "field_evidence",
    ]
    return {field: field_text(row, field)[:18000] for field in fields if field_text(row, field)}


@dataclass
class SectorResult:
    master_id: str
    scheme_name: str
    original_sectors: list[str]
    primary_sector: str
    secondary_sectors: list[str]
    all_sectors: list[str]
    confidence: float
    method: str
    review_required: bool
    evidence_summary: str
    scored_candidates: dict[str, float]
    fetched_urls: list[str]
    fetch_notes: list[str]
    llm_used: bool
    llm_note: str


class Taxonomy:
    def __init__(self, payload: Mapping[str, Any]):
        self.payload = dict(payload)
        self.sectors = list(payload.get("sectors", []))
        self.names = [str(item["name"]) for item in self.sectors]
        self.name_set = set(self.names)
        self.cross_sector_values = set(payload.get("cross_sector_values", []))
        self.weights = dict(payload.get("field_weights", {}))
        self.minimum_specific_score = float(payload.get("minimum_specific_score", 5.0))
        self.secondary_ratio = float(payload.get("secondary_score_ratio", 0.58))
        self.max_secondary = int(payload.get("maximum_secondary_sectors", 2))
        self.review_below = float(payload.get("manual_review_confidence_below", 0.55))
        self.alias_to_name: dict[str, str] = {}
        for item in self.sectors:
            self.alias_to_name[norm_key(item["name"])] = str(item["name"])
            for alias in item.get("aliases", []):
                self.alias_to_name[norm_key(alias)] = str(item["name"])

    def canonicalize(self, value: str) -> str | None:
        key = norm_key(value)
        if key in self.alias_to_name:
            return self.alias_to_name[key]
        for name in self.names:
            if key == norm_key(name):
                return name
        return None


def phrase_hits(text: str, aliases: Sequence[str], negatives: Sequence[str]) -> tuple[int, list[str]]:
    low = f" {norm_key(text)} "
    if not low.strip():
        return 0, []
    for negative in negatives:
        if norm_key(negative) and norm_key(negative) in low:
            return 0, []
    hits: list[str] = []
    for alias in aliases:
        a = norm_key(alias)
        if not a:
            continue
        if len(a) <= 3 and a.isalpha():
            matched = re.search(rf"\b{re.escape(a)}\b", low) is not None
        else:
            matched = a in low
        if matched:
            hits.append(alias)
    return len(hits), hits


def deterministic_scores(evidence: Mapping[str, str], taxonomy: Taxonomy) -> tuple[dict[str, float], dict[str, list[str]]]:
    scores: defaultdict[str, float] = defaultdict(float)
    reasons: defaultdict[str, list[str]] = defaultdict(list)
    for item in taxonomy.sectors:
        name = str(item["name"])
        aliases = list(item.get("aliases", []))
        negatives = list(item.get("negative", []))
        for field, text in evidence.items():
            count, hits = phrase_hits(text, aliases, negatives)
            if not count:
                continue
            weight = float(taxonomy.weights.get(field, taxonomy.weights.get("other", 1.0)))
            contribution = weight * min(count, 3)
            scores[name] += contribution
            reasons[name].append(f"{field}: {', '.join(hits[:4])}")
    return dict(scores), dict(reasons)


def broad_default(row: Mapping[str, Any], combined_text: str, taxonomy: Taxonomy) -> tuple[str, str]:
    text = norm_key(combined_text)
    kind = record_kind(row)
    finance_terms = ["credit guarantee", "fund of funds", "seed fund", "loan scheme", "bill discounting", "startup fund", "working capital"]
    innovation_terms = ["nidhi", "prayas", "entrepreneur in residence", "technology business incubator", "incubation", "accelerator", "startup ecosystem", "entrepreneurship"]
    if any(term in text for term in finance_terms) or kind in {"CREDIT_SUPPORT", "CREDIT_GUARANTEE", "FUND"}:
        return "Cross-sector MSME & Startup Finance", "broad financial instrument without an industry restriction"
    if any(term in text for term in innovation_terms) or kind in {"INCUBATION_SUPPORT", "FELLOWSHIP"}:
        return "Cross-sector Innovation & Entrepreneurship", "broad innovation/entrepreneurship support without an industry restriction"
    return "Sector Agnostic / Multi-sector", "no reliable industry-specific evidence; assigned explicit sector-agnostic category"


def confidence_from_scores(top: float, second: float, has_official: bool, used_existing: bool) -> float:
    if top <= 0:
        return 0.62
    margin = max(0.0, top - second)
    confidence = 0.50 + min(top / 30.0, 0.28) + min(margin / 30.0, 0.12)
    if has_official:
        confidence += 0.05
    if used_existing:
        confidence += 0.04
    return round(min(confidence, 0.97), 3)


def lm_studio_available(url: str, timeout: float = 1.2) -> bool:
    try:
        import requests
        base = url.split("/v1/", 1)[0] + "/v1/models"
        response = requests.get(base, timeout=timeout)
        return response.ok
    except Exception:
        return False


def lm_review(
    *, url: str, model: str, scheme_name: str, evidence: str,
    proposed: list[str], taxonomy: Taxonomy, timeout: int = 90,
) -> tuple[list[str] | None, float | None, str]:
    try:
        import requests
        prompt = {
            "task": "Verify sector classification for a Government startup/MSME support scheme.",
            "rules": [
                "Use only sectors from allowed_sectors.",
                "Sector describes the beneficiary industry/domain, not grant/loan/incubation support type.",
                "Use Cross-sector categories when the scheme applies across industries.",
                "Do not infer a narrow sector from the ministry or department name alone.",
                "Return strict JSON with primary_sector, secondary_sectors, confidence, reason."
            ],
            "scheme_name": scheme_name,
            "allowed_sectors": taxonomy.names,
            "proposed_sectors": proposed,
            "evidence": evidence[:14000],
        }
        response = requests.post(
            url,
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 550,
                "messages": [
                    {"role": "system", "content": "You are a conservative evidence-verification agent. Output JSON only."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return None, None, "LM_NO_JSON"
        parsed = json.loads(match.group(0))
        sectors = [parsed.get("primary_sector", ""), *list(parsed.get("secondary_sectors", []) or [])]
        canonical = [taxonomy.canonicalize(value) for value in sectors]
        canonical = [value for value in canonical if value]
        if not canonical:
            return None, None, "LM_INVALID_TAXONOMY"
        confidence = float(parsed.get("confidence", 0.0))
        reason = normalized(parsed.get("reason"))[:500]
        return list(dict.fromkeys(canonical)), max(0.0, min(confidence, 1.0)), reason or "LM_VERIFIED"
    except Exception as exc:
        return None, None, f"LM_ERROR:{type(exc).__name__}"


def classify_row(
    row: Mapping[str, Any], taxonomy: Taxonomy, *, allow_network: bool,
    use_lm: bool, lm_url: str, lm_model: str, delay: float,
) -> SectorResult:
    evidence = structured_evidence(row)
    fetched_urls: list[str] = []
    fetch_notes: list[str] = []
    if allow_network:
        for url, role in safe_urls(row):
            text, note = fetch_text(url)
            fetched_urls.append(url)
            fetch_notes.append(f"{url}::{note}")
            if text:
                evidence[role] = (evidence.get(role, "") + " " + text)[:MAX_TEXT]
            if delay > 0:
                time.sleep(delay)

    original = [taxonomy.canonicalize(item) for item in parse_list(row.get("sector"))]
    original = [item for item in original if item]
    scores, reasons = deterministic_scores(evidence, taxonomy)
    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    top_name, top_score = ranked[0] if ranked else ("", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    used_existing = False
    if original:
        existing_name = original[0]
        existing_score = scores.get(existing_name, 0.0)
        if existing_score >= max(2.5, top_score * 0.72):
            top_name, top_score = existing_name, max(existing_score, top_score)
            used_existing = True

    if top_score < taxonomy.minimum_specific_score:
        combined = " ".join(evidence.values())
        top_name, fallback_reason = broad_default(row, combined, taxonomy)
        top_score = max(top_score, 3.0)
        reasons.setdefault(top_name, []).append(fallback_reason)
        method = "CROSS_SECTOR_FALLBACK"
    else:
        method = "EXISTING_SECTOR_CONFIRMED" if used_existing else "DETERMINISTIC_EVIDENCE"

    secondary: list[str] = []
    for name, score in ranked:
        if name == top_name or name in taxonomy.cross_sector_values:
            continue
        if score >= max(taxonomy.minimum_specific_score, top_score * taxonomy.secondary_ratio):
            secondary.append(name)
        if len(secondary) >= taxonomy.max_secondary:
            break

    proposed = [top_name, *secondary]
    llm_used = False
    llm_note = "LM_NOT_REQUESTED"
    confidence = confidence_from_scores(top_score, second_score, bool(fetched_urls), used_existing)

    ambiguous = confidence < 0.72 or (len(ranked) > 1 and second_score >= top_score * 0.82)
    if use_lm and ambiguous:
        llm_sectors, lm_confidence, llm_note = lm_review(
            url=lm_url,
            model=lm_model,
            scheme_name=normalized(row.get("scheme_name")),
            evidence="\n".join(f"{key}: {value}" for key, value in evidence.items()),
            proposed=proposed,
            taxonomy=taxonomy,
        )
        if llm_sectors:
            llm_used = True
            proposed = llm_sectors[: 1 + taxonomy.max_secondary]
            top_name = proposed[0]
            secondary = proposed[1:]
            confidence = round(max(confidence, float(lm_confidence or 0.0)), 3)
            method = "LM_STUDIO_VERIFIED"

    evidence_bits = reasons.get(top_name, [])[:4]
    if llm_used and llm_note:
        evidence_bits.append(f"LM review: {llm_note}")
    if not evidence_bits:
        evidence_bits.append("controlled sector-agnostic fallback")
    review_required = confidence < taxonomy.review_below
    if original and original[0] != top_name and scores.get(original[0], 0) >= taxonomy.minimum_specific_score:
        review_required = True
        method = "SECTOR_CONFLICT_REVIEW"
        evidence_bits.append(f"original sector conflicted: {original[0]}")

    return SectorResult(
        master_id=normalized(row.get("master_id") or row.get("normalized_scheme_id")),
        scheme_name=normalized(row.get("scheme_name") or row.get("canonical_name")),
        original_sectors=original,
        primary_sector=top_name,
        secondary_sectors=secondary,
        all_sectors=[top_name, *secondary],
        confidence=confidence,
        method=method,
        review_required=review_required,
        evidence_summary="; ".join(evidence_bits)[:1500],
        scored_candidates={name: round(score, 2) for name, score in ranked[:8]},
        fetched_urls=fetched_urls,
        fetch_notes=fetch_notes,
        llm_used=llm_used,
        llm_note=llm_note,
    )


def discover_catalogue(root: Path, explicit: Path | None) -> Path:
    if explicit:
        path = explicit if explicit.is_absolute() else root / explicit
        if not path.exists():
            raise FileNotFoundError(f"Catalogue not found: {path}")
        return path
    default = root / DEFAULT_CATALOGUE
    if default.exists():
        return default
    candidates = sorted(
        (root / "data" / "catalogue_preview").glob("**/*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No catalogue CSV found under data/catalogue_preview")
    return candidates[0]


def validate(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]],
    results: Sequence[SectorResult], taxonomy: Taxonomy,
) -> dict[str, Any]:
    before_ids = [normalized(row.get("master_id") or row.get("normalized_scheme_id")) for row in before]
    after_ids = [normalized(row.get("master_id") or row.get("normalized_scheme_id")) for row in after]
    main_after = [row for row in after if is_visible_main_record(row)]
    missing = [normalized(row.get("scheme_name")) for row in main_after if not parse_list(row.get("sector"))]
    invalid: list[dict[str, Any]] = []
    for row in main_after:
        for value in parse_list(row.get("sector")):
            if value not in taxonomy.name_set:
                invalid.append({"master_id": row.get("master_id"), "sector": value})
    support_type_errors = []
    for row in main_after:
        for value in parse_list(row.get("sector")):
            if norm_key(value) in GENERIC_SUPPORT_TERMS:
                support_type_errors.append({"master_id": row.get("master_id"), "sector": value})
    checks = {
        "row_count_preserved": len(before) == len(after),
        "master_id_order_preserved": before_ids == after_ids,
        "all_visible_main_records_have_sector": not missing,
        "all_sector_values_in_taxonomy": not invalid,
        "no_support_type_used_as_sector": not support_type_errors,
        "one_result_per_input_row": len(results) == len(before),
    }
    return {
        "service_version": VERSION,
        "validated_at": utc_now(),
        "counts": {
            "input_rows": len(before),
            "output_rows": len(after),
            "visible_main_records": len(main_after),
            "records_missing_sector": len(missing),
            "invalid_sector_values": len(invalid),
            "manual_review_records": sum(1 for result in results if result.review_required),
            "network_enriched_records": sum(1 for result in results if result.fetched_urls),
            "lm_verified_records": sum(1 for result in results if result.llm_used),
        },
        "checks": checks,
        "missing_sector_scheme_names": missing,
        "invalid_sectors": invalid,
        "support_type_errors": support_type_errors,
        "validation_passed": all(checks.values()),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    catalogue = discover_catalogue(root, Path(args.input) if args.input else None)
    taxonomy_path = Path(args.taxonomy)
    taxonomy_path = taxonomy_path if taxonomy_path.is_absolute() else root / taxonomy_path
    output_dir = Path(args.output_dir)
    output_dir = output_dir if output_dir.is_absolute() else root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    taxonomy = Taxonomy(read_json(taxonomy_path))
    rows, original_fields = read_csv(catalogue)
    lm_mode = args.lm_studio
    use_lm = lm_mode == "on" or (lm_mode == "auto" and lm_studio_available(args.lm_url))

    results: list[SectorResult] = []
    enriched: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        result = classify_row(
            row,
            taxonomy,
            allow_network=args.allow_network,
            use_lm=use_lm,
            lm_url=args.lm_url,
            lm_model=args.lm_model,
            delay=args.delay,
        )
        results.append(result)
        updated = dict(row)
        updated["sector"] = list_cell(result.all_sectors)
        updated["primary_sector"] = result.primary_sector
        updated["secondary_sectors"] = list_cell(result.secondary_sectors)
        updated["sector_confidence"] = f"{result.confidence:.3f}"
        updated["sector_classification_method"] = result.method
        updated["sector_evidence"] = result.evidence_summary
        updated["sector_review_required"] = "true" if result.review_required else "false"
        updated["sector_verified_at"] = utc_now()
        updated["sector_agent_version"] = VERSION
        enriched.append(updated)
        if args.progress:
            print(f"[{index}/{len(rows)}] {result.scheme_name}: {result.primary_sector} ({result.confidence:.2f})")

    extra_fields = [
        "primary_sector", "secondary_sectors", "sector_confidence",
        "sector_classification_method", "sector_evidence",
        "sector_review_required", "sector_verified_at", "sector_agent_version",
    ]
    fields = list(original_fields)
    if "sector" not in fields:
        fields.append("sector")
    for field in extra_fields:
        if field not in fields:
            fields.append(field)

    enriched_path = output_dir / "catalogue_with_verified_sectors_v3_4_0_6.csv"
    atomic_write_csv(enriched_path, enriched, fields)

    audit_fields = [
        "master_id", "scheme_name", "original_sectors", "primary_sector",
        "secondary_sectors", "all_sectors", "confidence", "method",
        "review_required", "evidence_summary", "scored_candidates",
        "fetched_urls", "fetch_notes", "llm_used", "llm_note",
    ]
    audit_rows = []
    for result in results:
        payload = asdict(result)
        for field in ["original_sectors", "secondary_sectors", "all_sectors", "fetched_urls", "fetch_notes"]:
            payload[field] = list_json(payload[field])
        payload["scored_candidates"] = json.dumps(payload["scored_candidates"], ensure_ascii=False)
        audit_rows.append(payload)
    atomic_write_csv(output_dir / "sector_verification_audit_v3_4_0_6.csv", audit_rows, audit_fields)
    atomic_write_csv(
        output_dir / "sector_manual_review_queue_v3_4_0_6.csv",
        [row for row in audit_rows if str(row["review_required"]).casefold() == "true"],
        audit_fields,
    )

    distribution = Counter(result.primary_sector for row, result in zip(rows, results) if is_visible_main_record(row))
    dist_rows = [
        {"sector": sector, "record_count": count, "percentage": round(count * 100 / max(1, sum(distribution.values())), 2)}
        for sector, count in sorted(distribution.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    atomic_write_csv(output_dir / "sector_distribution_v3_4_0_6.csv", dist_rows, ["sector", "record_count", "percentage"])
    taxonomy_rows = [
        {"sector": item["name"], "aliases": "; ".join(item.get("aliases", [])), "is_cross_sector": item["name"] in taxonomy.cross_sector_values}
        for item in taxonomy.sectors
    ]
    atomic_write_csv(output_dir / "sector_taxonomy_v3_4_0_6.csv", taxonomy_rows, ["sector", "aliases", "is_cross_sector"])

    validation = validate(rows, enriched, results, taxonomy)
    validation["input_catalogue"] = str(catalogue)
    validation["enriched_catalogue"] = str(enriched_path)
    validation["network_allowed"] = bool(args.allow_network)
    validation["lm_studio_mode"] = lm_mode
    validation["lm_studio_used"] = use_lm

    backup_path = ""
    applied = False
    if args.apply:
        if not validation["validation_passed"]:
            raise RuntimeError("Validation failed; refusing to replace the dashboard catalogue")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = root / "backups" / "sector_verification_v3_4_0_6"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{catalogue.stem}_before_sector_agent_{stamp}{catalogue.suffix}"
        shutil.copy2(catalogue, backup)
        shutil.copy2(enriched_path, catalogue)
        backup_path = str(backup)
        applied = True

    summary = {
        "service_version": VERSION,
        "generated_at": utc_now(),
        "input_catalogue": str(catalogue),
        "output_directory": str(output_dir),
        "counts": validation["counts"],
        "primary_sector_distribution": dict(distribution),
        "methods": dict(Counter(result.method for result in results)),
        "validation_passed": validation["validation_passed"],
        "applied_to_dashboard_catalogue": applied,
        "backup_path": backup_path,
        "network_allowed": bool(args.allow_network),
        "lm_studio_used": use_lm,
        "outputs": {
            "enriched_catalogue": enriched_path.name,
            "audit": "sector_verification_audit_v3_4_0_6.csv",
            "review_queue": "sector_manual_review_queue_v3_4_0_6.csv",
            "distribution": "sector_distribution_v3_4_0_6.csv",
            "taxonomy": "sector_taxonomy_v3_4_0_6.csv",
            "validation": "sector_validation_v3_4_0_6.json",
        },
    }
    write_json(output_dir / "sector_validation_v3_4_0_6.json", validation)
    write_json(output_dir / "sector_summary_v3_4_0_6.json", summary)
    return summary


def self_test() -> int:
    taxonomy = Taxonomy(read_json(Path(__file__).resolve().parents[1] / "config" / "sector_taxonomy_v3_4_0_6.json"))
    samples = [
        ({"master_id": "1", "scheme_name": "NIDHI PRAYAS", "record_kind": "INCUBATION_SUPPORT", "objectives": "Supports innovators and startups from idea to prototype"}, "Cross-sector Innovation & Entrepreneurship"),
        ({"master_id": "2", "scheme_name": "Credit Guarantee Scheme for Startups", "record_kind": "CREDIT_GUARANTEE", "benefits": "credit guarantee for eligible startups across sectors"}, "Cross-sector MSME & Startup Finance"),
        ({"master_id": "3", "scheme_name": "Bio-AI Innovation Challenge", "record_kind": "GRANT", "objectives": "biotechnology, genomics and artificial intelligence innovation"}, "Biotechnology & Life Sciences"),
        ({"master_id": "4", "scheme_name": "AgriTech Innovation Fund", "record_kind": "FUND", "objectives": "farm mechanisation, crop and agriculture technology"}, "Agriculture & AgriTech"),
        ({"master_id": "5", "scheme_name": "General Startup Support Programme", "record_kind": "SCHEME_OR_PROGRAMME", "eligibility": "startups from all sectors may apply"}, "Sector Agnostic / Multi-sector"),
    ]
    checks: dict[str, bool] = {}
    for row, expected in samples:
        result = classify_row(row, taxonomy, allow_network=False, use_lm=False, lm_url="", lm_model="", delay=0)
        checks[f"{row['master_id']}_{expected}"] = result.primary_sector == expected
    checks["taxonomy_unique"] = len(taxonomy.names) == len(set(taxonomy.names))
    checks["cross_sector_present"] = taxonomy.cross_sector_values.issubset(taxonomy.name_set)
    passed = all(checks.values())
    print(json.dumps({"service_version": VERSION, "tests": checks, "self_test_passed": passed}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--project-root", default=".")
    value.add_argument("--input", help="Catalogue CSV path; auto-detected when omitted")
    value.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    value.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    value.add_argument("--allow-network", action="store_true", help="Fetch official pages for additional sector evidence")
    value.add_argument("--lm-studio", choices=["off", "auto", "on"], default="auto")
    value.add_argument("--lm-url", default=DEFAULT_LM_STUDIO_URL)
    value.add_argument("--lm-model", default="local-model")
    value.add_argument("--delay", type=float, default=0.35)
    value.add_argument("--apply", action="store_true", help="Back up and replace the active catalogue only after validation")
    value.add_argument("--progress", action="store_true")
    value.add_argument("--self-test", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.self_test:
        return self_test()
    try:
        summary = run(args)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["validation_passed"] else 2
    except Exception as exc:
        print(json.dumps({"service_version": VERSION, "error": str(exc), "error_type": type(exc).__name__}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
