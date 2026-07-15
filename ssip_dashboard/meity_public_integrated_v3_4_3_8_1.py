from __future__ import annotations

from copy import copy
from dataclasses import is_dataclass, replace
from typing import Any, Callable


CALL_KINDS = {
    "APPLICATION_CALL",
    "CALL",
    "CHALLENGE",
    "CHALLENGE_CALL",
    "ACCELERATOR_COHORT",
    "COHORT",
}
HISTORICAL_KINDS = {
    "HISTORICAL_REFERENCE",
    "RESULT_ANNOUNCEMENT",
}
CURRENT_STATUSES = {"OPEN", "UPCOMING"}


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def is_meity_record(record: Any) -> bool:
    haystack = " ".join(
        [
            clean(getattr(record, "source", "")),
            clean(getattr(record, "ministry", "")),
            clean(getattr(record, "department", "")),
            clean(getattr(record, "implementing_agency", "")),
        ]
    ).casefold()
    return "meity" in haystack or (
        "electronics and information technology" in haystack
    )


def is_public_record(record: Any) -> bool:
    return (
        clean(getattr(record, "publication_status", "")).upper()
        == "PUBLISHED"
        and int(getattr(record, "is_public", 0) or 0) == 1
    )


def clone_with(record: Any, **updates: Any) -> Any:
    if is_dataclass(record):
        return replace(record, **updates)
    if hasattr(record, "model_copy"):
        return record.model_copy(update=updates)
    if hasattr(record, "_replace"):
        return record._replace(**updates)
    cloned = copy(record)
    for key, value in updates.items():
        setattr(cloned, key, value)
    return cloned


def public_safe_record(record: Any) -> Any:
    kind = clean(getattr(record, "record_kind", "")).upper()
    status = clean(
        getattr(record, "application_status", "")
    ).upper()
    application_url = clean(
        getattr(record, "application_url", "")
    )

    allow_apply = (
        kind in CALL_KINDS
        and status in CURRENT_STATUSES
        and application_url.startswith(("https://", "http://"))
    )
    if allow_apply:
        return record
    return clone_with(record, application_url="")


def partition_published_meity(
    records: list[Any],
) -> dict[str, list[Any]]:
    published = [
        public_safe_record(record)
        for record in records
        if is_meity_record(record) and is_public_record(record)
    ]
    programmes: list[Any] = []
    calls: list[Any] = []
    historical: list[Any] = []

    for record in published:
        kind = clean(getattr(record, "record_kind", "")).upper()
        if kind in HISTORICAL_KINDS:
            historical.append(record)
        elif kind in CALL_KINDS:
            status = clean(
                getattr(record, "application_status", "")
            ).upper()
            if status in CURRENT_STATUSES:
                calls.append(record)
        else:
            programmes.append(record)

    key = lambda item: clean(
        getattr(item, "scheme_name", "")
    ).casefold()
    programmes.sort(key=key)
    calls.sort(key=key)
    historical.sort(key=key)
    return {
        "programmes": programmes,
        "calls": calls,
        "historical": historical,
    }


def render_integrated_meity_public_page(
    *,
    st: Any,
    bundle: Any,
    historical_archive: Any,
    page_intro: Callable[..., str],
    metric_card: Callable[..., str],
    public_record_card: Callable[..., str],
    published_call_filters: Callable[..., list[Any]],
    published_call_card: Callable[..., str],
    render_historical_archive: Callable[[], None],
) -> None:
    populations = partition_published_meity(
        list(getattr(bundle, "records", []) or [])
    )
    programmes = populations["programmes"]
    current_calls = populations["calls"]
    history_records = tuple(
        getattr(historical_archive, "records", ()) or ()
    )

    st.markdown(
        page_intro(
            "MeitY intelligence",
            "MeitY Schemes, Programmes & Calls",
            (
                "Published permanent MeitY identities, verified current calls "
                "and governed historical references are available here in "
                "the main SSIP dashboard."
            ),
            badge=(
                f"{len(programmes)} schemes/programmes · "
                f"{len(current_calls)} current calls · "
                f"{len(history_records)} historical"
            ),
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card(
            "Schemes & programmes",
            len(programmes),
            "Published permanent MeitY identities",
            "blue",
        )
        + metric_card(
            "Open calls",
            sum(
                clean(
                    getattr(record, "application_status", "")
                ).upper()
                == "OPEN"
                for record in current_calls
            ),
            "Verified current application windows",
            "green",
        )
        + metric_card(
            "Upcoming",
            sum(
                clean(
                    getattr(record, "application_status", "")
                ).upper()
                == "UPCOMING"
                for record in current_calls
            ),
            "Verified future application windows",
            "purple",
        )
        + metric_card(
            "Historical references",
            len(history_records),
            "Reference-only official MeitY records",
            "orange",
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    programme_tab, call_tab, history_tab = st.tabs(
        [
            "Schemes & Programmes",
            "Current Calls & Challenges",
            "Historical Archive",
        ]
    )

    with programme_tab:
        st.info(
            "Permanent schemes and programmes are shown without a public "
            "Apply button. Temporary cohorts, calls and challenges remain "
            "separate."
        )
        if programmes:
            st.markdown(
                '<div class="scheme-results-grid">'
                + "".join(
                    public_record_card(record)
                    for record in programmes
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "No published permanent MeitY schemes or programmes are "
                "available in the current public catalogue."
            )

    with call_tab:
        st.info(
            "Only published OPEN or UPCOMING records appear here. "
            "Unverified, closed and historical records never expose an "
            "Apply action."
        )
        if current_calls:
            parent_names = {
                clean(getattr(record, "master_id", "")): clean(
                    getattr(record, "scheme_name", "")
                )
                for record in list(
                    getattr(bundle, "records", []) or []
                )
            }
            visible = published_call_filters(
                current_calls,
                key_prefix="meity_integrated_calls",
                parent_names=parent_names,
            )
            st.markdown(
                '<div class="call-grid">'
                + "".join(
                    published_call_card(
                        record,
                        parent_names=parent_names,
                    )
                    for record in visible
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "No verified open or upcoming MeitY calls are currently "
                "published."
            )

    with history_tab:
        render_historical_archive()

    st.caption(
        "MeitY Admin classification and projection tools are available only "
        "inside the SSIP Admin Review application."
    )
