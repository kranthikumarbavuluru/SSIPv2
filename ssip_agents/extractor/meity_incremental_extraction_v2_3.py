from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .fetcher import SourceFetcher
from .field_extractor import EvidenceFirstFieldExtractor
from .models import SourceDocument
from .scheme_extraction_agent_v1 import DEFAULT_CONFIG, SchemeExtractionAgentV1
from .utils import atomic_write_json, load_json, normalize_space, utc_now_iso


logger = logging.getLogger(__name__)

HOTFIX_VERSION = "2.3.0"
MEITY_SOURCE_NAME = "MeitY Startup Hub"
MEITY_HOSTS = {
    "msh.meity.gov.in",
    "meitystartuphub.in",
    "www.meitystartuphub.in",
}

DEFAULT_MEITY_AUTHORITY: dict[str, Any] = {
    "ministry": "Ministry of Electronics and Information Technology",
    "department": "Ministry of Electronics and Information Technology",
    "implementing_agency": "MeitY Startup Hub",
    "official_url": "https://msh.meity.gov.in/",
    "evidence_note": "Official MeitY Startup Hub source configuration",
    "confidence": 0.95,
}

DEFAULT_INCREMENTAL_CONFIG: dict[str, Any] = {
    **DEFAULT_CONFIG,
    "browser_force_hosts": sorted(MEITY_HOSTS),
    "minimum_reuse_confidence": 0.75,
    "reextract_quality_flags": [
        "ELIGIBILITY_NOT_FOUND",
        "BENEFITS_NOT_FOUND",
        "APPLICATION_PROCESS_NOT_FOUND",
        "NO_SOURCE_DOCUMENTS_FETCHED",
    ],
    "publish_canonical": True,
    "canonical_output_filename": "extracted_scheme_records_v1.json",
    "versioned_output_filename": "extracted_scheme_records_v2_3.json",
}


@dataclass(slots=True)
class MeityIncrementalRunResult:
    records: list[dict[str, Any]]
    meity_records: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    audit: list[dict[str, Any]]
    summary: dict[str, Any]


