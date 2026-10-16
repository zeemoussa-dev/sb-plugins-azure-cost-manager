"""What the screen says about a customer's consumption.

Worth pinning: a customer's enrollments read as one (a renewal is not a drop to
zero), the partial current month is never evidence, an anomaly must be both
sharp and material, and the burn-down measures consumption since the signed
term began against the signed value.
"""
from __future__ import annotations

from datetime import date

from backend import consumption_analysis as analysis

TODAY = date(2026, 10, 16)


def month(service: dict[str, float], subscription: dict[str, float] | None = None) -> dict:
    spend = {"service": service, "subscription": subscription or {"Prod": sum(service.values())}}
    return {"fetched_at": "2026-10-16T00:00:00+00:00", "currency": "USD", "actual": spend, "amortized": spend}


def merged(entries: dict) -> dict:
    return analysis.merge(entries)[0]


def test_a_renewal_reads_as_one_customer_not_a_drop_to_zero():
    old = {"months": {"2026-02": month({"VM": 600}), "2026-03": month({"VM": 200}), "2026-04": month({})}}
    new = {"months": {"2026-03": month({"VM": 400}), "2026-04": month({"VM": 610})}}

    combined, currency = analysis.merge({"20000001": old, "20000002": new})
    trend = analysis.monthly_totals(combined, "2026-10")

    assert [m["actual"] for m in trend] == [600, 600, 610]
    assert currency == "USD"
    assert combined["2026-03"]["actual"]["account"] == {"20000001": 200, "20000002": 400}


def test_trend_reports_month_over_month_and_marks_the_current_month_partial():
    combined = merged({"a": {"months": {"2026-08": month({"VM": 100}), "2026-09": month({"VM": 150}),
                                        "2026-10": month({"VM": 40})}}})

    trend = analysis.monthly_totals(combined, "2026-10")

    assert [m["mom_pct"] for m in trend] == [None, 50.0, None]
    assert [m["partial"] for m in trend] == [False, False, True]


def test_breakdown_ranks_by_cost_and_compares_with_the_month_before():
    combined = merged({"a": {"months": {"2026-08": month({"Storage": 50}),
                                        "2026-09": month({"Virtual Machines": 300, "Storage": 100})}}})

    result = analysis.breakdown(combined, "2026-09", "service")

    assert [row["name"] for row in result["rows"]] == ["Virtual Machines", "Storage"]
    assert result["rows"][1]["change_pct"] == 100.0
    assert result["rows"][0]["share_pct"] == 75.0


def test_an_anomaly_must_be_sharp_and_material():
    steady = {"Virtual Machines": 1000, "DNS": 2, "SQL": 400}
    combined = merged({"a": {"months": {
        "2026-06": month(steady), "2026-07": month(steady), "2026-08": month(steady),
        "2026-09": month({"Virtual Machines": 2500, "DNS": 9, "SQL": 100, "Azure OpenAI": 300}),
    }}})

    found = {a["service"]: a["kind"] for a in analysis.anomalies(combined, "2026-09")}

    assert found == {"Virtual Machines": "spike", "SQL": "drop", "Azure OpenAI": "new"}


def commitment(amount=1_200_000, start="2025-10-01", end="2027-09-30"):
    return {"type": "MACC", "amount": amount, "currency": "USD", "start": start, "end": end, "note": ""}


def test_burn_down_counts_only_consumption_since_the_term_started():
    trend = [{"month": "2025-09", "actual": 99_999, "partial": False},
             {"month": "2025-10", "actual": 40_000, "partial": False},
             {"month": "2025-11", "actual": 60_000, "partial": False}]

    result = analysis.burn_down(commitment(), trend, date(2025, 12, 1))

    assert result["consumed"] == 100_000
    assert [point["consumed"] for point in result["cumulative"]] == [40_000, 100_000]


def test_burn_down_projects_a_shortfall_when_the_run_rate_is_too_low():
    trend = [{"month": m, "actual": 30_000, "partial": False}
             for m in ("2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
                       "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")]

    result = analysis.burn_down(commitment(), trend, TODAY)

    assert result["consumed"] == 360_000
    assert result["consumed_pct"] == 30.0
    assert result["pace_gap"] < 0  # behind an even pace over the two-year term
    assert result["projected_shortfall"] > 0
    assert result["verdict"] == "Shortfall projected at the end of the term"


def test_burn_down_on_track_when_the_run_rate_covers_the_remainder():
    trend = [{"month": m, "actual": 80_000, "partial": False}
             for m in ("2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
                       "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")]

    result = analysis.burn_down(commitment(), trend, TODAY)

    assert result["remaining"] == 240_000
    assert result["projected_shortfall"] == 0
    assert result["projected_exhaustion"] == "2027-01"
    assert result["verdict"] == "On track to consume the commitment within the term"


def test_forecast_prefers_azure_and_adds_what_is_already_billed_this_month():
    trend = [{"month": "2026-09", "actual": 900, "partial": False},
             {"month": "2026-10", "actual": 400, "partial": True}]
    azure = [{"month": "2026-10", "cost": 500}, {"month": "2026-11", "cost": 950}]

    result = analysis.forecast(trend, azure, TODAY)

    by_month = {m["month"]: (m["cost"], m["source"]) for m in result["months"]}
    assert by_month["2026-10"] == (900, "azure")
    assert by_month["2026-11"] == (950, "azure")
    assert by_month["2026-12"] == (900, "run-rate")
    assert result["year_end_total"] == 900 + 900 + 950 + 900


def test_forecasts_of_a_customers_enrollments_are_summed():
    entries = {"a": {"forecast": [{"month": "2026-11", "cost": 10}]},
               "b": {"forecast": [{"month": "2026-11", "cost": 5}, {"month": "2026-12", "cost": 7}]},
               "stopped": {"forecast": None}}

    assert analysis.merge_forecasts(entries) == [{"month": "2026-11", "cost": 15}, {"month": "2026-12", "cost": 7}]
