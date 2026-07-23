from __future__ import annotations

import unittest

from services.meity_historical_reconstruction_v3_4_3_7_8 import (
    ARCHIVE_RULES,
    EXCLUSION_RULES,
    EXPECTED_WITHDRAWN_IDS,
    REVIEW_RULES,
)


class MeitYHistoricalReconstructionTests(unittest.TestCase):
    def test_frozen_population_is_partitioned_once(self) -> None:
        archive = set(ARCHIVE_RULES)
        review = set(REVIEW_RULES)
        excluded = set(EXCLUSION_RULES)
        self.assertFalse(archive & review)
        self.assertFalse(archive & excluded)
        self.assertFalse(review & excluded)
        self.assertEqual(
            archive | review | excluded,
            set(EXPECTED_WITHDRAWN_IDS),
        )

    def test_expected_archive_review_and_exclusion_counts(self) -> None:
        self.assertEqual(len(ARCHIVE_RULES), 7)
        self.assertEqual(len(REVIEW_RULES), 0)
        self.assertEqual(len(EXCLUSION_RULES), 9)

    def test_historical_records_never_allow_apply(self) -> None:
        for rule in ARCHIVE_RULES.values():
            self.assertNotIn("application_url", rule)
            self.assertIn(
                rule["programme_type"],
                {
                    "GRAND_CHALLENGE",
                    "ACCELERATOR_COHORT",
                    "ACCELERATOR_PROGRAMME",
                    "HACKATHON",
                },
            )

    def test_permanent_scheme_identity_is_not_used_as_call(self) -> None:
        samridh = [
            rule for rule in ARCHIVE_RULES.values()
            if "SAMRIDH" in rule["canonical_title"].upper()
        ]
        self.assertEqual(len(samridh), 1)
        self.assertEqual(samridh[0]["canonical_title"], "SAMRIDH Cohort 2")


if __name__ == "__main__":
    unittest.main()