class MeityIncrementalExtractionV23(SchemeExtractionAgentV1):
    """Incrementally extract MeitY Startup Hub records without disturbing other sources.

    The agent always fetches the selected MeitY source pages so that it can compare
    current source hashes with the hashes stored in the previous extraction record.
    Field extraction is skipped when the source is unchanged and the previous record
    remains complete enough for reuse.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        config_path: Path | None = None,
        source_authorities_path: Path | None = None,
        fetcher_factory: Callable[..., SourceFetcher] = SourceFetcher,
    ) -> None:
        super().__init__(
            project_root=project_root,
            config_path=config_path,
            source_authorities_path=source_authorities_path,
        )
        merged = dict(DEFAULT_INCREMENTAL_CONFIG)
        merged.update(self.config)
        self.config = merged
        self.fetcher_factory = fetcher_factory

        # Do not require a separate config edit merely to run this hotfix.
        existing = self.source_authorities.get(MEITY_SOURCE_NAME)
        if not isinstance(existing, dict):
            self.source_authorities[MEITY_SOURCE_NAME] = dict(DEFAULT_MEITY_AUTHORITY)
        else:
            authority = dict(DEFAULT_MEITY_AUTHORITY)
            authority.update(existing)
            self.source_authorities[MEITY_SOURCE_NAME] = authority

    @staticmethod
    def _urls_from_master(master: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("official_page_url", "best_available_url"):
            value = normalize_space(master.get(key))
            if value:
                urls.append(value)
        for key in ("core_pages", "active_calls", "supporting_documents"):
            for item in master.get(key) or []:
                if isinstance(item, dict):
                    value = normalize_space(item.get("url"))
                    if value:
                        urls.append(value)
        return urls

    @staticmethod
    def _urls_from_record(record: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("official_page_url", "application_url"):
            value = normalize_space(record.get(key))
            if value:
                urls.append(value)
        for item in record.get("source_evidence") or []:
            if isinstance(item, dict):
                value = normalize_space(item.get("url"))
                if value:
                    urls.append(value)
        return urls

    @staticmethod
    def _url_is_meity(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").casefold()
        except ValueError:
            return False
        return host in MEITY_HOSTS or host.endswith(".msh.meity.gov.in")

    @classmethod
    def _is_meity_master(cls, master: dict[str, Any]) -> bool:
        source = normalize_space(master.get("source")).casefold()
        if source == MEITY_SOURCE_NAME.casefold():
            return True
        return any(cls._url_is_meity(url) for url in cls._urls_from_master(master))

    @classmethod
    def _is_meity_record(cls, record: dict[str, Any]) -> bool:
        source = normalize_space(record.get("source")).casefold()
        if source == MEITY_SOURCE_NAME.casefold():
            return True
        return any(cls._url_is_meity(url) for url in cls._urls_from_record(record))

    @staticmethod
    def _fingerprint_source_evidence(source_evidence: list[dict[str, Any]]) -> str | None:
        rows: list[dict[str, str]] = []
        for item in source_evidence:
            if not isinstance(item, dict):
                continue
            source_hash = normalize_space(item.get("source_hash"))
            if not source_hash:
                continue
            rows.append(
                {
                    "url": normalize_space(item.get("url")),
                    "source_hash": source_hash,
                }
            )
        if not rows:
            return None
        rows.sort(key=lambda item: (item["url"], item["source_hash"]))
        payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _fingerprint_documents(cls, documents: list[SourceDocument]) -> str | None:
        evidence = [
            {
                "url": normalize_space(document.url),
                "source_hash": normalize_space(document.source_hash),
            }
            for document in documents
            if normalize_space(document.source_hash)
        ]
        return cls._fingerprint_source_evidence(evidence)

    @classmethod
    def _existing_fingerprint(cls, record: dict[str, Any] | None) -> str | None:
        if not record:
            return None
        incremental = record.get("incremental_metadata")
        if isinstance(incremental, dict):
            value = normalize_space(incremental.get("source_fingerprint"))
            if value:
                return value
        return cls._fingerprint_source_evidence(list(record.get("source_evidence") or []))

    def _record_is_reusable(self, record: dict[str, Any] | None) -> tuple[bool, list[str]]:
        if not record:
            return False, ["NO_EXISTING_RECORD"]

        reasons: list[str] = []
        confidence = float(record.get("extraction_confidence") or 0.0)
        minimum = float(self.config.get("minimum_reuse_confidence", 0.75))
        if confidence < minimum:
            reasons.append("LOW_EXTRACTION_CONFIDENCE")

        existing_flags = {
            normalize_space(flag)
            for flag in (record.get("quality_flags") or [])
            if normalize_space(flag)
        }
        reextract_flags = {
            normalize_space(flag)
            for flag in (self.config.get("reextract_quality_flags") or [])
            if normalize_space(flag)
        }
        reasons.extend(sorted(existing_flags & reextract_flags))

        if not record.get("source_evidence"):
            reasons.append("SOURCE_EVIDENCE_MISSING")
        if not normalize_space(record.get("official_page_url")):
            reasons.append("OFFICIAL_PAGE_URL_MISSING")
        if not normalize_space(record.get("scheme_name")):
            reasons.append("SCHEME_NAME_MISSING")

        return not reasons, reasons

    def _select_meity_masters(
        self,
        masters: list[dict[str, Any]],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        selected = [master for master in masters if self._is_meity_master(master)]
        selected.sort(
            key=lambda item: (
                0 if item.get("current_status") == "ACTIVE_CALL_OPEN" else 1,
                -float(item.get("best_relevance_score") or 0),
                normalize_space(item.get("canonical_name")),
            )
        )
        if limit is not None and limit >= 0:
            selected = selected[:limit]
        return selected

    async def _fetch_documents(
        self,
        *,
        master: dict[str, Any],
        fetcher: SourceFetcher,
        force_refresh: bool,
    ) -> tuple[list[SourceDocument], list[str]]:
        source_specs = self._select_sources(master)
        if not source_specs:
            return [], []

        tasks = [
            fetcher.fetch(
                url=spec["url"],
                title_hint=spec["title"],
                master_id=normalize_space(master.get("master_id")),
                source=normalize_space(master.get("source")),
                force_refresh=force_refresh,
            )
            for spec in source_specs
        ]
        fetched = await asyncio.gather(*tasks)
        documents = [
            document
            for document in fetched
            if isinstance(document, SourceDocument) and len(document.text) >= 20
        ]
        return documents, [spec["url"] for spec in source_specs]

    @staticmethod
    def _metadata(
        *,
        action: str,
        source_fingerprint: str | None,
        previous_fingerprint: str | None,
        reason_codes: list[str],
        checked_at: str,
    ) -> dict[str, Any]:
        return {
            "hotfix_version": HOTFIX_VERSION,
            "action": action,
            "source_fingerprint": source_fingerprint,
            "previous_source_fingerprint": previous_fingerprint,
            "reason_codes": reason_codes,
            "checked_at": checked_at,
        }

    async def _process_master(
        self,
        *,
        master: dict[str, Any],
        existing_record: dict[str, Any] | None,
        fetcher: SourceFetcher,
        field_extractor: EvidenceFirstFieldExtractor,
        force_refresh: bool,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
        checked_at = utc_now_iso()
        master_id = normalize_space(master.get("master_id"))
        scheme_name = normalize_space(master.get("canonical_name"))
        source = normalize_space(master.get("source")) or MEITY_SOURCE_NAME
        previous_fingerprint = self._existing_fingerprint(existing_record)
        reusable, incompleteness_reasons = self._record_is_reusable(existing_record)

        documents, source_urls = await self._fetch_documents(
            master=master,
            fetcher=fetcher,
            force_refresh=force_refresh,
        )
        current_fingerprint = self._fingerprint_documents(documents)

        if not documents:
            action = "RETAINED_AFTER_FETCH_FAILURE" if existing_record else "FAILED_NEW_RECORD"
            failure = {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": source,
                "error_type": "NO_USABLE_SOURCE_CONTENT",
                "error_message": "No selected MeitY source returned usable content.",
                "source_urls": source_urls,
                "failed_at": checked_at,
                "hotfix_version": HOTFIX_VERSION,
            }
            retained = copy.deepcopy(existing_record) if existing_record else None
            if retained is not None:
                retained["incremental_metadata"] = self._metadata(
                    action=action,
                    source_fingerprint=previous_fingerprint,
                    previous_fingerprint=previous_fingerprint,
                    reason_codes=["FETCH_FAILED"],
                    checked_at=checked_at,
                )
            audit = {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": source,
                "action": action,
                "reason_codes": ["FETCH_FAILED"],
                "source_urls": source_urls,
                "previous_source_fingerprint": previous_fingerprint,
                "current_source_fingerprint": None,
                "checked_at": checked_at,
            }
            return retained, audit, failure

        if existing_record and reusable and previous_fingerprint == current_fingerprint:
            action = "REUSED_UNCHANGED"
            reused = copy.deepcopy(existing_record)
            reused["incremental_metadata"] = self._metadata(
                action=action,
                source_fingerprint=current_fingerprint,
                previous_fingerprint=previous_fingerprint,
                reason_codes=["SOURCE_HASH_UNCHANGED", "EXISTING_RECORD_REUSABLE"],
                checked_at=checked_at,
            )
            audit = {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": source,
                "action": action,
                "reason_codes": ["SOURCE_HASH_UNCHANGED", "EXISTING_RECORD_REUSABLE"],
                "source_urls": source_urls,
                "previous_source_fingerprint": previous_fingerprint,
                "current_source_fingerprint": current_fingerprint,
                "extraction_confidence": reused.get("extraction_confidence"),
                "quality_flags": list(reused.get("quality_flags") or []),
                "checked_at": checked_at,
            }
            return reused, audit, None

        if existing_record is None:
            action = "EXTRACTED_NEW"
            reason_codes = ["NO_EXISTING_RECORD"]
        elif not reusable:
            action = "REEXTRACTED_INCOMPLETE"
            reason_codes = incompleteness_reasons
        else:
            action = "REEXTRACTED_SOURCE_CHANGED"
            reason_codes = ["SOURCE_HASH_CHANGED"]

        try:
            record = field_extractor.extract(master=master, documents=documents)
            record["source"] = source
            record["extractor_version"] = HOTFIX_VERSION
            record["incremental_metadata"] = self._metadata(
                action=action,
                source_fingerprint=current_fingerprint,
                previous_fingerprint=previous_fingerprint,
                reason_codes=reason_codes,
                checked_at=checked_at,
            )
            audit = {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": source,
                "action": action,
                "reason_codes": reason_codes,
                "source_urls": source_urls,
                "previous_source_fingerprint": previous_fingerprint,
                "current_source_fingerprint": current_fingerprint,
                "extraction_confidence": record.get("extraction_confidence"),
                "quality_flags": list(record.get("quality_flags") or []),
                "checked_at": checked_at,
            }
            return record, audit, None
        except Exception as exc:
            logger.exception("MeitY field extraction failed for %s", scheme_name)
            action = "RETAINED_AFTER_EXTRACTION_FAILURE" if existing_record else "FAILED_NEW_RECORD"
            failure = {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": source,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
                "source_urls": source_urls,
                "failed_at": checked_at,
                "hotfix_version": HOTFIX_VERSION,
            }
            retained = copy.deepcopy(existing_record) if existing_record else None
            if retained is not None:
                retained["incremental_metadata"] = self._metadata(
                    action=action,
                    source_fingerprint=previous_fingerprint,
                    previous_fingerprint=previous_fingerprint,
                    reason_codes=["FIELD_EXTRACTION_FAILED"],
                    checked_at=checked_at,
                )
            audit = {
                "master_id": master_id,
                "scheme_name": scheme_name,
                "source": source,
                "action": action,
                "reason_codes": ["FIELD_EXTRACTION_FAILED"],
                "source_urls": source_urls,
                "previous_source_fingerprint": previous_fingerprint,
                "current_source_fingerprint": current_fingerprint,
                "checked_at": checked_at,
            }
            return retained, audit, failure

    @staticmethod
    def _record_key(record: dict[str, Any]) -> tuple[str, str, str]:
        master_id = normalize_space(record.get("master_id"))
        if master_id:
            return ("master_id", master_id, "")
        return (
            "fallback",
            normalize_space(record.get("source")).casefold(),
            normalize_space(record.get("scheme_name")).casefold(),
        )

    def _merge_records(
        self,
        *,
        existing_records: list[dict[str, Any]],
        processed_by_master_id: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, int]:
        merged: list[dict[str, Any]] = []
        consumed: set[str] = set()
        non_meity_preserved = 0
        orphaned_meity_preserved = 0

        for existing in existing_records:
            master_id = normalize_space(existing.get("master_id"))
            replacement = processed_by_master_id.get(master_id) if master_id else None
            if replacement is not None:
                merged.append(replacement)
                consumed.add(master_id)
                continue

            # Preserve every record not explicitly replaced. This guarantees that a
            # partial MeitY run or a changed master list cannot delete prior data.
            preserved = copy.deepcopy(existing)
            merged.append(preserved)
            if self._is_meity_record(existing):
                orphaned_meity_preserved += 1
            else:
                non_meity_preserved += 1

        for master_id, record in processed_by_master_id.items():
            if master_id not in consumed:
                merged.append(record)

        return merged, non_meity_preserved, orphaned_meity_preserved

    async def run(
        self,
        *,
        input_path: Path | None = None,
        existing_records_path: Path | None = None,
        output_dir: Path | None = None,
        limit: int | None = None,
        force_refresh: bool = False,
        publish_canonical: bool | None = None,
    ) -> MeityIncrementalRunResult:
        input_path = input_path or self.data_dir / "scheme_master_candidates_v1.json"
        output_dir = output_dir or self.data_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        existing_records_path = existing_records_path or (
            self.data_dir / str(self.config["canonical_output_filename"])
        )

        masters = load_json(input_path, default=None)
        if not isinstance(masters, list):
            raise ValueError(f"Expected a JSON list in {input_path}")

        existing_records = load_json(existing_records_path, default=[])
        if not isinstance(existing_records, list):
            raise ValueError(f"Expected a JSON list in {existing_records_path}")

        selected = self._select_meity_masters(masters, limit=limit)
        existing_by_master_id = {
            normalize_space(record.get("master_id")): record
            for record in existing_records
            if normalize_space(record.get("master_id"))
        }

        cache_dir = output_dir / "extraction_cache_v2_3"
        master_semaphore = asyncio.Semaphore(int(self.config["master_concurrency"]))

        fetcher_kwargs = {
            "cache_dir": cache_dir,
            "timeout_seconds": float(self.config["timeout_seconds"]),
            "max_connections": int(self.config["http_concurrency"]),
            "cache_ttl_hours": int(self.config["cache_ttl_hours"]),
            "max_download_mb": int(self.config["max_download_mb"]),
            "max_pdf_pages": int(self.config["max_pdf_pages"]),
            "use_browser_fallback": bool(self.config["use_browser_fallback"]),
            "browser_text_threshold": int(self.config["browser_text_threshold"]),
            "browser_ignore_https_errors": bool(
                self.config.get("browser_ignore_https_errors", False)
            ),
            "browser_force_hosts": list(self.config.get("browser_force_hosts") or []),
            "insecure_ssl_hosts": list(self.config.get("insecure_ssl_hosts") or []),
            "retries": int(self.config["retries"]),
            "user_agent": "SSIP-MeitY-Incremental-Extraction/2.3",
        }

        async with self.fetcher_factory(**fetcher_kwargs) as fetcher:
            field_extractor = EvidenceFirstFieldExtractor(
                source_authorities=self.source_authorities
            )

            async def limited_process(
                master: dict[str, Any],
            ) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
                async with master_semaphore:
                    master_id = normalize_space(master.get("master_id"))
                    return await self._process_master(
                        master=master,
                        existing_record=existing_by_master_id.get(master_id),
                        fetcher=fetcher,
                        field_extractor=field_extractor,
                        force_refresh=force_refresh,
                    )

            results = await asyncio.gather(*(limited_process(master) for master in selected))
            url_failures = [failure.to_dict() for failure in fetcher.failures]
            fetch_stats = dict(fetcher.stats)

        processed_records = [record for record, _, _ in results if record is not None]
        audit = [item for _, item, _ in results]
        failures = [failure for _, _, failure in results if failure is not None]
        failures.extend(url_failures)

        processed_by_master_id = {
            normalize_space(record.get("master_id")): record
            for record in processed_records
            if normalize_space(record.get("master_id"))
        }
        merged, non_meity_preserved, orphaned_meity_preserved = self._merge_records(
            existing_records=existing_records,
            processed_by_master_id=processed_by_master_id,
        )

        meity_records = [record for record in merged if self._is_meity_record(record)]
        versioned_output = output_dir / str(self.config["versioned_output_filename"])
        failures_output = output_dir / "meity_incremental_extraction_failures_v2_3.json"
        audit_output = output_dir / "meity_incremental_extraction_audit_v2_3.json"
        summary_output = output_dir / "meity_incremental_extraction_summary_v2_3.json"

        action_counts = dict(Counter(item["action"] for item in audit))
        summary = {
            "hotfix_version": HOTFIX_VERSION,
            "source": MEITY_SOURCE_NAME,
            "input_master_count": len(masters),
            "meity_master_candidate_count": len(selected),
            "existing_record_count": len(existing_records),
            "existing_meity_record_count": sum(
                1 for record in existing_records if self._is_meity_record(record)
            ),
            "existing_non_meity_record_count": sum(
                1 for record in existing_records if not self._is_meity_record(record)
            ),
            "processed_meity_record_count": len(processed_records),
            "output_record_count": len(merged),
            "output_meity_record_count": len(meity_records),
            "non_meity_records_preserved": non_meity_preserved,
            "orphaned_meity_records_preserved": orphaned_meity_preserved,
            "failure_count": len(failures),
            "actions": action_counts,
            "quality_flags": dict(
                Counter(
                    flag
                    for record in meity_records
                    for flag in (record.get("quality_flags") or [])
                )
            ),
            "average_meity_extraction_confidence": round(
                sum(float(record.get("extraction_confidence") or 0) for record in meity_records)
                / len(meity_records),
                3,
            )
            if meity_records
            else 0.0,
            "fetch_statistics": fetch_stats,
            "meity_candidates": [
                {
                    "master_id": master.get("master_id"),
                    "canonical_name": master.get("canonical_name"),
                    "current_status": master.get("current_status"),
                    "best_available_url": master.get("best_available_url"),
                }
                for master in selected
            ],
            "input_path": str(input_path),
            "existing_records_path": str(existing_records_path),
            "versioned_output_path": str(versioned_output),
            "generated_at": utc_now_iso(),
        }

        atomic_write_json(versioned_output, merged)
        atomic_write_json(failures_output, failures)
        atomic_write_json(audit_output, audit)
        atomic_write_json(summary_output, summary)

        should_publish = (
            bool(self.config.get("publish_canonical", True))
            if publish_canonical is None
            else publish_canonical
        )
        if should_publish:
            canonical_output = output_dir / str(self.config["canonical_output_filename"])
            if canonical_output.exists():
                backup = output_dir / "extracted_scheme_records_v1.pre_v2_3_backup.json"
                shutil.copy2(canonical_output, backup)
            atomic_write_json(canonical_output, merged)
            summary["canonical_output_path"] = str(canonical_output)
            summary["canonical_published"] = True
        else:
            summary["canonical_published"] = False

        # Rewrite summary after publish metadata is known.
        atomic_write_json(summary_output, summary)

        return MeityIncrementalRunResult(
            records=merged,
            meity_records=meity_records,
            failures=failures,
            audit=audit,
            summary=summary,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SSIP MeitY Incremental Extraction Hotfix v2.3"
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--existing-records", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore the fetch cache while checking MeitY source hashes.",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Do not replace data/extracted_scheme_records_v1.json.",
    )
    return parser.parse_args()


async def _async_main() -> None:
    args = _parse_args()
    agent = MeityIncrementalExtractionV23(project_root=args.project_root)
    result = await agent.run(
        input_path=args.input,
        existing_records_path=args.existing_records,
        output_dir=args.output_dir,
        limit=args.limit,
        force_refresh=args.force_refresh,
        publish_canonical=not args.no_publish,
    )
    print(json.dumps(result.summary, indent=2, ensure_ascii=False))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
