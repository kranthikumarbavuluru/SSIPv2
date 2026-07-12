from __future__ import annotations

import csv
import html
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .call_extractor import SnapshotCallExtractor, parse_date
from .common import clean, stable_id, utc_now
from .live_refresh import OfficialLiveCallRefresher
from .profile import DepartmentProfile
from .repository import EvidenceRepository


CALL_FIELDS = [
    "call_id", "department_code", "call_title", "record_role", "call_type", "applicant_layer",
    "applicant_layer_reason", "parent_master_id",
    "parent_resolution", "parent_resolution_reason", "opening_date", "closing_date",
    "application_status", "status_reason", "startup_relevance", "startup_relevance_reason",
    "sector_scope", "primary_sector", "secondary_sectors", "sector_reason",
    "sector_review_required", "detail_url", "attachment_url", "source_container_url",
    "source_container_role", "source_row_number", "source_fetched_at", "eligible_applicants",
    "funding_summary", "funding_maximum", "application_url", "guideline_url", "evidence_note",
    "implementing_entity", "implementation_role", "status_basis", "status_evidence",
    "last_verified_at", "startup_stage",
]

PROGRAMME_FIELDS = [
    "master_id", "code", "canonical_name", "entity_type", "parent_master_id",
    "public_classification", "sector_scope", "primary_sector", "secondary_sectors",
    "official_master_url", "evidence_text", "review_status",
]

QUEUE_FIELDS = [
    "entity_type", "entity_id", "display_name", "proposed_action", "priority",
    "parent_resolution", "application_status", "startup_relevance", "sector_scope",
    "primary_sector", "official_url", "reasons", "review_status",
]


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8-sig")
    os.replace(temporary, path)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            for key, value in normalized.items():
                if isinstance(value, list):
                    normalized[key] = "; ".join(str(item) for item in value)
            writer.writerow(normalized)
    os.replace(temporary, path)


