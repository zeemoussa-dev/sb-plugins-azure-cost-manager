"""Baseline and quota (operator, 2026-10-22): Core42 counts as revenue toward the
seller's quota only what a customer consumes above its baseline -- the average of
a few months' consumption.

One baseline for every customer: a start month and a number of months, averaged
into a monthly line (by default the three months before the fiscal year). Each
fiscal-year month's consumption minus that line is counted net -- a month under
the line takes away what an earlier month added. Closed months are actual; the
current and later months are the automatic forecast, with the pipeline beside it.
The consumption measure is the report's (Marketplace and credits filters).

Pipeline against what happened: the consumption Open and Won opportunities
planned for the fiscal year's closed months, against what the customer actually
added above its line in those months.
"""
from __future__ import annotations

from . import months

DEFAULT_BASELINE_MONTHS = 3
DEFAULT_FY_START_MONTH = 7          # Microsoft's fiscal year: July to June
LONGEST_BASELINE = 24
LONGEST_PERIOD = 24
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_NAMED_SPANS = {("01", "06"): "H1", ("07", "12"): "H2", ("01", "03"): "Q1", ("04", "06"): "Q2", ("07", "09"): "Q3",
                ("10", "12"): "Q4", ("01", "12"): "CY"}
COUNTED_STATUSES = {"Open", "Won"}


def fiscal_year(current_month: str, fy_start_month: int) -> tuple[str, str]:
    """The first and last month of the fiscal year `current_month` falls in."""
    year, month = int(current_month[:4]), int(current_month[5:7])
    start_year = year if month >= fy_start_month else year - 1
    first = f"{start_year:04d}-{fy_start_month:02d}"
    return first, months.shift(first, 11)


def fy_label(first: str, fy_start_month: int) -> str:
    """FY27 for July 2026 - June 2027: named after the calendar year it ends in."""
    last = months.shift(first, 11)
    return f"FY{last[2:4]}" if fy_start_month != 1 else f"FY{first[2:4]}"


def period_label(first: str, last: str) -> str:
    """H2 2026 for July to December 2026; otherwise the months themselves."""
    named = _NAMED_SPANS.get((first[5:7], last[5:7])) if first[:4] == last[:4] else None
    if named:
        return f"{named} {first[:4]}"
    return f"{_MONTHS[int(first[5:7]) - 1]} {first[:4]} – {_MONTHS[int(last[5:7]) - 1]} {last[:4]}"


def _is_month(value) -> bool:
    return isinstance(value, str) and len(value) == 7 and value[4] == "-" and value.replace("-", "").isdigit() \
        and 1 <= int(value[5:7]) <= 12


def settings(stored: dict | None, current_month: str) -> dict:
    """The stored settings with their defaults filled in. The quota's period is the
    one set (operator, 2026-10-22: "this year the quota was set for H2 only"), else
    the fiscal year; `fy*` name the period either way."""
    stored = stored or {}
    fy_start = int(stored.get("fy_start_month") or DEFAULT_FY_START_MONTH)
    custom = bool(stored.get("period_first") and stored.get("period_last"))
    if custom:
        first, last = stored["period_first"], stored["period_last"]
        label = period_label(first, last)
    else:
        first, last = fiscal_year(current_month, fy_start)
        label = fy_label(first, fy_start)
    count = int(stored.get("baseline_months") or DEFAULT_BASELINE_MONTHS)
    start = stored.get("baseline_start") or months.shift(first, -count)
    return {"fy_start_month": fy_start, "fy_first": first, "fy_last": last, "fy": label,
            "period_is_default": not custom,
            "baseline_start": start, "baseline_months": count,
            "baseline_last": months.shift(start, count - 1), "quota": stored.get("quota"),
            "baseline_is_default": not stored.get("baseline_start")}


def validated(changes: dict) -> dict:
    """The settings an edit may change, checked."""
    clean: dict = {}
    if "fy_start_month" in changes:
        value = int(changes["fy_start_month"])
        if not 1 <= value <= 12:
            raise ValueError("the fiscal year starts in a month from 1 to 12")
        clean["fy_start_month"] = value
    if "baseline_months" in changes:
        value = int(changes["baseline_months"])
        if not 1 <= value <= LONGEST_BASELINE:
            raise ValueError(f"the baseline is 1 to {LONGEST_BASELINE} months")
        clean["baseline_months"] = value
    if "baseline_start" in changes:
        value = changes["baseline_start"] or None
        if value is not None and not _is_month(value):
            raise ValueError("the baseline starts in a month, YYYY-MM")
        clean["baseline_start"] = value
    if "period_first" in changes or "period_last" in changes:
        first, last = changes.get("period_first") or None, changes.get("period_last") or None
        if (first is None) != (last is None):
            raise ValueError("a quota period has both a first and a last month, or neither (the fiscal year)")
        if first is not None:
            if not _is_month(first) or not _is_month(last):
                raise ValueError("a quota period runs between months, YYYY-MM")
            span = len(months.span(first, last)) if first <= last else 0
            if not 1 <= span <= LONGEST_PERIOD:
                raise ValueError(f"a quota period ends after it starts and lasts at most {LONGEST_PERIOD} months")
        clean["period_first"], clean["period_last"] = first, last
    if "quota" in changes:
        value = changes["quota"]
        if value in (None, ""):
            clean["quota"] = None
        else:
            amount = float(value)
            if amount < 0:
                raise ValueError("the quota is not negative")
            clean["quota"] = amount
    return clean


