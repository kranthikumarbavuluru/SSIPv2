from __future__ import annotations

from dataclasses import dataclass

from .common import canonical_key, clean, first, low, stable_id


@dataclass(frozen=True)
class CanonicalIdentity:
    scheme_master_id: str
    canonical_name: str
    official_abbreviation: str
    aliases: str
    historical_names: str
    department: str
    ministry: str
    scheme_family: str
    parent_scheme_id: str
    official_master_url: str
    identity_confidence: float
    identity_evidence: str
    identity_review_status: str


class CanonicalIdentityAgent:
    FAMILIES = (
        (("nidhi-prayas", "nidhi prayas", "prayas"), "NIDHI-PRAYAS", "NIDHI", "NIDHI"),
        (("startup india seed fund", "sisfs"), "Startup India Seed Fund Scheme", "SISFS", "Startup India"),
        (("credit guarantee scheme for startups", "cgss"), "Credit Guarantee Scheme for Startups", "CGSS", "Startup India"),
        (("nidhi seed support",), "NIDHI Seed Support Program", "NIDHI-SSP", "NIDHI"),
        (("entrepreneur-in-residence", "nidhi-eir", "nidhi eir"), "NIDHI Entrepreneur-in-Residence", "NIDHI-EIR", "NIDHI"),
    )

    def family(self, text: str) -> tuple[str, str, str]:
        value = low(text)
        for aliases, canonical, abbreviation, family in self.FAMILIES:
            if any(alias in value for alias in aliases):
                return canonical, abbreviation, family
        return "", "", ""

    def create_master(self, row: dict[str, str]) -> CanonicalIdentity:
        source_name = first(row, "canonical_name", "scheme_name", "title", "name")
        canonical, abbreviation, family = self.family(source_name)
        canonical = canonical or clean(source_name)
        existing_id = first(row, "scheme_master_id", "master_id")
        master_id = existing_id or stable_id("scheme", canonical, first(row, "official_page_url", "source_url"))
        review = "VERIFIED_EXISTING_ID" if existing_id and canonical else "IDENTITY_REVIEW_REQUIRED"
        confidence = 0.98 if existing_id and canonical else 0.72
        return CanonicalIdentity(
            master_id,
            canonical,
            abbreviation,
            source_name if canonical_key(source_name) != canonical_key(canonical) else "",
            first(row, "historical_names"),
            first(row, "department"),
            first(row, "ministry"),
            family or first(row, "scheme_family"),
            "",
            first(row, "official_master_url", "official_page_url", "source_url"),
            confidence,
            "Existing master ID and official title preserved." if existing_id else "Deterministic identity derived from a named official master page.",
            review,
        )

    def resolve_call_parent(self, row: dict[str, str], masters: list[dict[str, str]]) -> tuple[str, str]:
        text = f"{first(row, 'scheme_name', 'call_title', 'title')} {first(row, 'parent_scheme_name')}"
        canonical, _, _ = self.family(text)
        if canonical:
            wanted = canonical_key(canonical)
            for master in masters:
                if canonical_key(first(master, "canonical_name", "scheme_name")) == wanted:
                    return first(master, "scheme_master_id", "master_id"), "Matched permanent programme family."
        explicit = first(row, "parent_scheme_id")
        if explicit:
            return explicit, "Existing parent scheme ID preserved."
        return "", "No defensible parent identity; manual review required."
