"""FinOps to the max (operator, 2026-10-24).

Worth pinning: the findings are the plugin's -- Hybrid Benefit is the license meters
billed, a renewal is a purchase month plus a term, waste is a rule over a
subscription's footprint -- and Compass's savings plan keeps only moves about those
findings, with the saving the plugin priced. The customer's report is never handed
the seller's pitches, quota or memory.
"""
from __future__ import annotations

import json

from backend import advisor, finops_extra


def test_hybrid_benefit_is_the_license_meters_billed_over_closed_months():
    actual = {month: {"Windows Server D4s v5|Virtual Machines": 300.0, "SQL Server Enterprise|Virtual Machines": 900.0,
                      "SQL Server on Azure Arc Standard|Arc": 5000.0, "SUSE Linux Enterprise|Virtual Machines": 30.0,
                      "D4s v5|Virtual Machines": 4000.0}
              for month in ("2026-07", "2026-08", "2026-09")}

    found = finops_extra.hybrid_benefit(actual, ["2026-07", "2026-08", "2026-09"])

    assert [(row["product"], row["monthly"]) for row in found] == [("SQL Server", 900.0), ("Windows Server", 300.0)]


def test_a_commitment_may_renew_a_year_or_three_after_it_was_bought():
    found = finops_extra.renewals([{"month": "2025-12", "bought_up_front": 12000.0},
                                   {"month": "2023-01", "bought_up_front": 5000.0}], "2026-10")

    assert found[0]["renews_if"] == {"1y": "2026-12", "3y": "2028-12"} and found[0]["soon"] == ["1y"]
    assert found[1]["soon"] == []


def test_waste_is_asked_about_never_assumed():
    rows = [{"subscription": "app-dev", "environment": "Development", "monthly": 2000.0,
             "top_services": [{"name": "Storage", "monthly": 800.0}],
             "top_meters": [{"name": "Premium SSD P30", "monthly": 600.0}]},
            {"subscription": "logs-prod", "environment": "Production", "monthly": 5000.0,
             "top_services": [{"name": "Log Analytics", "monthly": 2500.0}], "top_meters": []},
            {"subscription": "archive", "environment": None, "monthly": 3000.0,
             "top_services": [{"name": "Storage", "monthly": 2000.0}, {"name": "Backup", "monthly": 1000.0}],
             "top_meters": []},
            {"subscription": "mixed", "environment": None, "monthly": 3000.0,
             "top_services": [{"name": "Storage", "monthly": 1000.0}], "top_meters": []}]

    found = {(item["subscription"], item["kind"]) for item in finops_extra.waste(rows)}

    assert found == {("app-dev", "premium-disks-non-production"), ("logs-prod", "monitoring-share"),
                     ("archive", "storage-only")}


def test_a_plan_keeps_moves_about_the_findings_with_the_plugins_saving():
    facts = {"candidates": [{"meter": "D4s v5", "monthly_on_demand": 4000.0,
                             "savings_monthly_by_option": {"ri_1y": 1200.0, "ri_3y": 2300.0, "sp_1y": 900.0}}],
             "hybrid_benefit": [{"product": "SQL Server", "monthly": 900.0}],
             "worth_a_look": [{"subscription": "archive", "monthly_at_stake": 3000.0}]}
    reply = json.dumps({"summary": "Commit the D-series.", "reinvest": "Put it into AI.", "questions": ["Licenses?"],
                        "moves": [{"kind": "reserve", "ref": "D4s v5", "option": "sp_1y", "risk": "low"},
                                  {"kind": "savings_plan", "ref": "D4s v5", "option": "sp_1y", "risk": "nope"},
                                  {"kind": "hybrid_benefit", "ref": "SQL Server"},
                                  {"kind": "investigate", "ref": "archive"},
                                  {"kind": "reserve", "ref": "E8s v5", "option": "ri_3y"},
                                  {"kind": "delete_everything", "ref": "D4s v5"}]})

    plan = advisor.check_finops_plan(reply, facts)

    assert [(move["kind"], move["option"], move["saving_monthly"]) for move in plan["moves"]] == [
        ("reserve", "ri_3y", 2300.0), ("savings_plan", "sp_1y", 900.0), ("hybrid_benefit", None, 900.0),
        ("investigate", None, None)]
    assert plan["moves"][1]["risk"] == "medium" and plan["moves"][3]["monthly"] == 3000.0
    assert [move["subject"] for move in plan["moves"]] == ["meter", "meter", "license", "subscription"]

