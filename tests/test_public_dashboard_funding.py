from __future__ import annotations

import unittest
from types import SimpleNamespace

from ssip_dashboard.funding import format_inr, funding_summary, parse_amount


class PublicDashboardFundingTest(unittest.TestCase):
    def test_parse_amount_accepts_positive_structured_numbers(self) -> None:
        self.assertEqual(parse_amount("1,50,000"), 150000)
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("-5"))
        self.assertIsNone(parse_amount("not recorded"))

    def test_funding_summary_uses_structured_values_only(self) -> None:
        records = [
            SimpleNamespace(funding_minimum=10000, funding_maximum=50000),
            SimpleNamespace(funding_minimum=None, funding_maximum=None),
            SimpleNamespace(beneficiary_support_maximum=200000),
        ]
        summary = funding_summary(records)
        self.assertEqual(summary["minimum_recorded_funding"], 10000)
        self.assertEqual(summary["maximum_recorded_funding"], 200000)
        self.assertEqual(summary["records_with_funding"], 2)
        self.assertEqual(summary["records_missing_funding"], 1)

    def test_format_inr(self) -> None:
        self.assertEqual(format_inr(None), "Not recorded")
        self.assertEqual(format_inr(10000), "Rs 10,000")
        self.assertEqual(format_inr(500000), "Rs 5.00 Lakh")


if __name__ == "__main__":
    unittest.main()
