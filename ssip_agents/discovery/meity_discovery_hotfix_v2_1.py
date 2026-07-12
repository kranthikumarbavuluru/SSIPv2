from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from ssip_agents.discovery.discovery_agent_v2 import DiscoveryAgentV2, DiscoveryConfig

logger = logging.getLogger(__name__)


class _DirectPageDiscoveryAgent(DiscoveryAgentV2):
    """Bypass robots lookup only for explicitly configured direct-page runs.

    Discovery Agent v2 consults robots.txt even when ``respect_robots`` is
    false. For this bounded hotfix (one request per configured official URL),
    skipping that extra lookup avoids repeated delays on the JavaScript-heavy
    portal while retaining the normal per-host request delay.
    """

    async def _can_fetch(self, client, seed, url):  # type: ignore[override]
        if not self.config.respect_robots:
            return True, self.config.request_delay
        return await super()._can_fetch(client, seed, url)


HOTFIX_VERSION = "2.1.0"
DEFAULT_SOURCE_NAME = "MeitY Startup Hub"
DEFAULT_DOMAIN = "msh.meity.gov.in"


DEFAULT_CONFIG: dict[str, Any] = {
    "source_name": DEFAULT_SOURCE_NAME,
    "official_domain": DEFAULT_DOMAIN,
    "bootstrap_pages": [
        {
            "name": "SAMRIDH",
            "url": "https://msh.meity.gov.in/schemes/samridh",
            "title": "SAMRIDH Scheme",
            "description": "Official MeitY Startup Hub scheme page for SAMRIDH.",
            "page_type": "SCHEME",
            "bootstrap_score": 38.0,
            "positive_terms": [
                "samridh",
                "scheme",
                "startup",
                "accelerator",
                "financial support",
            ],
        },
        {
            "name": "TIDE 2.0",
            "url": "https://msh.meity.gov.in/schemes/tide",
            "title": "TIDE 2.0 Scheme",
            "description": "Official MeitY Startup Hub scheme page for TIDE 2.0.",
            "page_type": "SCHEME",
            "bootstrap_score": 38.0,
            "positive_terms": [
                "tide 2.0",
                "scheme",
                "startup",
                "incubation",
                "technology",
            ],
        },
        {
            "name": "SASACT",
            "url": "https://msh.meity.gov.in/schemes/sasact",
            "title": "Scheme for Accelerating Startups around Post-COVID Technology (SASACT)",
            "description": "Official MeitY Startup Hub scheme page for SASACT.",
            "page_type": "SCHEME",
            "bootstrap_score": 38.0,
            "positive_terms": [
                "sasact",
                "scheme",
                "startup",
                "technology",
                "support",
            ],
        },
        {
            "name": "GENESIS",
            "url": "https://msh.meity.gov.in/schemes/genesis",
            "title": "GENESIS Scheme",
            "description": "Official MeitY Startup Hub scheme page for GENESIS.",
            "page_type": "SCHEME",
            "bootstrap_score": 38.0,
            "positive_terms": [
                "genesis",
                "scheme",
                "startup",
                "tier ii",
                "tier iii",
            ],
        },
        {
            "name": "SITAA Contactless Fingerprint Authentication",
            "url": "https://msh.meity.gov.in/challenges/home/5f56490b-947e-4893-b9da-fe11f15251ec",
            "title": "SITAA – Contactless Fingerprint Authentication Challenge",
            "description": "Official MeitY Startup Hub challenge page under SITAA.",
            "page_type": "CHALLENGE",
            "bootstrap_score": 34.0,
            "positive_terms": [
                "sitaa",
                "challenge",
                "uidai",
                "startup",
                "innovation",
            ],
        },
        {
            "name": "SITAA Presentation Attack Detection",
            "url": "https://msh.meity.gov.in/challenges/home/35ed1bc3-26e1-4aef-99ee-3f759a530f55",
            "title": "SITAA – Presentation Attack Detection Challenge",
            "description": "Official MeitY Startup Hub challenge page under SITAA.",
            "page_type": "CHALLENGE",
            "bootstrap_score": 34.0,
            "positive_terms": [
                "sitaa",
                "challenge",
                "uidai",
                "research",
                "innovation",
            ],
        },
    ],
    "navigation_pages": [],
    "discovery": {
        "max_depth": 0,
        "max_pages_per_seed": 1,
        "workers_per_seed": 1,
        "max_links_per_page": 10,
        "exploration_links_per_page": 0,
        "candidate_threshold": 7.0,
        "document_threshold": 6.0,
        "crawl_threshold": 1.0,
        "discover_sitemaps": False,
        "use_browser_fallback": True,
        "max_browser_pages_per_seed": 1,
        "browser_wait_ms": 1600,
        "request_delay": 0.30,
        "respect_robots": False,
        "timeout_connect": 6.0,
        "timeout_read": 15.0,
        "max_retries": 2,
    },
    "accepted_path_prefixes": [
        "/schemes/",
        "/challenges/",
    ],
    "accepted_document_extensions": [
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
    ],
}


