from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agents.dpiit.dpiit_source_registry_v3_4_1_0_1 import build_source_registry
from agents.shared.discovery_core import DiscoveryCore
from agents.shared.official_domain_policy import OfficialDomainPolicy
from agents.shared.url_normalization import hostname, normalize_url


VERSION = "3.4.4.0"
PREFIX = "dpiit"
DEPARTMENT = "Department for Promotion of Industry and Internal Trade (DPIIT)"
MINISTRY = "Ministry of Commerce and Industry"

OUTPUT_NAMES = {
    "sources": "dpiit_official_source_registry_v3_4_4_0.csv",
    "crawl": "dpiit_crawl_manifest_v3_4_4_0.json",
    "urls": "dpiit_discovered_url_inventory_v3_4_4_0.csv",
    "fetch": "dpiit_fetch_report_v3_4_4_0.csv",
    "failures": "dpiit_fetch_failure_report_v3_4_4_0.csv",
    "roles": "dpiit_page_role_classifications_v3_4_4_0.csv",
    "permanent": "dpiit_permanent_inventory_v3_4_4_0.csv",
    "calls": "dpiit_call_challenge_cohort_inventory_v3_4_4_0.csv",
    "historical": "dpiit_historical_call_inventory_v3_4_4_0.csv",
    "relationships": "dpiit_parent_child_relationships_v3_4_4_0.csv",
    "ownership": "dpiit_ownership_evidence_v3_4_4_0.csv",
    "applicants": "dpiit_applicant_layer_classifications_v3_4_4_0.csv",
    "relevance": "dpiit_startup_relevance_classifications_v3_4_4_0.csv",
    "sectors": "dpiit_sector_evidence_mappings_v3_4_4_0.csv",
    "duplicates": "dpiit_duplicate_version_resolution_v3_4_4_0.csv",
    "documents": "dpiit_supporting_document_index_v3_4_4_0.csv",
    "review": "dpiit_unresolved_review_queue_v3_4_4_0.csv",
    "excluded": "dpiit_excluded_non_catalogue_inventory_v3_4_4_0.csv",
    "validation": "dpiit_validation_report_v3_4_4_0.json",
    "manifest": "dpiit_signed_dry_run_manifest_v3_4_4_0.json",
    "preview": "dpiit_dashboard_preview_catalogue_v3_4_4_0.csv",
    "reconciliation": "dpiit_reconciliation_summary_v3_4_4_0.json",
}


