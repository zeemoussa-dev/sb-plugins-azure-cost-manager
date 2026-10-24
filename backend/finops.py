"""FinOps: paying less for the same consumption, and keeping it that way.

Pure functions over one customer's synced months (its enrollments, a parent's
affiliates' included), like `consumption_analysis`. Read from the meter detail,
`"<meter subcategory>|<pricing model>" -> cost` per month:

- `meters` is actual cost. On-demand costs the same actual or amortized, so the
  steady on-demand candidates read every month synced.
- `meters_amortized` is amortized: a reservation's usage carries its share of the
  purchase instead of costing nothing, so coverage is read from it (synced for
  the last 13 months only, `consumption_sync.FINOPS_MONTHS`).

The current month is partial and is never evidence: coverage, candidates and
growth read closed months only.
"""
from __future__ import annotations

import re
from datetime import date
from statistics import mean, pstdev

from . import categories, finops_extra, months

COMMITMENT_MODELS = ("Reservation", "SavingsPlan")
ON_DEMAND = "OnDemand"

VIRTUAL_MACHINES = "Virtual machines"
GPU = "GPU"
AZURE_OPENAI = "Azure OpenAI"
OTHER_ELIGIBLE = "Other reservable services"
# A VM meter ends with its series ("Dsv5 Series", "D2 v3 Series Windows");
# database compute that names a VM series goes on ("... Ddsv5 Series Compute").
_VM_SERIES = re.compile(r"\bSeries( Windows| Linux)?$", re.IGNORECASE)
# Azure's catch-all meter subcategory: not a meter anyone can reserve, even when
# a reservation's charge lands on it.
NOT_A_METER = {"", "Unassigned"}

# A steady candidate: on-demand every one of the last six closed months, at least
# this much a month, varying little -- what a reservation or savings plan is for.
STEADY_MONTHS = 6
STEADY_MIN_MONTHLY = 1_000.0
STEADY_MAX_VARIATION = 0.25
# A reservation bought up front shows as its purchase under actual cost; a month
# whose commitment charges run this far past their amortized cost had a purchase.
PURCHASE_MIN_EXCESS = 10_000.0
GROWTH_WINDOW = 3
TOP_GROWTH = 5


def family(meter_subcategory: str, reservable: set[str]) -> str | None:
    """The commitment family a meter belongs to, or None when no reservation or
    savings plan applies. Beyond VMs, GPUs and Azure OpenAI, a meter counts as
    reservable once this customer has ever had it reserved."""
    if meter_subcategory in NOT_A_METER:
        return None
    line = categories.classify(meter_subcategory, "")
    if meter_subcategory == categories.OPENAI:
        return AZURE_OPENAI
    if line and line.startswith("GPU"):
        return GPU
    if _VM_SERIES.search(meter_subcategory or ""):
        return VIRTUAL_MACHINES
    if meter_subcategory in reservable:
        return OTHER_ELIGIBLE
    return None


def _split(key: str) -> tuple[str, str]:
    meter_subcategory, _, pricing_model = key.partition("|")
    return meter_subcategory, pricing_model


def _summed(entries: dict[str, dict], field: str) -> dict[str, dict[str, float]]:
    """Every enrollment's meter detail added up, per month."""
    by_month: dict[str, dict[str, float]] = {}
    for entry in entries.values():
        for month, data in (entry.get("months") or {}).items():
            meters = data.get(field) or {}
            if field == "meters_amortized":
                meters = meters.get("by") or {}
            if not meters:
                continue
            target = by_month.setdefault(month, {})
            for key, cost in meters.items():
                target[key] = target.get(key, 0.0) + cost
    return by_month


def _reservable(*meter_months: dict[str, dict[str, float]]) -> set[str]:
    return {_split(key)[0] for meters in meter_months for month in meters.values() for key, cost in month.items()
            if _split(key)[1] in COMMITMENT_MODELS and cost > 0}


