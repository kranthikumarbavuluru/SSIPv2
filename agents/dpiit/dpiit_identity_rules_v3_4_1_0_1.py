from __future__ import annotations

import re


CANONICAL_DEPARTMENT = "Department for Promotion of Industry and Internal Trade (DPIIT)"
CURRENT_ALIASES = {
    "dpiit",
    "department for promotion of industry and internal trade",
    "department of promotion of industry and internal trade",
}
HISTORICAL_ALIASES = {"dipp", "department of industrial policy and promotion"}
NON_DEPARTMENT_IDENTITIES = {"startup india", "startup india hub", "bhaskar", "maarg"}

SCHEME_ALIAS_GROUPS = {
    "Startup India Seed Fund Scheme": {"startup india seed fund", "startup india seed fund scheme", "sisfs"},
    "Fund of Funds for Startups": {"fund of funds for startups", "ffs"},
    "Credit Guarantee Scheme for Startups": {"credit guarantee scheme for startups", "cgss"},
}


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def canonical_department(value: str) -> tuple[str, str]:
    key = normalized_name(value)
    if key in CURRENT_ALIASES or key in HISTORICAL_ALIASES:
        status = "CURRENT_ALIAS" if key in CURRENT_ALIASES else "HISTORICAL_ALIAS"
        return CANONICAL_DEPARTMENT, status
    return value.strip(), "NOT_A_DEPARTMENT_ALIAS"


def alias_group(value: str) -> str:
    key = normalized_name(value)
    for canonical, aliases in SCHEME_ALIAS_GROUPS.items():
        if key in {normalized_name(alias) for alias in aliases}:
            return canonical
    return ""

