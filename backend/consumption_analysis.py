"""What a customer's consumption says: trend, breakdowns, anomalies, burn-down
against the signed value, forecast.

Pure functions over local data -- no Azure, no files -- so every number on the
screen can be pinned by a test. A customer's enrollments are merged first, so a
renewal or a linked enrollment reads as one customer. The current month is
partial and is never used as evidence: not as a baseline, not as a run rate, not
as an anomaly.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import categories, dashboard, forecasting, months

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

# What a month's total counts. Marketplace burns a customer's MACC but not the
# seller's quota, and a credit (e.g. a Contract Price Match Credit) lowers what
# was billed -- so both are switches (operator, 2026-10-16). Including Marketplace
# and subtracting credits is the partner export's "Total Consumption".
# `marketplace` may also be "core42": Core42's revenue is the whole MACC burn except
# Marketplace bought from other publishers (operator, 2026-10-18).
DEFAULT_MEASURE = {"marketplace": True, "credits": True}
# The billing date (operator, 2026-10-21): the day of the month from which the month
# before counts as closed. Azure settles a month's figures for about five days after
# it ends. Taken out of the report's view the same day ("it can be a billing report
# done separately"), so the report reads calendar months unless a caller asks.
DEFAULT_BILLING_DAY = 1
LATEST_BILLING_DAY = 28


def report_date(today: date, billing_day: int | None) -> date:
    """The date the report is as of: `billing_day - 1` days back, so before the
    billing date it falls in the month before, which therefore stays open."""
    day = DEFAULT_BILLING_DAY if billing_day is None else billing_day
    if not 1 <= day <= LATEST_BILLING_DAY:
        raise ValueError(f"the billing date is a day from 1 to {LATEST_BILLING_DAY}")
    return today - timedelta(days=day - 1)
MARKETPLACE_MEASURES = (True, False, "core42")
# Publisher names that are Core42's own Marketplace offers (operator: Core42 and G42).
CORE42_PUBLISHER_MARKS = ("core42", "g42")


def is_core42_publisher(publisher: str) -> bool:
    lowered = (publisher or "").lower().replace(" ", "")
    return any(mark in lowered for mark in CORE42_PUBLISHER_MARKS)


def _pct(new: float, old: float) -> float | None:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _add(into: dict[str, float], name: str, cost: float) -> None:
    into[name] = into.get(name, 0.0) + cost


def _empty_month() -> dict:
    return {**{kind: {"service": {}, "subscription": {}, "account": {}, "pairs": {}} for kind in COST_KINDS},
            "meters": {}, "meters_amortized": {}, "marketplace_offers": {},
            "measured": {"usage": 0.0, "marketplace": 0.0, "marketplace_macc": 0.0, "marketplace_core42": 0.0,
                         "credits": 0.0, "credit_details": {}, "by_account": {}, "from_balance": 0}}


def _not_eligible_marketplace(data: dict, not_eligible: set[str]) -> float:
    """The month's Marketplace spend on offers marked as not counting toward a MACC."""
    return sum(item["cost"] for item in (data.get("marketplace") or {}).get("items") or []
               if f"{item['publisher']}|{item['offer']}" in not_eligible)


def core42_marketplace(data: dict) -> float:
    """The month's Marketplace spend on Core42's own offers -- the only Marketplace
    that is Core42 revenue. Read from the month's charges, so a month whose
    Marketplace has not been fetched counts none."""
    return sum(item["cost"] for item in (data.get("marketplace") or {}).get("items") or []
               if is_core42_publisher(item.get("publisher", "")))


