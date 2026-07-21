from __future__ import annotations

import argparse
from pathlib import Path


OLD_ADMIN_IMPORT = (
    "from services.admin_review_service_v1 import "
    "AdminReviewService  # noqa: E402"
)
NEW_ADMIN_IMPORT = (
    "from services.admin_review_service_v3_4_3_7_2 import "
    "AdminReviewService  # noqa: E402"
)

REGISTRY_IMPORT_MARKER = (
    "from services.meity_admin_bridge_v3_4_3_7_1 import "
    "MeitYAdminBridge, MeitYBridgePaths"
)
REGISTRY_NEW_IMPORT = """
from services.meity_identity_reconciliation_v3_4_3_7_2 import (
    MeitYLegacyIdentityReconciliationBridge,
    MeitYReconciliationPaths,
)
""".strip()

REGISTRY_RETURN_MARKER = "    return output\n\n\ndef get_intake("
REGISTRY_DESCRIPTOR_BLOCK = """
    reconciliation_map = (
        project_root
        / "data/departments/meity/v3_4_3_7_2/"
        "meity_legacy_identity_reconciliation_v3_4_3_7_2.csv"
    )
    if meity_queue.exists() and reconciliation_map.exists():
        output.append(
            IntakeDescriptor(
                provider_id="meity_v3_4_3_7_2",
                department=(
                    "Ministry of Electronics and Information Technology"
                ),
                version=(
                    "MeitY v3.4.3.7.2 Identity Reconciliation"
                ),
                source_path=str(reconciliation_map),
                description=(
                    "Reconciles the legacy rejected SASACT and GENESIS "
                    "aliases with their governed permanent-scheme "
                    "canonical identities. Legacy rejection history is "
                    "preserved; no current call or Apply route is asserted."
                ),
            )
        )

""".rstrip()

REGISTRY_RESOLVER_MARKER = (
    "    if provider_id == \"meity_v3_4_3_7\":\n"
    "        return MeitYAdminBridge("
    "MeitYBridgePaths.defaults(project_root, database_path))\n"
    "    raise KeyError"
)
REGISTRY_RESOLVER_REPLACEMENT = (
    "    if provider_id == \"meity_v3_4_3_7\":\n"
    "        return MeitYAdminBridge("
    "MeitYBridgePaths.defaults(project_root, database_path))\n"
    "    if provider_id == \"meity_v3_4_3_7_2\":\n"
    "        return MeitYLegacyIdentityReconciliationBridge(\n"
    "            MeitYReconciliationPaths.defaults("
    "project_root, database_path)\n"
    "        )\n"
    "    raise KeyError"
)


