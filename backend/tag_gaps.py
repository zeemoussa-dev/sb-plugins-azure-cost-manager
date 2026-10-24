"""Where a customer's tagging falls short (operator, 2026-10-24: "tagging recommendations
using Compass, and tagging guidance and gaps for the customer"). Pure, like `tags`:
the gaps are computed here, Compass only turns them into a plan and a guide.

The standard is the six business dimensions `tags` already reads; a gap is a dimension
not used at all, used on too little of the spend, spelled several ways, or whose values
drift (`prd`, `prod`, `PROD`). Subscription names that state an environment show what
tag inheritance could fill in without touching a resource.
"""
from __future__ import annotations

import re

from . import tags

COVERAGE_TARGET = 80.0
DRIFT_SHOWN = 5


def _coverage_by_month(months: dict[str, dict[str, float]], current_month: str) -> list[dict]:
    found = []
    for month, values in sorted(months.items()):
        if month >= current_month:
            continue
        total = sum(values.values())
        if total:
            found.append({"month": month, "coverage_pct": round((total - values.get(tags.UNTAGGED, 0.0)) / total * 100, 1)})
    return found


def _value_drift(entries: dict[str, dict], dimension: str) -> list[dict]:
    """Values written more than one way, the most expensive first: what one spelling
    per value would fold together."""
    spelled: dict[str, dict[str, float]] = {}
    for entry in entries.values():
        for key, data in (((entry.get("tags") or {}).get("by_key") or {}).items()):
            if tags.dimension_of(key) != dimension:
                continue
            for values in (data.get("months") or {}).values():
                for value, cost in values.items():
                    if not value.strip():
                        continue
                    folded = tags.folded_value(dimension, value)
                    group = folded if dimension == "Environment" else re.sub(r"[^a-z0-9]", "", folded.lower())
                    target = spelled.setdefault(group, {})
                    target[value.strip()] = target.get(value.strip(), 0.0) + cost
    drift = [{"value": max(ways, key=ways.get) if dimension != "Environment" else group,
              "written_as": sorted(ways, key=lambda way: -ways[way]), "cost": round(sum(ways.values()), 2)}
             for group, ways in spelled.items() if len(ways) > 1]
    return sorted(drift, key=lambda item: -item["cost"])[:DRIFT_SHOWN]


def gaps(report: dict, entries: dict[str, dict], subscriptions: list[dict], current_month: str) -> dict:
    """`report`: `tags.report`'s result; `subscriptions`: the Solutions view's rows."""
    used = {item["dimension"]: item for item in report["dimensions"]}
    dimensions = []
    for dimension in tags.DIMENSIONS:
        item = used.get(dimension)
        if not item:
            dimensions.append({"dimension": dimension, "used": False})
            continue
        trend = _coverage_by_month(item["months"], current_month)
        last = item["months"].get(item["last_month"] or "", {})
        dimensions.append({
            "dimension": dimension, "used": True, "coverage_pct": item["coverage_pct"],
            "below_target": item["coverage_pct"] is not None and item["coverage_pct"] < COVERAGE_TARGET,
            "untagged_last_month": round(last.get(tags.UNTAGGED, 0.0), 2), "last_month": item["last_month"],
            "coverage_trend": trend[-6:], "spellings": item["all_spellings"], "values": item["values"],
            "value_drift": _value_drift(entries, dimension),
        })
    named = [row for row in subscriptions if row.get("environment")]
    total = sum(row.get("monthly") or 0.0 for row in subscriptions)
    by_environment: dict[str, float] = {}
    for row in named:
        by_environment[row["environment"]] = by_environment.get(row["environment"], 0.0) + (row.get("monthly") or 0.0)
    return {
        "standard": list(tags.DIMENSIONS), "coverage_target_pct": COVERAGE_TARGET,
        "tag_keys": report["tag_keys"], "dimensions": dimensions,
        "missing": [item["dimension"] for item in dimensions if not item["used"]],
        # Environment from the subscription's own name: what inheriting a subscription tag could fill.
        "environment_in_subscription_names": {
            "subscriptions": len(named), "of_subscriptions": len(subscriptions),
            "monthly": round(sum(by_environment.values()), 2),
            "share_pct": round(sum(by_environment.values()) / total * 100, 1) if total else None,
            "by_environment": {name: round(cost, 2) for name, cost in sorted(by_environment.items(), key=lambda item: -item[1])},
        },
    }