@dataclass(slots=True)
class MergeResult:
    records: list[dict[str, Any]]
    added_count: int
    updated_count: int
    unchanged_count: int


class MeityDiscoveryHotfixV21:
    """
    MeitY-specific discovery adapter for the JavaScript-heavy MSH portal.

    The adapter deliberately does not replace Discovery Agent v2. It runs the
    existing agent against direct official scheme/challenge pages, adds a small
    deterministic bootstrap set for resilience, and safely merges only new or
    stronger MeitY candidates into ``data/discovery_results_v2.json``.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.config_path = (
            Path(config_path).resolve()
            if config_path is not None
            else self.project_root / "config" / "meity_discovery_hotfix_v2_1.json"
        )
        self.config = self._load_config(self.config_path)
        self.source_name = str(
            self.config.get("source_name", DEFAULT_SOURCE_NAME)
        ).strip() or DEFAULT_SOURCE_NAME
        self.official_domain = str(
            self.config.get("official_domain", DEFAULT_DOMAIN)
        ).strip().lower() or DEFAULT_DOMAIN

        self.discovery_path = self.data_dir / "discovery_results_v2.json"
        self.meity_output_path = self.data_dir / "meity_discovery_results_v2_1.json"
        self.summary_path = self.data_dir / "meity_discovery_summary_v2_1.json"
        self.backup_dir = self.data_dir / "backups"

    @staticmethod
    def _deep_copy_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @classmethod
    def _load_config(cls, path: Path) -> dict[str, Any]:
        config = cls._deep_copy_json(DEFAULT_CONFIG)
        if not path.exists():
            return config

        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Hotfix config must be a JSON object: {path}")

        # Top-level replacement is intentional for page lists so administrators
        # can fully control the direct official pages without editing Python.
        for key, value in loaded.items():
            if key == "discovery" and isinstance(value, dict):
                config["discovery"].update(value)
            else:
                config[key] = value
        return config

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _utc_iso(cls) -> str:
        return cls._utc_now().isoformat()

    @staticmethod
    def _atomic_write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _load_json_list(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"Expected a JSON array: {path}")
        return [dict(item) for item in value if isinstance(item, Mapping)]

    @staticmethod
    def canonical_url(url: str) -> str:
        normalised = DiscoveryAgentV2.normalize_url(str(url or ""))
        return normalised or str(url or "").strip()

    def _is_official_meity_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == self.official_domain or host.endswith(
            f".{self.official_domain}"
        )

    def _accept_candidate(self, record: Mapping[str, Any]) -> bool:
        url = self.canonical_url(str(record.get("url", "")))
        if not url or not self._is_official_meity_url(url):
            return False

        path = (urlparse(url).path or "/").lower()
        prefixes = [
            str(item).lower()
            for item in self.config.get("accepted_path_prefixes", [])
        ]
        extensions = [
            str(item).lower()
            for item in self.config.get("accepted_document_extensions", [])
        ]

        if any(path.startswith(prefix) for prefix in prefixes):
            return True
        return any(path.endswith(extension) for extension in extensions)

    def _make_seed_sources(self) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        for page in list(self.config.get("bootstrap_pages", [])) + list(
            self.config.get("navigation_pages", [])
        ):
            if not isinstance(page, Mapping):
                continue
            url = self.canonical_url(str(page.get("url", "")))
            if not url or not self._is_official_meity_url(url):
                logger.warning("Skipped non-official or invalid MeitY URL: %s", url)
                continue
            name = str(page.get("name", "MeitY page")).strip() or "MeitY page"
            pages.append(
                {
                    "name": f"{self.source_name} | {name}",
                    "url": url,
                    "allowed_domains": [self.official_domain],
                    "positive_terms": list(page.get("positive_terms", [])),
                    "negative_terms": [
                        "privacy",
                        "login",
                        "contact us",
                        "gallery",
                    ],
                }
            )
        return pages

    def _make_discovery_config(self) -> DiscoveryConfig:
        values = dict(self.config.get("discovery", {}))
        allowed_fields = DiscoveryConfig.__dataclass_fields__.keys()
        clean_values = {key: value for key, value in values.items() if key in allowed_fields}
        return DiscoveryConfig(**clean_values)

    def build_bootstrap_candidates(self) -> list[dict[str, Any]]:
        discovered_at = self._utc_iso()
        candidates: list[dict[str, Any]] = []
        for page in self.config.get("bootstrap_pages", []):
            if not isinstance(page, Mapping):
                continue
            url = self.canonical_url(str(page.get("url", "")))
            if not url or not self._is_official_meity_url(url):
                continue

            page_type = str(page.get("page_type", "SCHEME")).upper()
            title = str(page.get("title", page.get("name", ""))).strip()
            reason_type = "challenge" if page_type == "CHALLENGE" else "scheme"
            score = float(page.get("bootstrap_score", 34.0))
            candidates.append(
                {
                    "url": url,
                    "source": self.source_name,
                    "status": "PENDING",
                    "content_kind": "html",
                    "relevance_score": score,
                    "relevance_reasons": [
                        "hotfix:official-meity-bootstrap-url",
                        f"hotfix:direct-{reason_type}-page",
                        f"title:primary:{reason_type}",
                        "title:audience:startup",
                    ],
                    "title": title,
                    "description": str(page.get("description", "")).strip(),
                    "anchor_text": title,
                    "depth": 0,
                    "parent_url": "https://msh.meity.gov.in/",
                    "discovery_method": "meity-hotfix-bootstrap-v2.1",
                    "hash": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                    "discovered_at": discovered_at,
                }
            )
        return candidates

    @staticmethod
    def _merge_reasons(*reason_sets: Iterable[Any]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for reason_set in reason_sets:
            for reason in reason_set or []:
                text = str(reason).strip()
                if text and text not in seen:
                    output.append(text)
                    seen.add(text)
        return output

    @classmethod
    def _choose_stronger_record(
        cls,
        existing: Mapping[str, Any],
        incoming: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        current = dict(existing)
        candidate = dict(incoming)
        changed = False

        existing_score = float(current.get("relevance_score") or 0.0)
        incoming_score = float(candidate.get("relevance_score") or 0.0)
        if incoming_score > existing_score:
            current["relevance_score"] = incoming_score
            changed = True

        merged_reasons = cls._merge_reasons(
            current.get("relevance_reasons", []),
            candidate.get("relevance_reasons", []),
        )
        if merged_reasons != current.get("relevance_reasons", []):
            current["relevance_reasons"] = merged_reasons
            changed = True

        for field in (
            "title",
            "description",
            "anchor_text",
            "parent_url",
            "content_kind",
            "status",
        ):
            old_value = current.get(field)
            new_value = candidate.get(field)
            if (not old_value) and new_value:
                current[field] = new_value
                changed = True

        old_method = str(current.get("discovery_method", ""))
        new_method = str(candidate.get("discovery_method", ""))
        if "meity-hotfix" in new_method and "meity-hotfix" not in old_method:
            current["discovery_method"] = (
                f"{old_method}+{new_method}" if old_method else new_method
            )
            changed = True

        if candidate.get("source") == DEFAULT_SOURCE_NAME and current.get(
            "source"
        ) != DEFAULT_SOURCE_NAME:
            current["source"] = DEFAULT_SOURCE_NAME
            changed = True

        return current, changed

    @classmethod
    def merge_candidate_lists(
        cls,
        existing: Sequence[Mapping[str, Any]],
        incoming: Sequence[Mapping[str, Any]],
    ) -> MergeResult:
        records: list[dict[str, Any]] = []
        positions: dict[str, int] = {}

        for raw in existing:
            record = dict(raw)
            canonical = cls.canonical_url(str(record.get("url", "")))
            if not canonical:
                continue
            record["url"] = canonical
            if canonical in positions:
                index = positions[canonical]
                records[index], _ = cls._choose_stronger_record(records[index], record)
            else:
                positions[canonical] = len(records)
                records.append(record)

        added = 0
        updated = 0
        unchanged = 0
        for raw in incoming:
            record = dict(raw)
            canonical = cls.canonical_url(str(record.get("url", "")))
            if not canonical:
                continue
            record["url"] = canonical
            if canonical not in positions:
                positions[canonical] = len(records)
                records.append(record)
                added += 1
                continue

            index = positions[canonical]
            merged, changed = cls._choose_stronger_record(records[index], record)
            records[index] = merged
            if changed:
                updated += 1
            else:
                unchanged += 1

        records.sort(
            key=lambda item: (
                str(item.get("source", "")).lower(),
                -float(item.get("relevance_score") or 0.0),
                str(item.get("url", "")),
            )
        )
        return MergeResult(records, added, updated, unchanged)

    async def discover_live_candidates(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        seeds = self._make_seed_sources()
        if not seeds:
            raise RuntimeError("No valid MeitY seed pages are configured.")

        agent = _DirectPageDiscoveryAgent(
            seed_sources=seeds,
            config=self._make_discovery_config(),
        )
        results = await agent.run()

        accepted: list[dict[str, Any]] = []
        for raw in results:
            if not self._accept_candidate(raw):
                continue
            record = dict(raw)
            record["url"] = self.canonical_url(str(record.get("url", "")))
            record["source"] = self.source_name
            method = str(record.get("discovery_method", "crawl"))
            record["discovery_method"] = f"meity-hotfix-v2.1:{method}"
            accepted.append(record)

        return accepted, agent.last_run_stats

    def _backup_existing_discovery(self) -> Path | None:
        if not self.discovery_path.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._utc_now().strftime("%Y%m%dT%H%M%SZ")
        backup_path = (
            self.backup_dir
            / f"discovery_results_v2_before_meity_hotfix_{stamp}.json"
        )
        shutil.copy2(self.discovery_path, backup_path)
        return backup_path

    async def run(self, *, dry_run: bool = False) -> dict[str, Any]:
        existing = self._load_json_list(self.discovery_path)
        live_candidates, network_stats = await self.discover_live_candidates()
        bootstrap_candidates = self.build_bootstrap_candidates()

        # First consolidate live and bootstrap MeitY candidates, then merge them
        # into the full cross-source discovery file.
        hotfix_merge = self.merge_candidate_lists(live_candidates, bootstrap_candidates)
        hotfix_candidates = [
            record
            for record in hotfix_merge.records
            if self._is_official_meity_url(str(record.get("url", "")))
        ]
        full_merge = self.merge_candidate_lists(existing, hotfix_candidates)

        existing_meity_count = sum(
            1
            for record in existing
            if str(record.get("source", "")) == self.source_name
        )
        final_meity_count = sum(
            1
            for record in full_merge.records
            if str(record.get("source", "")) == self.source_name
        )

        backup_path: Path | None = None
        if not dry_run:
            backup_path = self._backup_existing_discovery()
            self._atomic_write_json(self.meity_output_path, hotfix_candidates)
            self._atomic_write_json(self.discovery_path, full_merge.records)

        summary = {
            "hotfix_version": HOTFIX_VERSION,
            "source": self.source_name,
            "official_domain": self.official_domain,
            "dry_run": dry_run,
            "existing_candidate_count_before": len(existing),
            "existing_meity_candidate_count_before": existing_meity_count,
            "live_candidate_count": len(live_candidates),
            "bootstrap_candidate_count": len(bootstrap_candidates),
            "hotfix_unique_candidate_count": len(hotfix_candidates),
            "new_unique_candidates_added": full_merge.added_count,
            "existing_candidates_updated": full_merge.updated_count,
            "unchanged_duplicate_candidates": full_merge.unchanged_count,
            "merged_candidate_count_after": len(full_merge.records),
            "meity_candidate_count_after": final_meity_count,
            "network_stats": network_stats,
            "input_path": str(self.discovery_path),
            "meity_output_path": str(self.meity_output_path),
            "merged_output_path": str(self.discovery_path),
            "backup_path": str(backup_path) if backup_path else None,
            "generated_at": self._utc_iso(),
        }

        if not dry_run:
            self._atomic_write_json(self.summary_path, summary)
        return summary


async def run_meity_hotfix(
    project_root: str | Path,
    *,
    config_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    hotfix = MeityDiscoveryHotfixV21(
        project_root=project_root,
        config_path=config_path,
    )
    return await hotfix.run(dry_run=dry_run)


__all__ = [
    "HOTFIX_VERSION",
    "MeityDiscoveryHotfixV21",
    "MergeResult",
    "run_meity_hotfix",
]
