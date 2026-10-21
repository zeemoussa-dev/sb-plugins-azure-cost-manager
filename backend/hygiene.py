"""Subscription hygiene for one customer (operator, 2026-10-21): how many
subscriptions it runs, which are new, which went dormant, how many are tiny, and
how concentrated its spend is -- the estate behind the bill.

Read from the subscription breakdown of closed months (Cost Management's actual
cost). Tag coverage sits beside it on the page, from the Tags report.
"""
from __future__ import annotations

# A subscription spending under this a month is tiny -- sprawl, or a sandbox.
TINY_MONTHLY = 50.0
# A subscription averaging this or more over three months, then under a tenth of
# it, went dormant; one at this or more that was not there before is new.
MATERIAL_MONTHLY = 100.0
DORMANT_SHARE = 0.1
LISTED = 10


def analyse(merged: dict, current_month: str) -> dict:
    closed = sorted(month for month in merged if month < current_month)
    if not closed:
        return {"last_month": None}

    def subscriptions_of(month: str) -> dict[str, float]:
        return ((merged.get(month) or {}).get("actual") or {}).get("subscription") or {}

    last = closed[-1]
    now = {name: cost for name, cost in subscriptions_of(last).items() if cost > 0}
    earlier = [subscriptions_of(month) for month in closed[-4:-1]]
    earlier_avg = {name: sum(month.get(name, 0.0) for month in earlier) / len(earlier)
                   for name in {name for month in earlier for name in month}} if earlier else {}
    year = {name for month in closed[-12:] for name, cost in subscriptions_of(month).items() if cost > 0}
    new = sorted(({"subscription": name, "last": round(cost, 2)} for name, cost in now.items()
                  if cost >= MATERIAL_MONTHLY and earlier and not any(month.get(name) for month in earlier)),
                 key=lambda row: -row["last"])
    dormant = sorted(({"subscription": name, "before": round(avg, 2), "last": round(now.get(name, 0.0), 2)}
                      for name, avg in earlier_avg.items()
                      if avg >= MATERIAL_MONTHLY and now.get(name, 0.0) < avg * DORMANT_SHARE),
                     key=lambda row: -row["before"])
    total = sum(now.values())
    ranked = sorted(now.values(), reverse=True)
    return {
        "last_month": last,
        "subscriptions": len(now),
        "subscriptions_12m": len(year),
        "tiny": sum(1 for cost in now.values() if cost < TINY_MONTHLY),
        "top_share_pct": round(ranked[0] / total * 100, 1) if total else None,
        "top3_share_pct": round(sum(ranked[:3]) / total * 100, 1) if total else None,
        "new": new[:LISTED],
        "new_count": len(new),
        "dormant": dormant[:LISTED],
        "dormant_count": len(dormant),
    }
