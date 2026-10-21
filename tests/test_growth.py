"""Growth and churn signals.

Worth pinning: only closed months count; a 20% move over three months is a
signal either way; a material service that fell away has stopped, and one that
appeared is new; a sharp drop compares last month with the three before it.
"""
from __future__ import annotations

from backend import consumption_analysis as analysis, growth, solution_plays


def month(total: float, services: dict[str, float] | None = None) -> dict:
    spend = {"service": services or {"Virtual Machines": total}, "subscription": {"Prod": total}}
    return {"currency": "USD", "actual": spend, "amortized": spend, "meters": {}}


def signals_for(monthly: dict[str, dict]) -> dict:
    merged, _ = analysis.merge({"1": {"months": monthly}})
    trend = analysis.monthly_totals(merged, "2026-10")
    return growth.analyse(trend, merged, solution_plays.mapping(None))


def test_three_months_up_a_fifth_or_more_is_growing():
    found = signals_for({**{f"2026-0{m}": month(1000) for m in (3, 4, 5, 6)},
                         **{f"2026-0{m}": month(1300) for m in (7, 8, 9)},
                         "2026-10": month(10)})   # the open month never counts

    assert found["last_month"] == "2026-09"
    assert found["status"] == "growing" and found["change_3m_pct"] == 30.0
    assert [signal["kind"] for signal in found["signals"]] == ["growing"]


def test_a_service_that_fell_away_has_stopped_and_one_that_appeared_is_new():
    before = {"Virtual Machines": 5000.0, "Azure Databricks": 2000.0}
    found = signals_for({**{f"2026-0{m}": month(7000, before) for m in range(3, 9)},
                         "2026-09": month(5500, {"Virtual Machines": 5000.0, "Microsoft Fabric": 1500.0})})

    assert [row["service"] for row in found["stopped"]] == ["Azure Databricks"]
    assert [row["service"] for row in found["started"]] == ["Microsoft Fabric"]
    data = next(row for row in found["by_play"] if row["play"] == solution_plays.DATA)
    assert data["recent"] == round((2000 + 2000 + 1500) / 3, 2)


def test_last_month_under_half_the_three_before_is_a_sharp_drop():
    found = signals_for({**{f"2026-0{m}": month(4000) for m in range(3, 9)}, "2026-09": month(1000)})

    assert "drop" in [signal["kind"] for signal in found["signals"]]


def test_a_customer_with_little_history_is_new():
    assert signals_for({"2026-08": month(100), "2026-09": month(120)})["status"] == "new"
