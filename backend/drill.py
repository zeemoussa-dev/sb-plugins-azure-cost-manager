"""Drilling into one thing a report shows (operator, 2026-10-23: "check any text can
be drilled down ... every graph"): a service, a subscription, a solution play or a
month -- its monthly trend, and what it is made of on the other axis.

A service opens into the subscriptions that run it, a subscription into its
services (and resource groups), a play into its services, a month into its
services and subscriptions. The pairs behind the first two are kept since 0.39.0;
a month synced before has none until it is fetched again, and the answer says so.
"""
from __future__ import annotations

from . import months, solution_plays

KINDS = ("service", "subscription", "play", "month")
RECENT_MONTHS = 3
YEAR = 12


def _closed(merged: dict, current_month: str) -> list[str]:
    return [month for month in sorted(merged) if month < current_month]


def _pairs(merged: dict, month: str) -> dict[str, dict[str, float]]:
    return (merged.get(month) or {}).get("actual", {}).get("pairs") or {}


def _sum_into(into: dict[str, dict[str, float]], window: str, found: dict[str, float]) -> None:
    for name, cost in found.items():
        row = into.setdefault(name, {"recent": 0.0, "year": 0.0})
        row[window] += cost


def _rows(totals: dict[str, dict[str, float]], recent_months: int) -> list[dict]:
    rows = [{"name": name, "monthly": round(values["recent"] / max(1, recent_months), 2),
             "last_12": round(values["year"], 2)} for name, values in totals.items()
            if round(values["recent"], 2) or round(values["year"], 2)]
    return sorted(rows, key=lambda row: (-row["monthly"], -row["last_12"]))


def _breakdown(merged: dict, months_wanted: list[str], recent: list[str], pick) -> list[dict]:
    totals: dict[str, dict[str, float]] = {}
    for month in months_wanted:
        found = pick(month)
        if month in recent:
            _sum_into(totals, "recent", found)
        _sum_into(totals, "year", found)
    return _rows(totals, len(recent))


def from_footprints(entries: dict[str, dict], kind: str, name: str) -> list[dict]:
    """The same breakdown from the tags sync's footprint (the last closed months by
    subscription and service), for history synced before the pairs were kept."""
    totals: dict[str, float] = {}
    for entry in entries.values():
        footprint = entry.get("footprint") or {}
        spread = footprint.get("months") or 1
        for subscription, found in (footprint.get("subscriptions") or {}).items():
            services = found.get("services") or {}
            if kind == "service" and name in services:
                totals[subscription] = totals.get(subscription, 0.0) + services[name] / spread
            elif kind == "subscription" and subscription == name:
                for service, cost in services.items():
                    totals[service] = totals.get(service, 0.0) + cost / spread
    return sorted(({"name": key, "monthly": round(cost, 2), "last_12": None} for key, cost in totals.items()
                   if round(cost, 2)), key=lambda row: -row["monthly"])


def analyse(merged: dict, kind: str, name: str, current_month: str, plays: dict[str, str],
            resource_groups: dict[str, float] | None = None) -> dict:
    """`{kind, name, trend, parts, parts_kind, ...}` for one item of a customer's merged months."""
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    closed = _closed(merged, current_month)
    year = closed[-YEAR:]
    recent = closed[-RECENT_MONTHS:]

    def spend(month: str, axis: str) -> dict[str, float]:
        return (merged.get(month) or {}).get("actual", {}).get(axis) or {}

    def by_play(month: str) -> dict[str, float]:
        data = merged.get(month) or {}
        return solution_plays.split(spend(month, "service"), data.get("meters"), plays,
                                    (data.get("measured") or {}).get("marketplace"))

    if kind == "month":
        if name not in merged:
            raise ValueError(f"no data for {name}")
        services = sorted(spend(name, "service").items(), key=lambda item: -item[1])
        subscriptions = sorted(spend(name, "subscription").items(), key=lambda item: -item[1])
        previous = months.shift(name, -1)
        before = spend(previous, "service")
        return {"kind": kind, "name": name, "previous": previous if previous in merged else None,
                "total": round(sum(cost for _, cost in services), 2),
                "parts_kind": "service",
                "parts": [{"name": service, "cost": round(cost, 2), "before": round(before.get(service, 0.0), 2)}
                          for service, cost in services if round(cost, 2)],
                "subscriptions": [{"name": sub, "cost": round(cost, 2)} for sub, cost in subscriptions if round(cost, 2)],
                "by_play": [{"name": play, "cost": round(cost, 2)}
                            for play, cost in sorted(by_play(name).items(), key=lambda item: -item[1]) if round(cost, 2)]}

    if kind == "service":
        trend = [{"month": month, "cost": round(spend(month, "service").get(name, 0.0), 2)} for month in sorted(merged)]
        parts = _breakdown(merged, year, recent, lambda month: {
            subscription: services[name] for subscription, services in _pairs(merged, month).items() if name in services})
        parts_kind, extra = "subscription", {"play": solution_plays.play_of(name, plays)}
    elif kind == "subscription":
        trend = [{"month": month, "cost": round(spend(month, "subscription").get(name, 0.0), 2)} for month in sorted(merged)]
        parts = _breakdown(merged, year, recent, lambda month: _pairs(merged, month).get(name) or {})
        parts_kind = "service"
        extra = {"resource_groups": [{"name": group, "monthly": round(cost, 2)} for group, cost in
                                     sorted((resource_groups or {}).items(), key=lambda item: -item[1])[:15]]}
    else:
        trend = [{"month": month, "cost": round(by_play(month).get(name, 0.0), 2)} for month in sorted(merged)]
        parts = _breakdown(merged, year, recent, lambda month: {
            service: cost for service, cost in spend(month, "service").items()
            if solution_plays.play_of(service, plays) == name})
        parts_kind, extra = "service", {}
    with_pairs = [month for month in year if _pairs(merged, month)]
    return {"kind": kind, "name": name, "trend": trend, "parts_kind": parts_kind, "parts": parts,
            "recent_months": recent, "pairs_missing": kind in ("service", "subscription") and len(with_pairs) < len(year),
            **extra}
