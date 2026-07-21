from __future__ import annotations

from agents.shared.page_role_classifier import ConservativePageRoleClassifier, PageRoleDecision


class DPIITPageRoleClassifier:
    def __init__(self) -> None:
        self.core = ConservativePageRoleClassifier()

    def classify(self, row: dict[str, str]) -> PageRoleDecision:
        return self.core.classify(
            url=row.get("normalized_url", row.get("discovered_url", "")),
            title=row.get("page_title", ""),
            candidate_name=row.get("candidate_name", ""),
            ownership_status=row.get("ownership_status", ""),
            source_type=row.get("source_type", ""),
        )

