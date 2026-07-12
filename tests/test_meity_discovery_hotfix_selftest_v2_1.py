import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.meity_discovery_hotfix_v2_1 import (  # noqa: E402
    MeityDiscoveryHotfixV21,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "data").mkdir(parents=True)
        (root / "config").mkdir(parents=True)

        config = {
            "source_name": "MeitY Startup Hub",
            "official_domain": "msh.meity.gov.in",
            "bootstrap_pages": [
                {
                    "name": "SAMRIDH",
                    "url": "https://msh.meity.gov.in/schemes/samridh/",
                    "title": "SAMRIDH Scheme",
                    "description": "Official scheme page.",
                    "page_type": "SCHEME",
                    "bootstrap_score": 38.0,
                },
                {
                    "name": "TIDE 2.0",
                    "url": "https://msh.meity.gov.in/schemes/tide",
                    "title": "TIDE 2.0 Scheme",
                    "description": "Official scheme page.",
                    "page_type": "SCHEME",
                    "bootstrap_score": 38.0,
                },
            ],
            "navigation_pages": [],
            "discovery": {},
            "accepted_path_prefixes": ["/schemes/"],
            "accepted_document_extensions": [".pdf"],
        }
        config_path = root / "config" / "meity_discovery_hotfix_v2_1.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        hotfix = MeityDiscoveryHotfixV21(root, config_path=config_path)
        bootstrap = hotfix.build_bootstrap_candidates()
        assert len(bootstrap) == 2
        assert bootstrap[0]["url"] == "https://msh.meity.gov.in/schemes/samridh"

        existing = [
            {
                "url": "https://www.startupindia.gov.in/example",
                "source": "Startup India",
                "relevance_score": 10.0,
                "relevance_reasons": ["existing"],
                "title": "Existing scheme",
            },
            {
                "url": "https://msh.meity.gov.in/schemes/samridh",
                "source": "MeitY Startup Hub",
                "relevance_score": 5.0,
                "relevance_reasons": ["old"],
                "title": "",
            },
        ]
        merged = hotfix.merge_candidate_lists(existing, bootstrap)

        assert len(merged.records) == 3
        assert merged.added_count == 1
        assert merged.updated_count == 1
        assert len({item["url"] for item in merged.records}) == 3

        samridh = next(
            item
            for item in merged.records
            if item["url"] == "https://msh.meity.gov.in/schemes/samridh"
        )
        assert samridh["relevance_score"] == 38.0
        assert samridh["title"] == "SAMRIDH Scheme"
        assert "hotfix:official-meity-bootstrap-url" in samridh["relevance_reasons"]

        assert hotfix._accept_candidate(samridh)
        assert not hotfix._accept_candidate(
            {"url": "https://example.com/schemes/not-official"}
        )

    print("MeitY Discovery Hotfix self-test passed.")
    print("Bootstrap candidates: 2")
    print("Unique merged records: 3")
    print("Duplicate URLs: 0")


if __name__ == "__main__":
    main()
