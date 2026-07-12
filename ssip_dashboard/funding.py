from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from statistics import median
from typing import Any


FUNDING_FIELDS = (
    "funding_minimum",
    "funding_maximum",
    "beneficiary_support_minimum",
    "beneficiary_support_maximum",
    "intermediary_support_maximum",
)

UNIT_MULTIPLIERS = {
    "thousand": 1_000,
    "k": 1_000,
    "lakh": 100_000,
    "lac": 100_000,
    "lakhs": 100_000,
    "lacs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
    "million": 1_000_000,
    "mn": 1_000_000,
}

FUNDING_BUCKETS = (
    ("up_to_10_lakh", "Up to Rs 10 lakh"),
    ("10_lakh_to_1_crore", "Rs 10 lakh to Rs 1 crore"),
    ("1_crore_to_10_crore", "Rs 1 crore to Rs 10 crore"),
    ("10_crore_to_50_crore", "Rs 10 crore to Rs 50 crore"),
    ("above_50_crore", "Above Rs 50 crore"),
    ("not_specified", "Funding not specified"),
)


def parse_amount(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    normalized = text.casefold().replace("₹", "rs").replace("inr", "rs")
    match = re.search(
        r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>crores?|cr|lakhs?|lacs?|thousand|million|mn|k)?",
        normalized,
    )
    if match and match.group("unit"):
        amount = Decimal(match.group("number")) * UNIT_MULTIPLIERS[match.group("unit")]
        return int(amount)
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0:
        return None
    return int(amount)


def structured_funding_values(record: Any) -> list[int]:
    values: list[int] = []
    for field in FUNDING_FIELDS:
        amount = parse_amount(getattr(record, field, None))
        if amount is not None:
            values.append(amount)
    return values


def has_structured_funding(record: Any) -> bool:
    return bool(structured_funding_values(record))


def format_inr(amount: int | None) -> str:
    if amount is None:
        return "Not recorded"
    if amount >= 10_000_000:
        return f"Rs {amount / 10_000_000:,.2f} Cr"
    if amount >= 100_000:
        return f"Rs {amount / 100_000:,.2f} Lakh"
    return f"Rs {amount:,.0f}"


def funding_bucket(amount: int | None) -> str:
    if amount is None:
        return "not_specified"
    if amount <= 1_000_000:
        return "up_to_10_lakh"
    if amount <= 10_000_000:
        return "10_lakh_to_1_crore"
    if amount <= 100_000_000:
        return "1_crore_to_10_crore"
    if amount <= 500_000_000:
        return "10_crore_to_50_crore"
    return "above_50_crore"


def funding_bucket_label(bucket: str) -> str:
    labels = dict(FUNDING_BUCKETS)
    return labels.get(bucket, bucket.replace("_", " ").title())


def funding_bucket_counts(records: list[Any]) -> dict[str, int]:
    counts = {bucket: 0 for bucket, _label in FUNDING_BUCKETS}
    for record in records:
        values = structured_funding_values(record)
        key = funding_bucket(max(values) if values else None)
        counts[key] += 1
    return counts


def funding_summary(records: list[Any]) -> dict[str, Any]:
    values: list[int] = []
    records_with_funding = 0
    for record in records:
        record_values = structured_funding_values(record)
        if record_values:
            records_with_funding += 1
            values.extend(record_values)
    return {
        "minimum_recorded_funding": min(values) if values else None,
        "maximum_recorded_funding": max(values) if values else None,
        "median_maximum_funding": int(median(values)) if values else None,
        "records_with_funding": records_with_funding,
        "records_missing_funding": len(records) - records_with_funding,
    }