def coverage(amortized: dict[str, dict[str, float]], reservable: set[str], closed: list[str]) -> dict:
    """Per closed month and family: what commitments covered against on-demand."""
    trend = []
    for month in closed:
        meters = amortized.get(month)
        if meters is None:
            continue
        by_family: dict[str, dict[str, float]] = {}
        for key, cost in meters.items():
            meter_subcategory, pricing_model = _split(key)
            name = family(meter_subcategory, reservable)
            if not name or pricing_model not in (ON_DEMAND, *COMMITMENT_MODELS):
                continue
            bucket = by_family.setdefault(name, {"covered": 0.0, "on_demand": 0.0})
            bucket["covered" if pricing_model in COMMITMENT_MODELS else "on_demand"] += cost
        covered = sum(bucket["covered"] for bucket in by_family.values())
        on_demand = sum(bucket["on_demand"] for bucket in by_family.values())
        trend.append({
            "month": month, "covered": round(covered, 2), "on_demand": round(on_demand, 2),
            "coverage_pct": round(covered / (covered + on_demand) * 100, 1) if covered + on_demand > 0 else None,
            "families": [{"family": name, "covered": round(bucket["covered"], 2),
                          "on_demand": round(bucket["on_demand"], 2),
                          "coverage_pct": round(bucket["covered"] / (bucket["covered"] + bucket["on_demand"]) * 100, 1)
                          if bucket["covered"] + bucket["on_demand"] > 0 else None}
                         for name, bucket in sorted(by_family.items(),
                                                    key=lambda item: -(item[1]["covered"] + item[1]["on_demand"]))],
        })
    return {"months": trend, "latest": trend[-1] if trend else None}


def steady_candidates(actual: dict[str, dict[str, float]], reservable: set[str], closed: list[str]) -> list[dict]:
    """Meters running on demand at a steady level for the last six closed months,
    largest first: where a reservation or savings plan pays."""
    window = closed[-STEADY_MONTHS:]
    if len(window) < STEADY_MONTHS:
        return []
    per_meter: dict[str, list[float]] = {}
    for index, month in enumerate(window):
        for key, cost in (actual.get(month) or {}).items():
            meter_subcategory, pricing_model = _split(key)
            if pricing_model != ON_DEMAND or not family(meter_subcategory, reservable):
                continue
            per_meter.setdefault(meter_subcategory, [0.0] * len(window))[index] += cost
    found = []
    for meter_subcategory, series in per_meter.items():
        average = mean(series)
        if min(series) <= 0 or average < STEADY_MIN_MONTHLY:
            continue
        variation = pstdev(series) / average
        if variation > STEADY_MAX_VARIATION:
            continue
        found.append({"meter": meter_subcategory, "family": family(meter_subcategory, reservable),
                      "monthly_on_demand": round(average, 2), "lowest_month": round(min(series), 2),
                      "variation_pct": round(variation * 100, 1), "annual_on_demand": round(average * 12, 2),
                      "months": {month: round(cost, 2) for month, cost in zip(window, series)}})
    return sorted(found, key=lambda candidate: -candidate["monthly_on_demand"])


def purchases(actual: dict[str, dict[str, float]], amortized: dict[str, dict[str, float]],
              closed: list[str]) -> list[dict]:
    """Months where commitment charges ran far past their amortized cost: a
    reservation or savings plan bought up front."""
    found = []
    for month in closed:
        if month not in amortized:
            continue
        charged = sum(cost for key, cost in (actual.get(month) or {}).items() if _split(key)[1] in COMMITMENT_MODELS)
        spread = sum(cost for key, cost in amortized[month].items() if _split(key)[1] in COMMITMENT_MODELS)
        if charged - spread >= max(PURCHASE_MIN_EXCESS, spread * 0.5):
            found.append({"month": month, "charged": round(charged, 2), "amortized": round(spread, 2),
                          "bought_up_front": round(charged - spread, 2)})
    return found


def growth(merged: dict, closed: list[str], key: str) -> list[dict]:
    """The services (or subscriptions) that grew most: the last three closed months
    against the three before, by the monthly average."""
    if len(closed) < GROWTH_WINDOW * 2:
        return []
    recent, before = closed[-GROWTH_WINDOW:], closed[-GROWTH_WINDOW * 2:-GROWTH_WINDOW]

    def average(window: list[str]) -> dict[str, float]:
        totals: dict[str, float] = {}
        for month in window:
            for name, cost in (((merged.get(month) or {}).get("actual") or {}).get(key) or {}).items():
                totals[name] = totals.get(name, 0.0) + cost / len(window)
        return totals

    now, then = average(recent), average(before)
    rows = [{"name": name, "monthly_now": round(now.get(name, 0.0), 2), "monthly_before": round(then.get(name, 0.0), 2),
             "change": round(now.get(name, 0.0) - then.get(name, 0.0), 2),
             "change_pct": round((now.get(name, 0.0) - then[name]) / then[name] * 100, 1) if then.get(name) else None}
            for name in set(now) | set(then)]
    return sorted((row for row in rows if row["change"] > 0), key=lambda row: -row["change"])[:TOP_GROWTH]


