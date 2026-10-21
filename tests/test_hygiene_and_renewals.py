"""Subscription hygiene and Marketplace renewals.

Worth pinning: a dormant subscription was material and fell under a tenth; a new
one was not billed in the three months before; a renewal's cadence is the usual
gap between its charges, once-only is taken as yearly, and a missed one is overdue.
"""
from __future__ import annotations

from backend import hygiene, renewals


def subs(spend: dict[str, float]) -> dict:
    return {"actual": {"subscription": spend}}


def test_new_dormant_tiny_and_concentration():
    merged = {"2026-06": subs({"Prod": 9000.0, "Old": 800.0}), "2026-07": subs({"Prod": 9000.0, "Old": 800.0}),
              "2026-08": subs({"Prod": 9000.0, "Old": 800.0}),
              "2026-09": subs({"Prod": 9000.0, "Old": 20.0, "AI Lab": 600.0, "Sandbox": 10.0}),
              "2026-10": subs({"Prod": 1.0})}

    found = hygiene.analyse(merged, "2026-10")

    assert (found["last_month"], found["subscriptions"], found["tiny"]) == ("2026-09", 4, 2)
    assert [row["subscription"] for row in found["new"]] == ["AI Lab"]
    assert [row["subscription"] for row in found["dormant"]] == ["Old"]
    assert found["top_share_pct"] == round(9000 / 9630 * 100, 1)


def charge(publisher, offer, cost, recurring=True):
    return {"publisher": publisher, "offer": offer, "plan": "Annual", "subscription": "Prod",
            "cost": cost, "recurring": recurring}


def entries(charges_by_month: dict[str, list[dict]]) -> dict[str, dict]:
    return {"1": {"months": {month: {"marketplace": {"items": items}} for month, items in charges_by_month.items()}}}


def test_cadence_next_renewal_and_overdue():
    yearly = entries({"2024-11": [charge("Informatica", "IDMC", 373_301.0)],
                      "2025-11": [charge("Informatica", "IDMC", 373_301.0)]})
    once = entries({"2025-12": [charge("Context Labs", "Decarb", 816_192.0)]})
    missed = entries({"2025-06": [charge("Fortinet", "FortiGate", 9000.0)], "2025-07": [charge("Fortinet", "FortiGate", 9000.0)]})
    metered = entries({"2026-09": [charge("Ntegral", "Oracle Linux", 50.0, recurring=False)]})

    rows = renewals.calendar([("ADNOC", yearly), ("Mubadala", once), ("DGE", missed), ("TAQA", metered)], "2026-10")

    by_offer = {row["offer"]: row for row in rows}
    assert (by_offer["IDMC"]["cadence"], by_offer["IDMC"]["next_month"], by_offer["IDMC"]["status"]) == \
        ("yearly", "2026-11", "upcoming")
    assert (by_offer["Decarb"]["cadence_assumed"], by_offer["Decarb"]["next_month"]) == (True, "2026-12")
    assert "FortiGate" not in by_offer          # monthly, missed since 2025-08: long gone, not a calendar entry
    assert "Oracle Linux" not in by_offer       # metered, not a renewal
