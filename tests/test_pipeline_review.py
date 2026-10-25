"""The pipeline review (PLAN.md): monthly snapshots, and each customer's plan against its
growth above the quota baseline over the quota period (operator, 2026-10-25).

Worth pinning: snapshots are one per month, the running one refreshed when stale, the
first weekly one counted as its month; an affiliate takes its parent's account manager
field by field, and one with its own manager is measured on its own; a scope is only
services its technologies name; a natural trend is fitted only up to its cut-off; the
plan is set against the growth above baseline per unit, month by month, closed months
actual; a verdict reads that growth against what was planned to date.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend import account_owners, pipeline_review


def test_snapshots_are_monthly_and_the_running_one_is_refreshed_when_stale():
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    assert pipeline_review.stale({"taken_at": "2026-10-25T05:00:00+00:00"}, now)
    assert not pipeline_review.stale({"taken_at": "2026-10-25T09:00:00+00:00"}, now)
    # The weekly snapshot taken first counts as its month; a retake replaces the month's.
    found = pipeline_review.normalized([{"week_end": "2026-10-18", "taken_at": "2026-10-25T13:00:00+00:00"}])
    assert found[0]["month"] == "2026-10"
    kept = pipeline_review.kept([{"month": "2026-09"}, {"month": "2026-10", "n": 1}], {"month": "2026-10", "n": 2})
    assert [row.get("n") for row in kept] == [None, 2]


def test_an_affiliate_takes_its_parents_coverage_field_by_field():
    parent = {"account_manager": "[[naima.bikbi@core42.ai|Naima Bikbi]]", "segment": "Strategic Accounts",
              "pss": ["[[dalbir.maan@core42.ai]]"]}

    found = account_owners.covering({"segment": "Major Accounts"}, parent, {"dalbir.maan@core42.ai": "Dalbir Maan"})

    assert found["account_manager"] == {"key": "naima.bikbi@core42.ai", "name": "Naima Bikbi"}
    assert found["segment"] == "Major Accounts" and found["inherited"] == ["account_manager", "pss"]
    assert found["pss"] == [{"key": "dalbir.maan@core42.ai", "name": "Dalbir Maan"}]


def test_an_affiliate_with_its_own_manager_is_its_own_unit():
    customers = {"dge": {"parent": None, "account_manager": {"key": "fatma"}},
                 "doh": {"parent": "dge", "account_manager": {"key": "salah"}, "inherited": []},
                 "adeo": {"parent": "dge", "account_manager": {"key": "fatma"}, "inherited": ["account_manager"]}}

    assert pipeline_review.unit_of("doh", customers) == "doh"
    assert pipeline_review.unit_of("adeo", customers) == "dge" and pipeline_review.unit_of("dge", customers) == "dge"


def test_a_scope_is_only_services_the_technologies_name():
    services = {"Microsoft Sentinel", "Log Analytics", "Virtual Machines"}

    assert pipeline_review.scope_of({"technologies": ["sentinel", "Log analytics"]}, services) == [
        "Log Analytics", "Microsoft Sentinel"]
    assert pipeline_review.scope_of({"technologies": []}, services) == []


def test_the_natural_trend_is_fitted_only_up_to_its_cut_off():
    trend = [{"month": f"2026-{month:02d}", "actual": 100.0 + 10 * month, "partial": False} for month in range(1, 10)]

    before = pipeline_review.natural(trend[:6] + [{**point, "actual": 5000.0} for point in trend[6:]], "2026-06", 3)

    assert before["fitted_through"] == "2026-06" and list(before["by_month"]) == ["2026-07", "2026-08", "2026-09"]
    assert before["by_month"]["2026-07"] < 300                      # the 5000s after the cut-off never entered it
    assert pipeline_review.natural(trend[:3], "2026-03", 3) is None   # too little history


def test_an_opportunitys_plan_or_its_monthly_figure_carried_forward():
    assert pipeline_review.planned_by_month({"plan": [{"month": "2026-11", "usd": 5000}]}) == {"2026-11": 5000.0}
    assert pipeline_review.planned_by_month({"plan": {"2026-11": 5000}}) == {"2026-11": 5000.0}
    carried = pipeline_review.planned_by_month({"consumption_start": "2026-11", "expected_monthly_usd": 1000})
    assert len(carried) == 12 and carried["2027-10"] == 1000.0


def test_settings_are_checked():
    with pytest.raises(ValueError):
        pipeline_review.validated({"stage_weights": {"Committed": 1.5}})
    with pytest.raises(ValueError):
        pipeline_review.validated({"stage_weights": {"Signed": 0.9}})
    assert pipeline_review.settings({"stage_weights": {"Proposed": 0.4}})["stage_weights"]["Committed"] == 0.8


def _snapshot(month, rows):
    return {"month": month, "opportunities": rows}


def _row(key, **fields):
    return {"id": key, "title": key, "stem": key, "customer_id": "c1", "customer": "Contoso", "status": "Open",
            "stage": "Qualified", "consumption_start": "2026-11", "expected_monthly_usd": 1000, "plan": {},
            "created": "2026-10-20", "account_manager": {"key": "a@x", "name": "Ajay"}, **fields}


def test_movement_since_last_month():
    before = _snapshot("2026-09", [_row("moved"), _row("gone"), _row("won")])
    after = _snapshot("2026-10", [_row("moved", stage="Proposed", consumption_start="2027-01", expected_monthly_usd=2000),
                                  _row("won", status="Won"), _row("fresh")])

    kinds = sorted((change["kind"], change["id"]) for change in pipeline_review.movement(before, after)["changes"])

    assert kinds == [("amount", "moved"), ("new", "fresh"), ("removed", "gone"), ("slipped", "moved"),
                     ("stage up", "moved"), ("won", "won")]


def test_the_first_snapshot_reads_new_from_the_month_opened():
    found = pipeline_review.movement(None, _snapshot("2026-10", [_row("in", created="2026-10-24"),
                                                                  _row("out", created="2026-09-30")]))

    assert found["first_snapshot"] and [change["id"] for change in found["changes"]] == ["in"]


def test_landing_covers_the_quota_period_raw_and_weighted():
    chosen = pipeline_review.settings(None)
    rows = [_row("a", plan={"2026-07": 1000.0, "2026-11": 1000.0}), _row("b", stage="Committed", plan={"2026-11": 1000.0}),
            _row("c", status="Lost", plan={"2026-11": 5000.0})]

    found = pipeline_review.landing(rows, chosen, ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"])

    assert found["months"]["2026-07"]["raw"] == 1000.0                 # a month gone still counts
    assert found["months"]["2026-11"]["raw"] == 2000.0 and found["months"]["2026-11"]["weighted"] == 1050.0


def test_verdicts_read_growth_against_plan():
    assert pipeline_review.verdict(1000, 30, 20) == "not growing"
    assert pipeline_review.verdict(1000, 790, 20) == "short"
    assert pipeline_review.verdict(1000, 800, 20) == "landed"
    assert pipeline_review.verdict(1000, 1210, 20) == "over"
    assert pipeline_review.verdict(0, 500, 20) == "growing without opportunities"


def test_each_units_plan_against_its_growth_above_baseline():
    customers = {"c1": {"name": "Contoso", "parent": None, "account_manager": {"key": "a@x", "name": "Ajay"}}}
    groups = {"c1": {"name": "Contoso", "baseline": 10000.0, "months": [
        {"month": "2026-07", "kind": "actual", "above": 800.0},
        {"month": "2026-08", "kind": "actual", "above": 1200.0},
        {"month": "2026-09", "kind": "forecast", "above": 1500.0}]}}
    rows = [_row("a", plan={"2026-07": 1000.0, "2026-08": 1000.0, "2026-09": 1000.0})]

    found = pipeline_review.growth_against_plan(groups, rows, {"a": "c1"}, customers, pipeline_review.settings(None),
                                                ["2026-07", "2026-08", "2026-09"], 20)

    row = found["rows"][0]
    assert (row["growth_to_date"], row["planned_to_date"], row["verdict"]) == (2000.0, 2000.0, "landed")
    assert (row["growth_period"], row["planned_period"]) == (3500.0, 3000.0)
    assert found["months"]["2026-09"]["kind"] == "forecast"


def test_the_rollup_by_account_manager_drills_into_their_customers():
    customers = {"c1": {"name": "Contoso", "parent": None, "account_manager": {"key": "a@x", "name": "Ajay"}},
                 "c2": {"name": "Fabrikam", "parent": None, "account_manager": None}}
    growth = {"rows": [
        {"id": "c1", "name": "Contoso", "opportunities": 1, "planned_period": 3000.0, "weighted_period": 750.0,
         "planned_to_date": 2000.0, "growth_to_date": 2000.0, "growth_period": 3500.0, "verdict": "landed"},
        {"id": "c2", "name": "Fabrikam", "opportunities": 0, "planned_period": 0.0, "weighted_period": 0.0,
         "planned_to_date": 0.0, "growth_to_date": 400.0, "growth_period": 900.0, "verdict": "growing without opportunities"}]}

    managers = pipeline_review.rollup([], growth, {}, customers, "all", pipeline_review.settings(None), [], set(), {}, 20)
    one = pipeline_review.rollup([], growth, {}, customers, "am:a@x", pipeline_review.settings(None), [], set(), {}, 20)

    assert [(row["label"], row["drill"], row["verdict"]) for row in managers] == [
        ("Ajay", "am:a@x", "landed"), ("No account manager", "am:", "growing without opportunities")]
    assert one[0]["drill"] == "customer:c1"


def test_gaps_name_what_weakens_the_review():
    found = pipeline_review.gaps(
        [{"title": "A", "consumption_start": "2026-11", "plan": {}, "scope": []},
         {"title": "B", "consumption_start": None, "plan": {"2026-11": 10.0}, "scope": ["Storage"]}],
        {"c1": {"name": "Contoso", "account_manager": None}})

    assert found["customers_without_account_manager"] == ["Contoso"]
    assert found["opportunities_without_start"] == ["B"]
