"""Baseline and quota.

Worth pinning: the fiscal year and its default baseline (the three months
before it); the baseline averages its months, a missing month counting zero;
above the line is counted net, closed months actual and the rest forecast; the
pipeline planned for closed months is weighed against what was added.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend import quota
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook


def test_the_fiscal_year_and_its_default_baseline():
    chosen = quota.settings({}, "2026-10")

    assert (chosen["fy_first"], chosen["fy_last"], chosen["fy"]) == ("2026-07", "2027-06", "FY27")
    assert (chosen["baseline_start"], chosen["baseline_last"]) == ("2026-04", "2026-06")
    assert quota.fiscal_year("2026-03", 7) == ("2025-07", "2026-06")
    custom = quota.settings({"baseline_start": "2026-01", "baseline_months": 6, "fy_start_month": 1}, "2026-10")
    assert (custom["fy_first"], custom["baseline_last"], custom["fy"]) == ("2026-01", "2026-06", "FY26")


def test_above_the_line_is_net_closed_months_actual_and_the_rest_forecast():
    trend = [{"month": m, "actual": a, "partial": False} for m, a in
             (("2026-04", 100.0), ("2026-05", 100.0), ("2026-07", 150.0), ("2026-08", 50.0), ("2026-09", 120.0))]
    series = [{"month": "2026-10", "forecast": 130.0, "pipeline": 25.0}, {"month": "2026-11", "forecast": 90.0, "pipeline": 0}]
    chosen = quota.settings({}, "2026-10")         # baseline April-June; June missing counts as zero

    found = quota.analyse(trend, series, chosen, "2026-10")

    assert found["baseline"] == round(200 / 3, 2) and found["baseline_covered"] == 2
    july = found["months"][0]
    assert (july["month"], july["kind"], july["above"]) == ("2026-07", "actual", round(150 - 200 / 3, 2))
    assert found["above_to_date"] == round(150 + 50 + 120 - 3 * 200 / 3, 2)    # August below the line takes away
    october = next(row for row in found["months"] if row["month"] == "2026-10")
    assert (october["kind"], october["consumption"], october["pipeline"]) == ("forecast", 130.0, 25.0)
    # Months with no forecast stand at the line: they add nothing.
    december = next(row for row in found["months"] if row["month"] == "2026-12")
    assert december["above"] == 0.0
    assert found["above_with_pipeline"] == round(found["above_projected"] + 25.0, 2)


def test_the_pipeline_planned_for_closed_months_against_what_was_added():
    found = {"above_to_date": 1000.0, "months": [{"month": m, "kind": "actual"} for m in ("2026-07", "2026-08", "2026-09")]}
    opportunities = [
        {"id": "1", "title": "AI landing zone", "status": "Won", "stage": "Committed",
         "plan": [{"month": "2026-08", "usd": 800}, {"month": "2026-09", "usd": 800}, {"month": "2026-11", "usd": 800}]},
        {"id": "2", "title": "Lost deal", "status": "Lost", "stage": "", "plan": [{"month": "2026-08", "usd": 5000}]},
    ]

    against = quota.pipeline_against_actual(opportunities, found, "2026-10")

    assert (against["planned_to_date"], against["gap"], against["behind"]) == (1600.0, -600.0, True)
    assert [item["title"] for item in against["opportunities"]] == ["AI landing zone"]


def test_settings_are_checked_and_kept(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    service = ConsumptionService(store, CustomerBook(store, AccountDirectory(lambda: [])), today=lambda: date(2026, 10, 22))

    saved = service.save_quota_settings({"quota": "5000000", "baseline_start": "2026-03", "baseline_months": 4})

    assert (saved["quota"], saved["baseline_start"], saved["baseline_last"]) == (5_000_000.0, "2026-03", "2026-06")
    assert service.save_quota_settings({"baseline_start": None})["baseline_is_default"] is True
    for bad in ({"fy_start_month": 13}, {"baseline_months": 0}, {"quota": -1}, {"baseline_start": "March"}):
        with pytest.raises(ValueError):
            service.save_quota_settings(bad)
