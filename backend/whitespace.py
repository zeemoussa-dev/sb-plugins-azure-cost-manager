"""Service whitespace against peers (operator, 2026-10-21): the Azure services
most other customers use and this one does not -- each a conversation, and an
opportunity to create.

A customer "uses" a service when it averaged `USES_MONTHLY` or more over its last
three closed months. A service is common when at least `COMMON_SHARE` of the
customers, and `COMMON_USERS` of them, use it. Peers are every top-level customer,
a group with its affiliates; Marketplace and Unassigned spend are left out, as
they are not services to propose.
"""
from __future__ import annotations

from statistics import median

from . import solution_plays

USES_MONTHLY = 500.0
COMMON_SHARE = 0.3
COMMON_USERS = 3
CLOSED_MONTHS = 3
_NOT_PROPOSED = {solution_plays.MARKETPLACE, solution_plays.UNASSIGNED}


def usage(merged: dict, current_month: str) -> dict[str, float]:
    """Service -> average monthly actual cost over the last closed months."""
    closed = sorted(month for month in merged if month < current_month)[-CLOSED_MONTHS:]
    totals: dict[str, float] = {}
    for month in closed:
        for service, cost in ((merged[month].get("actual") or {}).get("service") or {}).items():
            totals[service] = totals.get(service, 0.0) + cost
    return {service: total / len(closed) for service, total in totals.items()} if closed else {}


def analyse(usage_by_customer: dict[str, dict[str, float]], plays: dict[str, str]) -> dict[str, dict]:
    """Per customer: the services it uses, and its gaps -- common services it does
    not use -- most common first, with what a typical user spends a month."""
    using: dict[str, list[float]] = {}
    for spend in usage_by_customer.values():
        for service, monthly in spend.items():
            if monthly >= USES_MONTHLY and solution_plays.play_of(service, plays) not in _NOT_PROPOSED:
                using.setdefault(service, []).append(monthly)
    peers = len(usage_by_customer)
    common = {service: amounts for service, amounts in using.items()
              if len(amounts) >= COMMON_USERS and peers and len(amounts) / peers >= COMMON_SHARE}
    found = {}
    for customer, spend in usage_by_customer.items():
        uses = {service for service, monthly in spend.items() if monthly >= USES_MONTHLY}
        gaps = sorted(({"service": service, "play": solution_plays.play_of(service, plays),
                        "users": len(amounts), "adoption_pct": round(len(amounts) / peers * 100),
                        "typical_monthly": round(median(amounts), 2)}
                       for service, amounts in common.items() if service not in uses),
                      key=lambda gap: (-gap["users"], -gap["typical_monthly"]))
        found[customer] = {"uses": len(uses), "monthly": round(sum(spend.values()), 2), "gaps": gaps}
    return found
