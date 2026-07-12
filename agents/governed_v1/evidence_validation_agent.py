from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import first, hostname, load_json, trusted_hostname


@dataclass(frozen=True)
class EvidenceDecision:
    valid: bool
    trusted_domain: bool
    missing_fields: tuple[str, ...]
    reason: str


class EvidenceValidationAgent:
    def __init__(self, allowlist_path: Path) -> None:
        payload = load_json(allowlist_path)
        self.domains = payload.get("domains", [])
        self.authority_domains = payload.get("authority_domains", {})

    def validate(self, row: dict[str, str]) -> EvidenceDecision:
        url = first(row, "official_master_url", "official_page_url", "source_url")
        trusted = trusted_hostname(hostname(url), self.domains)
        required = {
            "scheme_master_id": first(row, "scheme_master_id", "master_id"),
            "canonical_name": first(row, "canonical_name", "scheme_name"),
            "official_source": url,
            "startup_beneficiary_evidence": first(row, "startup_beneficiary_evidence"),
            "startup_access_evidence": first(row, "startup_access_evidence"),
            "primary_sector": first(row, "primary_sector", "sector"),
        }
        missing = tuple(name for name, value in required.items() if not value)
        valid = trusted and not missing
        reason = "Official evidence gates passed." if valid else f"trusted_domain={trusted}; missing={','.join(missing) or 'none'}"
        return EvidenceDecision(valid, trusted, missing, reason)
