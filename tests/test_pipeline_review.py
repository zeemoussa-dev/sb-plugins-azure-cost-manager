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


def _snapshot(week, rows):
    return {"week_end": week, "opportunities": rows}


def _row(key, **fields):
    return {"id": key, "title": key, "stem": key, "customer_id": "c1", "customer": "Contoso", "status": "Open",
            "stage": "Qualified", "consumption_start": "2026-11", "expected_monthly_usd": 1000, "plan": {},
            "created": "2026-10-20", "account_manager": {"key": "a@x", "name": "Ajay"}, **fields}


def test_movement_between_two_weeks():
    before = _snapshot("2026-10-18", [_row("moved"), _row("gone"), _row("won")])
    after = _snapshot("2026-10-25", [_row("moved", stage="Proposed", consumption_start="2027-01", expected_monthly_usd=2000),
                                     _row("won", status="Won"), _row("fresh")])

    kinds = sorted((change["kind"], change["id"]) for change in pipeline_review.movement(before, after)["changes"])

    assert kinds == [("amount", "moved"), ("new", "fresh"), ("removed", "gone"), ("slipped", "moved"),
                     ("stage up", "moved"), ("won", "won")]


def test_the_first_snapshot_reads_new_from_opened_dates():
    found = pipeline_review.movement(None, _snapshot("2026-10-18", [_row("in", created="2026-10-14"),
                                                                     _row("out", created="2026-10-01")]))

    assert found["first_snapshot"] and [change["id"] for change in found["changes"]] == ["in"]


def test_landing_is_raw_and_weighted_by_stage():
    chosen = pipeline_review.settings(None)
    rows = [_row("a", plan={"2026-11": 1000.0}), _row("b", stage="Committed", plan={"2026-11": 1000.0}),
            _row("c", status="Lost", plan={"2026-11": 5000.0})]

    found = pipeline_review.landing(rows, chosen, "2026-10", 3)

    assert found["months"]["2026-11"]["raw"] == 2000.0 and found["months"]["2026-11"]["weighted"] == 1050.0
    assert found["months"]["2026-10"]["raw"] == 0.0


def test_verdicts_at_the_tolerance_edges():
    assert pipeline_review.verdict(1000, 30, 20) == "late"
    assert pipeline_review.verdict(1000, 790, 20) == "short"
    assert pipeline_review.verdict(1000, 800, 20) == "landed"
    assert pipeline_review.verdict(1000, 1200, 20) == "landed"
    assert pipeline_review.verdict(1000, 1210, 20) == "over"


def test_planned_vs_actual_and_its_accuracy():
    rows = [_row("a", plan={"2026-08": 1000.0, "2026-09": 1000.0}), _row("b", plan={"2026-09": 500.0})]
    measured = {"a": {"months": ["2026-08", "2026-09"], "added": {"2026-08": 900.0, "2026-09": 1100.0}, "against": "scope"},
                "b": {"months": ["2026-09"], "added": None, "against": "no scope: add its technologies", "unscoped": True}}

    found = pipeline_review.planned_vs_actual(rows, measured, 20)

    # Unscoped is listed, never measured on the whole customer, and stays out of accuracy.
    assert [(row["id"], row["verdict"]) for row in found["rows"]] == [("a", "landed"), ("b", "no scope")]
    assert found["accuracy"] == 0.9


def test_levels_and_the_rollup_drill_down():
    customers = {"c1": {"name": "Contoso", "parent": None, "account_manager": {"key": "a@x", "name": "Ajay"},
                        "segment": "Strategic Accounts", "pss": [{"key": "d@x", "name": "Dalbir"}]},
                 "c2": {"name": "Contoso Labs", "parent": "c1", "account_manager": None}}
    assert pipeline_review.in_level("c2", customers, "customer:c1")
    assert pipeline_review.in_level("c1", customers, "pss:d@x") and pipeline_review.in_level("c2", customers, "am:")
    rows = [_row("a", plan={"2026-11": 1000.0}), _row("b", customer_id="c2", account_manager=None, plan={"2026-11": 100.0})]

    managers = pipeline_review.rollup(rows, [], customers, "all", pipeline_review.settings(None), "2026-10", 3, {})

    assert [(row["label"], row["drill"]) for row in managers] == [("Ajay", "am:a@x"), ("No account manager", "am:")]
