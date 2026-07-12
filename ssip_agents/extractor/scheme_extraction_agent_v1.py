from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fetcher import SourceFetcher
from .field_extractor import EvidenceFirstFieldExtractor
from .models import SourceDocument
from .utils import atomic_write_json, load_json, normalize_space, utc_now_iso


logger = logging.getLogger(__name__)


DEFAULT_CONFIG: dict[str, Any] = {
    "readiness_allowlist": [
        "READY_FOR_EXTRACTION",
        "NEEDS_CONTENT_EXTRACTION_AND_REVIEW",
    ],
    "max_sources_per_master": 6,
    "master_concurrency": 3,
    "http_concurrency": 8,
    "timeout_seconds": 30,
    "cache_ttl_hours": 24,
    "max_download_mb": 20,
    "max_pdf_pages": 80,
    "use_browser_fallback": True,
    "browser_text_threshold": 450,
    "browser_ignore_https_errors": False,
    "insecure_ssl_hosts": [],
    "retries": 2,
}


@dataclass(slots=True)
class ExtractionRunResult:
    records: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    summary: dict[str, Any]


class SchemeExtractionAgentV1:
    def __init__(
        self,
        *,
        project_root: Path,
        config_path: Path | None = None,
        source_authorities_path: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.config_path = config_path or self.project_root / "config" / "extractor_config.json"
        self.source_authorities_path = (
            source_authorities_path
            or self.project_root / "config" / "source_authorities.json"
        )

        file_config = load_json(self.config_path, default={})
        self.config = dict(DEFAULT_CONFIG)
        if isinstance(file_config, dict):
            self.config.update(file_config)

        source_authorities = load_json(self.source_authorities_path, default={})
        self.source_authorities = (
            source_authorities if isinstance(source_authorities, dict) else {}
        )

    @staticmethod
    def _source_priority(item: dict[str, Any]) -> tuple[int, float, str]:
        classification = str(item.get("classification", "")).upper()
        kind_rank = {
            "SCHEME": 0,
            "PROGRAMME": 1,
            "CALL": 2,
            "GUIDELINE": 3,
            "POLICY": 4,
            "REFERENCE_DOCUMENT": 5,
        }.get(classification, 9)

        score = float(item.get("relevance_score") or 0)
        return kind_rank, -score, str(item.get("url", ""))

    def _select_sources(self, master: dict[str, Any]) -> list[dict[str, str]]:
        candidates: list[dict[str, Any]] = []

        official_url = normalize_space(master.get("official_page_url"))
        if official_url:
            candidates.append(
                {
                    "url": official_url,
                    "title": normalize_space(master.get("official_page_title")),
                    "classification": "SCHEME",
                    "relevance_score": master.get("best_relevance_score", 0),
                }
            )

        candidates.extend(master.get("core_pages") or [])
        candidates.extend(master.get("active_calls") or [])

        best_url = normalize_space(master.get("best_available_url"))
        if best_url:
            candidates.append(
                {
                    "url": best_url,
                    "title": normalize_space(master.get("best_available_title")),
                    "classification": "CALL"
                    if master.get("master_type") == "ACTIVE_CALL_FAMILY"
                    else "SCHEME",
                    "relevance_score": master.get("best_relevance_score", 0),
                }
            )

        supporting = list(master.get("supporting_documents") or [])
        supporting.sort(key=self._source_priority)
        candidates.extend(supporting)

        # Preserve strongest record for each URL.
        best_by_url: dict[str, dict[str, Any]] = {}
        for item in candidates:
            url = normalize_space(item.get("url"))
            if not url:
                continue

            existing = best_by_url.get(url)
            if existing is None or self._source_priority(item) < self._source_priority(existing):
                best_by_url[url] = item

        ordered = sorted(best_by_url.values(), key=self._source_priority)

        max_sources = int(self.config["max_sources_per_master"])
        selected = ordered[:max_sources]

        return [
            {
                "url": normalize_space(item.get("url")),
                "title": normalize_space(item.get("title")),
                "classification": normalize_space(item.get("classification")),
            }
            for item in selected
        ]

    def _select_masters(
        self,
        masters: list[dict[str, Any]],
        *,
        limit: int | None = None,
        include_readiness: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        readiness_allowlist = set(
            include_readiness
            or self.config.get("readiness_allowlist")
            or DEFAULT_CONFIG["readiness_allowlist"]
        )

        selected = [
            master
            for master in masters
            if str(master.get("readiness", "")) in readiness_allowlist
        ]

        selected.sort(
            key=lambda item: (
                0 if item.get("current_status") == "ACTIVE_CALL_OPEN" else 1,
                -float(item.get("best_relevance_score") or 0),
                str(item.get("canonical_name", "")),
            )
        )

        if limit is not None and limit >= 0:
            selected = selected[:limit]

        return selected

    async def _extract_one(
        self,
        *,
        master: dict[str, Any],
        fetcher: SourceFetcher,
        field_extractor: EvidenceFirstFieldExtractor,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        master_id = normalize_space(master.get("master_id"))
        source = normalize_space(master.get("source"))
        name = normalize_space(master.get("canonical_name"))
        source_specs = self._select_sources(master)

        if not source_specs:
            return None, {
                "master_id": master_id,
                "scheme_name": name,
                "source": source,
                "error_type": "NO_SOURCE_URLS",
                "error_message": "No source URLs were available in the master candidate.",
                "failed_at": utc_now_iso(),
            }

        logger.info(
            "Extracting: %s | %s | %d source(s)",
            source,
            name,
            len(source_specs),
        )

        tasks = [
            fetcher.fetch(
                url=spec["url"],
                title_hint=spec["title"],
                master_id=master_id,
                source=source,
            )
            for spec in source_specs
        ]
        fetched = await asyncio.gather(*tasks)
        documents: list[SourceDocument] = [
            document
            for document in fetched
            if isinstance(document, SourceDocument) and len(document.text) >= 20
        ]

        if not documents:
            return None, {
                "master_id": master_id,
                "scheme_name": name,
                "source": source,
                "error_type": "NO_USABLE_SOURCE_CONTENT",
                "error_message": (
                    "Every selected source failed or returned insufficient text. "
                    "Review extraction_failures_v1.json for URL-level errors."
                ),
                "source_urls": [spec["url"] for spec in source_specs],
                "failed_at": utc_now_iso(),
            }

        record = field_extractor.extract(master=master, documents=documents)
        logger.info(
            "Extracted: %s | confidence=%.3f | flags=%d",
            name,
            record["extraction_confidence"],
            len(record["quality_flags"]),
        )
        return record, None

    async def run(
        self,
        *,
        input_path: Path | None = None,
        output_dir: Path | None = None,
        limit: int | None = None,
        include_readiness: list[str] | None = None,
    ) -> ExtractionRunResult:
        input_path = input_path or self.data_dir / "scheme_master_candidates_v1.json"
        output_dir = output_dir or self.data_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        masters = load_json(input_path, default=None)
        if not isinstance(masters, list):
            raise ValueError(
                f"Expected a JSON list in {input_path}, got "
                f"{type(masters).__name__ if masters is not None else 'missing file'}"
            )

        selected = self._select_masters(
            masters,
            limit=limit,
            include_readiness=include_readiness,
        )

        cache_dir = output_dir / "extraction_cache_v1"
        master_semaphore = asyncio.Semaphore(int(self.config["master_concurrency"]))

        async with SourceFetcher(
            cache_dir=cache_dir,
            timeout_seconds=float(self.config["timeout_seconds"]),
            max_connections=int(self.config["http_concurrency"]),
            cache_ttl_hours=int(self.config["cache_ttl_hours"]),
            max_download_mb=int(self.config["max_download_mb"]),
            max_pdf_pages=int(self.config["max_pdf_pages"]),
            use_browser_fallback=bool(self.config["use_browser_fallback"]),
            browser_text_threshold=int(self.config["browser_text_threshold"]),
            browser_ignore_https_errors=bool(
                self.config.get("browser_ignore_https_errors", False)
            ),
            insecure_ssl_hosts=list(self.config.get("insecure_ssl_hosts") or []),
            retries=int(self.config["retries"]),
        ) as fetcher:
            field_extractor = EvidenceFirstFieldExtractor(
                source_authorities=self.source_authorities
            )

            async def limited_extract(
                master: dict[str, Any],
            ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
                async with master_semaphore:
                    return await self._extract_one(
                        master=master,
                        fetcher=fetcher,
                        field_extractor=field_extractor,
                    )

            results = await asyncio.gather(
                *(limited_extract(master) for master in selected)
            )

            records = [record for record, _ in results if record is not None]
            master_failures = [failure for _, failure in results if failure is not None]
            url_failures = [failure.to_dict() for failure in fetcher.failures]
            failures = master_failures + url_failures

            records.sort(
                key=lambda item: (
                    str(item.get("source", "")),
                    str(item.get("scheme_name", "")),
                )
            )

            summary = self._build_summary(
                input_count=len(masters),
                selected_count=len(selected),
                records=records,
                failures=failures,
                fetch_stats=fetcher.stats,
                input_path=input_path,
            )

        atomic_write_json(output_dir / "extracted_scheme_records_v1.json", records)
        atomic_write_json(output_dir / "extraction_failures_v1.json", failures)
        atomic_write_json(output_dir / "extraction_summary_v1.json", summary)

        return ExtractionRunResult(
            records=records,
            failures=failures,
            summary=summary,
        )

    @staticmethod
    def _build_summary(
        *,
        input_count: int,
        selected_count: int,
        records: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        fetch_stats: dict[str, int],
        input_path: Path,
    ) -> dict[str, Any]:
        return {
            "input_master_count": input_count,
            "selected_for_extraction_count": selected_count,
            "extracted_record_count": len(records),
            "failure_count": len(failures),
            "records_by_source": dict(Counter(record["source"] for record in records)),
            "records_by_scheme_status": dict(
                Counter(record["scheme_status"] for record in records)
            ),
            "quality_flags": dict(
                Counter(
                    flag
                    for record in records
                    for flag in record.get("quality_flags", [])
                )
            ),
            "average_extraction_confidence": round(
                sum(float(record["extraction_confidence"]) for record in records)
                / len(records),
                3,
            )
            if records
            else 0.0,
            "fetch_statistics": dict(fetch_stats),
            "input_path": str(input_path),
            "generated_at": utc_now_iso(),
            "extractor_version": "1.0.0",
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SSIP Scheme Extraction Agent v1")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="SSIP project root. Defaults to current working directory.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional path to scheme_master_candidates_v1.json",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of master candidates to process.",
    )
    parser.add_argument(
        "--readiness",
        action="append",
        default=None,
        help="Readiness value to include. Repeat for multiple values.",
    )
    return parser.parse_args()


async def _async_main() -> None:
    args = _parse_args()
    agent = SchemeExtractionAgentV1(project_root=args.project_root)
    result = await agent.run(
        input_path=args.input,
        limit=args.limit,
        include_readiness=args.readiness,
    )
    print(result.summary)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