def merge(entries: dict[str, dict], labels: dict[str, str] | None = None,
          not_eligible: set[str] | None = None) -> tuple[dict, str | None]:
    """The customer's accounts as one: per month, per cost kind, spend by
    `service`, `subscription` and `account` (the enrollment, labelled); meter
    detail; and the month's measured components.

    An enrollment with a billing-period balance (EA) is measured by it -- usage,
    Marketplace and credits, exactly as invoiced. One without is measured by its
    Cost Management actual cost, which already holds any Marketplace and knows of
    no credits, so for it the two switches change nothing."""
    labels = labels or {}
    merged: dict[str, dict] = {}
    currency = None
    for account, entry in entries.items():
        label = labels.get(account, account)
        for month, data in (entry.get("months") or {}).items():
            target = merged.setdefault(month, _empty_month())
            currency = currency or data.get("currency") or (data.get("balance") or {}).get("currency")
            for kind in COST_KINDS:
                spend = data.get(kind) or {}
                for key in BREAKDOWNS:
                    for name, cost in (spend.get(key) or {}).items():
                        _add(target[kind][key], name, cost)
                total = sum((spend.get("service") or {}).values())
                if total:
                    _add(target[kind]["account"], label, total)
                for subscription, services in (spend.get("pairs") or {}).items():
                    into = target[kind]["pairs"].setdefault(subscription, {})
                    for service, cost in services.items():
                        _add(into, service, cost)
            for key, cost in (data.get("meters") or {}).items():
                _add(target["meters"], key, cost)
            for key, cost in ((data.get("meters_amortized") or {}).get("by") or {}).items():
                _add(target["meters_amortized"], key, cost)
            # The month's invoiced Marketplace offers, by name: what tells a third-party
            # license billed as "Virtual Machine Licenses" from Microsoft's own.
            for item in (data.get("marketplace") or {}).get("items") or []:
                _add(target["marketplace_offers"], item.get("offer") or "", item.get("cost") or 0.0)
            balance = data.get("balance") or {}
            if balance and not balance.get("missing"):
                marketplace = balance.get("marketplace", 0.0)
                parts = {"usage": balance.get("usage", 0.0), "marketplace": marketplace,
                         "marketplace_macc": marketplace - _not_eligible_marketplace(data, not_eligible or set()),
                         "marketplace_core42": core42_marketplace(data),
                         "credits": balance.get("credits", 0.0)}
                target["measured"]["from_balance"] += 1
                for detail in balance.get("credit_details") or []:
                    _add(target["measured"]["credit_details"], detail.get("name") or "Credit", detail["value"])
            else:
                parts = {"usage": sum(((data.get("actual") or {}).get("service") or {}).values()),
                         "marketplace": 0.0, "marketplace_macc": 0.0, "marketplace_core42": 0.0, "credits": 0.0}
            for key, value in parts.items():
                target["measured"][key] += value
            if any(parts.values()):
                target["measured"]["by_account"][label] = parts
    return merged, currency


def measured_total(parts: dict, measure: dict | None = None) -> float:
    """`measure["marketplace"]` is True (all of it), False (none), "macc" (only
    offers not marked as ineligible -- what burns a MACC) or "core42" (only Core42's
    own offers -- what makes the total Core42's revenue)."""
    measure = {**DEFAULT_MEASURE, **(measure or {})}
    if measure["marketplace"] == "macc":
        marketplace = parts.get("marketplace_macc", parts.get("marketplace", 0.0))
    elif measure["marketplace"] == "core42":
        marketplace = parts.get("marketplace_core42", 0.0)
    else:
        marketplace = parts.get("marketplace", 0.0) if measure["marketplace"] else 0.0
    return parts.get("usage", 0.0) + marketplace - (parts.get("credits", 0.0) if measure["credits"] else 0.0)


def merge_forecasts(entries: dict[str, dict]) -> list[dict] | None:
    totals: dict[str, float] = {}
    for entry in entries.values():
        for row in entry.get("forecast") or []:
            _add(totals, row["month"], row["cost"])
    return [{"month": month, "cost": cost} for month, cost in sorted(totals.items())] or None


def _total(merged: dict, month: str, kind: str = "actual") -> float:
    return sum(((merged.get(month) or {}).get(kind) or {}).get("service", {}).values())


