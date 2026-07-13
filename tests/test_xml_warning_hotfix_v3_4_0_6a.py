from __future__ import annotations
import importlib.util
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sector_verification_agent_v3_4_0_6.py"
spec = importlib.util.spec_from_file_location("sector_agent_hotfix", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_xml_input_emits_no_warning_and_extracts_text():
    xml = '<?xml version="1.0"?><urlset><url><loc>https://example.gov/scheme</loc></url></urlset>'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        text = module.strip_html(xml)
    assert "https://example.gov/scheme" in text
    assert caught == []
