"""This month so far: what is changing in a customer's tenant, early enough to
open an opportunity (operator, 2026-10-18).

Read from the daily figures the on-demand "Refresh this month" brings
(`entry["daily"]`: last month and this one, by day, per service, subscription
and resource group). Azure's daily costs lag a day or two, so "this month" runs
to the last day there is data for, and last month is compared over the same
number of days.

A workload is NEW when it cost nothing all last month -- and, for a service or
subscription, nothing in the three closed months before it either, from the
monthly sync. Every new workload is flagged (operator's choice: "Any new
workload"); the operator decides which is an opportunity.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from . import months, tags

DIMENSIONS = ("service", "subscription", "resource_group", "tag:Project", "tag:Owner", "tag:Environment")
LABELS = {"service": "Service", "subscription": "Subscription", "resource_group": "Resource group",
          "tag:Project": "Project", "tag:Owner": "Owner", "tag:Environment": "Environment"}
LOOKBACK_MONTHS = 3
TOP_MOVERS = 8
UNTAGGED_VALUES = {"", "Unassigned"}


def _summed(entries: dict[str, dict], key: str) -> dict[str, dict[str, float]]:
    """day -> name -> cost across the enrollments. A tag's values are folded as the
    Tags report folds them (prd/prod/production → Production); untagged is left out."""
    dimension = key[4:] if key.startswith("tag:") else None
    days: dict[str, dict[str, float]] = {}
    spelled: dict[str, dict[str, float]] = {}
    for entry in entries.values():
        for day, names in ((entry.get("daily") or {}).get(key) or {}).items():
            target = days.setdefault(day, {})
            for name, cost in names.items():
                if dimension:
                    if name.strip() in UNTAGGED_VALUES:
                        continue
                    name = tags.folded_value(dimension, name)
                    # "Atlas" and "atlas " are one project: the most-billed spelling names it.
                    variants = spelled.setdefault(" ".join(name.lower().split()), {})
                    variants[name] = variants.get(name, 0.0) + cost
                target[name] = target.get(name, 0.0) + cost
    if not dimension:
        return days
    canonical = {variant: max(variants, key=variants.get) for variants in spelled.values() for variant in variants}
    merged: dict[str, dict[str, float]] = {}
    for day, names in days.items():
        target = merged.setdefault(day, {})
        for name, cost in names.items():
            target[canonical[name]] = target.get(canonical[name], 0.0) + cost
    return merged


def _present(entries: dict[str, dict], key: str) -> bool:
    return any(key in (entry.get("daily") or {}) for entry in entries.values())


def _total(days: dict[str, dict[str, float]], first: str, last: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for day, names in days.items():
        if first <= day <= last:
            for name, cost in names.items():
                totals[name] = totals.get(name, 0.0) + cost
    return totals


def _seen_before(merged: dict, key: str, current_month: str) -> set[str]:
    """Names with cost in the closed months before last month, from the monthly sync."""
    seen: set[str] = set()
    for offset in range(2, LOOKBACK_MONTHS + 2):
        month = months.shift(current_month, -offset)
        seen |= {name for name, cost in (((merged.get(month) or {}).get("actual") or {}).get(key) or {}).items()
                 if cost > 0}
    return seen


def analyse(entries: dict[str, dict], merged: dict, today: date) -> dict:
    fetched = [(entry.get("daily") or {}).get("fetched_at") for entry in entries.values()]
    fetched = [stamp for stamp in fetched if stamp]
    if not fetched:
        return {"has_data": False}
    # A refresh cut off part-way leaves some enrollments unfetched; their spend is
    # absent from every figure, so the page must say so rather than look complete.
    missing = sorted(name for name, entry in entries.items() if not (entry.get("daily") or {}).get("fetched_at"))
    current = months.month_of(today)
    previous = months.shift(current, -1)
    service_days = _summed(entries, "service")
    with_data = sorted(day for day, names in service_days.items() if day.startswith(current) and names)
    through = with_data[-1] if with_data else f"{current}-01"
    elapsed = int(through[8:10]) if with_data else 0
    days_in_month = monthrange(today.year, today.month)[1]
    previous_days = monthrange(int(previous[:4]), int(previous[5:]))[1]
    same_last = f"{previous}-{min(elapsed, previous_days):02d}" if elapsed else f"{previous}-00"

    def total_of(days: dict, first: str, last: str) -> float:
        return sum(_total(days, first, last).values())

    mtd = total_of(service_days, f"{current}-01", through)
    last_same = total_of(service_days, f"{previous}-01", same_last)
    last_full = total_of(service_days, f"{previous}-01", f"{previous}-{previous_days:02d}")

    daily = []
    running_now = running_then = 0.0
    for day_number in range(1, days_in_month + 1):
        this_day = f"{current}-{day_number:02d}"
        then_day = f"{previous}-{day_number:02d}" if day_number <= previous_days else None
        now = sum((service_days.get(this_day) or {}).values()) if day_number <= elapsed else None
        then = sum((service_days.get(then_day) or {}).values()) if then_day else None
        running_now += now or 0.0
        running_then += then or 0.0
        daily.append({"day": day_number, "this_month": round(now, 2) if now is not None else None,
                      "last_month": round(then, 2) if then is not None else None,
                      "this_month_to_date": round(running_now, 2) if now is not None else None,
                      "last_month_to_date": round(running_then, 2) if then is not None else None})

    dimensions, new_workloads = {}, []
    for key in DIMENSIONS:
        if key.startswith("tag:") and not _present(entries, key):
            continue  # the refresh found no such tag on these enrollments, or tags never synced
        days = _summed(entries, key)
        now = _total(days, f"{current}-01", through)
        then = _total(days, f"{previous}-01", same_last)
        last_month_any = {name for name, cost in _total(days, f"{previous}-01", f"{previous}-{previous_days:02d}").items()
                          if cost > 0}
        monthly_known = key in ("service", "subscription")
        seen = last_month_any | (_seen_before(merged, key, current) if monthly_known else set())
        rows = []
        for name in set(now) | set(then):
            cost_now, cost_then = now.get(name, 0.0), then.get(name, 0.0)
            is_new = cost_now > 0 and name not in seen
            rows.append({"name": name, "this_month": round(cost_now, 2), "last_month_same_days": round(cost_then, 2),
                         "change": round(cost_now - cost_then, 2),
                         "change_pct": round((cost_now - cost_then) / cost_then * 100, 1) if cost_then else None,
                         "new": is_new})
            if is_new:
                new_workloads.append({"kind": key, "kind_label": LABELS[key], "name": name, "this_month": round(cost_now, 2)})
        movers = sorted((row for row in rows if not row["new"] and row["change"] > 0), key=lambda row: -row["change"])
        dimensions[key] = {"label": LABELS[key], "movers": movers[:TOP_MOVERS],
                           "new": sorted((row for row in rows if row["new"]), key=lambda row: -row["this_month"]),
                           # Every row: the page shows the first few and "Show all" the rest.
                           "rows": sorted(rows, key=lambda row: -row["this_month"])}

    return {
        "has_data": True,
        "fetched_at": min(fetched),
        "missing_enrollments": missing,
        "month": current,
        "through": through if elapsed else None,
        "days_elapsed": elapsed,
        "days_in_month": days_in_month,
        "month_to_date": round(mtd, 2),
        "last_month_same_days": round(last_same, 2),
        "pace_pct": round((mtd - last_same) / last_same * 100, 1) if last_same else None,
        "projected_month_end": round(mtd / elapsed * days_in_month, 2) if elapsed else None,
        "last_month_total": round(last_full, 2),
        "daily": daily,
        "dimensions": dimensions,
        "new_workloads": sorted(new_workloads, key=lambda item: -item["this_month"]),
    }
