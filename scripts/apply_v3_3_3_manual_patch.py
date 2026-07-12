from __future__ import annotations
import py_compile
import re
import shutil
import textwrap
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
METRICS = ROOT / "ssip_dashboard" / "metrics.py"
POPULATIONS = ROOT / "ssip_dashboard" / "catalogue_populations.py"
APP = ROOT / "apps" / "public_dashboard_app_v2_9.py"
BACKUPS = ROOT / "backups"

POPULATION_REPLACEMENT = '\ndef split_catalogue_populations(records: list[Any]) -> CataloguePopulations:\n    # Evidence-only detection deliberately runs before application-call\n    # classification. This prevents a sitemap, PDF manual, report, FAQ or\n    # directory incorrectly labelled APPLICATION_CALL from entering calls.\n    seen_ids: set[str] = set()\n    main: list[Any] = []\n    calls: list[Any] = []\n    archived: list[Any] = []\n    verification: list[Any] = []\n    evidence: list[Any] = []\n    excluded: list[Any] = []\n\n    for record in records:\n        ok, reason = is_main_scheme_record(record, seen_ids)\n\n        if ok:\n            seen_ids.add(value(record, "master_id"))\n            main.append(record)\n            if is_archived(record):\n                archived.append(record)\n            if requires_verification(record):\n                verification.append(record)\n            continue\n\n        evidence_only, evidence_reason = is_evidence_only(record)\n        poor_name_reason = poor_scheme_name_reason(record)\n\n        if (\n            evidence_only\n            or poor_name_reason\n            in {\n                "RAW_OR_URL_ENCODED_FILENAME_AS_NAME",\n                "GENERIC_SCHEME_NAME",\n                "SITEMAP_OR_DIRECTORY_TITLE",\n            }\n        ):\n            evidence.append(record)\n        elif is_application_call(record) and not is_rejected(record):\n            calls.append(record)\n        else:\n            excluded.append(record)\n\n    return CataloguePopulations(\n        main_scheme_records=main,\n        application_call_records=calls,\n        archived_scheme_records=archived,\n        verification_required_scheme_records=verification,\n        evidence_only_records=evidence,\n        excluded_records=excluded,\n    )\n'
METRICS_IMPORT = 'from .catalogue_populations import (\n    primary_sector,\n    primary_sector_counts,\n    primary_support_type,\n    primary_support_type_counts,\n    split_catalogue_populations,\n)\n'
COMPUTE_METRICS_REPLACEMENT = '\ndef compute_metrics(records: list[Any]) -> DashboardMetrics:\n    populations = split_catalogue_populations(visible_records(records))\n    scheme_records = populations.main_scheme_records\n    application_call_records = populations.application_call_records\n\n    bucket_counts = Counter(status_bucket(record) for record in scheme_records)\n    funding = funding_summary(scheme_records)\n\n    sector_values = {\n        primary_sector(record)\n        for record in scheme_records\n        if primary_sector(record) != "Sector Not Specified"\n    }\n    support_values = {\n        primary_support_type(record)\n        for record in scheme_records\n        if primary_support_type(record) != "SUPPORT_TYPE_NOT_SPECIFIED"\n    }\n\n    return DashboardMetrics(\n        total_catalogue_records=len(scheme_records),\n        application_call_records=len(application_call_records),\n        evidence_or_directory_records=(\n            len(populations.evidence_only_records)\n            + len(populations.excluded_records)\n        ),\n        total_explicit_ministries=explicit_count(scheme_records, "ministry"),\n        total_explicit_departments=explicit_count(scheme_records, "department"),\n        total_implementing_agencies=explicit_count(\n            scheme_records, "implementing_agency"\n        ),\n        total_source_organisations=explicit_count(scheme_records, "source"),\n        total_sectors=len(sector_values),\n        total_grant_support_types=len(support_values),\n        open_records=bucket_counts["OPEN"],\n        closing_soon_records=bucket_counts["CLOSING_SOON"],\n        upcoming_records=bucket_counts["UPCOMING"],\n        verification_required_records=bucket_counts["VERIFICATION_REQUIRED"],\n        closed_records=bucket_counts["CLOSED"],\n        historical_records=bucket_counts["HISTORICAL"],\n        records_with_funding_information=funding["records_with_funding"],\n        records_missing_funding_information=funding["records_missing_funding"],\n        records_with_application_portals=sum(\n            1 for record in scheme_records\n            if getattr(record, "application_url", "")\n        ),\n        records_with_manuals_guidelines=sum(\n            1 for record in scheme_records\n            if getattr(record, "guideline_urls", [])\n        ),\n        minimum_recorded_funding=funding["minimum_recorded_funding"],\n        maximum_recorded_funding=funding["maximum_recorded_funding"],\n        records_missing_ministry=sum(\n            1 for record in scheme_records\n            if not str(getattr(record, "ministry", "") or "").strip()\n        ),\n        records_missing_department=sum(\n            1 for record in scheme_records\n            if not str(getattr(record, "department", "") or "").strip()\n        ),\n        records_missing_sector=sum(\n            1 for record in scheme_records\n            if primary_sector(record) == "Sector Not Specified"\n        ),\n    )\n'
LATEST_RECORDS_REPLACEMENT = '\ndef latest_records(records: list[Any], *, limit: int = 5) -> list[Any]:\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    return sorted(\n        main_records,\n        key=lambda record: str(getattr(record, "last_updated", "") or ""),\n        reverse=True,\n    )[:limit]\n'
OPEN_RECORDS_REPLACEMENT = '\ndef open_records(records: list[Any], *, limit: int | None = None) -> list[Any]:\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    output = [\n        record\n        for record in main_records\n        if status_bucket(record) in {"OPEN", "CLOSING_SOON"}\n    ]\n    return output if limit is None else output[:limit]\n'
GOVERNMENT_REPLACEMENT = '\ndef government_level_coverage(\n    records: list[Any],\n    lookup: dict[str, str] | None = None,\n) -> Counter[str]:\n    counter: Counter[str] = Counter(\n        {level: 0 for level in GOVERNMENT_LEVELS}\n    )\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    for record in main_records:\n        counter[government_level(record, lookup)] += 1\n    return counter\n'
STATUS_REPLACEMENT = '\ndef status_coverage(records: list[Any]) -> Counter[str]:\n    counter: Counter[str] = Counter()\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    for record in main_records:\n        counter[status_bucket(record)] += 1\n    return counter\n'
DEPARTMENT_REPLACEMENT = '\ndef department_coverage(records: list[Any]) -> Counter[str]:\n    counter: Counter[str] = Counter()\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    for record in main_records:\n        label = (\n            str(getattr(record, "department", "") or "").strip()\n            or str(getattr(record, "implementing_agency", "") or "").strip()\n            or str(getattr(record, "source", "") or "").strip()\n            or "Unspecified"\n        )\n        counter[label] += 1\n    return counter\n'
SECTOR_REPLACEMENT = '\ndef sector_coverage(records: list[Any]) -> Counter[str]:\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    return primary_sector_counts(main_records)\n'
GRANT_REPLACEMENT = '\ndef grant_support_distribution(records: list[Any]) -> Counter[str]:\n    main_records = split_catalogue_populations(\n        visible_records(records)\n    ).main_scheme_records\n    return primary_support_type_counts(main_records)\n'
SCHEME_DETAILS_REPLACEMENT = '\ndef render_scheme_details(bundle: CatalogueBundle) -> None:\n    records = sorted(\n        split_catalogue_populations(\n            bundle.records\n        ).main_scheme_records,\n        key=lambda record: (\n            record.scheme_name.casefold(),\n            (\n                record.department\n                or record.implementing_agency\n                or record.source\n                or ""\n            ).casefold(),\n        ),\n    )\n\n    if not records:\n        st.info("No eligible scheme or programme records are available.")\n        return\n\n    records_by_id = {record.master_id: record for record in records}\n    record_labels = {}\n    for item in records:\n        agency = (\n            item.department\n            or item.implementing_agency\n            or item.source\n            or "Agency not recorded"\n        )\n        record_labels[item.master_id] = f"{item.scheme_name} — {agency}"\n\n    selected_id = st.selectbox(\n        "Select scheme",\n        options=[record.master_id for record in records],\n        format_func=lambda item_id: record_labels[item_id],\n    )\n    record = records_by_id[selected_id]\n\n    st.markdown(scheme_card(record), unsafe_allow_html=True)\n    c1, c2, c3 = st.columns(3)\n    c1.write(f"**Ministry**  \\n{record.ministry or \'Not recorded\'}")\n    c2.write(\n        f"**Department / Agency**  \\n"\n        f"{record.department or record.implementing_agency or record.source or \'Not recorded\'}"\n    )\n    c3.write(\n        f"**Record Type**  \\n"\n        f"{record.record_kind.replace(\'_\', \' \').title()}"\n    )\n\n    detail_sections = [\n        ("Objectives", record.objectives),\n        ("Eligibility", record.eligibility),\n        ("Benefits", record.benefits),\n        ("Application Process", record.application_process),\n        ("Required Documents", record.required_documents),\n        ("Contacts", record.contacts),\n    ]\n\n    for title, items in detail_sections:\n        with st.expander(title, expanded=title in {"Objectives", "Eligibility"}):\n            if items:\n                for item in items:\n                    st.markdown(f"- {item}")\n            else:\n                st.caption("Not recorded in structured catalogue data.")\n\n    st.markdown("### Official links")\n\n    if record.official_page_url:\n        st.markdown(\n            f"- [Official scheme/programme page]({record.official_page_url})"\n        )\n    if record.application_url:\n        st.markdown(\n            f"- [Application portal]({record.application_url})"\n        )\n\n    for index, url in enumerate(record.guideline_urls or [], start=1):\n        st.markdown(f"- [Guideline / manual {index}]({url})")\n\n    if not (\n        record.official_page_url\n        or record.application_url\n        or record.guideline_urls\n    ):\n        st.caption("No official resource links are recorded.")\n'

