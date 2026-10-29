"""The Analysis tab: one slice of a customer's bill, its figures and Compass's reading."""
from __future__ import annotations

import pytest

from backend import focus_analysis

GROUPS = [{"name": "Genome programme", "match": ["EGP", "genom"]}]
CURRENT = "2026-10"


def merged_months() -> dict:
    """Six closed months and the running one: EGP Data's Storage doubles in the last three."""
    found = {}
    for index, month in enumerate(["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]):
        storage = 100.0 if index < 3 else 200.0
        found[month] = {"actual": {"pairs": {
            "EGP Data(1)": {"Storage": storage, "Virtual Machines": 50.0},
            "Labware Prod(2)": {"Storage": 30.0, "SQL Database": 20.0},
        }}}
    return found


def test_options_list_groups_subscriptions_and_services_by_their_recent_monthly_average():
    found = focus_analysis.options(merged_months(), GROUPS, CURRENT)
    assert found["groups"] == GROUPS
    assert found["subscriptions"][0] == {"name": "EGP Data(1)", "monthly": 250.0, "group": "Genome programme"}
    assert [row["name"] for row in found["services"]] == ["Storage", "Virtual Machines", "SQL Database"]


def test_a_slice_is_its_services_in_its_subscriptions_and_groups():
    focus = focus_analysis.validated({"groups": ["Genome programme"], "services": ["Storage"]}, GROUPS)
    found = focus_analysis.figures(merged_months(), focus, GROUPS, CURRENT)
    assert found["monthly_recent"] == 200.0 and found["monthly_before"] == 100.0 and found["change_pct"] == 100.0
    assert [row["name"] for row in found["subscriptions"]] == ["EGP Data(1)"]
    assert found["current_month"] == CURRENT and found["months"][-1] == CURRENT
    # Against the whole bill: 200 of 300 in the last closed months.
    assert found["share_of_bill_pct"] == 66.7


def test_services_alone_cover_every_subscription():
    focus = focus_analysis.validated({"services": ["Storage"]}, GROUPS)
    found = focus_analysis.figures(merged_months(), focus, GROUPS, CURRENT)
    assert found["monthly_recent"] == 230.0
    assert focus_analysis.title_of(focus) == "Storage in all subscriptions"


def test_the_choice_is_validated_and_keyed_whatever_its_order():
    first = focus_analysis.validated({"subscriptions": ["b", "a"], "services": ["Storage"]}, GROUPS)
    second = focus_analysis.validated({"services": ["Storage"], "subscriptions": ["a", "b", "a"]}, GROUPS)
    assert focus_analysis.key_of(first) == focus_analysis.key_of(second)
    for bad in ({}, {"groups": ["Nope"]}, {"services": "Storage"}, "x"):
        with pytest.raises(ValueError):
            focus_analysis.validated(bad, GROUPS)


def test_tag_values_naming_the_slice_are_handed_over_with_their_whole_tagged_spend():
    entries = {"1": {"tags": {"by_key": {
        "applicationname": {"months": {"2026-09": {"labware genome storage prod": 48_449.0, "fabric": 900.0}}},
        "owner": {"months": {"2026-09": {"genome team": 10.0}}},
    }}}}
    focus = focus_analysis.validated({"groups": ["Genome programme"]}, GROUPS)
    assert focus_analysis.tag_hints(entries, focus, GROUPS, "2026-09") == [
        {"tag": "applicationname", "value": "labware genome storage prod", "monthly": 48_449.0}]


def test_the_footprint_is_only_the_slice_subscriptions():
    entries = {"1": {"footprint": {"months": 2, "subscriptions": {
        "EGP Data(1)": {"meters": {"Hot LRS Data Stored": 400.0}, "resource_groups": {"rg-egp": 300.0}},
        "Labware Prod(2)": {"meters": {"SQL vCore": 100.0}, "resource_groups": {"rg-lab": 100.0}},
    }}}}
    found = focus_analysis.footprint(entries, ["EGP Data(1)"])
    assert found == {"meters": [{"name": "Hot LRS Data Stored", "monthly": 200.0}],
                     "resource_groups": [{"name": "rg-egp", "monthly": 150.0}]}


def test_compass_answer_is_trimmed_to_its_shape():
    reply = ('{"headline": "Storage doubled.", "cost_story": "EGP Data grew.", '
             '"architecture": {"workload": "A genome data lake", "confidence": "certain", "evidence": ["Hot LRS"]}, '
             '"optimisation": [{"move": "Tier to cool", "why": "cold reads", "check_first": "access logs"}, {"why": "no move"}], '
             '"growth": [{"pitch": "Compass for genomics", "why": "in-country AI"}], "questions": ["Retention?"]}')
    found = focus_analysis.check(reply)
    assert found["architecture"]["confidence"] == "low"
    assert [item["move"] for item in found["optimisation"]] == ["Tier to cool"]
    assert found["growth"] == [{"pitch": "Compass for genomics", "why": "in-country AI"}]
