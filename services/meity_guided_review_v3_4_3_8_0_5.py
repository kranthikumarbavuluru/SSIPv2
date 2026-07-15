from __future__ import annotations

from typing import Any


PLAIN_ACTION_LABELS = {
    "PENDING": "Choose an action",
    "CONFIRM_HISTORICAL": "Confirm as a historical reference",
    "CONFIRM_PROGRAMME_IDENTITY": "Confirm the programme identity",
    "CONFIRM_NEW_PROGRAMME_FOR_STAGING_REVIEW": (
        "Confirm as a new programme for later staging review"
    ),
    "CONFIRM_CALL_AND_PARENT": "Confirm the call or challenge and its parent",
    "CONFIRM_CURRENT_CALL_EVIDENCE_COMPLETE": (
        "Confirm the current opportunity evidence"
    ),
    "CONFIRM_REVIEW_CLASSIFICATION": "Confirm this classification",
    "NEEDS_MORE_EVIDENCE": "Needs more official evidence",
    "DEFER": "Review this later",
    "REJECT_CLASSIFICATION": "Reject this classification",
}

PLAIN_ACTION_HELP = {
    "CONFIRM_HISTORICAL": (
        "Use when the official page is a past result, closed cohort or "
        "historical reference."
    ),
    "CONFIRM_PROGRAMME_IDENTITY": (
        "Use when the official source clearly confirms the permanent "
        "programme name and identity."
    ),
    "CONFIRM_NEW_PROGRAMME_FOR_STAGING_REVIEW": (
        "Use when the programme identity is clear, but it still requires the "
        "separate staging and publication process."
    ),
    "CONFIRM_CALL_AND_PARENT": (
        "Use when the call or challenge identity and its parent programme are "
        "both supported by official evidence."
    ),
    "CONFIRM_CURRENT_CALL_EVIDENCE_COMPLETE": (
        "Use only when the current deadline and official application route "
        "are both verified."
    ),
    "CONFIRM_REVIEW_CLASSIFICATION": (
        "Use when the displayed classification matches the official source."
    ),
    "NEEDS_MORE_EVIDENCE": (
        "Use when the official link, title, record type, date or parent is "
        "still unclear."
    ),
    "DEFER": "Use when you want to return to this record later.",
    "REJECT_CLASSIFICATION": (
        "Use when the page is unrelated, incorrectly classified or not a "
        "valid scheme, programme, call or historical reference."
    ),
}


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def truthy(value: Any) -> bool:
    return clean(value).casefold() in {"1", "true", "yes", "y"}


def plain_action_label(code: str) -> str:
    value = clean(code)
    return PLAIN_ACTION_LABELS.get(
        value,
        value.replace("_", " ").title() if value else "Choose an action",
    )


def action_help(code: str) -> str:
    return PLAIN_ACTION_HELP.get(
        clean(code),
        "Choose this only when the official evidence supports the decision.",
    )


def allowed_action_records(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    codes = [
        clean(value)
        for value in clean(bundle.get("allowed_decisions")).split(";")
        if clean(value)
    ]
    if not codes:
        codes = ["PENDING", "NEEDS_MORE_EVIDENCE", "DEFER"]

    records: list[dict[str, Any]] = []
    for code in codes:
        if code == "ACCEPT_RECOMMENDATION":
            continue
        records.append(
            {
                "code": code,
                "label": plain_action_label(code),
                "help": action_help(code),
                "positive": code.startswith("CONFIRM_"),
            }
        )
    if not any(row["code"] == "PENDING" for row in records):
        records.insert(
            0,
            {
                "code": "PENDING",
                "label": plain_action_label("PENDING"),
                "help": "No decision has been saved.",
                "positive": False,
            },
        )
    return records


def record_kind_text(child: dict[str, Any]) -> str:
    entity_type = clean(child.get("entity_type"))
    temporal = clean(child.get("temporal_validation"))

    if temporal == "HISTORICAL_BY_TITLE_OR_DEADLINE":
        return "This appears to be a historical MeitY reference."
    if "PROGRAMME" in entity_type or "SCHEME" in entity_type:
        return "This appears to be a permanent MeitY programme or scheme."
    if any(
        marker in entity_type
        for marker in ("CALL", "CHALLENGE", "HACKATHON", "COHORT", "EOI", "RFP")
    ):
        return "This appears to be a MeitY call, challenge or cohort."
    if "RESULT" in entity_type:
        return "This appears to be a result or selection announcement."
    return "The exact record type still requires Admin review."


def link_summary(child: dict[str, Any]) -> str:
    information = clean(child.get("verified_information_url"))
    application = clean(child.get("verified_application_url"))
    withheld = clean(child.get("application_route_withheld_reason"))

    parts: list[str] = []
    if information:
        parts.append("A matching official information source was verified.")
    else:
        parts.append("A matching official information source was not verified.")

    if application:
        parts.append("A current official application route was verified.")
    elif withheld:
        parts.append("The application route is withheld until evidence improves.")
    else:
        parts.append("No application route was captured.")

    return " ".join(parts)


def recommended_instruction(
    bundle: dict[str, Any],
    child: dict[str, Any],
) -> str:
    if not truthy(bundle.get("link_integrity_complete")):
        return (
            "Check the official source. Then choose “Needs more official "
            "evidence”, “Review this later”, or reject the classification."
        )

    if truthy(bundle.get("safe_positive_decision_allowed")):
        return (
            "The safety checks passed. Confirm only after the official page "
            "matches the displayed name and record type."
        )

    if clean(child.get("temporal_validation")) == (
        "CURRENT_STATUS_EVIDENCE_COMPLETE"
    ):
        return (
            "Verify the closing date and application route before confirming "
            "this as a current opportunity."
        )

    return "Review the official source and choose the most suitable action."


def queue_bucket(
    bundle: dict[str, Any],
    child: dict[str, Any],
) -> str:
    if clean(child.get("temporal_validation")) == (
        "CURRENT_STATUS_EVIDENCE_COMPLETE"
    ):
        return "CURRENT OPPORTUNITY CHECK"
    if not truthy(bundle.get("link_integrity_complete")):
        return "NEEDS EVIDENCE"
    if truthy(bundle.get("safe_positive_decision_allowed")):
        return "READY TO CONFIRM"
    return "NEEDS EVIDENCE"


def note_required(
    bundle: dict[str, Any],
    decision_code: str,
) -> bool:
    if truthy(bundle.get("requires_admin_note")):
        return True
    return clean(decision_code) in {
        "NEEDS_MORE_EVIDENCE",
        "REJECT_CLASSIFICATION",
    }


def simple_record_summary(
    bundle: dict[str, Any],
    child: dict[str, Any],
) -> list[str]:
    return [
        record_kind_text(child),
        link_summary(child),
        recommended_instruction(bundle, child),
    ]