def patch_registry(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if REGISTRY_NEW_IMPORT not in text:
        if REGISTRY_IMPORT_MARKER not in text:
            raise RuntimeError(
                "MeitY v3.4.3.7.1 registry import marker not found."
            )
        text = text.replace(
            REGISTRY_IMPORT_MARKER,
            REGISTRY_IMPORT_MARKER + "\n" + REGISTRY_NEW_IMPORT,
            1,
        )

    if 'provider_id="meity_v3_4_3_7_2"' not in text:
        if REGISTRY_RETURN_MARKER not in text:
            raise RuntimeError(
                "Registry return marker not found."
            )
        text = text.replace(
            REGISTRY_RETURN_MARKER,
            REGISTRY_DESCRIPTOR_BLOCK
            + "\n"
            + REGISTRY_RETURN_MARKER,
            1,
        )

    if 'provider_id == "meity_v3_4_3_7_2"' not in text:
        if REGISTRY_RESOLVER_MARKER not in text:
            raise RuntimeError(
                "Registry provider resolver marker not found."
            )
        text = text.replace(
            REGISTRY_RESOLVER_MARKER,
            REGISTRY_RESOLVER_REPLACEMENT,
            1,
        )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_admin_ui(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if NEW_ADMIN_IMPORT not in text:
        if OLD_ADMIN_IMPORT not in text:
            raise RuntimeError(
                "AdminReviewService import marker not found."
            )
        text = text.replace(
            OLD_ADMIN_IMPORT,
            NEW_ADMIN_IMPORT,
            1,
        )

    assignment_old = (
        "    duplicate_candidates = "
        "service.duplicate_candidates(selected_id, record)\n"
    )
    assignment_new = (
        assignment_old
        + "    reconciled_aliases = "
        "service.reconciled_aliases(selected_id)\n"
    )
    if "reconciled_aliases = service.reconciled_aliases" not in text:
        if assignment_old not in text:
            raise RuntimeError(
                "Duplicate-candidate assignment marker not found."
            )
        text = text.replace(
            assignment_old,
            assignment_new,
            1,
        )

    warning_old = (
        "    if duplicate_candidates:\n"
        "        st.warning(\n"
        "            f\"{len(duplicate_candidates)} possible duplicate "
        "record(s) found. Review them before deciding.\"\n"
        "        )\n"
    )
    warning_new = (
        warning_old
        + "    if reconciled_aliases:\n"
        "        st.info(\n"
        "            f\"{len(reconciled_aliases)} legacy rejected "
        "identity record(s) are explicitly reconciled to this "
        "canonical ID. Their rejection and audit history remain "
        "preserved.\"\n"
        "        )\n"
    )
    if "legacy rejected identity record(s)" not in text:
        if warning_old not in text:
            raise RuntimeError(
                "Duplicate warning marker not found."
            )
        text = text.replace(
            warning_old,
            warning_new,
            1,
        )

    overview_old = (
        "        if duplicate_candidates:\n"
        "            st.markdown(\"#### Possible duplicates\")\n"
        "            st.dataframe(duplicate_candidates, "
        "use_container_width=True, hide_index=True)\n"
    )
    overview_new = (
        overview_old
        + "        if reconciled_aliases:\n"
        "            st.markdown("
        "\"#### Reconciled legacy identities\")\n"
        "            st.dataframe(reconciled_aliases, "
        "use_container_width=True, hide_index=True)\n"
    )
    if "#### Reconciled legacy identities" not in text:
        if overview_old not in text:
            raise RuntimeError(
                "Duplicate overview marker not found."
            )
        text = text.replace(
            overview_old,
            overview_new,
            1,
        )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(project_root: Path) -> None:
    registry = (
        project_root
        / "services/department_review_intake_v1.py"
    ).read_text(encoding="utf-8")
    admin_ui = (
        project_root
        / "ui/admin_review_app_v1.py"
    ).read_text(encoding="utf-8")

    registry_markers = (
        REGISTRY_NEW_IMPORT,
        'provider_id="meity_v3_4_3_7_2"',
        'provider_id == "meity_v3_4_3_7_2"',
    )
    ui_markers = (
        NEW_ADMIN_IMPORT,
        "reconciled_aliases = service.reconciled_aliases",
        "legacy rejected identity record(s)",
        "#### Reconciled legacy identities",
    )
    missing = [
        marker
        for marker in registry_markers
        if marker not in registry
    ] + [
        marker
        for marker in ui_markers
        if marker not in admin_ui
    ]
    if missing:
        raise RuntimeError(
            f"v3.4.3.7.2 patch validation failed: {missing}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not args.check:
        registry_changed = patch_registry(
            root / "services/department_review_intake_v1.py"
        )
        ui_changed = patch_admin_ui(
            root / "ui/admin_review_app_v1.py"
        )
        print(
            "Registry patch: "
            + ("APPLIED" if registry_changed else "ALREADY_APPLIED")
        )
        print(
            "Admin UI patch: "
            + ("APPLIED" if ui_changed else "ALREADY_APPLIED")
        )

    validate(root)
    print("SSIP v3.4.3.7.2 source patches: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