def month_end_factor(entries: dict[str, dict], current_month: str, days_in_month: int) -> float | None:
    """How much the running month's billed-so-far scales to a whole month: the days each
    enrollment's month figures cover (fetched a day behind, as Cost Management lags),
    weighted by what each has billed. None when nothing is billed yet."""
    weighted, total = 0.0, 0.0
    for entry in entries.values():
        found = (entry.get("months") or {}).get(current_month) or {}
        billed = sum(((found.get("actual") or {}).get("service") or {}).values())
        if billed <= 0:
            continue
        fetched = str(found.get("fetched_at") or "")
        covered = days_in_month if not fetched.startswith(current_month) else max(1, int(fetched[8:10]) - 1)
        weighted += billed * days_in_month / min(covered, days_in_month)
        total += billed
    return weighted / total if total else None


def analyse(trend: list[dict], forecast_series: list[dict] | None, chosen: dict, current_month: str,
            month_end_factor: float | None = None) -> dict:
    """One customer's baseline, its fiscal year month by month, and what counts
    above the line: to date (closed months), and projected to the year's end.

    The running month is what it has billed so far at its pace (`month_end_factor`), not
    the trend's figure: the trend read a month already billing more than it predicted as
    a fall (operator, 2026-10-25: "always a drop in the current month"). The months after
    it carry that pace forward -- the run rate, not the trend x seasonality model
    (operator, same day). Before anything is billed in the month, the model applies."""
    actual = {row["month"]: row["actual"] for row in trend if not row["partial"]}
    billed_now = next((row["actual"] for row in trend if row["month"] == current_month), 0.0)
    pace = billed_now * month_end_factor if billed_now > 0 and month_end_factor else None
    baseline_months = months.span(chosen["baseline_start"], chosen["baseline_last"])
    baseline = sum(actual.get(month, 0.0) for month in baseline_months) / len(baseline_months)
    forecast = {row["month"]: row for row in forecast_series or [] if row.get("forecast") is not None}
    rows, exact = [], []
    for month in months.span(chosen["fy_first"], chosen["fy_last"]):
        if month < current_month and month in actual:
            value, kind, pipeline = actual[month], "actual", 0.0
        elif month < current_month:
            value, kind, pipeline = 0.0, "actual", 0.0
        else:
            projected = forecast.get(month) or {}
            # No forecast (too little history): the line itself, adding nothing.
            value = pace if pace is not None else projected.get("forecast", baseline)
            kind, pipeline = "forecast", projected.get("pipeline", 0.0) or 0.0
        rows.append({"month": month, "kind": kind, "consumption": round(value, 2), "baseline": round(baseline, 2),
                     "above": round(value - baseline, 2), "pipeline": round(pipeline, 2)})
        exact.append((kind, value - baseline))
    # Added up before rounding, so the year's figure is not twelve roundings off.
    to_date = sum(above for kind, above in exact if kind == "actual")
    projected = sum(above for _, above in exact)
    return {
        "baseline": round(baseline, 2),
        "baseline_covered": sum(1 for month in baseline_months if month in actual),
        "months": rows,
        "above_to_date": round(to_date, 2),
        "above_projected": round(projected, 2),
        "above_with_pipeline": round(projected + sum(row["pipeline"] for row in rows), 2),
    }


def pipeline_against_actual(opportunities: list[dict], found: dict, current_month: str) -> dict:
    """The consumption the pipeline planned for the year's closed months, against
    what was added above the line in them; the opportunities that planned it."""
    closed = {row["month"] for row in found["months"] if row["kind"] == "actual" and row["month"] < current_month}
    listed = []
    for opportunity in opportunities:
        if opportunity.get("status") not in COUNTED_STATUSES:
            continue
        plan = [row for row in opportunity.get("plan") or [] if row.get("month") in closed]
        planned = sum(float(row.get("usd") or 0) for row in plan)
        if planned:
            listed.append({"id": opportunity.get("id"), "title": opportunity.get("title"),
                           "status": opportunity.get("status"), "stage": opportunity.get("stage"),
                           "route": opportunity.get("route"), "first_month": min(row["month"] for row in plan),
                           "planned_to_date": round(planned, 2)})
    planned_total = sum(item["planned_to_date"] for item in listed)
    achieved = found["above_to_date"]
    return {"planned_to_date": round(planned_total, 2), "achieved_to_date": achieved,
            "gap": round(achieved - planned_total, 2), "behind": bool(listed) and achieved < planned_total,
            "opportunities": sorted(listed, key=lambda item: -item["planned_to_date"])}
