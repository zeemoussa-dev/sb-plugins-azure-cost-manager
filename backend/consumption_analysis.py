"""What a customer's consumption says: trend, breakdowns, anomalies, burn-down
against the signed value, forecast.

Pure functions over local data -- no Azure, no files -- so every number on the
screen can be pinned by a test. A customer's enrollments are merged first, so a
renewal or a linked enrollment reads as one customer. The current month is
partial and is never used as evidence: not as a baseline, not as a run rate, not
as an anomaly.
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
COST_KINDS = ("actual", "amortized")
BREAKDOWNS = ("service", "subscription")


def _pct(new: float, old: float) -> float | None:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _add(into: dict[str, float], name: str, cost: float) -> None:
    into[name] = into.get(name, 0.0) + cost


def merge(entries: dict[str, dict], labels: dict[str, str] | None = None) -> tuple[dict, str | None]:
    """The customer's accounts as one: per month, per cost kind, spend by
    `service`, `subscription` and `account` (the enrollment, labelled)."""
    labels = labels or {}
    merged: dict[str, dict] = {}
    currency = None
    for account, entry in entries.items():
        for month, data in (entry.get("months") or {}).items():
            target = merged.setdefault(month, {kind: {"service": {}, "subscription": {}, "account": {}}
                                               for kind in COST_KINDS})
            currency = currency or data.get("currency")
            for kind in COST_KINDS:
                spend = data.get(kind) or {}
                for key in BREAKDOWNS:
                    for name, cost in (spend.get(key) or {}).items():
                        _add(target[kind][key], name, cost)
                total = sum((spend.get("service") or {}).values())
                if total:
                    _add(target[kind]["account"], labels.get(account, account), total)
    return merged, currency


def merge_forecasts(entries: dict[str, dict]) -> list[dict] | None:
    totals: dict[str, float] = {}
    for entry in entries.values():
        for row in entry.get("forecast") or []:
            _add(totals, row["month"], row["cost"])
    return [{"month": month, "cost": cost} for month, cost in sorted(totals.items())] or None


def _total(merged: dict, month: str, kind: str = "actual") -> float:
    return sum(((merged.get(month) or {}).get(kind) or {}).get("service", {}).values())


def monthly_totals(merged: dict, current_month: str) -> list[dict]:
    trend, previous = [], None
    for month in sorted(merged):
        actual, amortized = _total(merged, month), _total(merged, month, "amortized")
        partial = month >= current_month
        trend.append({"month": month, "actual": round(actual, 2), "amortized": round(amortized, 2),
                      "mom_pct": None if partial or previous is None else _pct(actual, previous),
                      "partial": partial})
        if not partial:
            previous = actual
    return trend


def breakdown(merged: dict, month: str, key: str, limit: int | None = TOP_SERVICES) -> dict:
    """The month's spend by `service`, `subscription` or `account`, against the month before."""
    this_month = ((merged.get(month) or {}).get("actual") or {}).get(key, {})
    last_month = ((merged.get(months.shift(month, -1)) or {}).get("actual") or {}).get(key, {})
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


def anomalies(merged: dict, month: str) -> list[dict]:
    """Services whose `month` moved sharply against their trailing baseline."""
    def services(candidate: str) -> dict[str, float]:
        return ((merged.get(candidate) or {}).get("actual") or {}).get("service", {})

    baseline_months = [months.shift(month, -offset) for offset in range(1, BASELINE_MONTHS + 1)
                       if months.shift(month, -offset) in merged]
    if not baseline_months or month not in merged:
        return []
    current = services(month)
    floor = sum(current.values()) * ANOMALY_MIN_SHARE_PCT / 100
    names = set(current) | {name for candidate in baseline_months for name in services(candidate)}
    found = []
    for service in names:
        cost = current.get(service, 0.0)
        baseline = sum(services(candidate).get(service, 0.0) for candidate in baseline_months) / len(baseline_months)
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


def burn_down(commitment: dict | None, trend: list[dict], today: date) -> dict | None:
    """Consumption since the term started against what the customer signed for:
    where it stands, where an even pace would have it, and where the run rate
    takes it by the end of the term."""
    if not commitment:
        return None
    amount = float(commitment["amount"])
    start, end = date.fromisoformat(commitment["start"]), date.fromisoformat(commitment["end"])
    start_month, end_month = months.month_of(start), months.month_of(end)
    in_term = [month for month in trend if start_month <= month["month"] <= end_month]
    cumulative, running = [], 0.0
    for month in in_term:
        running += month["actual"]
        cumulative.append({"month": month["month"], "consumed": round(running, 2), "partial": month["partial"]})
    consumed = running
    term_days = max((end - start).days, 1)
    elapsed_share = min(max((today - start).days / term_days, 0.0), 1.0)
    on_pace = amount * elapsed_share
    rate = run_rate(trend)
    months_left = max(0.0, months.months_between(today, end))
    projected_at_end = consumed + (rate or 0.0) * months_left
    exhaustion = None
    if rate and rate > 0 and consumed < amount:
        exhaustion = months.shift(months.month_of(today), int((amount - consumed) / rate))
    return {
        **commitment,
        "consumed": round(consumed, 2),
        "remaining": round(amount - consumed, 2),
        "consumed_pct": round(consumed / amount * 100, 1),
        "elapsed_pct": round(elapsed_share * 100, 1),
        "on_pace": round(on_pace, 2),
        "pace_gap": round(consumed - on_pace, 2),
        "run_rate": rate,
        "projected_at_end": round(projected_at_end, 2),
        "projected_shortfall": round(max(0.0, amount - projected_at_end), 2),
        "projected_exhaustion": exhaustion if exhaustion and exhaustion <= end_month else None,
        "cumulative": cumulative,
        "verdict": ("Commitment consumed" if consumed >= amount
                    else "On track to consume the commitment within the term" if projected_at_end >= amount
                    else "Shortfall projected at the end of the term"),
    }


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


def analyse(merged: dict, currency: str | None, commitment: dict | None,
            azure_forecast: list[dict] | None, today: date) -> dict:
    current_month = months.month_of(today)
    trend = monthly_totals(merged, current_month)
    last_closed = months.shift(current_month, -1)
    return {
        "currency": currency,
        "months": trend,
        "last_closed_month": last_closed,
        "top_services": breakdown(merged, last_closed, "service"),
        "subscriptions": breakdown(merged, last_closed, "subscription", limit=None),
        "enrollments": breakdown(merged, last_closed, "account", limit=None),
        "anomalies": anomalies(merged, last_closed),
        "commitment": burn_down(commitment, trend, today),
        "forecast": forecast(trend, azure_forecast, today),
    }
