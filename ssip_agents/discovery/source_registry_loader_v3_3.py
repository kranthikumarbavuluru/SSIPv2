from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


VERSION = "3.3.0"


@dataclass(frozen=True)
class RegistrySource:
    source_id: str
    name: str
    scope: str
    ministry: str
    department: str
    agency: str
    source_type: str
    priority: str
    official_url: str
    seed_urls: tuple[str, ...]
    coverage_note: str
    status: str
    enabled: bool
    respect_robots: bool
    rate_limit_per_domain_per_second: float
    max_depth: int
    max_pages_per_seed: int


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return str(value or "").strip()


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_url(url: str) -> str:
    text = clean(url)
    if not text:
        return ""
    parsed = urlparse(text)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def canonical_host(url: str, aliases: dict[str, str] | None = None) -> str:
    host = urlparse(normalize_url(url)).netloc.lower()
    if host.startswith("www."):
        host_without_www = host[4:]
    else:
        host_without_www = host
    alias_map = {key.lower(): value.lower() for key, value in (aliases or {}).items()}
    return alias_map.get(host, alias_map.get(host_without_www, host_without_www))


def _bool_from_source(item: dict[str, Any], defaults: dict[str, Any], key: str) -> bool:
    return bool(item[key]) if key in item else bool(defaults.get(key))


def source_from_item(item: dict[str, Any], defaults: dict[str, Any]) -> RegistrySource:
    seed_urls = tuple(normalize_url(url) for url in item.get("seed_urls", []) if normalize_url(url))
    return RegistrySource(
        source_id=clean(item.get("source_id")),
        name=clean(item.get("name")),
        scope=clean(item.get("scope")),
        ministry=clean(item.get("ministry")),
        department=clean(item.get("department")),
        agency=clean(item.get("agency")),
        source_type=clean(item.get("source_type")),
        priority=clean(item.get("priority")),
        official_url=normalize_url(clean(item.get("official_url"))),
        seed_urls=seed_urls,
        coverage_note=clean(item.get("coverage_note")),
        status=clean(item.get("status")) or clean(defaults.get("status")),
        enabled=_bool_from_source(item, defaults, "enabled"),
        respect_robots=_bool_from_source(item, defaults, "respect_robots"),
        rate_limit_per_domain_per_second=float(
            item.get("rate_limit_per_domain_per_second", defaults.get("rate_limit_per_domain_per_second", 0.5))
        ),
        max_depth=int(item.get("max_depth", defaults.get("max_depth", 1))),
        max_pages_per_seed=int(item.get("max_pages_per_seed", defaults.get("max_pages_per_seed", 25))),
    )


def load_registry_sources(project_root: Path | None = None) -> tuple[list[RegistrySource], dict[str, Any]]:
    root = project_root or project_root_from_file()
    registry_path = root / "config" / "official_source_registry_v3_3.json"
    registry = load_json(registry_path)
    defaults = registry.get("defaults", {})
    sources_by_id: dict[str, RegistrySource] = {}

    base_name = clean(registry.get("base_registry"))
    if base_name:
        base_payload = load_json(root / "config" / base_name)
        for item in base_payload.get("sources", []):
            source = source_from_item(item, defaults)
            sources_by_id[source.source_id] = source

    for item in registry.get("additional_sources", []):
        source = source_from_item(item, defaults)
        sources_by_id[source.source_id] = source

    return list(sources_by_id.values()), registry


