"""Core42's revenue against the MACC burn (operator, 2026-10-18).

Worth pinning: Marketplace and credits always count against the signed value
(only an offer marked as not eligible is left out); Core42's revenue is that
burn less Marketplace bought from any publisher but Core42 or G42; credits stay
a filter on it.
"""
from __future__ import annotations

from datetime import date

from backend import consumption_analysis as analysis

TODAY = date(2026, 10, 18)


def item(publisher: str, offer: str, cost: float) -> dict:
    return {"publisher": publisher, "offer": offer, "plan": "", "subscription": "Prod", "recurring": True,
            "cost": cost, "quantity": 1, "unit": "", "lines": 1}


def month() -> dict:
    return {"currency": "USD", "actual": {"service": {"VM": 1000.0}, "subscription": {"Prod": 1000.0}},
            "balance": {"usage": 1000.0, "marketplace": 600.0, "credits": 50.0},
            "marketplace": {"items": [item("Core42", "Compass", 200), item("G42 Cloud", "Sovereign", 100),
                                      item("Databricks", "Lakehouse", 300)]}}


def test_core42_revenue_leaves_out_other_publishers_marketplace_only():
    merged, _ = analysis.merge({"1": {"months": {"2026-09": month()}}})
    parts = merged["2026-09"]["measured"]

    assert parts["marketplace_core42"] == 300
    assert analysis.measured_total(parts, {"marketplace": True, "credits": True}) == 1550
    assert analysis.measured_total(parts, {"marketplace": "core42", "credits": True}) == 1250
    assert analysis.measured_total(parts, {"marketplace": "core42", "credits": False}) == 1300


def test_every_month_carries_core42_revenue_beside_the_measured_total():
    merged, _ = analysis.merge({"1": {"months": {"2026-09": month()}}})

    row = analysis.monthly_totals(merged, "2026-10", {"marketplace": False, "credits": True})[0]

    assert (row["actual"], row["core42_revenue"], row["marketplace_core42"]) == (950, 1250, 300)


def test_the_signed_value_always_counts_marketplace_and_credits():
    switched_off = {"include_marketplace": False, "subtract_credits": False}

    assert analysis.commitment_measure(switched_off) == {"marketplace": "macc", "credits": True}


def test_publishers_are_matched_ignoring_case_and_spaces():
    assert analysis.is_core42_publisher("CORE 42 LLC") and analysis.is_core42_publisher("g42")
    assert not analysis.is_core42_publisher("Databricks")


def test_the_workbook_totals_follow_the_core42_filter():
    from backend.export_xlsx import _components

    merged, _ = analysis.merge({"1": {"months": {"2026-09": month()}}})
    core42 = {"marketplace": "core42", "credits": True}

    assert _components(merged["2026-09"], core42)["total"] == 1250
    assert _components(month(), core42)["total"] == 1250   # one enrollment's month, read from its balance


def test_other_g42_group_publishers_are_not_core42_revenue():
    assert not analysis.is_core42_publisher("Presight AI")
