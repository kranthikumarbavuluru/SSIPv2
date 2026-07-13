from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from agents.shared.discovery_core import DiscoveryCore
from agents.shared.official_domain_policy import OfficialDomainPolicy
from agents.shared.url_normalization import hostname, normalize_url
from agents.shared.validation_core import stable_id

from .dpiit_identity_rules_v3_4_1_0_1 import alias_group, normalized_name
from .dpiit_ownership_rules_v3_4_1_0_1 import determine_ownership
from .dpiit_page_role_classifier_v3_4_1_0_1 import DPIITPageRoleClassifier


CANDIDATE_FIELDS = [
    "candidate_id", "source_id", "discovered_url", "normalized_url", "page_title",
    "candidate_name", "official_domain", "platform_host", "suspected_owner",
    "ownership_status", "page_role", "parent_candidate_id", "discovery_method",
    "http_status", "content_type", "is_official_domain", "duplicate_group_id",
    "discovery_timestamp", "classification_confidence", "classification_reasons",
    "review_required", "rejection_reason",
]


def candidate_name(title: str) -> str:
    return re.sub(r"\s*[|–—-]\s*(?:Startup India|DPIIT).*$", "", title.strip(), flags=re.I).strip() or title.strip()


class DPIITDiscoveryAgent:
    def __init__(self, sources: list[dict[str, str]], live: bool = False,
                 max_links_per_source: int = 25) -> None:
        self.sources = {row["source_id"]: row for row in sources}
        domains = sorted({row["official_domain"] for row in sources})
        self.policy = OfficialDomainPolicy(domains)
        self.core = DiscoveryCore(self.policy, enabled=live)
        self.live = live
        self.max_links_per_source = max_links_per_source
        self.classifier = DPIITPageRoleClassifier()

    def _live_seeds(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        seeds: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for source in sorted(self.sources.values(), key=lambda row: row["source_id"]):
            page = self.core.fetch(source["official_url"])
            seeds.append({
                "source_id": source["source_id"], "url": page.final_url or source["official_url"],
                "title": page.title or source["source_name"],
                "ownership_proven": hostname(source["official_url"]).endswith("dpiit.gov.in"),
                "http_status": page.http_status, "content_type": page.content_type,
                "discovery_method": "LIVE_REGISTERED_SOURCE",
            })
            if page.error:
                failures.append({"source_id": source["source_id"], "url": source["official_url"], "reason": page.error})
            for target, anchor in page.links[: self.max_links_per_source]:
                seeds.append({
                    "source_id": source["source_id"], "url": target,
                    "title": anchor or target.rsplit("/", 1)[-1],
                    "ownership_proven": hostname(target).endswith("dpiit.gov.in"),
                    "http_status": "DISCOVERED_NOT_FETCHED", "content_type": "",
                    "discovery_method": "LIVE_REGISTERED_SOURCE_LINK",
                })
        return seeds, failures

    def discover(self, preview_seeds: list[dict[str, Any]], as_of: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        seeds, failures = self._live_seeds() if self.live else (preview_seeds, [])
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rejected_preclassification: list[dict[str, str]] = []
        for seed in seeds:
            source = self.sources.get(str(seed.get("source_id", "")))
            url = str(seed.get("url", ""))
            normalized = normalize_url(url, source["official_url"] if source else "")
            decision = self.policy.evaluate(normalized)
            if not source or not decision.accepted:
                rejected_preclassification.append({"source_id": str(seed.get("source_id", "")), "url": url, "reason": decision.reason})
                continue
            grouped[normalized].append(seed)

        rows: list[dict[str, str]] = []
        for normalized, variants in sorted(grouped.items()):
            seed = sorted(variants, key=lambda item: (str(item.get("source_id", "")), str(item.get("url", ""))))[0]
            source = self.sources[str(seed["source_id"])]
            title = str(seed.get("title", "")).strip() or source["source_name"]
            owner = determine_ownership(normalized, source, bool(seed.get("ownership_proven", False)))
            duplicate_group = stable_id("dupurl", normalized) if len(variants) > 1 else ""
            row = {
                "candidate_id": stable_id("dpiit_candidate", normalized),
                "source_id": source["source_id"],
                "discovered_url": str(seed.get("url", normalized)),
                "normalized_url": normalized,
                "page_title": title,
                "candidate_name": candidate_name(title),
                "official_domain": hostname(normalized),
                "platform_host": source["platform_host"],
                "suspected_owner": owner.suspected_owner,
                "ownership_status": owner.ownership_status,
                "page_role": "",
                "parent_candidate_id": "",
                "discovery_method": str(seed.get("discovery_method", "GOVERNED_REGISTRY_SEED")),
                "http_status": str(seed.get("http_status", "PREVIEW_NOT_FETCHED")),
                "content_type": str(seed.get("content_type", "")),
                "is_official_domain": "1",
                "duplicate_group_id": duplicate_group,
                "discovery_timestamp": as_of,
                "classification_confidence": "",
                "classification_reasons": owner.reason,
                "review_required": "0",
                "rejection_reason": "",
                "source_type": source["source_type"],
                "parent_name": str(seed.get("parent_name", "")),
                "service_review": "1" if seed.get("service_review") else "0",
            }
            classification = self.classifier.classify(row)
            row["page_role"] = classification.role
            row["classification_confidence"] = f"{classification.confidence:.2f}"
            row["classification_reasons"] = ";".join((owner.reason, *classification.reasons))
            if classification.role == "NON_SCHEME":
                row["rejection_reason"] = classification.reasons[0]
            rows.append(row)

        by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            group_name = alias_group(row["candidate_name"]) or normalized_name(row["candidate_name"])
            if group_name:
                by_name[normalized_name(group_name)].append(row)
        for name_rows in by_name.values():
            unique_urls = {row["normalized_url"] for row in name_rows}
            if len(unique_urls) > 1:
                group_id = stable_id("dupidentity", *sorted(unique_urls))
                for row in name_rows:
                    row["duplicate_group_id"] = row["duplicate_group_id"] or group_id

        parent_by_name: dict[str, str] = {}
        for row in rows:
            if row["page_role"] in {"SCHEME_MASTER", "UMBRELLA_PROGRAMME"}:
                parent_by_name[normalized_name(row["candidate_name"])] = row["candidate_id"]
        for row in rows:
            parent_name = row.pop("parent_name", "")
            service_review = row.pop("service_review", "0")
            if parent_name:
                row["parent_candidate_id"] = parent_by_name.get(normalized_name(parent_name), "")
            review_reasons = []
            if row["ownership_status"] == "NEEDS_VERIFICATION":
                review_reasons.append("OWNERSHIP_UNRESOLVED")
            if row["page_role"] in {"AWARD_EDITION", "CHALLENGE_INSTANCE", "APPLICATION_CALL", "ARCHIVED_PAGE"}:
                review_reasons.append("TEMPORARY_OR_HISTORICAL_IDENTITY")
            if row["page_role"] == "APPLICATION_PORTAL" and not row["parent_candidate_id"]:
                review_reasons.append("APPLICATION_PORTAL_WITHOUT_PARENT")
            if row["page_role"] in {"GUIDELINE", "FAQ"} and not row["parent_candidate_id"]:
                review_reasons.append("SUPPORTING_PAGE_WITHOUT_PARENT")
            if row["duplicate_group_id"]:
                review_reasons.append("DUPLICATE_OR_ALIAS_GROUP")
            if service_review == "1":
                review_reasons.append("SERVICE_VERSUS_SCHEME_REVIEW")
            if row["rejection_reason"]:
                review_reasons = []
            row["review_required"] = "1" if review_reasons else "0"
            if review_reasons:
                row["classification_reasons"] += ";" + ";".join(review_reasons)
        return rows, failures + rejected_preclassification