class DSTPilotPipeline:
    def __init__(
        self,
        project_root: Path,
        profile_path: Path | None = None,
        output_dir: Path | None = None,
        today: date | None = None,
        live_refresh: bool = False,
    ) -> None:
        self.root = project_root.resolve()
        self.profile_path = (profile_path or self.root / "config/dst_department_agent_v1.json").resolve()
        self.output_dir = (output_dir or self.root / "data/departments/dst/pilot_v1").resolve()
        self.today = today or date.today()
        self.live_refresh = live_refresh
        self.profile = DepartmentProfile.load(self.profile_path)

    def _programme_rows(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.profile.entities]

    def _apply_curated_call_overrides(self, extracted: list[Any]) -> list[Any]:
        by_url = {item.values.get("detail_url", "").rstrip("/"): item for item in extracted}
        for override in self.profile.payload.get("current_call_overrides", []):
            url = str(override["detail_url"]).rstrip("/")
            item = by_url.get(url)
            if item is None:
                opening = str(override.get("opening_date", ""))
                closing = str(override.get("closing_date", ""))
                values = {field: "" for field in CALL_FIELDS}
                values.update({
                    "call_id": stable_id("dst_call", url, override["call_title"], opening, closing),
                    "department_code": "DST", "call_title": override["call_title"], "record_role": "CALL_INSTANCE",
                    "parent_resolution": "UNRESOLVED", "parent_resolution_reason": "No permanent parent has been curator-approved.",
                    "opening_date": opening, "closing_date": closing, "application_status": override["application_status"],
                    "status_reason": "Status verified from the dated official detail page.",
                    "sector_review_required": "false", "detail_url": url, "source_container_url": url,
                    "source_container_role": "CURATED_CURRENT_OFFICIAL_PAGE", "source_fetched_at": utc_now(),
                })
                from .call_extractor import ExtractedCall
                item = ExtractedCall(values, [])
                extracted.append(item)
                by_url[url] = item
            for key, value in override.items():
                if key not in {"source_evidence"}:
                    item.values[key] = str(value) if not isinstance(value, list) else "; ".join(str(part) for part in value)
            source_text = str(override["source_evidence"])
            for field in ("startup_relevance", "sector_scope", "primary_sector", "eligible_applicants", "funding_summary", "application_status", "status_basis", "implementing_entity"):
                if item.values.get(field):
                    item.evidence.append({"field_name": field, "source_url": url, "evidence_text": source_text})
        return extracted

    @staticmethod
    def _programme_evidence(programmes: list[dict[str, Any]]) -> list[dict[str, str]]:
        evidence: list[dict[str, str]] = []
        for row in programmes:
            for field in ("canonical_name", "entity_type", "public_classification", "sector_scope", "primary_sector"):
                value = row.get(field)
                if value:
                    evidence.append({
                        "entity_type": "PROGRAMME",
                        "entity_id": str(row["master_id"]),
                        "field_name": field,
                        "source_url": str(row["official_master_url"]),
                        "evidence_text": f"{value}. {row['evidence_text']}",
                    })
        return evidence

    @staticmethod
    def _call_evidence(calls: list[Any]) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        for call in calls:
            for item in call.evidence:
                output.append({
                    "entity_type": "CALL",
                    "entity_id": call.values["call_id"],
                    **item,
                })
        return output

    @staticmethod
    def _curation_queue(programmes: list[dict[str, Any]], calls: list[dict[str, str]]) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        for row in programmes:
            reasons = ["Verify the curated identity, hierarchy and official master page before first publication."]
            if row["sector_scope"] == "UNKNOWN":
                reasons.append("Sector scope is intentionally UNKNOWN until explicit official evidence or curator approval exists.")
            queue.append({
                "entity_type": "PROGRAMME",
                "entity_id": row["master_id"],
                "display_name": row["canonical_name"],
                "proposed_action": "REVIEW_PROGRAMME_BASELINE",
                "priority": "HIGH",
                "parent_resolution": "CURATED_HIERARCHY",
                "application_status": "NOT_APPLICABLE_PERMANENT_PROGRAMME",
                "startup_relevance": row["public_classification"],
                "sector_scope": row["sector_scope"],
                "primary_sector": row.get("primary_sector", ""),
                "official_url": row["official_master_url"],
                "reasons": reasons,
                "review_status": "PENDING",
            })
        for row in calls:
            relevance = row["startup_relevance"]
            if relevance == "NOT_STARTUP_RELEVANT":
                continue
            reasons = [row["startup_relevance_reason"], row["parent_resolution_reason"], row["status_reason"], row["sector_reason"]]
            unresolved = row["parent_resolution"] in {"UNRESOLVED", "UMBRELLA_ONLY_REVIEW"}
            queue.append({
                "entity_type": "CALL",
                "entity_id": row["call_id"],
                "display_name": row["call_title"],
                "proposed_action": "REVIEW_ADD_CALL" if relevance == "STARTUP_RELEVANT" else ("REVIEW_ADD_ECOSYSTEM_CALL" if relevance == "STARTUP_ECOSYSTEM_CALL" else "REVIEW_POSSIBLE_STARTUP_CALL"),
                "priority": "HIGH" if unresolved or row["application_status"] in {"OPEN", "UPCOMING"} else "NORMAL",
                "parent_resolution": row["parent_resolution"],
                "application_status": row["application_status"],
                "startup_relevance": relevance,
                "sector_scope": row["sector_scope"],
                "primary_sector": row["primary_sector"],
                "official_url": row["detail_url"] or row["source_container_url"],
                "reasons": reasons,
                "review_status": "PENDING",
            })
        return queue

    def _validate(self, programmes: list[dict[str, Any]], calls: list[dict[str, str]]) -> dict[str, Any]:
        programme_ids = {str(row["master_id"]) for row in programmes}
        call_ids = [row["call_id"] for row in calls]
        checks = {
            "unique_programme_ids": len(programme_ids) == len(programmes),
            "unique_call_ids": len(call_ids) == len(set(call_ids)),
            "all_programme_parents_exist": all(not row.get("parent_master_id") or row["parent_master_id"] in programme_ids for row in programmes),
            "all_call_parents_exist_or_unresolved": all(not row.get("parent_master_id") or row["parent_master_id"] in programme_ids for row in calls),
            "no_index_container_stored_as_call": all(not row["call_title"].casefold().startswith(("archive call for proposals | page", "call for proposals | department")) for row in calls),
            "all_calls_have_detail_or_container_evidence": all(row["detail_url"] or row["source_container_url"] for row in calls),
            "open_calls_have_official_status_evidence": all(
                row["application_status"] != "OPEN"
                or (parse_date(row["opening_date"]) is not None and parse_date(row["closing_date"]) is not None)
                or (
                    row.get("status_basis") == "EXPLICIT_OFFICIAL_APPLY_ROUTE"
                    and bool(row.get("status_evidence"))
                    and bool(row.get("application_url"))
                    and bool(row.get("last_verified_at"))
                )
                for row in calls
            ),
            "programme_sector_scopes_controlled": all(row["sector_scope"] in {"AGNOSTIC", "SPECIFIC", "MULTI_SECTOR", "UNKNOWN"} for row in programmes),
            "unknown_programme_sectors_not_invented": all(row["sector_scope"] != "UNKNOWN" or not clean(row.get("primary_sector")) for row in programmes),
            "calls_do_not_inherit_parent_sector": all(row["sector_scope"] != "UNKNOWN" or not row["primary_sector"] for row in calls),
        }
        return {"passed": all(checks.values()), "checks": checks}

    @staticmethod
    def _html_preview(queue: list[dict[str, Any]], summary: dict[str, Any]) -> str:
        cards: list[str] = []
        for row in queue:
            reasons = "".join(f"<li>{html.escape(clean(reason))}</li>" for reason in row["reasons"] if clean(reason))
            url = html.escape(str(row["official_url"]), quote=True)
            cards.append(
                "<article>"
                f"<div class='meta'>{html.escape(row['entity_type'])} · {html.escape(row['priority'])} · {html.escape(row['review_status'])}</div>"
                f"<h2>{html.escape(row['display_name'])}</h2>"
                f"<p><b>Action:</b> {html.escape(row['proposed_action'])} &nbsp; <b>Parent:</b> {html.escape(row['parent_resolution'])}</p>"
                f"<p><b>Status:</b> {html.escape(row['application_status'])} &nbsp; <b>Sector scope:</b> {html.escape(row['sector_scope'])} {html.escape(row['primary_sector'])}</p>"
                f"<ul>{reasons}</ul><a href='{url}' target='_blank' rel='noopener'>Official evidence</a>"
                "</article>"
            )
        return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>DST Curation Preview</title><style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f4f7fb;color:#17233c;margin:0}}header{{background:#073b88;color:white;padding:28px max(24px,6vw)}}main{{max-width:1100px;margin:auto;padding:24px}}article{{background:white;border:1px solid #d8e3f5;border-radius:14px;padding:20px;margin:14px 0;box-shadow:0 4px 18px #173b6b12}}h1,h2{{margin:.2em 0}}.meta{{font-size:.8rem;text-transform:uppercase;color:#4f6685}}a{{color:#0759b8}}ul{{line-height:1.5}}.notice{{background:#fff4d6;border-left:5px solid #d99900;padding:14px}}</style></head>