def monthly_totals(merged: dict, current_month: str, measure: dict | None = None) -> list[dict]:
    """Per month: `actual` is the measured total (what the dashboard means by
    consumption), with its parts beside it and Cost Management's own figures."""
    trend, previous = [], None
    for month in sorted(merged):
        measured = merged[month].get("measured") or {"usage": _total(merged, month)}
        actual = measured_total(measured, measure)
        core42_revenue = measured_total(measured, {**DEFAULT_MEASURE, **(measure or {}), "marketplace": "core42"})
        partial = month >= current_month
        trend.append({"month": month, "actual": round(actual, 2),
                      "amortized": round(_total(merged, month, "amortized"), 2),
                      "cost_management": round(_total(merged, month), 2),
                      "usage": round(measured.get("usage", 0.0), 2),
                      "marketplace": round(measured.get("marketplace", 0.0), 2),
                      "marketplace_core42": round(measured.get("marketplace_core42", 0.0), 2),
                      "credits": round(measured.get("credits", 0.0), 2),
                      "core42_revenue": round(core42_revenue, 2),
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


def commitment_measure(commitment: dict) -> dict:
    """What counts against the signed value: Marketplace always burns the MACC --
    except offers marked as not eligible -- and a credit always lowers what was
    billed against it (operator, 2026-10-18: no per-commitment switches)."""
    return {"marketplace": "macc", "credits": True}


def affiliates_roll_up(commitment: dict | None) -> bool:
    """Whether a parent's affiliates burn its commitment: "roll up" (they signed none of
    their own, as DGE; the default) or "own" (each signed its own, as Mubadala) --
    `macc_affiliates` on the Customer note (operator, 2026-10-18)."""
    return (commitment or {}).get("affiliates") != "own"


def burn_down(commitment: dict | None, trend: list[dict], today: date,
              pipeline: dict[str, float] | None = None) -> dict | None:
    """Consumption since the term started against what the customer signed for:
    where it stands, where an even pace would have it, and where the run rate --
    and the run rate plus the pipeline's ramps -- take it by the end of the term.
    `trend` must be measured the commitment's way (`commitment_measure`)."""
    if not commitment:
        return None
    amount = float(commitment["amount"])
    start, end = date.fromisoformat(commitment["start"]), date.fromisoformat(commitment["end"])
    start_month, end_month = months.month_of(start), months.month_of(end)
    pipeline_in_term = sum(usd for month, usd in (pipeline or {}).items()
                           if months.month_of(today) <= month <= end_month)
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
        "pipeline_in_term": round(pipeline_in_term, 2),
        "projected_with_pipeline": round(projected_at_end + pipeline_in_term, 2),
        "shortfall_with_pipeline": round(max(0.0, amount - projected_at_end - pipeline_in_term), 2),
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


def gpu_and_ai(merged: dict, last: int = 13) -> list[dict]:
    """The last `last` months' GPU and AI lines, by how they were bought."""
    return [{"month": month, "lines": categories.detail(merged[month].get("meters") or {})}
            for month in sorted(merged)[-last:]]


def analyse(merged: dict, currency: str | None, commitment: dict | None,
            azure_forecast: list[dict] | None, today: date, measure: dict | None = None,
            scenario: dict | None = None, pipeline: dict[str, float] | None = None,
            burn_merged: dict | None = None) -> dict:
    """`burn_merged`: what burns the commitment when it is not everything shown -- a
    parent whose affiliates signed their own is burned by its own enrollments only."""
    measure = {**DEFAULT_MEASURE, **(measure or {})}
    current_month = months.month_of(today)
    trend = monthly_totals(merged, current_month, measure)
    last_closed = months.shift(current_month, -1)
    burning = merged if burn_merged is None else burn_merged
    burn = (burn_down(commitment, monthly_totals(burning, current_month, commitment_measure(commitment)),
                      today, pipeline) if commitment else None)
    automatic = forecasting.automatic(trend, today, pipeline)
    return {
        "currency": currency,
        "measure": measure,
        "months": trend,
        "last_closed_month": last_closed,
        "top_services": breakdown(merged, last_closed, "service"),
        "subscriptions": breakdown(merged, last_closed, "subscription", limit=None),
        "enrollments": breakdown(merged, last_closed, "account", limit=None),
        "anomalies": anomalies(merged, last_closed),
        "commitment": burn,
        "forecast": forecast(trend, azure_forecast, today),
        "automatic_forecast": automatic,
        "scenarios": forecasting.scenarios(trend, today, scenario, pipeline),
        "gpu_and_ai": gpu_and_ai(merged),
        "dashboard": dashboard.build(trend, merged, today, burn, automatic, measure),
    }
