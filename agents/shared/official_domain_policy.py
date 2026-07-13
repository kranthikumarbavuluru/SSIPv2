from __future__ import annotations

from dataclasses import dataclass

from .url_normalization import hostname


@dataclass(frozen=True)
class DomainDecision:
    accepted: bool
    matched_domain: str
    reason: str


class OfficialDomainPolicy:
    def __init__(self, allowed_domains: list[str] | tuple[str, ...]) -> None:
        self.allowed_domains = tuple(sorted({d.casefold().strip(".") for d in allowed_domains}))

    def evaluate(self, url: str) -> DomainDecision:
        host = hostname(url)
        for domain in self.allowed_domains:
            if host == domain or host.endswith("." + domain):
                return DomainDecision(True, domain, "OFFICIAL_ALLOWLIST_MATCH")
        return DomainDecision(False, "", f"DOMAIN_NOT_ALLOWED:{host or 'MISSING'}")

    def accepts(self, url: str) -> bool:
        return self.evaluate(url).accepted

