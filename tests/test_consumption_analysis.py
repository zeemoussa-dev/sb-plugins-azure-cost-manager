"""What the screen says about a customer's consumption.

Worth pinning: the partial current month is never evidence, an anomaly must be
both sharp and material, and a burn-down's verdict follows the run rate.
"""
from __future__ import annotations

from datetime import date

from backend import consumption_analysis as analysis
from conftest import cost_row

TODAY = date(2026, 10, 16)


def months_of(costs: dict[str, list[dict]]) -> dict:
    return {month: {"fetched_at": "2026-10-16T00:00:00+00:00", "actual": rows, "amortized": rows}
            for month, rows in costs.items()}


def test_trend_reports_month_over_month_and_marks_the_current_month_partial():
    cached = months_of({"2026-08": [cost_row("2026-08", 100)],
                        "2026-09": [cost_row("2026-09", 150)],
                        "2026-10": [cost_row("2026-10", 40)]})

    trend = analysis.monthly_totals(cached, "2026-10")

    assert [m["mom_pct"] for m in trend] == [None, 50.0, None]
    assert [m["partial"] for m in trend] == [False, False, True]


def test_breakdown_ranks_by_cost_and_compares_with_the_month_before():
    cached = months_of({
        "2026-08": [cost_row("2026-08", 50, "Storage")],
        "2026-09": [cost_row("2026-09", 300, "Virtual Machines"), cost_row("2026-09", 100, "Storage")],
    })

    result = analysis.breakdown(cached, "2026-09", "service")

    assert [row["name"] for row in result["rows"]] == ["Virtual Machines", "Storage"]
    assert result["rows"][1]["change_pct"] == 100.0
    assert result["rows"][0]["share_pct"] == 75.0


def test_an_anomaly_must_be_sharp_and_material():
    steady = [cost_row(m, 1000, "Virtual Machines") for m in ("2026-06", "2026-07", "2026-08")]
    cached = months_of({
        "2026-06": [steady[0], cost_row("2026-06", 2, "DNS"), cost_row("2026-06", 400, "SQL")],
        "2026-07": [steady[1], cost_row("2026-07", 2, "DNS"), cost_row("2026-07", 400, "SQL")],
        "2026-08": [steady[2], cost_row("2026-08", 2, "DNS"), cost_row("2026-08", 400, "SQL")],
        "2026-09": [cost_row("2026-09", 2500, "Virtual Machines"),   # spike
                    cost_row("2026-09", 9, "DNS"),                     # sharp, not material
                    cost_row("2026-09", 100, "SQL"),                   # drop
                    cost_row("2026-09", 300, "Azure OpenAI")],         # new
    })

    found = {a["service"]: a["kind"] for a in analysis.anomalies(cached, "2026-09")}

    assert found == {"Virtual Machines": "spike", "SQL": "drop", "Azure OpenAI": "new"}


def test_macc_burn_down_projects_a_shortfall_when_the_run_rate_is_too_low():
    trend = [{"month": m, "actual": 10_000, "partial": False} for m in ("2026-07", "2026-08", "2026-09")]
    commitment = {"kind": "macc", "lots": [{"original": 1_000_000, "remaining": 900_000, "currency": "USD",
                                            "start": "2025-07-01", "end": "2027-06-30", "status": "Active"}]}

    result = analysis.burn_down(commitment, trend, TODAY)

    assert result["consumed"] == 100_000
    assert result["consumed_pct"] == 10.0
    assert result["run_rate"] == 10_000
    assert result["projected_shortfall"] > 0
    assert result["verdict"] == "Shortfall projected at the end of the term"


def test_macc_burn_down_on_track_when_the_run_rate_covers_the_remainder():
    trend = [{"month": m, "actual": 100_000, "partial": False} for m in ("2026-07", "2026-08", "2026-09")]
    commitment = {"kind": "macc", "lots": [{"original": 1_000_000, "remaining": 500_000, "currency": "USD",
                                            "start": "2025-07-01", "end": "2027-06-30", "status": "Active"}]}

    result = analysis.burn_down(commitment, trend, TODAY)

    assert result["projected_shortfall"] == 0
    assert result["projected_exhaustion"] == "2027-03"


def test_ea_burn_down_reads_the_prepayment_balance():
    trend = [{"month": "2026-09", "actual": 20_000, "partial": False}]
    commitment = {"kind": "ea-prepayment", "balance": {"beginning_balance": 100_000, "new_purchases": 20_000,
                                                       "ending_balance": 60_000, "currency": "EUR"}}

    result = analysis.burn_down(commitment, trend, TODAY)

    assert (result["original"], result["consumed"], result["remaining"]) == (120_000, 60_000, 60_000)
    assert result["projected_exhaustion"] == "2027-01"


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


def test_forecast_without_azure_falls_back_to_the_run_rate():
    trend = [{"month": m, "actual": 300, "partial": False} for m in ("2026-07", "2026-08", "2026-09")]

    result = analysis.forecast(trend, None, TODAY)

    assert result["source"] == "run-rate"
    assert [m["cost"] for m in result["months"]] == [300, 300, 300]
