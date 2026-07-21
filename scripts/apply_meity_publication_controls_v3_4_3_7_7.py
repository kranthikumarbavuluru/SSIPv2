from __future__ import annotations

import argparse
from pathlib import Path


HELPER = r"""
def call_specific_quality_gate(row: sqlite3.Row) -> GateResult:
    blockers: list[str] = []
    warnings: list[str] = []

    keys = set(row.keys())
    record_kind = str(
        row["record_kind"] if "record_kind" in keys else ""
    ).strip().upper()
    if record_kind not in {"APPLICATION_CALL", "CHALLENGE"}:
        return GateResult(True, [], [])

    title = str(row["scheme_name"] or "").strip()
    title_key = " ".join(
        re.sub(r"[^a-z0-9]+", " ", title.casefold()).split()
    )
    official_url = str(row["official_page_url"] or "").strip()
    application_status = str(
        row["application_status"]
        if "application_status" in keys
        else ""
    ).strip().upper()

    try:
        payload = json.loads(str(row["raw_record_json"] or "{}"))
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    if application_status in {
        "",
        "VERIFICATION_REQUIRED",
        "STATUS_UNVERIFIED",
        "OPEN_STATUS_REQUIRES_DEADLINE_VERIFICATION",
    }:
        blockers.append(
            "application call status is not sufficiently verified for publication"
        )

    generic_titles = {
        "challenges",
        "event partner",
        "organisationprofile",
        "organisation profile",
        "press release all",
        "g20diaoverview",
        "g20 dia overview",
    }
    if (
        title_key in generic_titles
        or ".pdf" in title.casefold()
        or "%20" in title.casefold()
    ):
        blockers.append(
            "application call identity is generic, encoded or filename-derived"
        )

    path = urlparse(official_url).path.casefold().rstrip("/")
    if path in {
        "/challenges",
        "/event-partner",
        "/organisationprofile",
        "/press-release-all",
    }:
        blockers.append(
            "official_page_url is a directory or listing page, not an individual call"
        )

    parent_resolution = str(
        payload.get("parent_resolution") or ""
    ).strip().upper()
    parent_id = str(payload.get("parent_master_id") or "").strip()
    if (
        parent_resolution in {"", "UNRESOLVED", "UMBRELLA_ONLY_REVIEW"}
        and not parent_id
    ):
        blockers.append(
            "call parent relationship is unresolved and not approved as standalone"
        )

    applicant_layer = str(
        payload.get("applicant_layer") or ""
    ).strip().upper()
    if applicant_layer in {
        "",
        "REQUIRES_ADMIN_VERIFICATION",
        "UNKNOWN",
    }:
        blockers.append(
            "call applicant layer is not verified"
        )

    status_basis = str(payload.get("status_basis") or "").strip()
    status_evidence = str(
        payload.get("status_evidence") or ""
    ).strip()
    if not status_basis or not status_evidence:
        blockers.append(
            "call status basis and evidence are required"
        )

    closing_date = str(
        payload.get("closing_date")
        or (row["closing_date"] if "closing_date" in keys else "")
    ).strip()

    if application_status == "OPEN":
        if not valid_http_url(row["application_url"]):
            blockers.append(
                "open call requires a verified application_url"
            )
        if not closing_date:
            blockers.append(
                "open call requires a verified closing date"
            )
    elif application_status == "UPCOMING":
        opening_date = str(
            payload.get("opening_date")
            or (row["opening_date"] if "opening_date" in keys else "")
        ).strip()
        if not opening_date or not closing_date:
            blockers.append(
                "upcoming call requires verified opening and closing dates"
            )
    elif application_status == "CLOSED":
        if not closing_date and not status_evidence:
            blockers.append(
                "closed call requires historical deadline or closure evidence"
            )
    elif application_status not in {
        "OPEN",
        "UPCOMING",
        "CLOSED",
    }:
        blockers.append(
            "application call has an unsupported publication status"
        )

    return GateResult(
        passed=not blockers,
        blockers=list(dict.fromkeys(blockers)),
        warnings=list(dict.fromkeys(warnings)),
    )
"""

CALL_HOOK = """
    call_gate = call_specific_quality_gate(row)
    blockers.extend(call_gate.blockers)
    warnings.extend(call_gate.warnings)
"""


def replace_once(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Patch marker not found: {label}")
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    original = text

    text = replace_once(
        text,
        "import json\n",
        "import json\nimport re\n",
        "regular expression import",
    )
    text = replace_once(
        text,
        '    "unpublish",\n',
        '    "unpublish",\n    "withdraw-publication",\n',
        "write action",
    )
    text = replace_once(
        text,
        '        "unpublish": {\n            "PUBLISHED": ("UNPUBLISHED", 0),\n        },\n',
        '        "unpublish": {\n            "PUBLISHED": ("UNPUBLISHED", 0),\n        },\n'
        '        "withdraw-publication": {\n'
        '            "PUBLISHED": ("UNPUBLISHED", 0),\n'
        '        },\n',
        "withdraw transition",
    )
    text = replace_once(
        text,
        '    if action == "unpublish":\n        return -1\n',
        '    if action in {"unpublish", "withdraw-publication"}:\n'
        '        return -1\n',
        "public delta",
    )
    text = replace_once(
        text,
        '    elif action == "unpublish":\n',
        '    elif action in {"unpublish", "withdraw-publication"}:\n',
        "withdraw update values",
    )
    text = replace_once(
        text,
        '        "unpublish": "UNPUBLISH",\n',
        '        "unpublish": "UNPUBLISH",\n'
        '        "withdraw-publication": "WITHDRAW_PUBLICATION",\n',
        "withdraw audit action",
    )

    helper_marker = "\ndef quality_gate(row: sqlite3.Row) -> GateResult:\n"
    if "def call_specific_quality_gate(" not in text:
        if helper_marker not in text:
            raise RuntimeError("Quality helper insertion marker not found")
        text = text.replace(
            helper_marker,
            "\n" + HELPER.rstrip() + "\n\n\ndef quality_gate(row: sqlite3.Row) -> GateResult:\n",
            1,
        )

    hook_marker = (
        '    if str(row["publication_status"] or "") '
        '!= "READY_FOR_PUBLICATION":\n'
    )
    if "call_gate = call_specific_quality_gate(row)" not in text:
        if hook_marker not in text:
            raise RuntimeError("Call-quality hook marker not found")
        text = text.replace(
            hook_marker,
            CALL_HOOK + "\n" + hook_marker,
            1,
        )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        '"withdraw-publication"',
        '"WITHDRAW_PUBLICATION"',
        'def call_specific_quality_gate(',
        'call_gate = call_specific_quality_gate(row)',
        'application call status is not sufficiently verified',
        'application call identity is generic, encoded or filename-derived',
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError(
            f"MeitY publication-control validation failed: {missing}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = (
        Path(args.project_root).resolve()
        / "scripts/publication_control_service_v2_7_3_4.py"
    )
    if not args.check:
        changed = patch(path)
        print(
            "MeitY publication-control patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print("SSIP v3.4.3.7.7 publication controls: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
