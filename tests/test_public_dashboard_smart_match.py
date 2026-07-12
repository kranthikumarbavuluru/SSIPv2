from __future__ import annotations

import unittest
from types import SimpleNamespace

from ssip_dashboard.smart_match import MatchProfile, explainable_smart_match, score_record


def record(name, **kwargs):
    defaults = {
        "scheme_name": name,
        "target_beneficiaries": [],
        "eligibility": [],
        "sectors": [],
        "startup_stage": [],
        "geographic_scope": "",
        "funding_minimum": None,
        "funding_maximum": None,
        "application_status": "",
        "catalogue_section": "",
        "catalogue_inclusion": "",
        "opening_date": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class PublicDashboardSmartMatchTest(unittest.TestCase):
    def test_score_is_deterministic_and_explainable(self) -> None:
        scheme = record(
            "Biotech Seed Grant",
            target_beneficiaries=["Startups"],
            sectors=["Biotechnology"],
            startup_stage=["Prototype"],
            geographic_scope="National",
            funding_maximum=5000000,
            application_status="OPEN",
        )
        profile = MatchProfile(
            applicant_types=["Startups"],
            sectors=["Biotechnology"],
            startup_stages=["Prototype"],
            geographic_scope="India",
            funding_requirement=1000000,
        )
        result = score_record(scheme, profile)
        self.assertGreaterEqual(result.score, 90)
        self.assertIn("sector", result.matched_fields)
        self.assertIn("funding requirement", result.matched_fields)
        self.assertFalse(result.unmatched_requirements)

    def test_closed_records_are_excluded_by_default(self) -> None:
        records = [
            record("Closed Scheme", application_status="CLOSED", catalogue_section="CLOSED_OPPORTUNITIES"),
            record("Open Scheme", application_status="OPEN"),
        ]
        results = explainable_smart_match(records, MatchProfile())
        self.assertEqual([result.record.scheme_name for result in results], ["Open Scheme"])


if __name__ == "__main__":
    unittest.main()
