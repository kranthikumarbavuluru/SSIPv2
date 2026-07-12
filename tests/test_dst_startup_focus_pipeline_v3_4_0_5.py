from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_startup_focus_pipeline_v3_4_0_5.py"
SPEC = importlib.util.spec_from_file_location("dst_startup_focus_3405", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads((Path(__file__).resolve().parents[1] / "config" / "dst_startup_focus_rules_v3_4_0_5.json").read_text(encoding="utf-8"))


def test_self_test_passes() -> None:
    result = MODULE.self_test()
    assert result["self_test_passed"] is True
    assert all(result["tests"].values())


def test_institution_programme_does_not_enter_startup_scheme() -> None:
    classification, score, _ = MODULE.page_role(
        "https://dst.gov.in/fist",
        "Fund for Improvement of S&T Infrastructure in Universities",
        "Universities and higher educational institutions are eligible for institutional infrastructure funding.",
        CONFIG,
    )
    assert classification == "REJECTED_NON_STARTUP"
    assert score < 50


def test_startup_beneficiary_and_access_are_required() -> None:
    classification, score, _ = MODULE.page_role(
        "https://nidhi.dst.gov.in/nidhissp/",
        "NIDHI Seed Support Program",
        "Potential startups may apply through supported incubators under periodic calls for seed funding and commercialisation.",
        CONFIG,
    )
    assert classification in {"DIRECT_STARTUP_SCHEME", "STARTUP_ACCESS_PROGRAMME"}
    assert score >= 75


def test_calls_are_separate() -> None:
    classification, _, _ = MODULE.page_role(
        "https://tdb.gov.in/call-for-proposal-startups",
        "Call for Proposals: Empowering Technology Startups",
        "DPIIT startups are invited to apply through the online portal for funding.",
        CONFIG,
    )
    assert classification == "STARTUP_CALL_INSTANCE"


def test_publish_replaces_all_dst_rows_with_verified_startup_rows(tmp_path: Path) -> None:
    fields = [
        "master_id", "normalized_scheme_id", "scheme_name", "canonical_name", "short_name", "source",
        "ministry", "department", "implementing_agency", "normalized_record_kind", "record_kind",
        "current_record_kind", "programme_status", "application_status", "scheme_status", "status_evidence",
        "sector", "sectors", "scheme_type", "scheme_types", "catalogue_inclusion", "catalogue_section",
        "current_decision", "validation_decision", "publication_status", "official_page_url", "application_url",
        "guideline_urls", "guideline_url", "opening_date", "closing_date", "funding_minimum", "funding_maximum",
        "currency", "objective", "objectives", "eligibility", "benefits", "funding_summary",
        "application_process", "required_documents", "last_verified_date", "last_updated", "verification_status",
        "information_completeness", "field_evidence"
    ]
    catalogue = tmp_path / CONFIG["catalogue_path"]
    catalogue.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"master_id": "other1", "scheme_name": "Other Scheme", "source": "DPIIT", "department": "DPIIT"},
        {"master_id": "dst1", "scheme_name": "Climate Change Programme", "source": "DST", "department": "Department of Science and Technology", "official_page_url": "https://dst.gov.in/climate-change-programme"},
        {"master_id": "dst2", "scheme_name": "FIST", "source": "DST", "department": "Department of Science and Technology", "official_page_url": "https://dst.gov.in/fist"},
    ]
    MODULE.write_csv(catalogue, fields, rows)
    output_dir = tmp_path / CONFIG["output_directory"]
    result = MODULE.publish(tmp_path, CONFIG, output_dir)
    assert result["publication_passed"] is True
    _, final_rows = MODULE.read_csv(catalogue)
    dst_rows = [r for r in final_rows if MODULE.is_dst_row(r)]
    assert len(dst_rows) == 7
    assert all(r["catalogue_section"] == "STARTUP_SCHEMES" for r in dst_rows)
    assert all(r["sector"] for r in dst_rows)
    assert all("universities" not in r["eligibility"].casefold() for r in dst_rows)
    assert any(r["scheme_name"] == "NIDHI – PRAYAS" for r in dst_rows)
    assert any(r["scheme_name"] == "Technology Development Board Core Funding" for r in dst_rows)


def test_dashboard_patch_adds_calls_and_ecosystem(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "public_dashboard_app_v2_9.py"
    app.parent.mkdir(parents=True)
    app.write_text(
        'from __future__ import annotations\n\nAPP_VERSION = "3.2.0"\nPAGES = [\n    "Home",\n    "Scheme Explorer",\n    "Official Sources",\n    "Directory",\n    "Scheme Details",\n]\n\ndef render_scheme_details(bundle):\n    pass\n\ndef main():\n    page = "Home"\n    if page == "Home":\n        pass\n    elif page == "Directory":\n        pass\n    elif page == "Scheme Details":\n        render_scheme_details(None)\n',
        encoding="utf-8",
    )
    result = MODULE.patch_dashboard(app, "data/departments/dst/v3_4_0_5")
    assert result["patched"] is True
    text = app.read_text(encoding="utf-8")
    assert '"Calls & Opportunities"' in text
    assert '"Incubators & Ecosystem"' in text
    assert "def render_calls_and_opportunities" in text
    assert "def render_startup_ecosystem" in text
    assert 'APP_VERSION = "3.4.0.5"' in text
