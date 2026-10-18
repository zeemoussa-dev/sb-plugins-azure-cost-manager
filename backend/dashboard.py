"""The figures of the operator's consumption workbook, for any customer: the
headline KPIs and the series behind each chart -- by year, year-to-date against
last year, month-over-month and year-over-year, by enrollment and by quarter,
this year against last, and the plan-line mix by month.

"Latest month" is the last closed month: the current one is still being billed
and is shown on its own, never compared.
"""
from __future__ import annotations

from datetime import date

from . import categories, months


def _pct(new: float, old: float) -> float | None:
    return round((new / old - 1) * 100, 1) if old else None


def _quarter(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:]) - 1) // 3 + 1}"


def build(trend: list[dict], merged: dict, today: date, commitment: dict | None,
          automatic: dict | None, measure: dict) -> dict:
    by_month = {row["month"]: row for row in trend}
    closed = [row for row in trend if not row["partial"]]
    latest = closed[-1] if closed else None
    current = next((row for row in trend if row["partial"]), None)
    this_year, last_year = today.year, today.year - 1

    # Year to date covers the same months of each year, through the latest closed month.
    ytd_through = int(latest["month"][5:]) if latest and latest["month"].startswith(f"{this_year}-") else 0
    def ytd(year: int) -> float:
        return sum(row["actual"] for row in closed
                   if row["month"].startswith(f"{year:04d}-") and int(row["month"][5:]) <= ytd_through)

    years = sorted({int(row["month"][:4]) for row in trend})
    by_year = [{"year": year, "total": round(sum(row["actual"] for row in trend
                                                 if row["month"].startswith(f"{year:04d}-")), 2),
                "partial": year == this_year} for year in years]
    ytd_by_year = [{"year": year, "total": round(ytd(year), 2)} for year in years] if ytd_through else []

    def prior_year(month: str) -> dict | None:
        return by_month.get(months.shift(month, -12))

    monthly = []
    for row in trend:
        prior = prior_year(row["month"])
        monthly.append({**row, "yoy_pct": None if row["partial"] or not prior else _pct(row["actual"], prior["actual"])})

    # Each month as the plan lines it was spent on, adding up to its measured total.
    mix = []
    for row in trend:
        data = merged.get(row["month"]) or {}
        marketplace = (row.get("marketplace_core42", 0.0) if measure["marketplace"] == "core42"
                       else row["marketplace"] if measure["marketplace"] else 0.0)
        mix.append({"month": row["month"], "lines": categories.mix(row["actual"], data.get("meters") or {}, marketplace)})

    accounts = sorted({label for data in merged.values() for label in (data.get("actual") or {}).get("account", {})})
    by_quarter: dict[str, dict[str, float]] = {}
    for month, data in merged.items():
        for label, cost in ((data.get("actual") or {}).get("account") or {}).items():
            quarter = by_quarter.setdefault(_quarter(month), {})
            quarter[label] = quarter.get(label, 0.0) + cost
    quarterly = [{"quarter": quarter, "by_account": {label: round(cost, 2) for label, cost in values.items()}}
                 for quarter, values in sorted(by_quarter.items())]

    by_account_total: dict[str, float] = {}
    for data in merged.values():
        for label, cost in ((data.get("actual") or {}).get("account") or {}).items():
            by_account_total[label] = by_account_total.get(label, 0.0) + cost
    all_accounts_total = sum(by_account_total.values())

    def year_line(year: int) -> list[float | None]:
        return [by_month[f"{year:04d}-{number:02d}"]["actual"] if f"{year:04d}-{number:02d}" in by_month else None
                for number in range(1, 13)]

    def mom_line(year: int) -> list[float | None]:
        values = []
        for number in range(1, 13):
            month = f"{year:04d}-{number:02d}"
            row, previous = by_month.get(month), by_month.get(months.shift(month, -1))
            values.append(row["mom_pct"] if row and previous and not row["partial"] else None)
        return values

    burn = None
    if closed:
        last_three = [row["actual"] for row in closed[-3:]]
        burn = sum(last_three) / len(last_three)

    kpis = {
        "all_time": round(sum(row["actual"] for row in trend), 2),
        "months_of_history": len(trend),
        "first_month": trend[0]["month"] if trend else None,
        "ytd": round(ytd(this_year), 2) if ytd_through else None,
        "ytd_last_year": round(ytd(last_year), 2) if ytd_through else None,
        "ytd_growth_pct": _pct(ytd(this_year), ytd(last_year)) if ytd_through else None,
        "ytd_through": f"{this_year:04d}-{ytd_through:02d}" if ytd_through else None,
        "latest_month": latest["month"] if latest else None,
        "latest_total": latest["actual"] if latest else None,
        "latest_mom_pct": latest["mom_pct"] if latest else None,
        "latest_yoy_pct": (_pct(latest["actual"], prior_year(latest["month"])["actual"])
                           if latest and prior_year(latest["month"]) else None),
        "current_month": current["month"] if current else None,
        "current_so_far": current["actual"] if current else None,
        "active_enrollments": len([label for label, cost in
                                   ((merged.get(latest["month"]) or {}).get("actual") or {}).get("account", {}).items()
                                   if cost]) if latest else 0,
        "largest_enrollment_share_pct": (round(max(by_account_total.values()) / all_accounts_total * 100, 1)
                                         if all_accounts_total else None),
        "burn_rate_3m": round(burn, 2) if burn is not None else None,
        "next_12_months": automatic["next_12_months"] if automatic else None,
        "next_year_forecast": automatic["next_year_total"] if automatic else None,
        "credits_all_time": round(sum(row["credits"] for row in trend), 2),
        "marketplace_all_time": round(sum(row["marketplace"] for row in trend), 2),
        "core42_marketplace_all_time": round(sum(row.get("marketplace_core42", 0.0) for row in trend), 2),
        "core42_revenue_all_time": round(sum(row.get("core42_revenue", 0.0) for row in trend), 2),
        "core42_revenue_this_year": round(sum(row.get("core42_revenue", 0.0) for row in trend
                                              if row["month"].startswith(f"{this_year:04d}-")), 2),
    }
    if commitment:
        kpis.update({
            "commitment_consumed_pct": commitment["consumed_pct"],
            "commitment_remaining": commitment["remaining"],
            "runway_months": (round(commitment["remaining"] / burn, 1) if burn and commitment["remaining"] > 0
                              else None),
            "projected_exhaustion": commitment["projected_exhaustion"],
        })

    return {
        "kpis": kpis,
        "monthly": monthly,
        "by_year": by_year,
        "ytd_by_year": ytd_by_year,
        "mix": mix,
        "accounts": accounts,
        "quarterly": quarterly,
        "this_vs_last_year": {"this_year": this_year, "last_year": last_year,
                              "this": year_line(this_year), "last": year_line(last_year),
                              "this_mom": mom_line(this_year), "last_mom": mom_line(last_year)},
        "credit_details": _credit_details(merged),
    }


def _credit_details(merged: dict) -> list[dict]:
    """Every credit applied, by name and month -- a credit is money, and it should
    be visible where it changed a total."""
    rows = []
    for month in sorted(merged):
        for name, value in ((merged[month].get("measured") or {}).get("credit_details") or {}).items():
            rows.append({"month": month, "name": name, "value": round(value, 2)})
    return rows
