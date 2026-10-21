"""Marketplace renewals calendar (operator, 2026-10-21): when each recurring
Marketplace purchase is next expected to charge, and for how much.

Azure gives no renewal date, so it is read from the charges: a series is one
customer's recurring charges for one publisher, offer, plan and subscription. Its
cadence is the most common gap between charged months -- monthly, yearly, or
other -- and the next renewal is the last charge plus that gap. A series charged
once is taken as yearly, the common term for SaaS, and says so. A renewal whose
month has passed without a charge is overdue: renewed elsewhere, or cancelled.
"""
from __future__ import annotations

from collections import Counter

from . import months
from .consumption_analysis import is_core42_publisher

ASSUMED_CADENCE = 12
# An overdue renewal older than this is history, not a calendar entry.
OVERDUE_MONTHS = 3


def _gap(earlier: str, later: str) -> int:
    return (int(later[:4]) - int(earlier[:4])) * 12 + int(later[5:7]) - int(earlier[5:7])


def series(customers: list[tuple[str, dict[str, dict]]]) -> dict[tuple, dict[str, float]]:
    """(customer, publisher, offer, plan, subscription) -> month -> recurring charge."""
    found: dict[tuple, dict[str, float]] = {}
    for name, entries in customers:
        for entry in entries.values():
            for month, data in (entry.get("months") or {}).items():
                for item in ((data.get("marketplace") or {}).get("items") or []):
                    if not item.get("recurring") or not item.get("cost"):
                        continue
                    key = (name, item["publisher"], item["offer"], item.get("plan") or "", item.get("subscription") or "")
                    charges = found.setdefault(key, {})
                    charges[month] = charges.get(month, 0.0) + item["cost"]
    return found


def calendar(customers: list[tuple[str, dict[str, dict]]], current_month: str) -> list[dict]:
    rows = []
    for (customer, publisher, offer, plan, subscription), charges in series(customers).items():
        charged = sorted(month for month, cost in charges.items() if cost > 0)
        gaps = [_gap(a, b) for a, b in zip(charged, charged[1:])]
        cadence = Counter(gaps).most_common(1)[0][0] if gaps else ASSUMED_CADENCE
        next_month = months.shift(charged[-1], cadence)
        overdue = next_month < current_month
        if overdue and _gap(next_month, current_month) > OVERDUE_MONTHS:
            continue
        rows.append({
            "customer": customer, "publisher": publisher, "offer": offer, "plan": plan, "subscription": subscription,
            "core42": is_core42_publisher(publisher),
            "cadence_months": cadence, "cadence_assumed": not gaps,
            "cadence": "monthly" if cadence == 1 else "yearly" if cadence == 12 else f"every {cadence} months",
            "last_month": charged[-1], "last_amount": round(charges[charged[-1]], 2),
            "charges": len(charged), "next_month": next_month,
            "status": "overdue" if overdue else "due this month" if next_month == current_month else "upcoming",
        })
    return sorted(rows, key=lambda row: (row["next_month"], -row["last_amount"]))
