"""`azure-cost-manager.consumption`, a Customer note's own monthly consumption.

Worth pinning: a parent's figures are its own enrollments only; the switches
change the total, not the parts; the current month is marked open; the
forecast is the burn-down's run rate to the MACC's end (or the year's end);
`linked` names each note once, with its parent's note.
"""
from __future__ import annotations

from datetime import date

from backend import register
from backend.consumption_provider import SERVICE, ConsumptionProvider
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

TODAY = date(2026, 10, 17)
ACCOUNTS = [{"name": name, "display_name": name, "agreement_type": "EnterpriseAgreement",
             "term_start": "2026-01-01", "term_end": "2028-12-31"} for name in ("1", "2")]


def month(usage: float, marketplace: float = 0.0, credits: float = 0.0) -> dict:
    spend = {"service": {"VM": usage + marketplace}, "subscription": {"Prod": usage + marketplace}}
    return {"fetched_at": "2026-10-17T00:00:00+00:00", "currency": "USD", "actual": spend, "amortized": spend,
            "meters": {}, "balance": {"usage": usage, "marketplace": marketplace, "credits": credits,
                                      "fetched_at": "2026-10-17T00:00:00+00:00"}}


def provider(fake_api, parent_macc=True):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]))
    book.save(None, {"name": "Holding", "accounts": ["1"], "entity_customer": "Holding Note",
                     "commitment": {"type": "MACC", "amount": 1_000_000, "start": "2026-01-01", "end": "2027-03-31"}
                     if parent_macc else None})
    book.save(None, {"name": "Northwind", "accounts": ["2"], "parent": "holding", "entity_customer": "Northwind Note"})
    store.save_account("1", {"months": {**{f"2026-{m:02d}": month(1000, 100, 50) for m in range(1, 10)},
                                        "2026-10": month(300)}, "synced_at": "2026-10-17T00:00:00+00:00"})
    store.save_account("2", {"months": {f"2026-{m:02d}": month(9999) for m in range(1, 10)},
                             "synced_at": "2026-10-17T00:00:00+00:00"})
    service = ConsumptionService(store, book, today=lambda: TODAY)
    return ConsumptionProvider(service, book)


def test_a_parent_counts_only_its_own_enrollments_and_the_switches_change_the_total(fake_api):
    consumption = provider(fake_api)

    everything = consumption.monthly("Holding Note")
    usage_only = consumption.monthly("Holding Note", include_marketplace=False, subtract_credits=False)

    september = next(row for row in everything["months"] if row["month"] == "2026-09")
    assert september == {"month": "2026-09", "usage": 1000, "marketplace": 100, "credits": 50, "total": 1050,
                         "closed": True}
    assert next(row for row in usage_only["months"] if row["month"] == "2026-09")["total"] == 1000
    assert everything["months"][-1] == {"month": "2026-10", "usage": 300, "marketplace": 0, "credits": 0,
                                        "total": 300, "closed": False}
    assert everything["route"] == "/azure-cost-manager/report?report=Overview&customer=holding"
    assert everything["commitment"] == {"amount": 1_000_000, "start": "2026-01-01", "end": "2027-03-31"}


def test_the_forecast_is_the_run_rate_to_the_maccs_end_or_the_years(fake_api):
    with_macc = provider(fake_api).monthly("Holding Note")
    assert with_macc["forecast"][0] == {"month": "2026-10", "total": 1050}
    assert with_macc["forecast"][-1]["month"] == "2027-03"

    without = provider(type(fake_api)(), parent_macc=False).monthly("Holding Note")
    assert without["forecast"][-1]["month"] == "2026-12" and without["commitment"] is None


def test_linked_names_each_note_with_its_parents_note(fake_api):
    consumption = provider(fake_api)

    assert consumption.linked() == [
        {"customer_stem": "Holding Note", "name": "Holding", "parent_stem": None, "currency": "USD",
         "route": "/azure-cost-manager/report?report=Overview&customer=holding"},
        {"customer_stem": "Northwind Note", "name": "Northwind", "parent_stem": "Holding Note", "currency": "USD",
         "route": "/azure-cost-manager/report?report=Overview&customer=northwind"},
    ]
    assert consumption.monthly("Nobody") is None


def test_every_customer_is_listed_note_or_not_and_read_by_id(fake_api):
    consumption = provider(fake_api)
    consumption._book.save(None, {"name": "Litware", "accounts": ["2"], "parent": "holding"})

    rows = {row["id"]: row for row in consumption.customers()}

    assert rows["litware"] == {"id": "litware", "name": "Litware", "parent_id": "holding", "customer_stem": None,
                               "currency": "USD", "route": "/azure-cost-manager/report?report=Overview&customer=litware"}
    assert rows["holding"]["customer_stem"] == "Holding Note" and rows["holding"]["parent_id"] is None
    by_id = consumption.monthly_of("holding")
    assert by_id == consumption.monthly("Holding Note")
    assert consumption.monthly_of("litware")["months"][0]["total"] == 9999   # its own enrollment, no note needed
    assert consumption.monthly_of("nobody") is None


def test_register_provides_the_service(fake_api):
    register(fake_api)

    assert hasattr(fake_api.services[SERVICE], "monthly") and hasattr(fake_api.services[SERVICE], "linked")
