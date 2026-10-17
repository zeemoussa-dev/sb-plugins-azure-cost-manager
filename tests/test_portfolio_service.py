"""`azure-cost-manager.portfolio`, the service other plugins read a Customer
note's cost data through.

Worth pinning: it answers by the Customer note's stem, with the portfolio row
and a route to the customer's page here; None for a note nothing is linked to;
and register() provides it.
"""
from __future__ import annotations

from datetime import date

from backend import register
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook
from backend.portfolio_service import SERVICE, PortfolioService

ACCOUNTS = [{"name": "1", "display_name": "Contoso", "agreement_type": "MicrosoftCustomerAgreement",
             "term_start": "2026-01-01", "term_end": "2028-12-31"}]


def test_a_customer_note_gets_its_portfolio_row_and_a_route(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]))
    book.save(None, {"name": "Contoso", "accounts": ["1"], "entity_customer": "Contoso Note",
                     "commitment": {"type": "MACC", "amount": 120_000, "start": "2026-01-01", "end": "2028-12-31"}})
    spend = {"service": {"VM": 1_000.0}, "subscription": {"Prod": 1_000.0}}
    store.save_account("1", {"months": {f"2026-{m:02d}": {"fetched_at": "2026-10-17T00:00:00+00:00", "currency": "USD",
                                                          "actual": spend, "amortized": spend, "meters": {}}
                                        for m in range(1, 10)}, "synced_at": "2026-10-17T00:00:00+00:00"})
    service = PortfolioService(ConsumptionService(store, book, today=lambda: date(2026, 10, 17)), book)

    row = service.for_entity("Contoso Note")

    assert row["id"] == "contoso" and row["signed"] == 120_000
    assert row["burn"]["consumed"] == 9_000 and row["last_month"]["month"] == "2026-09"
    assert row["route"] == "/azure-cost-manager/report?report=Overview&customer=contoso"
    assert service.for_entity("Someone Else") is None


def test_register_provides_the_service(fake_api):
    register(fake_api)

    assert hasattr(fake_api.services[SERVICE], "for_entity")
