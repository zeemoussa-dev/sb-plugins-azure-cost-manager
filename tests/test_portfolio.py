"""The customer list's portfolio: every customer at a glance.

Worth pinning: a parent's row rolls its affiliates up exactly as its report
does, the trend line holds closed months only, and the status reads the burn
the way an account manager would -- behind, early, consumed, or no MACC yet.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

TODAY = date(2026, 10, 17)
SYNCED = "2026-10-17T00:00:00+00:00"
ACCOUNTS = [{"name": name, "display_name": name, "agreement_type": "MicrosoftCustomerAgreement",
             "term_start": "2026-01-01", "term_end": "2028-12-31"} for name in ("1", "2", "3", "4")]


def month(total: float) -> dict:
    spend = {"service": {"VM": total}, "subscription": {"Prod": total}}
    return {"fetched_at": SYNCED, "currency": "USD", "actual": spend, "amortized": spend, "meters": {}}


def macc(amount: float) -> dict:
    return {"type": "MACC", "amount": amount, "start": "2026-01-01", "end": "2028-12-31"}


def portfolio(fake_api, holding_macc=50_000_000, synced_at=SYNCED) -> dict[str, dict]:
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]))
    book.save(None, {"name": "Holding", "accounts": ["1"], "commitment": macc(holding_macc)})
    book.save(None, {"name": "Northwind", "accounts": ["2"], "parent": "holding", "commitment": macc(7_000_000)})
    book.save(None, {"name": "Litware", "accounts": ["3"], "parent": "holding"})
    book.save(None, {"name": "Contoso", "accounts": ["4"]})
    for account, monthly in (("1", 1_000_000), ("2", 500_000), ("3", 250_000), ("4", 10_000)):
        store.save_account(account, {"months": {f"2026-{m:02d}": month(monthly) for m in range(1, 11)},
                                     "synced_at": synced_at})
    service = ConsumptionService(store, book, today=lambda: TODAY,
                                 now=lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    return {row["id"]: row for row in service.portfolio()}


def test_a_parent_rolls_up_its_affiliates_and_counts_what_it_allocated(fake_api):
    rows = portfolio(fake_api)

    holding = rows["holding"]
    assert holding["affiliates"] == ["northwind", "litware"]
    assert holding["enrollments"] == 3
    # The burn counts the current, partial month: it was consumed.
    assert holding["burn"]["consumed"] == 10 * 1_750_000
    assert holding["allocated"] == 7_000_000
    assert rows["northwind"]["parent"] == "holding"
    assert rows["northwind"]["burn"]["consumed"] == 10 * 500_000


def test_the_trend_holds_closed_months_only(fake_api):
    rows = portfolio(fake_api)

    assert [point["month"] for point in rows["contoso"]["recent"]] == [f"2026-{m:02d}" for m in range(4, 10)]
    assert rows["contoso"]["last_month"]["month"] == "2026-09"
    assert rows["contoso"]["last_month"]["actual"] == 10_000


def test_the_status_reads_the_burn(fake_api):
    rows = portfolio(fake_api)

    # 1.75M a month for 27 more months easily covers 50M; Northwind's 500k a month
    # runs out of 7M in 2027 with more than a year of term left.
    assert rows["holding"]["status"] == "early"
    assert rows["northwind"]["status"] == "early"
    # No MACC of its own, and its parent's affiliates roll up: it consumes the parent's.
    assert (rows["litware"]["status"], rows["litware"]["covered_by"]) == ("parent-macc", "Holding")


def test_a_macc_the_run_rate_cannot_reach_is_behind(fake_api):
    assert portfolio(fake_api, holding_macc=500_000_000)["holding"]["status"] == "behind"


def test_a_macc_already_burnt_is_consumed(fake_api):
    assert portfolio(fake_api, holding_macc=10_000_000)["holding"]["status"] == "consumed"


def test_an_unsynced_customer_says_so_before_anything_else(fake_api):
    rows = portfolio(fake_api, synced_at=None)

    assert {row["status"] for row in rows.values()} == {"not-synced"}
    assert rows["holding"]["stale"] is True


def test_a_group_partly_synced_shows_what_it_has_and_counts_the_rest(fake_api):
    portfolio(fake_api)
    store = ConsumptionStore(fake_api)
    store.save_account("3", {**store.account("3"), "synced_at": None})
    book = CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]))
    service = ConsumptionService(store, book, today=lambda: TODAY,
                                 now=lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))

    holding = next(row for row in service.portfolio() if row["id"] == "holding")

    assert holding["status"] == "early"
    assert holding["synced_at"] == SYNCED
    assert holding["unsynced_enrollments"] == 1


def test_a_padded_currency_code_is_trimmed(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]))
    book.save(None, {"name": "Contoso", "accounts": ["4"]})
    store.save_account("4", {"months": {"2026-09": {**month(10), "currency": "USD  "}}, "synced_at": SYNCED})

    rows = ConsumptionService(store, book, today=lambda: TODAY).portfolio()

    assert rows[0]["currency"] == "USD"