def load_authority_rules(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = project_root or project_root_from_file()
    payload = load_json(root / "config" / "source_authorities_v3_3.json")
    return list(payload.get("authority_rules", []))


def load_validator_config(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or project_root_from_file()
    return load_json(root / "config" / "validator_config_v3_3.json")


def authority_for_source(source: RegistrySource, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in rules:
        field_name = clean(rule.get("match_field"))
        source_value = clean(getattr(source, field_name, ""))
        values = {clean(value).casefold() for value in rule.get("match_values", [])}
        if source_value.casefold() in values:
            return rule
    return None


def duplicate_seed_urls(sources: list[RegistrySource]) -> list[dict[str, Any]]:
    by_url: dict[str, list[str]] = defaultdict(list)
    for source in sources:
        for url in source.seed_urls:
            by_url[normalize_url(url)].append(source.source_id)
    return [
        {"seed_url": url, "source_ids": sorted(source_ids)}
        for url, source_ids in sorted(by_url.items())
        if len(source_ids) > 1
    ]


def source_to_seed(source: RegistrySource) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "name": source.name,
        "scope": source.scope,
        "priority": source.priority,
        "seed_urls": list(source.seed_urls),
        "respect_robots": source.respect_robots,
        "rate_limit_per_domain_per_second": source.rate_limit_per_domain_per_second,
        "max_depth": source.max_depth,
        "max_pages_per_seed": source.max_pages_per_seed,
    }


def planned_batches(sources: list[RegistrySource], registry: dict[str, Any]) -> list[dict[str, Any]]:
    source_map = {source.source_id: source for source in sources if source.enabled}
    planned = []
    used_ids: set[str] = set()
    for batch in registry.get("discovery_batches", []):
        batch_sources = []
        for source_id in batch.get("source_ids", []):
            source = source_map.get(clean(source_id))
            if source:
                batch_sources.append(source_to_seed(source))
                used_ids.add(source.source_id)
        planned.append(
            {
                "batch_id": clean(batch.get("batch_id")),
                "description": clean(batch.get("description")),
                "priority": clean(batch.get("priority")),
                "source_count": len(batch_sources),
                "seed_url_count": sum(len(source["seed_urls"]) for source in batch_sources),
                "sources": batch_sources,
            }
        )
    unbatched = [source_to_seed(source) for source in source_map.values() if source.source_id not in used_ids]
    if unbatched:
        planned.append(
            {
                "batch_id": "registry_remaining_sources",
                "description": "Enabled registry sources not assigned to a named v3.3.0 pilot batch.",
                "priority": "MEDIUM",
                "source_count": len(unbatched),
                "seed_url_count": sum(len(source["seed_urls"]) for source in unbatched),
                "sources": unbatched,
            }
        )
    return planned


def build_dry_run_report(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or project_root_from_file()
    sources, registry = load_registry_sources(root)
    authority_rules = load_authority_rules(root)
    validator = load_validator_config(root)
    enabled = [source for source in sources if source.enabled]
    aliases = validator.get("trusted_domain_aliases", {})
    trusted_domains = {clean(domain).lower() for domain in validator.get("trusted_domains", [])}

    missing_authority = [
        source.source_id for source in enabled if authority_for_source(source, authority_rules) is None
    ]
    missing_trusted = []
    for source in enabled:
        for url in source.seed_urls:
            host = canonical_host(url, aliases)
            if host not in trusted_domains:
                missing_trusted.append({"source_id": source.source_id, "seed_url": url, "host": host})

    batches = planned_batches(sources, registry)
    seed_url_count = sum(len(source.seed_urls) for source in enabled)
    report = {
        "version": VERSION,
        "generated_at": utc_now(),
        "dry_run": True,
        "network_requests_performed": 0,
        "database_writes_performed": 0,
        "registry_path": str(root / "config" / "official_source_registry_v3_3.json"),
        "output_policy": {
            "respect_robots": bool(validator.get("respect_robots", True)),
            "network_crawl_enabled": bool(validator.get("network_crawl_enabled", False)),
            "rate_limits": validator.get("rate_limits", {}),
        },
        "total_sources": len(sources),
        "total_enabled_sources": len(enabled),
        "central_sources": sum(1 for source in enabled if source.scope.casefold() == "central"),
        "state_ut_sources": sum(1 for source in enabled if source.scope.casefold() == "state/ut"),
        "ministry_distribution": dict(sorted(Counter(source.ministry for source in enabled).items())),
        "priority_distribution": dict(sorted(Counter(source.priority for source in enabled).items())),
        "seed_url_count": seed_url_count,
        "duplicate_seed_urls": duplicate_seed_urls(enabled),
        "missing_authority_mappings": missing_authority,
        "missing_trusted_domain_mappings": missing_trusted,
        "planned_discovery_batches": batches,
    }
    return report


def write_dry_run_report(project_root: Path | None = None, run_id: str | None = None) -> Path:
    root = project_root or project_root_from_file()
    safe_run_id = run_id or datetime.now(timezone.utc).strftime("dry_run_%Y%m%dT%H%M%SZ")
    output_dir = root / "outputs" / "catalogue_discovery_v3_3" / safe_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    report = build_dry_run_report(root)
    report["run_id"] = safe_run_id
    report["run_folder"] = str(output_dir)
    report_path = output_dir / "dry_run_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path