def fail(message: str) -> None:
    raise SystemExit(f"PATCH FAILED: {message}")

def backup(path: Path, stamp: str) -> Path:
    if not path.exists():
        fail(f"Required file not found: {path}")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    destination = BACKUPS / f"{path.stem}_before_v3_3_3_manual_{stamp}{path.suffix}"
    shutil.copy2(path, destination)
    return destination

def add_import(text: str, marker: str, insertion: str) -> str:
    if insertion.strip() in text:
        return text
    if marker not in text:
        fail(f"Import marker not found: {marker}")
    return text.replace(marker, marker + insertion, 1)

def replace_function(text: str, function_name: str, replacement: str) -> str:
    pattern = re.compile(rf"(?ms)^def {re.escape(function_name)}\(.*?(?=^def |\Z)")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        fail(f"Expected one function {function_name}; found {len(matches)}")
    start, end = matches[0].span()
    return text[:start] + textwrap.dedent(replacement).strip() + "\n\n\n" + text[end:]

def replace_exact_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected one exact match; found {count}")
    return text.replace(old, new, 1)

def patch_population_service() -> None:
    text = POPULATIONS.read_text(encoding="utf-8")
    text = replace_function(text, "split_catalogue_populations", POPULATION_REPLACEMENT)
    POPULATIONS.write_text(text, encoding="utf-8")

