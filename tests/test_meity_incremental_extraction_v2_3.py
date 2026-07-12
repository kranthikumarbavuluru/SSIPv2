from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.extractor.field_extractor import EvidenceFirstFieldExtractor
from ssip_agents.extractor.html_parser import parse_html_document
from ssip_agents.extractor.meity_incremental_extraction_v2_3 import (
    MeityIncrementalExtractionV23,
)


SCHEME_NAMES = [
    "SAMRIDH",
    "TIDE 2.0",
    "SASACT",
    "GENESIS",
    "SITAA Challenge One",
    "SITAA Challenge Two",
]


def build_html(name: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head><title>{name}</title></head>
      <body>
        <main>
          <h1>{name}</h1>
          <h2>Objective</h2>
          <p>Support technology startups and innovators through structured assistance.</p>

          <h2>Eligibility Criteria</h2>
          <ul>
            <li>DPIIT-recognised technology startups incorporated in India may apply.</li>
            <li>The applicant must present a working prototype.</li>
          </ul>

          <h2>Benefits and Funding Support</h2>
          <p>Selected startups may receive grant support up to INR 20 lakh.</p>

          <h2>How to Apply</h2>
          <ol>
            <li>Register on the MeitY Startup Hub application portal.</li>
            <li>Submit the application before 31 December 2026.</li>
          </ol>
          <a href="/apply/{name.lower().replace(' ', '-')}">Apply Online</a>

          <h2>Documents Required</h2>
          <ul>
            <li>Certificate of incorporation</li>
            <li>DPIIT recognition certificate</li>
          </ul>
        </main>
      </body>
    </html>
    """


class FakeFetcher:
    def __init__(self, *, documents_by_url: dict[str, Any], **_: Any) -> None:
        self.documents_by_url = documents_by_url
        self.failures: list[Any] = []
        self.stats = {
            "cache_hits": 0,
            "network_fetches": 0,
            "browser_renders": 0,
            "pdf_documents": 0,
            "html_documents": 0,
            "fetch_failures": 0,
        }

    async def __aenter__(self) -> "FakeFetcher":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def fetch(
        self,
        *,
        url: str,
        title_hint: str = "",
        master_id: str | None = None,
        source: str | None = None,
        force_refresh: bool = False,
    ) -> Any:
        del title_hint, master_id, source, force_refresh
        self.stats["network_fetches"] += 1
        document = self.documents_by_url.get(url)
        if document is None:
            self.stats["fetch_failures"] += 1
            return None
        self.stats["html_documents"] += 1
        return document


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_master(index: int, name: str) -> dict[str, Any]:
    url = f"https://msh.meity.gov.in/schemes/test-{index}"
    return {
        "master_id": f"meity-{index}",
        "canonical_name": name,
        "source": "MeitY Startup Hub",
        "master_type": "SCHEME_OR_PROGRAMME",
        "readiness": "READY_FOR_EXTRACTION",
        "current_status": "SCHEME_INFORMATION_AVAILABLE",
        "official_page_url": url,
        "best_available_url": url,
        "best_relevance_score": 0.95,
        "supporting_documents": [],
        "active_calls": [],
    }


async def run_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ssip_meity_v2_3_") as temp_dir:
        root = Path(temp_dir)
        data_dir = root / "data"
        output_dir = root / "output"
        second_output_dir = root / "output_second"

        masters = [make_master(i, name) for i, name in enumerate(SCHEME_NAMES, start=1)]
        masters.append(
            {
                "master_id": "non-meity-master",
                "canonical_name": "Non-MeitY Scheme",
                "source": "DST",
                "readiness": "READY_FOR_EXTRACTION",
                "current_status": "SCHEME_INFORMATION_AVAILABLE",
                "best_available_url": "https://dst.gov.in/example",
            }
        )

        documents_by_url = {}
        for master in masters[:6]:
            url = master["best_available_url"]
            documents_by_url[url] = parse_html_document(
                url=url,
                html=build_html(master["canonical_name"]),
                http_status=200,
            )

        extractor = EvidenceFirstFieldExtractor(
            source_authorities={
                "MeitY Startup Hub": {
                    "ministry": "Ministry of Electronics and Information Technology",
                    "department": "Ministry of Electronics and Information Technology",
                    "implementing_agency": "MeitY Startup Hub",
                    "official_url": "https://msh.meity.gov.in/",
                    "evidence_note": "Test authority",
                    "confidence": 0.95,
                }
            }
        )

        unchanged_record = extractor.extract(
            master=masters[0],
            documents=[documents_by_url[masters[0]["best_available_url"]]],
        )
        incomplete_record = extractor.extract(
            master=masters[1],
            documents=[documents_by_url[masters[1]["best_available_url"]]],
        )
        incomplete_record["eligibility"] = []
        incomplete_record["quality_flags"] = sorted(
            set(incomplete_record["quality_flags"] + ["ELIGIBILITY_NOT_FOUND"])
        )

        non_meity_record = {
            "master_id": "non-meity-existing",
            "scheme_name": "Existing DST Scheme",
            "source": "DST",
            "official_page_url": "https://dst.gov.in/existing",
            "quality_flags": [],
            "extraction_confidence": 0.875,
            "source_evidence": [{"url": "https://dst.gov.in/existing", "source_hash": "dst-hash"}],
            "sentinel": "MUST_REMAIN_UNCHANGED",
        }

        masters_path = data_dir / "scheme_master_candidates_v1.json"
        existing_path = data_dir / "extracted_scheme_records_v1.json"
        write_json(masters_path, masters)
        write_json(existing_path, [unchanged_record, incomplete_record, non_meity_record])

        def fetcher_factory(**kwargs: Any) -> FakeFetcher:
            return FakeFetcher(documents_by_url=documents_by_url, **kwargs)

        agent = MeityIncrementalExtractionV23(
            project_root=root,
            fetcher_factory=fetcher_factory,
        )
        result = await agent.run(
            input_path=masters_path,
            existing_records_path=existing_path,
            output_dir=output_dir,
            publish_canonical=False,
        )

        assert result.summary["hotfix_version"] == "2.3.0"
        assert result.summary["meity_master_candidate_count"] == 6
        assert result.summary["output_meity_record_count"] == 6
        assert result.summary["output_record_count"] == 7
        assert result.summary["non_meity_records_preserved"] == 1
        assert result.summary["failure_count"] == 0
        assert result.summary["actions"] == {
            "REUSED_UNCHANGED": 1,
            "REEXTRACTED_INCOMPLETE": 1,
            "EXTRACTED_NEW": 4,
        }

        preserved = next(record for record in result.records if record.get("source") == "DST")
        assert preserved == non_meity_record

        assert (output_dir / "extracted_scheme_records_v2_3.json").exists()
        assert (output_dir / "meity_incremental_extraction_audit_v2_3.json").exists()
        assert (output_dir / "meity_incremental_extraction_failures_v2_3.json").exists()
        assert (output_dir / "meity_incremental_extraction_summary_v2_3.json").exists()

        # A second run against the v2.3 output must reuse every MeitY record.
        second_result = await agent.run(
            input_path=masters_path,
            existing_records_path=output_dir / "extracted_scheme_records_v2_3.json",
            output_dir=second_output_dir,
            publish_canonical=False,
        )
        assert second_result.summary["actions"] == {"REUSED_UNCHANGED": 6}
        assert second_result.summary["non_meity_records_preserved"] == 1
        assert second_result.summary["failure_count"] == 0

        print(json.dumps(result.summary, indent=2))
        print("MeitY Incremental Extraction v2.3 self-test passed.")


def main() -> None:
    asyncio.run(run_test())


if __name__ == "__main__":
    main()
