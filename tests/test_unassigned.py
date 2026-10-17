"""Enrollments in no customer: what Settings lists so the operator can add them.

Worth pinning: assigned enrollments are left out; the rest are grouped the way
Settings suggests (a renewal, or linked under one parent); each group carries
its consumption from the light sync; the biggest come first.
"""
from __future__ import annotations

from datetime import date

from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

TODAY = date(2026, 10, 17)
ACCOUNTS = [
    {"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement"},
    {"name": "20002", "display_name": "Northwind Energy", "agreement_type": "EnterpriseAgreement"},
    {"name": "3", "display_name": "Northwind Energy-20002-Labs", "agreement_type": "EnterpriseAgreement"},
    {"name": "4", "display_name": "Litware", "agreement_type": "EnterpriseAgreement"},
]


def balance(usage: float, marketplace: float = 0.0, credits: float = 0.0) -> dict:
    return {"balance": {"usage": usage, "marketplace": marketplace, "credits": credits,
                        "fetched_at": "2026-10-17T00:00:00+00:00"}}


def test_unassigned_enrollments_are_grouped_with_their_consumption_biggest_first(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [dict(a) for a in ACCOUNTS])
    book = CustomerBook(store, directory)
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    store.save_account("20002", {"light": True, "months": {"2026-09": balance(1000, 100, 50), "2025-01": balance(9999)}})
    store.save_account("3", {"light": True, "months": {"2026-08": balance(500)}})
    service = ConsumptionService(store, book, today=lambda: TODAY)

    groups = service.unassigned(directory.accounts())

    assert [(g["name"], [a["name"] for a in g["accounts"]]) for g in groups] == [
        ("Northwind Energy", ["20002", "3"]), ("Litware", ["4"])]
    northwind = groups[0]
    assert (northwind["last_month"], northwind["last_twelve_months"], northwind["synced"]) == (1050, 1550, True)
    assert groups[1]["synced"] is False