def patch_metrics() -> None:
    text = METRICS.read_text(encoding="utf-8")
    text = add_import(text, "from .status import status_bucket\n", METRICS_IMPORT)
    for name, replacement in [
        ("compute_metrics", COMPUTE_METRICS_REPLACEMENT),
        ("latest_records", LATEST_RECORDS_REPLACEMENT),
        ("open_records", OPEN_RECORDS_REPLACEMENT),
        ("government_level_coverage", GOVERNMENT_REPLACEMENT),
        ("status_coverage", STATUS_REPLACEMENT),
        ("department_coverage", DEPARTMENT_REPLACEMENT),
        ("sector_coverage", SECTOR_REPLACEMENT),
        ("grant_support_distribution", GRANT_REPLACEMENT),
    ]:
        text = replace_function(text, name, replacement)
    METRICS.write_text(text, encoding="utf-8")

def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    text = add_import(
        text,
        "from ssip_dashboard.config import DashboardConfig\n",
        "from ssip_dashboard.catalogue_populations import split_catalogue_populations\n",
    )
    text = replace_exact_once(
        text,
        "def render_home(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:\n    records = bundle.records\n    metrics = compute_metrics(records)",
        "def render_home(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:\n    populations = split_catalogue_populations(bundle.records)\n    records = populations.main_scheme_records\n    metrics = compute_metrics(records)",
        "render_home wiring",
    )
    text = replace_exact_once(
        text,
        "def render_explorer(bundle: CatalogueBundle) -> None:\n    records = bundle.records",
        "def render_explorer(bundle: CatalogueBundle) -> None:\n    populations = split_catalogue_populations(bundle.records)\n    records = populations.main_scheme_records",
        "render_explorer wiring",
    )
    text = replace_exact_once(
        text,
        "    filtered = apply_filters(bundle.records, state)",
        "    filtered = apply_filters(records, state)",
        "explorer filter wiring",
    )
    text = replace_exact_once(
        text,
        "def render_departments(bundle: CatalogueBundle) -> None:\n    records = bundle.records",
        "def render_departments(bundle: CatalogueBundle) -> None:\n    records = split_catalogue_populations(bundle.records).main_scheme_records",
        "departments wiring",
    )
    text = replace_exact_once(
        text,
        "def render_sectors(bundle: CatalogueBundle) -> None:\n    records = bundle.records",
        "def render_sectors(bundle: CatalogueBundle) -> None:\n    records = split_catalogue_populations(bundle.records).main_scheme_records",
        "sectors wiring",
    )
    text = replace_function(text, "render_scheme_details", SCHEME_DETAILS_REPLACEMENT)
    APP.write_text(text, encoding="utf-8")

def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = [backup(path, stamp) for path in (POPULATIONS, METRICS, APP)]
    patch_population_service()
    patch_metrics()
    patch_app()
    for path in (POPULATIONS, METRICS, APP):
        py_compile.compile(str(path), doraise=True)
    print("=" * 72)
    print("SSIP v3.3.3 manual wiring patch applied")
    print("=" * 72)
    print("Backups:")
    for path in backups:
        print(path)
    print("Syntax checks: PASSED")
    print("Database writes: 0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
