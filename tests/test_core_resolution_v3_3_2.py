from __future__ import annotations

import unittest

from ssip_agents.discovery.core_resolution_runner_v3_3_2 import (
    is_core_programme_url,
    kind_from_url_title,
    priority_for_candidate,
)


class CoreResolutionV332Test(unittest.TestCase):
    def test_core_programme_url_accepts_permanent_scheme_pages(self) -> None:
        self.assertTrue(
            is_core_programme_url(
                "https://www.nsic.co.in/Schemes/SinglePointRegistration",
                "Single Point Registration Scheme",
            )
        )
        self.assertTrue(
            is_core_programme_url(
                "https://www.startupindia.gov.in/content/sih/en/credit-guarantee-scheme-for-startups.html",
                "Credit Guarantee Scheme for Startups",
            )
        )

    def test_core_programme_url_rejects_supporting_evidence(self) -> None:
        self.assertFalse(
            is_core_programme_url(
                "https://www.startupindia.gov.in/content/dam/startupindia/Startup-Schemes-Playbook-June-2026.pdf",
                "Startup Schemes Playbook",
            )
        )
        self.assertFalse(
            is_core_programme_url(
                "https://www.myscheme.gov.in/sitemap.xml",
                "Sitemap",
            )
        )

    def test_priority_assignment_keeps_pdf_and_directory_out_of_validated_core_bucket(self) -> None:
        pdf_priority = priority_for_candidate(
            {
                "official_page_url": "https://example.gov.in/scheme.pdf",
                "normalized_record_kind": "SCHEME_OR_PROGRAMME",
                "scheme_name": "Scheme PDF",
            }
        )
        directory_priority = priority_for_candidate(
            {
                "official_page_url": "https://example.gov.in/schemes",
                "normalized_record_kind": "SCHEME_OR_PROGRAMME",
                "scheme_name": "Schemes",
                "validation_issues": "NON_CORE_INDEX_OR_SITEMAP_PAGE",
            }
        )

        self.assertEqual(pdf_priority[0], "P3_OFFICIAL_PDF_NEEDS_IDENTITY_CHECK")
        self.assertEqual(directory_priority[0], "P4_DIRECTORY_OR_INDEX")

    def test_record_kind_inference_for_credit_and_funding(self) -> None:
        self.assertEqual(
            kind_from_url_title(
                "https://www.startupindia.gov.in/content/sih/en/credit-guarantee-scheme-for-startups.html",
                "Credit Guarantee Scheme for Startups",
            ),
            "CREDIT_GUARANTEE",
        )
        self.assertEqual(
            kind_from_url_title(
                "https://www.nsic.co.in/Schemes/BillDiscountingAgainstBG",
                "Bill Discounting Scheme",
            ),
            "CREDIT_SUPPORT",
        )


if __name__ == "__main__":
    unittest.main()
