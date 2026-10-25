"""The pipeline review's foundations (PLAN.md, release 1).

Worth pinning: the week reported is the last one closed (Sunday night); an affiliate
takes its parent's account manager field by field; a person shows by the link's alias,
else the Person note's name; an opportunity's scope is only services its technologies
name; a natural trend is fitted only on the months up to its cut-off; an opportunity's
baseline is cut before it was opened or started consuming and is then marked estimated;
a snapshot retaken replaces that week's.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from backend import account_owners, pipeline_review


def test_the_week_reported_is_the_last_one_closed():
    assert pipeline_review.week_end(date(2026, 10, 26)) == date(2026, 10, 25)   # Monday: the Sunday just gone
    assert pipeline_review.week_end(date(2026, 10, 25)) == date(2026, 10, 18)   # Sunday: this week is still open
    assert not pipeline_review.taken_late(date(2026, 10, 18), datetime(2026, 10, 19, 9))
    assert pipeline_review.taken_late(date(2026, 10, 18), datetime(2026, 10, 25, 9))


def test_an_affiliate_takes_its_parents_coverage_field_by_field():
    parent = {"account_manager": "[[naima.bikbi@core42.ai|Naima Bikbi]]", "segment": "Strategic Accounts",
              "pss": ["[[dalbir.maan@core42.ai]]"]}

    found = account_owners.covering({"segment": "Major Accounts"}, parent, {"dalbir.maan@core42.ai": "Dalbir Maan"})

    assert found["account_manager"] == {"key": "naima.bikbi@core42.ai", "name": "Naima Bikbi"}
    assert found["segment"] == "Major Accounts" and found["inherited"] == ["account_manager", "pss"]
    assert found["pss"] == [{"key": "dalbir.maan@core42.ai", "name": "Dalbir Maan"}]


def test_a_scope_is_only_services_the_technologies_name():
    services = {"Microsoft Sentinel", "Log Analytics", "Virtual Machines"}

    assert pipeline_review.scope_of({"technologies": ["sentinel", "Log analytics"]}, services) == [
        "Log Analytics", "Microsoft Sentinel"]
    assert pipeline_review.scope_of({"technologies": []}, services) == []


def test_the_natural_trend_is_fitted_only_up_to_its_cut_off():
    trend = [{"month": f"2026-{month:02d}", "actual": 100.0 + 10 * month, "partial": False} for month in range(1, 10)]
    trend += [{"month": "2026-10", "actual": 9999.0, "partial": True}]

    before = pipeline_review.natural(trend[:6] + [{**point, "actual": 5000.0} for point in trend[6:]], "2026-06", 3)

    assert before["fitted_through"] == "2026-06" and list(before["by_month"]) == ["2026-07", "2026-08", "2026-09"]
    assert before["by_month"]["2026-07"] < 300                      # the 5000s after the cut-off never entered it
    assert pipeline_review.natural(trend[:3], "2026-03", 3) is None   # too little history


def test_an_opportunitys_plan_or_its_monthly_figure_carried_forward():
    assert pipeline_review.planned_by_month({"plan": [{"month": "2026-11", "usd": 5000}]}) == {"2026-11": 5000.0}
    carried = pipeline_review.planned_by_month({"consumption_start": "2026-11", "expected_monthly_usd": 1000})
    assert len(carried) == 12 and carried["2027-10"] == 1000.0


def test_settings_are_checked_and_a_retaken_week_replaces_its_snapshot():
    with pytest.raises(ValueError):
        pipeline_review.validated({"stage_weights": {"Committed": 1.5}})
    with pytest.raises(ValueError):
        pipeline_review.validated({"stage_weights": {"Signed": 0.9}})
    assert pipeline_review.settings({"stage_weights": {"Proposed": 0.4}})["stage_weights"]["Committed"] == 0.8

    kept = pipeline_review.kept([{"week_end": "2026-10-11"}, {"week_end": "2026-10-18", "n": 1}],
                                {"week_end": "2026-10-18", "n": 2})
    assert [row.get("n") for row in kept] == [None, 2]


def test_gaps_name_what_weakens_the_review():
    found = pipeline_review.gaps(
        [{"title": "A", "consumption_start": "2026-11", "plan": {}, "scope": []},
         {"title": "B", "consumption_start": None, "plan": {"2026-11": 10.0}, "scope": ["Storage"]}],
        {"c1": {"name": "Contoso", "account_manager": None}})

    assert found["customers_without_account_manager"] == ["Contoso"]
    assert found["opportunities_without_start"] == ["B"] and found["opportunities_unscoped"] == ["A"]
