from __future__ import annotations

import unittest
from types import SimpleNamespace

from ssip_dashboard.filters import FilterState, apply_filters


def record(name, **kwargs):
    defaults = {
        "scheme_name": name,
        "search_blob": name.casefold(),
        "ministry": "",
        "department": "",
        "implementing_agency": "",
        "sectors": [],
        "target_beneficiaries": [],
        "startup_stage": [],
        "scheme_types": [],
        "application_status": "",
        "catalogue_section": "",
        "catalogue_inclusion": "",
        "opening_date": "",
        "closing_date": "",
        "funding_minimum": None,
        "funding_maximum": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class PublicDashboardFiltersTest(unittest.TestCase):
    def test_keyword_sector_status_and_funding_filters(self) -> None:
        records = [
            record("Bio Grant", search_blob="bio grant biotechnology", sectors=["Biotechnology"], application_status="OPEN", funding_maximum=5000000),
            record("Digital Support", search_blob="digital support", sectors=["Digital Technology"], application_status="CLOSED", funding_maximum=100000),
        ]
        state = FilterState(
            keyword="bio",
            sectors=["Biotechnology"],
            statuses=["OPEN"],
            min_funding=1000000,
        )
        filtered = apply_filters(records, state)
        self.assertEqual([item.scheme_name for item in filtered], ["Bio Grant"])

    def test_closed_records_can_be_excluded(self) -> None:
        records = [
            record("Open", application_status="OPEN"),
            record("Closed", application_status="CLOSED", catalogue_section="CLOSED_OPPORTUNITIES"),
        ]
        filtered = apply_filters(records, FilterState(include_archived=False))
        self.assertEqual([item.scheme_name for item in filtered], ["Open"])


if __name__ == "__main__":
    unittest.main()
