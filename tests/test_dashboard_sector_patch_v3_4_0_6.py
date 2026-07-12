from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "patch_dashboard_sector_taxonomy_v3_4_0_6.py"
spec = importlib.util.spec_from_file_location("sector_patch", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_replacement_preserves_canonical_taxonomy():
    namespace = {"re": __import__("re")}
    exec(module.REPLACEMENT, namespace)
    normalize = namespace["normalize_sector"]
    assert normalize("Biotechnology & Life Sciences") == "Biotechnology & Life Sciences"
    assert normalize("Cross-sector Innovation & Entrepreneurship") == "Cross-sector Innovation & Entrepreneurship"
    assert normalize("Biotechnology") == "Biotechnology & Life Sciences"
    assert normalize("") == "Sector Not Specified"
