from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_snapshot_text_recovery_v3_4_0_1_1.py"
SPEC = importlib.util.spec_from_file_location("dst_hotfix_34011", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_self_test_passes():
    result = MODULE.run_self_test()
    assert result["self_test_passed"] is True
    assert all(result["tests"].values())


def test_region_scoring_avoids_empty_main():
    html = b"""
    <html><head><title>Programme</title></head><body>
      <main></main>
      <div class='region-content'><h1>Programme Name</h1>
      <p>This is the official programme objective and eligibility information.</p></div>
    </body></html>
    """
    result = MODULE.extract_snapshot_text(html, "utf-8")
    assert result.status.startswith("SUCCESS")
    assert result.selected_selector != "main"
    assert "official programme objective" in result.main_text
    assert result.text_sha256 != MODULE.EMPTY_TEXT_SHA256


def test_call_supporting_page_not_scheme_identity():
    pattern = MODULE.classify_call_pattern(
        "Extension of last date for Call for Proposals",
        "The last date for submission has been extended.",
    )
    assert pattern == "DEADLINE_EXTENSION"


def test_document_and_external_classification():
    role = MODULE.derive_document_role(
        "scheme-guidelines-2026.pdf", "Download Guidelines", "https://dst.gov.in/scheme", "DOCUMENT"
    )
    assert role == "GUIDELINE"
    tier, recommendation = MODULE.classify_external_domain("onlinedst.gov.in", "GOVERNMENT_PORTAL")
    assert tier == "DST_RELATED_PORTAL"
    assert recommendation == "RECORD_AND_REVIEW"
