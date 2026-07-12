from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import re
from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.catalogue_populations import (
    primary_sector_counts,
    primary_support_type_counts,
    split_catalogue_populations,
)
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.funding import funding_bucket_counts
from ssip_dashboard.metrics import (
    compute_metrics,
    government_level_coverage,
    status_coverage,
)

config = DashboardConfig.from_env()
bundle = load_catalogue(config)
populations = split_catalogue_populations(bundle.records)
main_records = populations.main_scheme_records
metrics = compute_metrics(bundle.records)

government = government_level_coverage(bundle.records)
sectors = primary_sector_counts(main_records)
supports = primary_support_type_counts(main_records)
funding = funding_bucket_counts(main_records)
statuses = status_coverage(bundle.records)

bad_pattern = re.compile(
    r"(?i)(?:\.pdf$|%20|report|whitepaper|playbook|manual|guideline|"
    r"brochure|sitemap|directory|faq|awardee|result)"
)
bad_names = [
    record.scheme_name
    for record in main_records
    if bad_pattern.search(record.scheme_name)
]

print("=" * 72)
print("SSIP v3.3.3 population verification")
print("=" * 72)
print("Preview path:", config.normalization_path)
print("Loaded rows:", len(bundle.records))
print("Main schemes/programmes:", len(main_records))
print("Application calls:", len(populations.application_call_records))
print("Evidence-only:", len(populations.evidence_only_records))
print("Excluded:", len(populations.excluded_records))
print()
print("Metric total:", metrics.total_catalogue_records)
print("Government total:", sum(government.values()))
print("Sector total:", sum(sectors.values()))
print("Support total:", sum(supports.values()))
print("Funding total:", sum(funding.values()))
print("Status total:", sum(statuses.values()))
print("Bad names remaining:", len(bad_names))
for name in bad_names[:20]:
    print(" -", name)

expected = len(main_records)
checks = {
    "metric": metrics.total_catalogue_records == expected,
    "government": sum(government.values()) == expected,
    "sector": sum(sectors.values()) == expected,
    "support": sum(supports.values()) == expected,
    "funding": sum(funding.values()) == expected,
    "status": sum(statuses.values()) == expected,
    "clean_names": not bad_names,
}
print()
for name, passed in checks.items():
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
raise SystemExit(0 if all(checks.values()) else 1)
