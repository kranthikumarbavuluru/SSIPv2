from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.extractor.field_extractor import EvidenceFirstFieldExtractor
from ssip_agents.extractor.html_parser import parse_html_document


HTML = """
<!doctype html>
<html>
<head><title>Example Startup Seed Grant Scheme</title></head>
<body>
<main>
  <h1>Example Startup Seed Grant Scheme</h1>
  <h2>Objective</h2>
  <p>To help early-stage startups validate prototypes and commercialise innovations.</p>

  <h2>Eligibility Criteria</h2>
  <ul>
    <li>DPIIT-recognised startups incorporated in India may apply.</li>
    <li>The applicant must have a working prototype.</li>
  </ul>

  <h2>Benefits and Funding Support</h2>
  <p>Eligible startups may receive grant support up to INR 20 lakh.</p>

  <h2>How to Apply</h2>
  <ol>
    <li>Register on the application portal.</li>
    <li>Complete the online application before 31 December 2026.</li>
  </ol>
  <a href="/apply">Apply Online</a>

  <h2>Documents Required</h2>
  <ul>
    <li>Certificate of incorporation</li>
    <li>DPIIT recognition certificate</li>
  </ul>

  <h2>Contact</h2>
  <p>Email: help@example.gov.in Phone: +91-11-12345678</p>
</main>
</body>
</html>
"""


def main() -> None:
    document = parse_html_document(
        url="https://example.gov.in/scheme",
        html=HTML,
        http_status=200,
    )

    master = {
        "master_id": "example-master",
        "canonical_name": "Example Startup Seed Grant Scheme",
        "source": "Example Authority",
        "readiness": "READY_FOR_EXTRACTION",
        "current_status": "ACTIVE_CALL_OPEN",
        "official_page_url": "https://example.gov.in/scheme",
        "best_available_url": "https://example.gov.in/scheme",
        "supporting_documents": [],
        "active_calls": [
            {
                "url": "https://example.gov.in/scheme",
                "title": "Example Startup Seed Grant Scheme",
                "deadline": "2026-12-31",
            }
        ],
    }

    extractor = EvidenceFirstFieldExtractor(
        source_authorities={
            "Example Authority": {
                "ministry": "Example Ministry",
                "department": "Example Department",
                "implementing_agency": "Example Authority",
                "official_url": "https://example.gov.in/",
                "evidence_note": "Self-test configuration",
                "confidence": 0.9,
            }
        }
    )

    record = extractor.extract(master=master, documents=[document])

    assert record["scheme_name"] == "Example Startup Seed Grant Scheme"
    assert record["eligibility"], "Eligibility was not extracted"
    assert record["benefits"], "Benefits were not extracted"
    assert record["application_url"] == "https://example.gov.in/apply"
    assert record["funding_amount"]["maximum"] == 2_000_000
    assert record["closing_date"] == "2026-12-31"
    assert "Startups" in record["target_beneficiaries"]
    assert "Grant" in record["scheme_type"]
    assert record["required_documents"], "Required documents were not extracted"

    print("Extractor self-test passed.")
    print(f"Confidence: {record['extraction_confidence']}")
    print(f"Funding maximum: {record['funding_amount']['maximum']}")
    print(f"Closing date: {record['closing_date']}")
    print(f"Application URL: {record['application_url']}")


if __name__ == "__main__":
    main()
