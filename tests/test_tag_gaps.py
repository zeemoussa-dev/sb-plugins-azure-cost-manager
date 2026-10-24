"""Tagging gaps and Compass's tagging plan (operator, 2026-10-24).

Worth pinning: a gap is computed, not guessed -- a standard dimension not used, its
coverage by closed month, values written several ways; subscription names that state
an environment are what inheritance could fill. Compass's moves are kept only for a
standard dimension, carrying the plugin's coverage, never the model's.
"""
from __future__ import annotations

import json

from backend import advisor, tag_gaps, tags


def entry(by_key):
    return {"tags": {"keys": list(by_key), "by_key": {key: {"months": months} for key, months in by_key.items()}}}


def test_gaps_are_the_unused_dimensions_the_coverage_and_the_drifting_values():
    entries = {"1": entry({"Environment": {"2026-08": {"prd": 500.0, "prod": 200.0, "PROD": 100.0, "dev": 100.0},
                                           "2026-09": {"prod": 600.0, "dev": 100.0}},
                           "env": {"2026-09": {"Production": 50.0}}})}
    totals = {"2026-08": 1000.0, "2026-09": 1000.0, "2026-10": 300.0}
    report = tags.report(entries, totals, "2026-10")
    subscriptions = [{"subscription": "app-prod", "environment": "Production", "monthly": 600.0},
                     {"subscription": "shared", "environment": None, "monthly": 400.0}]

    found = tag_gaps.gaps(report, entries, subscriptions, "2026-10")

    environment = next(item for item in found["dimensions"] if item["dimension"] == "Environment")
    assert "Owner" in found["missing"] and "Environment" not in found["missing"]
    assert [point["coverage_pct"] for point in environment["coverage_trend"]] == [90.0, 75.0]
    assert environment["below_target"] and environment["spellings"] == ["Environment", "env"]
    assert environment["value_drift"][0]["value"] == "Production"
    assert set(environment["value_drift"][0]["written_as"]) == {"prd", "prod", "PROD", "Production"}
    assert found["environment_in_subscription_names"]["share_pct"] == 60.0


def test_a_tagging_plan_keeps_moves_on_the_standard_with_the_plugins_coverage():
    facts = {"dimensions": [{"dimension": "Environment", "used": True, "coverage_pct": 75.0, "untagged_last_month": 250.0},
                            {"dimension": "Owner", "used": False}]}
    reply = json.dumps({"summary": "s", "offer": "o", "questions": ["q"],
                        "moves": [{"kind": "inherit", "dimension": "Environment", "detail": "from subscriptions",
                                   "effort": "low"},
                                  {"kind": "adopt_key", "dimension": "Owner", "effort": "huge"},
                                  {"kind": "adopt_key", "dimension": "Colour"},
                                  {"kind": "delete_tags", "dimension": "Environment"}]})

    plan = advisor.check_tagging_plan(reply, facts)

    assert [(move["kind"], move["dimension"], move["coverage_pct"], move["effort"]) for move in plan["moves"]] == [
        ("inherit", "Environment", 75.0, "low"), ("adopt_key", "Owner", None, "medium")]


def test_the_customers_guide_is_never_handed_the_sellers_view():
    report = {"customer": {"name": "Contoso"}, "gaps": {"standard": ["Environment"], "dimensions": []}}
    seller = {"solutions": ["x"], "pitches": ["y"], "seller_says": ["z"]}

    assert "pitches" not in advisor.tagging_facts(report, seller, customer_view=True)
    assert advisor.tagging_facts(report, seller)["seller_says"] == ["z"]


def test_third_party_software_billed_as_licenses_is_not_taggable_spend():
    from backend import solution_plays
    month = {"actual": {"service": {"Virtual Machine Licenses": 10000.0, "Virtual Machines": 3000.0}},
             "meters": {"FortiFlex|Virtual Machine Licenses": 9800.0, "Windows Server|Virtual Machine Licenses": 200.0},
             "marketplace_offers": {"FortiFlex MSSP": 9800.0}, "measured": {"marketplace": 9900.0}}

    assert solution_plays.third_party_in_month(month, solution_plays.mapping(None)) == 9800.0

