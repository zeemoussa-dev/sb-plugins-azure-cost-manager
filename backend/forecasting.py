"""The operator's two forecasts, per customer.

**Automatic** -- a linear trend fitted to the closed months that billed anything,
times a month-of-year seasonal index, with its fit (R²) and a backtest error
(MAPE) so a forecast is never shown without how far to trust it.

**Scenarios** -- Base / Upside / Downside monthly growth from the last closed
month, optionally seasonal, plus a fixed monthly uplift from a chosen month.

The pipeline (Opportunity ramps) is reported beside each, never folded in
silently: what is expected from deals is a different claim from what the trend
says.
"""
from __future__ import annotations

from datetime import date

from . import months

MINIMUM_MONTHS = 6
SCENARIOS = ("Base", "Upside", "Downside")
DEFAULT_SCENARIO = {"growth": {"Base": 0.02, "Upside": 0.035, "Downside": 0.005},
                    "seasonality": True, "active": "Base", "uplift_usd": 0.0, "uplift_from": None}


def _closed_actuals(trend: list[dict]) -> list[dict]:
    return [month for month in trend if not month["partial"] and month["actual"] > 0]


def _fit(points: list[tuple[int, float]]) -> tuple[float, float, float]:
    """Least squares `y = intercept + slope * x`, and R²."""
    count = len(points)
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread if spread else 0.0
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for _, y in points)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    return slope, intercept, (1 - residual / total) if total else 0.0


def seasonal_index(trend: list[dict]) -> dict[int, float]:
    """Month of year (1-12) -> how that month runs against the trend, 1.0 = average.
    Months of year with no history read 1.0."""
    actuals = _closed_actuals(trend)
    if len(actuals) < MINIMUM_MONTHS:
        return {number: 1.0 for number in range(1, 13)}
    first = actuals[0]["month"]
    index_of = {month["month"]: _months_from(first, month["month"]) for month in actuals}
    slope, intercept, _ = _fit([(index_of[m["month"]], m["actual"]) for m in actuals])
    ratios: dict[int, list[float]] = {}
    for month in actuals:
        expected = intercept + slope * index_of[month["month"]]
        if expected > 0:
            ratios.setdefault(int(month["month"][5:]), []).append(month["actual"] / expected)
    all_ratios = [ratio for values in ratios.values() for ratio in values]
    normaliser = sum(all_ratios) / len(all_ratios) if all_ratios else 1.0
    return {number: (sum(ratios[number]) / len(ratios[number]) / normaliser) if ratios.get(number) else 1.0
            for number in range(1, 13)}


def _months_from(first: str, month: str) -> int:
    return (int(month[:4]) - int(first[:4])) * 12 + int(month[5:]) - int(first[5:])


def automatic(trend: list[dict], today: date, pipeline: dict[str, float] | None = None) -> dict | None:
    actuals = _closed_actuals(trend)
    if len(actuals) < MINIMUM_MONTHS:
        return None
    pipeline = pipeline or {}
    first = actuals[0]["month"]
    slope, intercept, r_squared = _fit([(_months_from(first, m["month"]), m["actual"]) for m in actuals])
    season = seasonal_index(trend)

    def model(month: str) -> float:
        return max(0.0, (intercept + slope * _months_from(first, month)) * season[int(month[5:])])

    errors = [abs(m["actual"] - model(m["month"])) / m["actual"] for m in actuals]
    current_month = months.month_of(today)
    horizon = f"{today.year + 1:04d}-12"
    actual_by_month = {m["month"]: m["actual"] for m in trend if not m["partial"]}
    series = [{"month": m, "actual": round(actual_by_month[m], 2), "model": round(model(m), 2),
               "forecast": None, "pipeline": round(pipeline.get(m, 0.0), 2)} for m in sorted(actual_by_month)]
    projected = [{"month": m, "actual": None, "model": None, "forecast": round(model(m), 2),
                  "pipeline": round(pipeline.get(m, 0.0), 2)} for m in months.span(current_month, horizon)]
    series += projected
    this_year = f"{today.year:04d}-"
    next_year = f"{today.year + 1:04d}-"
    closed_this_year = sum(v for m, v in actual_by_month.items() if m.startswith(this_year))
    this_year_total = closed_this_year + sum(p["forecast"] for p in projected if p["month"].startswith(this_year))
    next_year_total = sum(p["forecast"] for p in projected if p["month"].startswith(next_year))
    next_12 = sum(p["forecast"] for p in projected[:12])
    pipeline_next_12 = sum(p["pipeline"] for p in projected[:12])
    return {
        "method": "linear trend on billed months x month-of-year seasonal index",
        "slope": round(slope, 2), "intercept": round(intercept, 2), "r_squared": round(r_squared, 3),
        "mape": round(sum(errors) / len(errors), 3), "months_of_history": len(actuals),
        "seasonal_index": {str(number): round(value, 3) for number, value in season.items()},
        "next_12_months": round(next_12, 2),
        "next_12_months_with_pipeline": round(next_12 + pipeline_next_12, 2),
        "this_year_total": round(this_year_total, 2),
        "next_year": today.year + 1,
        "next_year_total": round(next_year_total, 2),
        "next_year_with_pipeline": round(next_year_total + sum(
            p["pipeline"] for p in projected if p["month"].startswith(next_year)), 2),
        "next_vs_this_pct": round((next_year_total / this_year_total - 1) * 100, 1) if this_year_total else None,
        "series": series,
    }


def scenarios(trend: list[dict], today: date, settings: dict | None,
              pipeline: dict[str, float] | None = None) -> dict | None:
    settings = {**DEFAULT_SCENARIO, **(settings or {})}
    growth = {**DEFAULT_SCENARIO["growth"], **(settings.get("growth") or {})}
    closed = [month for month in trend if not month["partial"]]
    if not closed:
        return None
    pipeline = pipeline or {}
    base_month, base_total = closed[-1]["month"], closed[-1]["actual"]
    season = seasonal_index(trend) if settings["seasonality"] else {number: 1.0 for number in range(1, 13)}
    base_season = season[int(base_month[5:])] or 1.0
    horizon = f"{today.year + 1:04d}-12"
    uplift_from = settings.get("uplift_from")
    rows = []
    for step, month in enumerate(months.span(months.shift(base_month, 1), horizon), start=1):
        uplift = float(settings.get("uplift_usd") or 0.0) if uplift_from and month >= uplift_from else 0.0
        row = {"month": month, "pipeline": round(pipeline.get(month, 0.0), 2)}
        for name in SCENARIOS:
            row[name] = round(base_total * (1 + growth[name]) ** step * season[int(month[5:])] / base_season + uplift, 2)
        row["active_with_pipeline"] = round(row[settings["active"]] + row["pipeline"], 2)
        rows.append(row)
    next_year = f"{today.year + 1:04d}-"
    return {
        "settings": {**settings, "growth": growth},
        "base_month": base_month, "base_total": round(base_total, 2),
        "rows": rows,
        "totals": {name: round(sum(row[name] for row in rows), 2) for name in SCENARIOS},
        "next_year": {name: round(sum(row[name] for row in rows if row["month"].startswith(next_year)), 2)
                      for name in SCENARIOS},
        "pipeline_total": round(sum(row["pipeline"] for row in rows), 2),
    }