def monthly_budget(commitment: dict | None, override: float | None) -> dict | None:
    """The operator's override, or the MACC spread evenly over its term (operator,
    2026-10-17)."""
    if override:
        return {"amount": round(float(override), 2), "source": "set"}
    if not commitment:
        return None
    term = months.span(commitment["start"][:7], commitment["end"][:7])
    return {"amount": round(float(commitment["amount"]) / len(term), 2), "source": "macc", "term_months": len(term)}


def budget_status(budget: dict | None, trend: list[dict], current_month_forecast: float | None) -> dict | None:
    if not budget:
        return None
    closed = [month for month in trend if not month["partial"]]
    last = closed[-1] if closed else None
    over_months = [month["month"] for month in closed[-12:] if month["actual"] > budget["amount"]]
    status = ("over" if last and last["actual"] > budget["amount"]
              else "forecast-over" if current_month_forecast and current_month_forecast > budget["amount"]
              else "within")
    return {**budget, "last_month": last["month"] if last else None, "last_month_actual": last["actual"] if last else None,
            "current_month_forecast": current_month_forecast, "over_in_last_12": over_months, "status": status}


PRICED_FAMILIES = (VIRTUAL_MACHINES, GPU)


def with_savings(candidates: list[dict], prices: dict[str, dict]) -> list[dict]:
    """Each candidate's estimated monthly saving per commitment option, from the
    price book; a candidate the price list cannot price says why."""
    priced = []
    for candidate in candidates:
        entry = prices.get(candidate["meter"]) if candidate["family"] in PRICED_FAMILIES else None
        discounts = (entry or {}).get("discounts")
        if discounts:
            savings = {option: round(candidate["monthly_on_demand"] * share, 2) for option, share in discounts.items()}
            priced.append({**candidate, "savings": savings, "priced_as": entry["product"], "not_priced": None})
        else:
            reason = ("priced from the next phase: databases, storage and capacities price per unit, not per hour"
                      if candidate["family"] not in PRICED_FAMILIES
                      else (entry or {}).get("reason") or "not priced yet: the next sync prices it")
            priced.append({**candidate, "savings": None, "priced_as": None, "not_priced": reason})
    return priced


def _savings_total(candidates: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for candidate in candidates:
        for option, saving in (candidate.get("savings") or {}).items():
            totals[option] = round(totals.get(option, 0.0) + saving, 2)
    return totals


def analyse(entries: dict[str, dict], merged: dict, trend: list[dict], commitment: dict | None,
            budget_override: float | None, current_month_forecast: float | None, today: date,
            prices: dict[str, dict] | None = None) -> dict:
    """The FinOps findings for one customer."""
    current = months.month_of(today)
    actual, amortized = _summed(entries, "meters"), _summed(entries, "meters_amortized")
    closed = sorted(month for month in set(actual) | set(amortized) | set(merged) if month < current)
    reservable = _reservable(actual, amortized)
    candidates = with_savings(steady_candidates(actual, reservable, closed), prices or {})
    covered = coverage(amortized, reservable, closed[-12:])
    bought = purchases(actual, amortized, closed[-12:])
    return {
        "has_meters": bool(actual),
        "has_amortized_meters": bool(amortized),
        "coverage": covered,
        "candidates": candidates,
        "candidates_monthly": round(sum(candidate["monthly_on_demand"] for candidate in candidates), 2),
        # Monthly, per option, over the candidates the price list could price.
        "savings_monthly": _savings_total(candidates),
        "purchases": bought,
        "hybrid_benefit": finops_extra.hybrid_benefit(actual, closed),
        "renewals": finops_extra.renewals(bought, current),
        "growth": {"services": growth(merged, closed, "service"), "subscriptions": growth(merged, closed, "subscription")},
        "budget": budget_status(monthly_budget(commitment, budget_override), trend, current_month_forecast),
    }
