from __future__ import annotations

from ui.admin_review_app_v1 import build_edited_record, lines_to_list, parse_optional_int


def main() -> None:
    assert lines_to_list("One\n\nTwo ") == ["One", "Two"]
    assert parse_optional_int("2,000,000") == 2000000
    assert parse_optional_int("") is None

    original = {
        "master_id": "sample-1",
        "scheme_name": "Sample",
        "funding_amount": {
            "minimum": None,
            "maximum": None,
            "currency": "INR",
            "beneficiary_support": {"minimum": None, "maximum": None},
        },
    }
    values = {
        "scheme_name": "Updated Sample",
        "source": "DST",
        "official_page_url": "https://example.gov.in",
        "funding_maximum": "50,00,000",
        "beneficiary_maximum": "50,00,000",
        "currency": "INR",
        "eligibility": "Startup\nResearch institution",
        "parent_resolution": "STANDALONE_OFFICIAL_CALL",
        "source_evidence_urls": "https://example.gov.in\nhttps://example.gov.in/guidelines.pdf",
    }
    edited = build_edited_record(original, values)
    assert edited["scheme_name"] == "Updated Sample"
    assert edited["funding_amount"]["maximum"] == 5000000
    assert edited["eligibility"] == ["Startup", "Research institution"]
    assert edited["parent_resolution"] == "STANDALONE_OFFICIAL_CALL"
    assert [item["url"] for item in edited["source_evidence"]] == [
        "https://example.gov.in", "https://example.gov.in/guidelines.pdf"
    ]
    print("Admin review UI helper self-test passed.")
    print("Funding maximum: 5000000")


if __name__ == "__main__":
    main()
