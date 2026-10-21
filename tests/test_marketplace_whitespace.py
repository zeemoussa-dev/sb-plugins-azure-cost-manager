"""Marketplace whitespace.

Worth pinning: Core42's own offers are its share, never whitespace; other
publishers' spend is grouped by a category read from their names; each
customer's share of Marketplace already with Core42 is reported.
"""
from __future__ import annotations

from backend import marketplace_whitespace as mpw


def solution(publisher, offer, total, buyers, eligible=True):
    return {"publisher": publisher, "offer": offer, "total": total, "macc_eligible": eligible, "kind": "SaaS",
            "adopted_by": len(buyers), "customers": [{"name": name, "total": cost} for name, cost in buyers.items()]}


def test_other_publishers_by_category_and_core42s_share():
    report = {"period": None, "solutions": [
        solution("Core42", "Compass", 300.0, {"ADNOC": 300.0}),
        solution("Fortinet", "FortiGate Next-Generation Firewall", 500.0, {"ADNOC": 400.0, "DGE": 100.0}),
        solution("ALPHA DATA P.J.S.C", "Azure Backup Powered by Veeam", 200.0, {"ADNOC": 200.0}, eligible=False),
        solution("Informatica", "Intelligent Data Management Cloud", 100.0, {"DGE": 100.0}),
    ]}

    found = mpw.analyse(report)

    assert (found["third_party"], found["core42"], found["core42_share_pct"]) == (800.0, 300.0, 27.3)
    assert [(row["category"], row["total"]) for row in found["categories"]] == \
        [("Security", 500.0), ("Backup & DR", 200.0), ("Data & Analytics", 100.0)]
    adnoc = next(row for row in found["customers"] if row["name"] == "ADNOC")
    assert (adnoc["third_party"], adnoc["macc_eligible"], adnoc["core42_share_pct"]) == (600.0, 400.0, 33.3)


def test_categories_are_read_from_names_and_unknown_is_other():
    assert mpw.category_of("Ntegral Inc.", "Oracle Linux 8.9") == "OS & images"
    assert mpw.category_of("Anthropic", "Claude") == "AI & ML"
    assert mpw.category_of("Context Labs B.V.", "Decarb-as-a-Service Platform") == mpw.OTHER
