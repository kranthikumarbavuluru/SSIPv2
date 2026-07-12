from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "dst_source_registry_and_crawler_v3_4_0_1.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("dst_crawler_v3401", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_self_test_passes():
    module = load_module()
    result = module.run_self_test()
    assert result["self_test_passed"], result


def test_call_title_is_not_scheme_identity():
    module = load_module()
    assert module.infer_role_hint(
        "https://dst.gov.in/callforproposals/tdp-2026",
        "Call for Project Proposals under Technology Development Programme",
        "CALL_INDEX_CURRENT",
    ) == "CALL_CANDIDATE"


def test_archive_pagination_is_preserved():
    module = load_module()
    normalized = module.normalize_url(
        "https://dst.gov.in/archive-call-for-proposals?utm_source=test&page=17#top"
    )
    assert normalized == "https://dst.gov.in/archive-call-for-proposals?page=17"
