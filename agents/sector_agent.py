from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .common import LMStudioClient, content_hash, lower, norm
from .taxonomy import SectorTaxonomy

@dataclass
class SectorDecision:
    master_id: str
    record_hash: str
    primary_sector: str
    secondary_sectors: str
    confidence: float
    method: str
    evidence: str
    evidence_url: str
    review_required: bool
    reason: str
    candidates_json: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

class SectorVerificationAgent:
    def __init__(
        self,
        taxonomy: SectorTaxonomy,
        llm: LMStudioClient | None,
        deterministic_accept_score: int = 14,
        deterministic_margin: int = 6,
        llm_min_confidence: float = 0.82,
    ):
        self.taxonomy = taxonomy
        self.llm = llm
        self.deterministic_accept_score = deterministic_accept_score
        self.deterministic_margin = deterministic_margin
        self.llm_min_confidence = llm_min_confidence

    @staticmethod
    def _evidence_excerpt(text: str, phrases: list[str], max_chars: int = 420) -> str:
        clean = norm(text)
        low = clean.casefold()
        for phrase in phrases:
            idx = low.find(phrase.casefold())
            if idx >= 0:
                start = max(0, idx - 120)
                end = min(len(clean), idx + len(phrase) + 260)
                return clean[start:end]
        return clean[:max_chars]

    def _fallback_cross_sector(self, text: str) -> tuple[str, str] | None:
        t = lower(text)
        startup_terms = (
            "startup", "start-up", "entrepreneur", "innovation", "innovator",
            "incubat", "msme", "micro and small enterprises", "technology commercialization",
            "technology commercialisation"
        )
        finance_terms = ("loan", "credit", "guarantee", "working capital", "bill discount", "finance")
        if any(x in t for x in startup_terms):
            if any(x in t for x in finance_terms):
                return (
                    "Cross-sector MSME & Startup Finance",
                    "General startup/MSME finance evidence without a narrower industry restriction."
                )
            return (
                "Cross-sector Innovation & Entrepreneurship",
                "General innovation, incubation, entrepreneurship or startup support without a narrower industry restriction."
            )
        if any(x in t for x in ("all sectors", "sector agnostic", "multi-sector", "multiple sectors")):
            return ("Sector Agnostic / Multi-sector", "Official text indicates multi-sector or sector-agnostic coverage.")
        return None

    def _llm_prompt(self, record: dict[str, str], evidence_text: str, candidates: list[dict[str, Any]]) -> tuple[str, str]:
        taxonomy = [
            {"name": s.name, "description": s.description}
            for s in self.taxonomy.sectors
        ]
        system = (
            "You are the SSIP Sector Adjudicator. Classify a government startup scheme using only "
            "the supplied evidence and the exact controlled taxonomy. Do not guess. "
            "The evidence_quote must be copied verbatim from supplied evidence. "
            "Return JSON only with keys primary_sector, secondary_sectors, confidence, "
            "evidence_quote, reason, review_required. Use review_required=true when evidence conflicts "
            "or is insufficient. Never create a new label."
        )
        user = json.dumps({
            "record": record,
            "official_evidence": evidence_text[:18000],
            "controlled_taxonomy": taxonomy,
            "deterministic_candidates": candidates[:6],
        }, ensure_ascii=False)
        return system, user

    def _validate_llm(self, result: dict[str, Any], evidence_text: str) -> tuple[bool, str]:
        primary = norm(result.get("primary_sector"))
        secondary = result.get("secondary_sectors") or []
        if isinstance(secondary, str):
            secondary = [norm(x) for x in re.split(r"[;,|]", secondary) if norm(x)]
        labels = [primary] + [norm(x) for x in secondary]
        if not primary or not self.taxonomy.validate_labels(labels):
            return False, "LLM_RETURNED_INVALID_TAXONOMY"
        quote = norm(result.get("evidence_quote"))
        if quote and quote.casefold() not in norm(evidence_text).casefold():
            return False, "LLM_EVIDENCE_NOT_FOUND_VERBATIM"
        try:
            conf = float(result.get("confidence", 0))
        except Exception:
            return False, "LLM_CONFIDENCE_INVALID"
        if not (0 <= conf <= 1):
            return False, "LLM_CONFIDENCE_OUT_OF_RANGE"
        return True, ""

    def classify(
        self,
        record: dict[str, str],
        master_id: str,
        evidence_text: str,
        evidence_url: str,
    ) -> SectorDecision:
        record_hash = content_hash(master_id, json.dumps(record, sort_keys=True), evidence_text)
        combined = norm(" ".join([
            record.get("name",""), record.get("objective",""), record.get("eligibility",""),
            record.get("benefits",""), record.get("support_type",""),
            record.get("startup_stage",""), evidence_text
        ]))
        candidates = self.taxonomy.score(combined)
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else {"score": -999}
        margin = top["score"] - second["score"]

        if top["score"] >= self.deterministic_accept_score and margin >= self.deterministic_margin:
            phrases = top["strong_hits"] + top["weak_hits"]
            secondary = [
                item["sector"] for item in candidates[1:4]
                if item["score"] >= self.deterministic_accept_score
                and item["score"] >= top["score"] * 0.65
            ]
            confidence = min(0.98, 0.70 + top["score"] / 100 + margin / 100)
            return SectorDecision(
                master_id, record_hash, top["sector"], "; ".join(secondary),
                round(confidence, 3), "DETERMINISTIC_EVIDENCE",
                self._evidence_excerpt(combined, phrases), evidence_url,
                False, f"Top score {top['score']} with margin {margin}.",
                json.dumps(candidates[:6], ensure_ascii=False)
            )

        if self.llm and self.llm.available():
            system, user = self._llm_prompt(record, evidence_text, candidates)
            try:
                first = self.llm.complete_json(system, user, temperature=0.0)
                valid, error = self._validate_llm(first, evidence_text)
                if valid:
                    # Independent verifier pass. Agreement is mandatory.
                    verify_system = (
                        "You are an independent sector verification auditor. Review the proposed JSON "
                        "against the exact evidence and controlled taxonomy. Return JSON only with keys "
                        "accept, primary_sector, confidence, evidence_quote, reason. "
                        "Accept only when the evidence directly supports the proposed sector."
                    )
                    verify_user = json.dumps({
                        "proposal": first,
                        "evidence": evidence_text[:18000],
                        "taxonomy": self.taxonomy.names,
                    }, ensure_ascii=False)
                    second_pass = self.llm.complete_json(verify_system, verify_user, temperature=0.0)
                    agree = (
                        bool(second_pass.get("accept"))
                        and norm(second_pass.get("primary_sector")) == norm(first.get("primary_sector"))
                    )
                    conf = min(float(first.get("confidence", 0)), float(second_pass.get("confidence", 0)))
                    quote = norm(first.get("evidence_quote"))
                    if agree and conf >= self.llm_min_confidence:
                        secondary = first.get("secondary_sectors") or []
                        if isinstance(secondary, str):
                            secondary = [norm(x) for x in re.split(r"[;,|]", secondary) if norm(x)]
                        return SectorDecision(
                            master_id, record_hash, norm(first["primary_sector"]),
                            "; ".join(secondary), round(conf, 3), "LLM_DOUBLE_VERIFIED",
                            quote or self._evidence_excerpt(evidence_text, []), evidence_url,
                            False, norm(first.get("reason")),
                            json.dumps(candidates[:6], ensure_ascii=False)
                        )
            except Exception as exc:
                llm_error = f"{type(exc).__name__}: {exc}"
            else:
                llm_error = error if not valid else "LLM_VERIFIER_DISAGREED_OR_LOW_CONFIDENCE"
        else:
            llm_error = "LM_STUDIO_UNAVAILABLE"

        fallback = self._fallback_cross_sector(combined)
        if fallback:
            sector, reason = fallback
            return SectorDecision(
                master_id, record_hash, sector, "", 0.74, "GOVERNED_CROSS_SECTOR_FALLBACK",
                self._evidence_excerpt(combined, ["startup", "entrepreneur", "innovation", "msme"]),
                evidence_url, True, f"{reason} Review retained. {llm_error}",
                json.dumps(candidates[:6], ensure_ascii=False)
            )

        return SectorDecision(
            master_id, record_hash, "Sector Agnostic / Multi-sector", "", 0.50,
            "FAIL_CLOSED_REVIEW", self._evidence_excerpt(combined, []), evidence_url,
            True, f"No defensible domain-specific evidence. {llm_error}",
            json.dumps(candidates[:6], ensure_ascii=False)
        )
