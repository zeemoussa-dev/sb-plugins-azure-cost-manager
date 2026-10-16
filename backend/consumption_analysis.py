"""What the consumption rows say: trend, top services, anomalies, burn-down, forecast.

Pure functions over the cached rows -- no Azure, no files -- so every number on
the screen can be pinned by a test. The current month is partial and is never
used as evidence: not as a baseline, not as a run rate, not as an anomaly.
"""
from __future__ import annotations

from datetime import date

from . import months

TOP_SERVICES = 10
BASELINE_MONTHS = 3
RUN_RATE_MONTHS = 3
# A service is flagged when its month moves this far from its baseline...
ANOMALY_CHANGE_PCT = 50.0
# ...and the move is at least this share of the whole month, so a service going
# from 2 to 5 does not bury the one that went from 40k to 90k.
ANOMALY_MIN_SHARE_PCT = 2.0


def _pct(new: float, old: float) -> float | None:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _sum_by(rows: list[dict], key: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        totals[row[key]] = totals.get(row[key], 0.0) + row["cost"]
    return totals


def monthly_totals(cached_months: dict, current_month: str) -> list[dict]:
    trend, previous = [], None
    for month in sorted(cached_months):
        entry = cached_months[month]
        actual = sum(row["cost"] for row in entry.get("actual") or [])
        amortized = sum(row["cost"] for row in entry.get("amortized") or [])
        partial = month >= current_month
        trend.append({"month": month, "actual": round(actual, 2), "amortized": round(amortized, 2),
                      "mom_pct": None if partial or previous is None else _pct(actual, previous),
                      "partial": partial})
        if not partial:
            previous = actual
    return trend


def breakdown(cached_months: dict, month: str, key: str, limit: int | None = TOP_SERVICES) -> dict:
    """The month's spend by `service` or `subscription`, against the month before."""
    rows = (cached_months.get(month) or {}).get("actual") or []
    before = (cached_months.get(months.shift(month, -1)) or {}).get("actual") or []
    this_month, last_month = _sum_by(rows, key), _sum_by(before, key)
    total = sum(this_month.values())
    ranked = sorted(this_month.items(), key=lambda item: item[1], reverse=True)
    shown = ranked[:limit] if limit else ranked
    return {
        "month": month,
        "total": round(total, 2),
        "rows": [{"name": name, "cost": round(cost, 2),
                  "share_pct": round(cost / total * 100, 1) if total else 0.0,
                  "previous": round(last_month.get(name, 0.0), 2),
                  "change_pct": _pct(cost, last_month.get(name, 0.0))}
                 for name, cost in shown],
        "others": round(sum(cost for _, cost in ranked[len(shown):]), 2),
    }


def anomalies(cached_months: dict, month: str) -> list[dict]:
    """Services whose `month` moved sharply against their trailing baseline."""
    by_month = {candidate: _sum_by((cached_months.get(candidate) or {}).get("actual") or [], "service")
                for candidate in months.span(months.shift(month, -BASELINE_MONTHS), month)}
    baseline_months = [months.shift(month, -offset) for offset in range(1, BASELINE_MONTHS + 1)
                       if months.shift(month, -offset) in cached_months]
    if not baseline_months or month not in cached_months:
        return []
    current = by_month[month]
    floor = sum(current.values()) * ANOMALY_MIN_SHARE_PCT / 100
    services = set(current) | {service for candidate in baseline_months for service in by_month[candidate]}
    found = []
    for service in services:
        cost = current.get(service, 0.0)
        baseline = sum(by_month[candidate].get(service, 0.0) for candidate in baseline_months) / len(baseline_months)
        delta = cost - baseline
        if delta == 0 or abs(delta) < floor:
            continue
        if baseline == 0:
            kind = "new"
        elif delta / baseline * 100 >= ANOMALY_CHANGE_PCT:
            kind = "spike"
        elif -delta / baseline * 100 >= ANOMALY_CHANGE_PCT:
            kind = "drop"
        else:
            continue
        found.append({"service": service, "month": month, "kind": kind, "cost": round(cost, 2),
                      "baseline": round(baseline, 2), "change": round(delta, 2),
                      "change_pct": _pct(cost, baseline)})
    return sorted(found, key=lambda anomaly: abs(anomaly["change"]), reverse=True)


def run_rate(trend: list[dict]) -> float | None:
    closed = [month["actual"] for month in trend if not month["partial"]][-RUN_RATE_MONTHS:]
    return round(sum(closed) / len(closed), 2) if closed else None


def _exhaustion(remaining: float, rate: float | None, today: date) -> str | None:
    if not rate or rate <= 0:
        return None
    months_left = remaining / rate
    if months_left > 240:
        return None
    return months.shift(months.month_of(today), int(months_left))


def burn_down(commitment: dict | None, trend: list[dict], today: date) -> dict | None:
    """How far through the agreement's commitment the customer is, and where
    the current run rate takes them."""
    if not commitment:
        return None
    rate = run_rate(trend)
    if commitment["kind"] == "macc":
        lots = [lot for lot in commitment.get("lots") or [] if (lot.get("status") or "Active") == "Active"]
        if not lots:
            return None
        original = sum(lot["original"] for lot in lots)
        remaining = sum(lot["remaining"] for lot in lots)
        end = max((lot["end"] for lot in lots if lot.get("end")), default=None)
        start = min((lot["start"] for lot in lots if lot.get("start")), default=None)
        currency = lots[0].get("currency")
    else:
        balance = commitment.get("balance") or {}
        original = balance.get("beginning_balance", 0.0) + balance.get("new_purchases", 0.0)
        remaining = balance.get("ending_balance", 0.0)
        start = end = None
        currency = balance.get("currency")
    consumed = original - remaining
    result = {
        "kind": commitment["kind"], "currency": currency,
        "original": round(original, 2), "consumed": round(consumed, 2), "remaining": round(remaining, 2),
        "consumed_pct": round(consumed / original * 100, 1) if original else None,
        "start": start, "end": end, "run_rate": rate,
        "projected_exhaustion": _exhaustion(remaining, rate, today),
        "projected_shortfall": None, "verdict": None,
    }
    if remaining <= 0:
        result["verdict"] = "Commitment fully consumed"
    elif end and rate:
        months_to_end = max(0.0, months.months_between(today, date.fromisoformat(end)))
        shortfall = remaining - rate * months_to_end
        result["projected_shortfall"] = round(max(0.0, shortfall), 2)
        result["verdict"] = ("On track to consume the commitment before the term ends" if shortfall <= 0
                             else "Shortfall projected at the end of the term")
    elif rate:
        result["verdict"] = "Balance runs out at the current run rate"
    return result


def forecast(trend: list[dict], azure_forecast: list[dict] | None, today: date) -> dict:
    """The rest of the calendar year, month by month, and where the year lands.
    Azure's own forecast wins where it has one; otherwise the run rate."""
    current_month = months.month_of(today)
    remaining_months = months.span(current_month, f"{today.year:04d}-12")
    from_azure = {row["month"]: row["cost"] for row in azure_forecast or []}
    rate = run_rate(trend)
    actual_so_far = {month["month"]: month["actual"] for month in trend}
    projected = []
    for month in remaining_months:
        if month in from_azure:
            cost, source = from_azure[month], "azure"
        elif rate is not None:
            cost, source = rate, "run-rate"
        else:
            continue
        if month == current_month:
            billed = actual_so_far.get(month, 0.0)
            # Azure forecasts only the unbilled remainder of the month.
            cost = cost + billed if source == "azure" else max(cost, billed)
        projected.append({"month": month, "cost": round(cost, 2), "source": source})
    closed_this_year = sum(month["actual"] for month in trend
                           if month["month"].startswith(f"{today.year:04d}-") and not month["partial"])
    return {
        "source": "azure" if from_azure else ("run-rate" if rate is not None else None),
        "months": projected,
        "year": today.year,
        "year_to_date_closed": round(closed_this_year, 2),
        "year_end_total": round(closed_this_year + sum(month["cost"] for month in projected), 2)
        if projected else None,
    }


def analyse(entry: dict, today: date) -> dict:
    cached_months = entry.get("months") or {}
    current_month = months.month_of(today)
    trend = monthly_totals(cached_months, current_month)
    last_closed = months.shift(current_month, -1)
    currency = next((row.get("currency") for month in cached_months.values()
                     for row in month.get("actual") or [] if row.get("currency")), None)
    return {
        "currency": currency,
        "months": trend,
        "last_closed_month": last_closed,
        "top_services": breakdown(cached_months, last_closed, "service"),
        "subscriptions": breakdown(cached_months, last_closed, "subscription", limit=None),
        "anomalies": anomalies(cached_months, last_closed),
        "commitment": burn_down(entry.get("commitment"), trend, today),
        "forecast": forecast(trend, entry.get("forecast"), today),
    }