<body><header><h1>DST agent curation preview</h1><p>Evidence-first pilot · generated {html.escape(summary['generated_at'])}</p></header><main><p class='notice'>Preview only. No production database or public dashboard record was modified.</p>
<p><b>{summary['programme_count']}</b> programme identities · <b>{summary['individual_call_count']}</b> individual call rows · <b>{summary['curation_queue_count']}</b> review items</p>{''.join(cards)}</main></body></html>"""

    def run(self) -> dict[str, Any]:
        crawl_root = self.root / "data/departments/dst/v3_4_0_1/crawl"
        crawled_pages = crawl_root / "dst_crawled_pages_v3_4_0_1.csv"
        if not crawled_pages.exists():
            raise FileNotFoundError(f"DST crawl inventory not found: {crawled_pages}")
        programmes = self._programme_rows()
        extracted = SnapshotCallExtractor(self.profile, self.today).extract(crawled_pages, crawl_root)
        live_inventory = ""
        live_refresh_page_count = 0
        live_refresh_error_count = 0
        if self.live_refresh:
            live_root = self.output_dir / "live_refresh"
            live_path = OfficialLiveCallRefresher(self.profile, live_root).run()
            live_inventory = str(live_path)
            with live_path.open("r", encoding="utf-8-sig", newline="") as handle:
                live_rows = list(csv.DictReader(handle))
            live_refresh_page_count = sum(row.get("fetch_status") == "OK" for row in live_rows)
            live_refresh_error_count = sum(row.get("fetch_status") == "ERROR" for row in live_rows)
            live_calls = SnapshotCallExtractor(self.profile, self.today).extract(live_path, live_root)
            by_id = {item.values["call_id"]: item for item in extracted}
            by_id.update({item.values["call_id"]: item for item in live_calls})
            extracted = list(by_id.values())
        extracted = self._apply_curated_call_overrides(extracted)
        calls = [item.values for item in extracted]
        queue = self._curation_queue(programmes, calls)
        validation = self._validate(programmes, calls)
        run_id = "dst_pilot_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary: dict[str, Any] = {
            "run_id": run_id,
            "generated_at": utc_now(),
            "verification_date": self.today.isoformat(),
            "source_snapshot": str(crawled_pages),
            "source_snapshot_is_production": False,
            "live_refresh_enabled": self.live_refresh,
            "live_refresh_inventory": live_inventory,
            "live_refresh_page_count": live_refresh_page_count,
            "live_refresh_error_count": live_refresh_error_count,
            "programme_count": len(programmes),
            "individual_call_count": len(calls),
            "startup_relevant_call_count": sum(row["startup_relevance"] == "STARTUP_RELEVANT" for row in calls),
            "startup_ecosystem_call_count": sum(row["startup_relevance"] == "STARTUP_ECOSYSTEM_CALL" for row in calls),
            "startup_call_review_count": sum(row["startup_relevance"] == "REVIEW_REQUIRED" for row in calls),
            "open_call_count": sum(row["application_status"] == "OPEN" for row in calls),
            "upcoming_call_count": sum(row["application_status"] == "UPCOMING" for row in calls),
            "unresolved_startup_parent_count": sum(row["startup_relevance"] != "NOT_STARTUP_RELEVANT" and row["parent_resolution"] in {"UNRESOLVED", "UMBRELLA_ONLY_REVIEW"} for row in calls),
            "curation_queue_count": len(queue),
            "production_modified": False,
            "validation": validation,
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(self.output_dir / "dst_programme_hierarchy_v1.csv", programmes, PROGRAMME_FIELDS)
        write_csv(self.output_dir / "dst_individual_calls_v1.csv", calls, CALL_FIELDS)
        write_csv(
            self.output_dir / "dst_startup_call_candidates_v1.csv",
            [row for row in calls if row["startup_relevance"] != "NOT_STARTUP_RELEVANT"],
            CALL_FIELDS,
        )
        queue_csv = [{**row, "reasons": " | ".join(row["reasons"])} for row in queue]
        write_csv(self.output_dir / "dst_curation_queue_v1.csv", queue_csv, QUEUE_FIELDS)
        atomic_write(self.output_dir / "dst_curation_preview_v1.html", self._html_preview(queue, summary))
        atomic_write(self.output_dir / "dst_pilot_summary_v1.json", json.dumps(summary, indent=2, ensure_ascii=False))

        repository = EvidenceRepository(self.output_dir / "dst_evidence_pilot_v1.db")
        try:
            repository.replace_programmes(programmes)
            repository.replace_calls(calls)
            repository.replace_evidence(self._programme_evidence(programmes) + self._call_evidence(extracted))
            repository.replace_queue([
                {
                    "entity_type": row["entity_type"], "entity_id": row["entity_id"],
                    "proposed_action": row["proposed_action"], "priority": row["priority"], "reasons": row["reasons"],
                }
                for row in queue
            ])
            repository.record_run(run_id, summary)
        finally:
            repository.close()
        if not validation["passed"]:
            raise RuntimeError("DST pilot validation failed; inspect dst_pilot_summary_v1.json")
        return summary