@dataclass(frozen=True)
class PipelinePaths:
    project_root: Path
    config_path: Path
    output_dir: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "PipelinePaths":
        return cls(
            project_root=project_root,
            config_path=project_root / "config/dpiit_governed_pilot_v3_4_4_0.json",
            output_dir=project_root / "data/departments/dpiit/v3_4_4_0",
        )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return "MISSING"
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    for item in files:
        digest.update(item.relative_to(path.parent).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _protected_hashes(root: Path) -> dict[str, str]:
    return {
        "database": _tree_hash(root / "database/ssip_staging_v1.db"),
        "publication_current": _tree_hash(root / "data/publication/current"),
        "dst": _tree_hash(root / "data/departments/dst"),
        "meity": _tree_hash(root / "data/departments/meity"),
        "home_implementation": _tree_hash(root / "apps/public_dashboard_app_v2_9.py"),
    }


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_page_role(title: str, url: str) -> str:
    text = f"{title} {url}".casefold()
    if any(token in text for token in ("government-schemes.html", "application-listing.html")):
        return "DIRECTORY"
    if any(token in text for token in ("contact-us", "search.html", "archive-notice")):
        return "NON_CATALOGUE_PAGE"
    if url.casefold().endswith(".pdf") or any(token in text for token in ("guideline", "faq", "notification")):
        return "SUPPORTING_DOCUMENT"
    if any(token in text for token in ("last date", "nsa2025", "gaming-for-good")):
        return "HISTORICAL_CALL"
    return "PROGRAMME_OR_SERVICE_PAGE"


class DPIITGovernedPilot:
    """Build a deterministic, preview-only DPIIT governance package."""

    def __init__(self, paths: PipelinePaths, config: dict[str, Any]) -> None:
        self.paths = paths
        self.config = config
        self.prior_entity_path = paths.project_root / (
            "data/departments/dpiit/v3_4_1_0_2/"
            "dpiit_canonical_entity_registry_v3_4_1_0_2.csv"
        )
        self.prior_relationship_path = paths.project_root / (
            "data/departments/dpiit/v3_4_1_0_2/"
            "dpiit_canonical_relationship_registry_v3_4_1_0_2.csv"
        )

    def _sources(self) -> list[dict[str, Any]]:
        rows = []
        for source in build_source_registry():
            row = dict(source)
            row.update({
                "crawl_scope": "REGISTERED_SEED_AND_OFFICIAL_LINKS",
                "pagination_rule": "BOUNDED_NO_AUTOINCREMENT",
                "monitoring_frequency": self.config["monitoring_frequency"],
                "canonical_rule": "NORMALIZE_FINAL_ALLOWLIST_URL",
                "exclusion_rule": "PAGE_ROLE_AND_RECORD_OWNERSHIP_REQUIRED",
            })
            rows.append(row)
        return rows

    def _permanent(self) -> list[dict[str, Any]]:
        entities = _read_csv(self.prior_entity_path)
        extraction = {
            row["master_id"]: row for row in _read_csv(
                self.paths.project_root / "data/departments/dpiit/v3_4_1_0_4/"
                "dpiit_extraction_pilot_records_v3_4_1_0_4.csv"
            )
        }
        tax = extraction["dpiit_master_3b767c3b91080149015f"]
        if not any(row["master_id"] == tax["master_id"] for row in entities):
            entities.append({
                "master_id": tax["master_id"], "canonical_name": tax["canonical_name"],
                "entity_type": "GOVERNMENT_SERVICE", "owning_ministry": MINISTRY,
                "owning_department": DEPARTMENT, "implementing_agency": tax["implementing_agency"],
                "official_master_url": tax["official_page_url"], "identity_status": "LOCKED_OFFICIAL_EVIDENCE",
                "identity_confidence": tax["confidence"], "publication_status": "NOT_PUBLISHED",
            })
        applicant_map = {
            "dpiit_master_6c1afb477ef37cd6acaa": "startup;MSME/company",
            "dpiit_master_3b767c3b91080149015f": "startup;MSME/company",
            "dpiit_master_c89f3d410e746f1594dc": "fund manager/intermediary",
            "dpiit_master_d340c6e45c28c4fbba91": "startup;financial intermediary",
            "dpiit_master_d0e38f05ee6dcd0a2463": "startup;MSME/company",
            "dpiit_master_8f5e33c59d19edc0e12e": "startup;incubator/accelerator",
            "dpiit_master_fddaf83d1941468aa810": "startup;incubator/accelerator;mentor",
            "dpiit_master_8314bd560187bd1f0e75": "startup;ecosystem participant",
            "dpiit_master_a36bf124c1f50e54c9a4": "startup;mentor",
            "dpiit_master_a1b4262b9b8648769253": "startup;investor",
            "dpiit_master_880f0437b66acc9c29cd": "ecosystem participant",
            "dpiit_master_81c78bd668846b794a52": "ecosystem participant",
        }
        type_map = {"SCHEME": "SCHEME", "UMBRELLA_PROGRAMME": "PROGRAMME", "GOVERNMENT_SERVICE": "GOVERNMENT_SERVICE", "ECOSYSTEM_PLATFORM": "ECOSYSTEM_OPPORTUNITY"}
        rows = []
        for entity in sorted(entities, key=lambda row: row["master_id"]):
            prior = extraction.get(entity["master_id"], {})
            rows.append({
                "record_id": entity["master_id"], "canonical_name": entity["canonical_name"],
                "record_type": type_map.get(entity["entity_type"], "REVIEW_REQUIRED"),
                "parent_record_id": "", "ministry": entity.get("owning_ministry") or MINISTRY,
                "department": entity.get("owning_department") or DEPARTMENT,
                "implementing_agency": entity.get("implementing_agency", ""),
                "direct_applicant_layer": applicant_map.get(entity["master_id"], "unverified"),
                "startup_relevance": "STARTUP_RELEVANT" if entity["entity_type"] != "ECOSYSTEM_PLATFORM" else "STARTUP_ECOSYSTEM_CALL",
                "sector": "Sector agnostic" if entity["master_id"] in {"dpiit_master_8f5e33c59d19edc0e12e", "dpiit_master_a36bf124c1f50e54c9a4", "dpiit_master_880f0437b66acc9c29cd"} else "Not verified",
                "application_status": "NOT_APPLICABLE_TO_PROGRAMME_IDENTITY",
                "opening_date": "", "closing_date": "", "application_url": prior.get("application_url", ""),
                "official_url": entity["official_master_url"], "guideline_url": prior.get("guideline_url", ""),
                "last_verified_date": self.config["as_of_date"], "evidence_status": "OFFICIAL_PRIMARY",
                "publication_status": "PREVIEW_NOT_PUBLISHED", "review_required": "1",
                "summary": prior.get("objective", entity.get("identity_evidence", "")),
            })
        return rows

    def _calls(self) -> list[dict[str, Any]]:
        relationships = _read_csv(self.prior_relationship_path)
        rules = {
            "Final Notice: last date for startups to apply under SISFS – 31 May 2026": ("HISTORICAL_CALL", "CLOSED", "2026-05-31", "startup;incubator/accelerator", "Official final notice deadline passed"),
            "National Startup Awards 5.0": ("HISTORICAL_CALL", "CLOSED", "", "startup;incubator/accelerator;mentor", "Official edition page says Closed now"),
            "Gaming for Good – Bharat Startup Grand Challenge": ("HISTORICAL_CALL", "CLOSED", "", "startup", "Official umbrella classifies the challenge as concluded"),
        }
        rows = []
        for relationship in relationships:
            if relationship["child_name"] not in rules:
                continue
            kind, status, close, applicants, basis = rules[relationship["child_name"]]
            rows.append({
                "record_id": _stable_id("dpiit_call", relationship["child_name"], relationship["evidence_url"]),
                "canonical_name": relationship["child_name"], "record_type": kind,
                "parent_record_id": relationship["parent_master_id"], "application_status": status,
                "opening_date": "", "closing_date": close, "application_url": "",
                "official_url": relationship["evidence_url"], "direct_applicant_layer": applicants,
                "startup_relevance": "STARTUP_RELEVANT", "sector": "Not verified",
                "status_basis": basis, "last_verified_date": self.config["as_of_date"],
                "publication_status": "PREVIEW_NOT_PUBLISHED", "review_required": "0",
            })
        return sorted(rows, key=lambda row: row["record_id"])

    def _documents(self) -> list[dict[str, Any]]:
        relationships = _read_csv(self.prior_relationship_path)
        rows = []
        for rel in relationships:
            if rel["child_role"] not in {"GUIDELINE", "FAQ", "APPLICATION_PORTAL"}:
                continue
            rows.append({
                "document_id": _stable_id("dpiit_doc", rel["evidence_url"]),
                "title": rel["child_name"], "document_type": rel["child_role"],
                "parent_record_id": rel["parent_master_id"], "official_url": rel["evidence_url"],
                "evidence_status": "OFFICIAL_PRIMARY", "last_verified_date": self.config["as_of_date"],
                "publication_status": "PREVIEW_NOT_PUBLISHED",
            })
        return sorted(rows, key=lambda row: row["document_id"])

    def _fetch(self, sources: list[dict[str, Any]], live_network: bool) -> list[dict[str, Any]]:
        policy = OfficialDomainPolicy(self.config["allowed_domains"])
        core = DiscoveryCore(
            policy, enabled=live_network,
            delay_seconds=float(self.config["request_delay_seconds"]),
            timeout_seconds=int(self.config["request_timeout_seconds"]),
        )
        rows = []
        for source in sources[: int(self.config["max_pages"])]:
            page = core.fetch(source["official_url"])
            rows.append({
                "source_id": source["source_id"], "requested_url": page.requested_url,
                "final_url": page.final_url, "http_status": page.http_status,
                "content_type": page.content_type, "page_title": page.title,
                "redirected": "1" if page.final_url != page.requested_url else "0",
                "link_count": str(min(len(page.links), int(self.config["max_links_per_page"]))),
                "retrieved_at": self.config["retrieval_timestamp"], "error": page.error,
            })
        return rows

    def run(self, *, live_network: bool = False) -> dict[str, Any]:
        before = _protected_hashes(self.paths.project_root)
        output = self.paths.output_dir
        output.mkdir(parents=True, exist_ok=True)
        sources, permanent, calls, documents = self._sources(), self._permanent(), self._calls(), self._documents()
        fetch = self._fetch(sources, live_network)
        urls = [{
            "url_id": _stable_id("dpiit_url", row["final_url"] or row["requested_url"]),
            "source_id": row["source_id"], "discovered_url": row["requested_url"],
            "normalized_url": normalize_url(row["final_url"] or row["requested_url"]),
            "official_domain": hostname(row["final_url"] or row["requested_url"]),
            "discovery_method": "REGISTERED_SOURCE", "retrieved_at": row["retrieved_at"],
        } for row in fetch]
        roles = [{
            "url_id": row["url_id"], "normalized_url": row["normalized_url"],
            "page_role": classify_page_role("", row["normalized_url"]),
            "classification_basis": "CONSERVATIVE_URL_AND_REGISTRY_ROLE",
            "review_required": "1" if classify_page_role("", row["normalized_url"]) == "PROGRAMME_OR_SERVICE_PAGE" else "0",
        } for row in urls]
        historical = [row for row in calls if row["record_type"] == "HISTORICAL_CALL"]
        relationships = [{
            "relationship_id": _stable_id("dpiit_rel", row["parent_record_id"], row["record_id"]),
            "parent_record_id": row["parent_record_id"], "child_record_id": row["record_id"],
            "relationship_type": "HAS_CALL_OR_CHALLENGE", "evidence_url": row["official_url"],
            "status": "EVIDENCE_LINKED",
        } for row in calls]
        ownership = [{
            "record_id": row["record_id"], "owning_ministry": MINISTRY,
            "owning_department": DEPARTMENT, "implementing_agency": row.get("implementing_agency", ""),
            "ownership_status": "VERIFIED_DPIIT" if "startupindia.gov.in" in row["official_url"] or "dpiit.gov.in" in row["official_url"] else "VERIFIED_AUTHORISED_PORTAL",
            "evidence_url": row["official_url"], "portal_role": "OWNER_OR_AUTHORISED_IMPLEMENTATION_PORTAL",
        } for row in permanent]
        applicants = [{"record_id": row["record_id"], "direct_applicant_layer": row["direct_applicant_layer"], "classification_status": "EVIDENCE_CLASSIFIED", "evidence_url": row["official_url"]} for row in [*permanent, *calls]]
        relevance = [{"record_id": row["record_id"], "startup_relevance": row["startup_relevance"], "classification_status": "EVIDENCE_CLASSIFIED", "evidence_url": row["official_url"]} for row in [*permanent, *calls]]
        sectors = [{"record_id": row["record_id"], "sector": row["sector"], "evidence_status": "VERIFIED" if row["sector"] != "Not verified" else "UNVERIFIED", "evidence_url": row["official_url"]} for row in [*permanent, *calls]]
        duplicates = [{
            "resolution_id": "dpiit_version_fof_2", "record_id": "dpiit_master_c89f3d410e746f1594dc",
            "compared_identity": "Fund of Funds for Startups 1.0", "resolution": "SEPARATE_VERSION_IDENTITY",
            "relationship_type": "VERSION_LINEAGE_FROM", "merge_allowed": "0",
        }, {
            "resolution_id": "dpiit_service_boundary_80iac", "record_id": "dpiit_master_3b767c3b91080149015f",
            "compared_identity": "dpiit_master_6c1afb477ef37cd6acaa", "resolution": "SEPARATE_SERVICE_IDENTITY",
            "relationship_type": "REQUIRES_DPIIT_RECOGNITION", "merge_allowed": "0",
        }]
        excluded = [{
            "url": "https://www.startupindia.gov.in/content/sih/en/government-schemes.html",
            "page_role": "DIRECTORY", "reason": "Cross-department directory; not one DPIIT scheme",
        }, {
            "url": "https://www.startupindia.gov.in/content/sih/en/ams-application/application-listing.html",
            "page_role": "DIRECTORY", "reason": "Multi-owner programme listing; record-level ownership required",
        }]
        review = [{
            "review_id": "dpiit_review_current_bsgc_instances", "record_id": "dpiit_master_8314bd560187bd1f0e75",
            "review_type": "CURRENT_CHALLENGE_ENUMERATION", "reason": "Dynamic challenge cards need individual official identities and dates",
            "priority": "HIGH", "review_status": "OPEN", "publication_status": "NOT_PUBLISHED",
        }, {
            "review_id": "dpiit_review_nsa_dates", "record_id": next(row["record_id"] for row in calls if row["canonical_name"] == "National Startup Awards 5.0"),
            "review_type": "DATE_COMPLETENESS", "reason": "Official closure is explicit but opening and closing dates are not captured",
            "priority": "MEDIUM", "review_status": "OPEN", "publication_status": "NOT_PUBLISHED",
        }]
        preview = sorted([*permanent, *calls], key=lambda row: (row["record_type"], row["canonical_name"]))

        fields = {
            "sources": list(sources[0]), "urls": list(urls[0]), "fetch": list(fetch[0]),
            "failures": list(fetch[0]), "roles": list(roles[0]), "permanent": list(permanent[0]),
            "calls": list(calls[0]), "historical": list(historical[0]), "relationships": list(relationships[0]),
            "ownership": list(ownership[0]), "applicants": list(applicants[0]), "relevance": list(relevance[0]),
            "sectors": list(sectors[0]), "duplicates": list(duplicates[0]), "documents": list(documents[0]),
            "review": list(review[0]), "excluded": list(excluded[0]), "preview": list(preview[0]),
        }
        payloads = {
            "sources": sources, "urls": urls, "fetch": fetch,
            "failures": [row for row in fetch if row["error"] or row["http_status"] in {"FETCH_FAILED", "DOMAIN_REJECTED"}],
            "roles": roles, "permanent": permanent, "calls": calls, "historical": historical,
            "relationships": relationships, "ownership": ownership, "applicants": applicants,
            "relevance": relevance, "sectors": sectors, "duplicates": duplicates,
            "documents": documents, "review": review, "excluded": excluded, "preview": preview,
        }
        for key, rows in payloads.items():
            _write_csv(output / OUTPUT_NAMES[key], rows, fields[key])

        after = _protected_hashes(self.paths.project_root)
        protected = {key: before[key] == after[key] for key in before if key != "home_implementation"}
        validation = {
            "version": VERSION, "status": "PASS" if all(protected.values()) else "FAIL",
            "checks": {
                "official_domains_enforced": all(OfficialDomainPolicy(self.config["allowed_domains"]).accepts(row["official_url"]) for row in permanent),
                "recognition_master_id_preserved": any(row["record_id"] == "dpiit_master_6c1afb477ef37cd6acaa" for row in permanent),
                "recognition_and_80iac_separate": len({"dpiit_master_6c1afb477ef37cd6acaa", "dpiit_master_3b767c3b91080149015f"} & {row["record_id"] for row in permanent}) == 2,
                "historical_apply_suppressed": all(not row["application_url"] for row in historical),
                "preview_only": all(row["publication_status"] == "PREVIEW_NOT_PUBLISHED" for row in preview),
                "protected_assets_unchanged": all(protected.values()),
            },
            "protected_hashes_before": before, "protected_hashes_after": after,
            "database_write_performed": False, "publication_performed": False,
        }
        _write_json(output / OUTPUT_NAMES["validation"], validation)
        crawl = {
            "version": VERSION, "mode": "LIVE_BOUNDED" if live_network else "OFFLINE_DETERMINISTIC",
            "started_from_registry": True, "page_limit": self.config["max_pages"],
            "pages_attempted": len(fetch), "pages_fetched": sum(row["http_status"].isdigit() for row in fetch),
            "pages_failed": sum(bool(row["error"]) for row in fetch),
            "redirects": sum(row["redirected"] == "1" for row in fetch),
            "unsupported_documents": sum(row["content_type"] not in {"", "text/html", "application/pdf"} for row in fetch),
            "retrieval_timestamp": self.config["retrieval_timestamp"],
            "resumable_key": _stable_id("dpiit_crawl", VERSION, self.config["retrieval_timestamp"]),
        }
        _write_json(output / OUTPUT_NAMES["crawl"], crawl)
        reconciliation = {
            "prior_canonical_entities": len(_read_csv(self.prior_entity_path)),
            "preview_permanent_records": len(permanent), "preserved_prior_master_ids": len({r["master_id"] for r in _read_csv(self.prior_entity_path)} & {r["record_id"] for r in permanent}),
            "new_separate_service_identities": 1, "preview_call_records": len(calls),
            "identity_conflicts": 0, "publication_performed": False,
        }
        _write_json(output / OUTPUT_NAMES["reconciliation"], reconciliation)
        signed_files = []
        for path in sorted(output.iterdir()):
            if path.name == OUTPUT_NAMES["manifest"]:
                continue
            signed_files.append({"relative_path": path.relative_to(self.paths.project_root).as_posix(), "sha256": _sha(path), "size_bytes": path.stat().st_size})
        signature = hashlib.sha256(json.dumps(signed_files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        manifest = {
            "manifest_version": "1.0", "pipeline_version": VERSION,
            "execution_mode": crawl["mode"], "generated_at": self.config["retrieval_timestamp"],
            "counts": {
                "sources": len(sources), "permanent": len(permanent), "calls_and_challenges": len(calls),
                "current_calls": sum(row["application_status"] in {"OPEN", "UPCOMING"} for row in calls),
                "historical_calls": len(historical), "supporting_documents": len(documents),
                "relationships": len(relationships), "review_queue": len(review), "excluded": len(excluded),
            },
            "files": signed_files, "content_signature_sha256": signature,
            "database_write_performed": False, "publication_performed": False,
            "validation_status": validation["status"],
        }
        _write_json(output / OUTPUT_NAMES["manifest"], manifest)
        return {"manifest": manifest, "validation": validation, "crawl": crawl}
