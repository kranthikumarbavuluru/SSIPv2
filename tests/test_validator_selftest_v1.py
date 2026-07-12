from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.validator.scheme_validation_agent_v1 import SchemeValidationAgentV1


def main() -> None:
    sample = {
        "master_id": "sample-1",
        "scheme_name": "Sample Startup Grant Call",
        "source": "DST",
        "ministry": "Ministry of Science and Technology",
        "department": "Department of Science and Technology (DST)",
        "implementing_agency": "Department of Science and Technology (DST)",
        "scheme_type": ["Grant", "Loan"],
        "geographic_scope": "State / UT specific",
        "states_or_uts": ["Delhi"],
        "objectives": ["Support technology startups to commercialise innovations."],
        "eligibility": ["DPIIT-recognised Indian startups may apply."],
        "benefits": ["Grant support up to INR 20,00,000 per startup."],
        "application_process": ["Submit the online application through the official portal."],
        "selection_process": [],
        "required_documents": [],
        "application_url": "https://dst.gov.in/sample-apply",
        "official_page_url": "https://dst.gov.in/sample-call",
        "closing_date": None,
        "contact_details": [{"type": "phone", "value": "15-07-2026 04"}],
        "funding_amount": {
            "minimum": 2,
            "maximum": 20000000,
            "currency": "INR",
            "funding_types": ["Grant", "Loan"],
            "amount_mentions": [
                {
                    "amount": 20000000,
                    "display_text": "INR 20,00,000",
                    "context": "Grant support up to INR 20,00,000 per startup. Last date to apply: 31 July 2026.",
                    "source_url": "https://dst.gov.in/sample-call",
                },
                {
                    "amount": 2,
                    "display_text": "rs2",
                    "context": "List of 27 Champion Sectors2 Manufacturing Sectors",
                    "source_url": "https://dst.gov.in/sample-call",
                },
            ],
        },
        "source_evidence": [{"url": "https://dst.gov.in/sample-call"}],
        "field_evidence": {},
        "master_current_status": "ACTIVE_CALL_OPEN",
    }

    validator = SchemeValidationAgentV1(as_of_date=date(2026, 7, 8))
    result = validator.validate_record(sample)

    assert result["closing_date"] == "2026-07-31"
    assert result["funding_amount"]["maximum"] == 2_000_000
    assert result["geographic_scope"] == "National (India)"
    assert result["contact_details"] == []
    assert result["application_status"] == "OPEN"
    print("Validator self-test passed.")
    print("Decision:", result["validation"]["decision"])
    print("Score:", result["validation"]["validation_score"])
    print("Deadline:", result["closing_date"])
    print("Funding maximum:", result["funding_amount"]["maximum"])


if __name__ == "__main__":
    main()
