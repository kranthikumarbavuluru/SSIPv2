from __future__ import annotations

import unittest

from ssip_agents.discovery.batch1_actual_runner_v3_3_1 import (
    deduplicate_preview_rows,
    is_core_catalogue_page,
)


class Batch1ActualV331Test(unittest.TestCase):
    def test_sitemap_and_index_pages_are_not_core_catalogue_pages(self) -> None:
        self.assertFalse(
            is_core_catalogue_page(
                "https://www.myscheme.gov.in/sitemap.xml",
                "Sitemap.xml",
                "SCHEME",
            )
        )
        self.assertFalse(
            is_core_catalogue_page(
                "https://example.gov.in/schemes/search",
                "Schemes Search",
                "SCHEME",
            )
        )
        self.assertFalse(
            is_core_catalogue_page(
                "https://example.gov.in/schemes",
                "Schemes",
                "SCHEME",
            )
        )
        self.assertFalse(
            is_core_catalogue_page(
                "https://example.gov.in/startup-schemes-playbook.pdf",
                "Startup Schemes Playbook.pdf",
                "SCHEME",
            )
        )
        self.assertTrue(
            is_core_catalogue_page(
                "https://example.gov.in/credit-guarantee-scheme",
                "Credit Guarantee Scheme",
                "CREDIT_GUARANTEE",
            )
        )

    def test_preview_deduplication_prefers_included_scheme_records(self) -> None:
        rows = [
            {
                "master_id": "m1",
                "scheme_name": "Older Review Record",
                "normalized_record_kind": "APPLICATION_CALL",
                "catalogue_inclusion": "PENDING_REVALIDATION",
            },
            {
                "master_id": "m1",
                "scheme_name": "Included Scheme Record",
                "normalized_record_kind": "SCHEME_OR_PROGRAMME",
                "catalogue_inclusion": "INCLUDED",
                "official_page_url": "https://example.gov.in/scheme",
            },
        ]

        deduped, duplicates = deduplicate_preview_rows(rows)

        self.assertEqual(duplicates, 1)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["scheme_name"], "Included Scheme Record")


if __name__ == "__main__":
    unittest.main()
