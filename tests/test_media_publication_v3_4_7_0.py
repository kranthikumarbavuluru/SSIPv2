from __future__ import annotations

from pathlib import Path
import unittest

from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.catalogue_populations import split_catalogue_populations
from ssip_dashboard.media_supplement import load_active_media_publication


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MediaPublicationTests(unittest.TestCase):
    def test_active_bundle_has_two_published_media_calls(self) -> None:
        bundle = load_active_media_publication(PROJECT_ROOT)
        self.assertEqual(bundle.manifest["activation_status"], "ACTIVE")
        self.assertEqual(len(bundle.records), 2)
        self.assertEqual(
            {record["master_id"] for record in bundle.records},
            {
                "media_call_dst_nidhi_ignition_abes_2026",
                "media_call_ap_rtih_medtech_catalyst_2026",
            },
        )
        self.assertEqual(
            next(record for record in bundle.records if "Ignition" in record["scheme_name"])["parent_master_id"],
            "dst_programme_nidhi_itbi",
        )
        rtih = next(record for record in bundle.records if record["scheme_name"].startswith("RTIH"))
        self.assertIn("ITE&C", rtih["department"])
        self.assertEqual({record["application_status"] for record in bundle.records}, {"OPEN"})

    def test_catalogue_and_call_population_include_media_records(self) -> None:
        catalogue = load_catalogue(DashboardConfig.from_env(PROJECT_ROOT))
        media = [record for record in catalogue.records if record.master_id.startswith("media_call_")]
        self.assertEqual(len(media), 2)
        calls = split_catalogue_populations(catalogue.records).application_call_records
        self.assertTrue({record.master_id for record in media}.issubset({record.master_id for record in calls}))


if __name__ == "__main__":
    unittest.main()
