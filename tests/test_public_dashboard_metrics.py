from __future__ import annotations

import unittest
from itertools import count
from types import SimpleNamespace

from ssip_dashboard.funding import funding_bucket, funding_bucket_counts, parse_amount
from ssip_dashboard.metrics import compute_metrics, government_level, government_level_coverage, source_scope_lookup


_RECORD_IDS = count(1)


def record(**kwargs):
    defaults = {
        "ministry": "",
        "department": "",
        "implementing_agency": "",
        "source": "",
        "sectors": [],
        "scheme_types": [],
        "application_status": "",
        "catalogue_section": "",
        "catalogue_inclusion": "",
        "opening_date": "",
        "application_url": "",
        "guideline_urls": [],
        "funding_minimum": None,
        "funding_maximum": None,
        "master_id": f"metric-fixture-{next(_RECORD_IDS)}",
        "scheme_name": "Metric Fixture Scheme",
        "record_kind": "SCHEME_OR_PROGRAMME",
        "official_page_url": "https://example.gov.in/scheme",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class PublicDashboardMetricsTest(unittest.TestCase):
    def test_honest_metrics_keep_ministry_department_source_separate(self) -> None:
        records = [
            record(
                ministry="Ministry A",
                department="Department A",
                implementing_agency="Agency A",
                source="Source A",
                sectors=["Biotechnology"],
                scheme_types=["Grant"],
                application_status="OPEN",
                application_url="https://apply.example",
                guideline_urls=["https://manual.example/file.pdf"],
                funding_maximum=100000,
            ),
            record(source="Source B", catalogue_section="HISTORICAL_PROGRAMMES"),
        ]
        metrics = compute_metrics(records)
        self.assertEqual(metrics.total_catalogue_records, 2)
        self.assertEqual(metrics.total_explicit_ministries, 1)
        self.assertEqual(metrics.total_explicit_departments, 1)
        self.assertEqual(metrics.total_source_organisations, 2)
        self.assertEqual(metrics.open_records, 1)
        self.assertEqual(metrics.historical_records, 1)
        self.assertEqual(metrics.records_with_application_portals, 1)
        self.assertEqual(metrics.records_with_manuals_guidelines, 1)

    def test_funding_parser_supports_units_and_buckets(self) -> None:
        self.assertEqual(parse_amount("10 lakh"), 1000000)
        self.assertEqual(parse_amount("1.5 crore"), 15000000)
        self.assertEqual(parse_amount("2 million"), 2000000)
        self.assertEqual(funding_bucket(900000), "up_to_10_lakh")
        self.assertEqual(funding_bucket(15000000), "1_crore_to_10_crore")
        counts = funding_bucket_counts([record(funding_maximum=900000), record()])
        self.assertEqual(counts["up_to_10_lakh"], 1)
        self.assertEqual(counts["not_specified"], 1)

    def test_government_level_uses_deterministic_source_mapping(self) -> None:
        sources = [
            SimpleNamespace(scope="Central", name="Source A", agency="Agency A", department="", ministry=""),
            SimpleNamespace(scope="State/UT", name="", agency="State Agency", department="", ministry=""),
        ]
        lookup = source_scope_lookup(sources)
        self.assertEqual(government_level(record(source="Source A"), lookup), "Central Government")
        self.assertEqual(government_level(record(implementing_agency="State Agency"), lookup), "State Government")
        self.assertEqual(government_level(record(source="Unknown"), lookup), "Unspecified")
        coverage = government_level_coverage([record(source="Source A"), record(source="Unknown")], lookup)
        self.assertEqual(coverage["Central Government"], 1)
        self.assertEqual(coverage["Unspecified"], 1)


if __name__ == "__main__":
    unittest.main()
