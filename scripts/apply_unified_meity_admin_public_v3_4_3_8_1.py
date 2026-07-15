from __future__ import annotations

import argparse
import ast
from pathlib import Path


ADMIN_NAV_OLD = (
    "from services.admin_workflow_navigation_v3_4_3_7_3 import ("
)
ADMIN_NAV_NEW = (
    "from services.admin_workflow_navigation_v3_4_3_8_1 import ("
)

ADMIN_IMPORT_ANCHOR = """from ssip_dashboard.dst_history import (  # noqa: E402
    RELEVANCE_ORDER,
    load_dst_historical_archive,
)
"""

ADMIN_EXTRA_IMPORTS = """
from ui.components.admin_quick_editor_v3_4_3_8_1 import (  # noqa: E402
    render_admin_quick_editor,
)
from ui.components.meity_admin_intelligence_v3_4_3_8_1 import (  # noqa: E402
    render_meity_admin_intelligence,
)
"""

ADMIN_ROUTE_OLD = """    if workspace == "Department Agent Intake":
        _render_agent_intake(st, service)
        return
    if workspace == "Publication Queue":
"""

ADMIN_ROUTE_NEW = """    if workspace == "Department Agent Intake":
        _render_agent_intake(st, service)
        return
    if workspace == "Quick Editor":
        render_admin_quick_editor(st, PROJECT_ROOT)
        return
    if workspace == "MeitY Intelligence Review":
        render_meity_admin_intelligence(st, PROJECT_ROOT)
        return
    if workspace == "Publication Queue":
"""

PUBLIC_IMPORT_ANCHOR = """from ssip_dashboard.meity_history import (
    MeitYHistoricalArchive,
    MeitYHistoricalRecord,
    load_meity_historical_archive,
)
"""

PUBLIC_EXTRA_IMPORT = """
from ssip_dashboard.meity_public_integrated_v3_4_3_8_1 import (
    render_integrated_meity_public_page,
)
"""

PUBLIC_FUNCTION_ANCHOR = (
    "def render_meity_page(bundle: CatalogueBundle) -> None:\n"
)

PUBLIC_FUNCTION_BODY = """def render_meity_page(bundle: CatalogueBundle) -> None:
    return render_integrated_meity_public_page(
        st=st,
        bundle=bundle,
        historical_archive=cached_meity_historical_archive(),
        page_intro=page_intro,
        metric_card=metric_card,
        public_record_card=public_record_card,
        published_call_filters=_render_published_call_filters,
        published_call_card=_published_call_card,
        render_historical_archive=render_meity_historical_archive,
    )

"""


def patch_admin(text: str) -> str:
    if ADMIN_NAV_NEW not in text:
        if ADMIN_NAV_OLD not in text:
            raise RuntimeError(
                "Admin navigation import anchor was not found."
            )
        text = text.replace(
            ADMIN_NAV_OLD,
            ADMIN_NAV_NEW,
            1,
        )

    if "render_admin_quick_editor" not in text:
        if ADMIN_IMPORT_ANCHOR not in text:
            raise RuntimeError(
                "Admin component import anchor was not found."
            )
        text = text.replace(
            ADMIN_IMPORT_ANCHOR,
            ADMIN_IMPORT_ANCHOR + ADMIN_EXTRA_IMPORTS,
            1,
        )

    if 'workspace == "Quick Editor"' not in text:
        if ADMIN_ROUTE_OLD not in text:
            raise RuntimeError(
                "Admin workspace route anchor was not found."
            )
        text = text.replace(
            ADMIN_ROUTE_OLD,
            ADMIN_ROUTE_NEW,
            1,
        )

    ast.parse(text)
    return text


def patch_public(text: str) -> str:
    if "render_integrated_meity_public_page" not in text:
        if PUBLIC_IMPORT_ANCHOR not in text:
            raise RuntimeError(
                "Public MeitY import anchor was not found."
            )
        text = text.replace(
            PUBLIC_IMPORT_ANCHOR,
            PUBLIC_IMPORT_ANCHOR + PUBLIC_EXTRA_IMPORT,
            1,
        )

    signature = (
        "return render_integrated_meity_public_page("
    )
    if signature not in text:
        if PUBLIC_FUNCTION_ANCHOR not in text:
            raise RuntimeError(
                "Public MeitY page function anchor was not found."
            )
        text = text.replace(
            PUBLIC_FUNCTION_ANCHOR,
            PUBLIC_FUNCTION_BODY,
            1,
        )

    text = text.replace(
        'APP_VERSION = "3.4.0.23-ui-final"',
        'APP_VERSION = "3.4.3.8.1-unified-meity"',
        1,
    )
    ast.parse(text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    admin_path = root / "ui/admin_review_app_v1.py"
    public_path = root / "apps/public_dashboard_app_v2_9.py"

    admin_before = admin_path.read_text(encoding="utf-8")
    public_before = public_path.read_text(encoding="utf-8")
    admin_after = patch_admin(admin_before)
    public_after = patch_public(public_before)

    if not args.validate_only:
        admin_path.write_text(admin_after, encoding="utf-8")
        public_path.write_text(public_after, encoding="utf-8")

    print(
        "SSIP v3.4.3.8.1 unified Admin/Public patch: "
        + ("VALIDATED" if args.validate_only else "APPLIED")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
