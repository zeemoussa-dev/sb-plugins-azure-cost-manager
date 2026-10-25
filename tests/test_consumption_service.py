"""Customers and the sync, against a fake Azure.

Worth pinning: related enrollments are suggested together, a signed value is
validated, the sync never asks for a settled month twice, saves per window so a
stopped sync resumes, waits out throttling instead of failing, and reading a
customer never calls Azure.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend import register
from backend.billing_client import AzureApiError, AzureThrottled
from backend.consumption_service import ConsumptionService
from backend.consumption_store import (CONSUMPTION_CACHE_FILE, CUSTOMERS_FILE, LEGACY_TRACKED_ACCOUNTS_FILE,
                                       ConsumptionStore)
from backend.consumption_sync import ConsumptionSync, _windows
from backend.customers import AccountDirectory, CustomerBook, CustomerError, group_key
from conftest import cost_row

TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)

ACCOUNTS = [
    {"name": "10000001", "display_name": "Contoso Oil", "agreement_type": "EnterpriseAgreement",
     "term_start": "2026-01-15", "term_end": "2028-09-30"},
    {"name": "10000002", "display_name": "Contoso Oil-10000001-PrivateSaaS", "agreement_type": "EnterpriseAgreement",
     "term_start": "2026-06-01", "term_end": "2028-09-30"},
    {"name": "20000001", "display_name": "Fabrikam Energy", "agreement_type": "EnterpriseAgreement",
     "term_start": "2024-10-24", "term_end": "2027-10-31"},
    {"name": "20000002", "display_name": "Fabrikam  Energy", "agreement_type": "EnterpriseAgreement",
     "term_start": "2026-03-09", "term_end": "2029-03-31"},
]


class FakeAzure:
    def __init__(self) -> None:
        self.queries: list[tuple] = []
        self.balances: list[tuple] = []
        self.marketplace: list[tuple] = []
        self.throttle_next = 0
        self.fail_windows: set[str] = set()

    def list_billing_accounts(self):
        return [dict(account) for account in ACCOUNTS]

    def query_monthly_cost(self, account_name, cost_type, first_month, last_month):
        if self.throttle_next:
            self.throttle_next -= 1
            raise AzureThrottled(42)
        if first_month in self.fail_windows:
            raise AzureApiError(500, "boom")
        self.queries.append((account_name, cost_type, first_month, last_month))
        return [cost_row("2026-09", 900, "VM", "Prod"), cost_row("2026-09", 100, "Storage", "Dev"),
                cost_row("2026-10", 300, "VM", "Prod")]

    def forecast_monthly(self, account_name, first_month, last_month, azure_only=False):
        return [{"month": "2026-11", "cost": 950}]

    def query_monthly_meters(self, account_name, first_month, last_month, cost_type="ActualCost"):
        self.queries.append((account_name, "meters" if cost_type == "ActualCost" else "meters-amortized",
                             first_month, last_month))
        return [{"month": "2026-09", "meter_subcategory": "NDsr H100 v5 Series", "pricing_model": "Reservation",
                 "cost": 200, "currency": "USD"},
                {"month": "2026-09", "meter_subcategory": "Azure OpenAI", "pricing_model": "Reservation",
                 "cost": 100, "currency": "USD"}]

    def marketplace_charges(self, account_name, month):
        self.marketplace.append((account_name, month))
        return [{"publisher": "Northwind", "offer": "Linux image", "plan": "8.9", "subscription": "Prod",
                 "cost": 30.0, "quantity": 30.0, "unit": "1 hour", "recurring": False},
                {"publisher": "Northwind", "offer": "Linux image", "plan": "8.9", "subscription": "Prod",
                 "cost": 20.0, "quantity": 20.0, "unit": "1 hour", "recurring": False}]

    def billing_period_balance(self, account_name, month):
        self.balances.append((account_name, month))
        if month < "2026-01":
            raise AzureApiError(404, "no such billing period")
        return {"usage": 1000.0, "marketplace": 50.0, "credits": 30.0,
                "credit_details": [{"name": "Contract Price Match Credit", "value": 30.0}],
                "billed_separately": 0.0, "currency": "USD"}


def build(fake_api, azure, now=NOW):
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(azure.list_billing_accounts, now=lambda: now)
    book = CustomerBook(store, directory)
    waits: list[float] = []
    sync = ConsumptionSync(store, directory, lambda: azure, today=lambda: TODAY, now=lambda: now, sleep=waits.append)
    service = ConsumptionService(store, book, today=lambda: TODAY, now=lambda: now)
    return store, book, sync, service, waits


def test_register_declares_its_data_files_and_one_router(fake_api):
    register(fake_api)

    assert CUSTOMERS_FILE in fake_api.seed_data_files
    assert len(fake_api.routers) == 1


def test_renewals_and_linked_enrollments_are_suggested_together():
    by_name = {account["name"]: account for account in ACCOUNTS}
    keys = {account["name"]: group_key(account, by_name) for account in ACCOUNTS}

    assert keys["10000001"] == keys["10000002"] == "contoso oil"
    assert keys["20000001"] == keys["20000002"] == "fabrikam energy"


def test_a_signed_value_needs_an_amount_and_a_term(fake_api):
    _, book, *_ = build(fake_api, FakeAzure())

    with pytest.raises(CustomerError, match="term"):
        book.save(None, {"name": "Fabrikam", "accounts": ["20000001"],
                         "commitment": {"type": "MACC", "amount": 1_000_000}})
    with pytest.raises(CustomerError, match="see"):
        book.save(None, {"name": "Fabrikam", "accounts": ["nope"]})
    # A malformed request is the caller's to fix (400), never a crash (500).
    with pytest.raises(CustomerError, match="text"):
        book.save(None, {"name": ["Fabrikam", "Contoso"], "accounts": ["20000001"]})

    saved = book.save(None, {"name": "Fabrikam", "accounts": ["20000001", "20000002"],
                             "commitment": {"type": "MACC", "amount": "3000000", "currency": "usd",
                                            "start": "2024-10-24", "end": "2027-10-31"}})

    assert saved["id"] == "fabrikam"
    assert saved["commitment"]["amount"] == 3_000_000.0
    assert saved["commitment"]["currency"] == "USD"


def test_tracked_accounts_from_0_1_are_carried_over_as_customers(fake_api):
    fake_api.files[LEGACY_TRACKED_ACCOUNTS_FILE] = json.dumps(
        {"accounts": [{"name": "20000001", "display_name": "Fabrikam Energy"}]})
    store, *_ = build(fake_api, FakeAzure())

    assert store.customers() == [{"id": "fabrikam-energy", "name": "Fabrikam Energy",
                                  "accounts": ["20000001"], "commitment": None}]


def test_history_reaches_back_to_the_term_start_in_windows_of_a_year(fake_api):
    azure = FakeAzure()
    _, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Fabrikam", "accounts": ["20000001"]})

    sync.run()

    windows = sorted({(first, last) for _, _, first, last in azure.queries})
    assert windows == [("2024-10", "2025-09"), ("2025-10", "2026-09"), ("2026-10", "2026-10")]


def test_amortized_meters_reach_back_only_the_thirteen_months_finops_reads(fake_api):
    azure = FakeAzure()
    store, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Fabrikam", "accounts": ["20000001"]})

    sync.run()

    amortized = sorted((first, last) for _, kind, first, last in azure.queries if kind == "meters-amortized")
    assert amortized == [("2025-10", "2026-09"), ("2026-10", "2026-10")]
    september = store.account("20000001")["months"]["2026-09"]["meters_amortized"]["by"]
    assert september == {"NDsr H100 v5 Series|Reservation": 200, "Azure OpenAI|Reservation": 100}


def test_a_restarted_sync_skips_what_it_synced_today_and_starts_with_the_never_synced(fake_api):
    azure = FakeAzure()
    _, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Contoso", "accounts": ["10000002"]})
    sync.run()
    book.save(None, {"name": "Fabrikam", "accounts": ["20000001"]})
    azure.queries.clear()

    sync.run()

    assert {account for account, *_ in azure.queries} == {"20000001"}
    # The progress counts only the enrollment fetched, not the one skipped.
    assert (sync.status()["accounts_done"], sync.status()["accounts_total"]) == (1, 1)
    azure.queries.clear()
    sync.run("contoso")   # one customer, asked for by name, is always refreshed
    assert {account for account, *_ in azure.queries} == {"10000002"}


def test_a_settled_month_is_never_asked_for_again(fake_api):
    azure = FakeAzure()
    _, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Contoso", "accounts": ["10000002"]})
    sync.run()
    azure.queries.clear()

    later = datetime(2026, 10, 23, tzinfo=timezone.utc)
    _, _, sync_later, *_ = build(fake_api, azure, now=later)
    sync_later.run()

    # Fetched on 16 Oct, September had settled (30 Sep + 5 days); only October is asked for.
    assert {(first, last) for _, _, first, last in azure.queries} == {("2026-10", "2026-10")}


def test_throttling_is_waited_out_not_failed(fake_api):
    azure = FakeAzure()
    azure.throttle_next = 2
    _, book, sync, _, waits = build(fake_api, azure)
    book.save(None, {"name": "Contoso", "accounts": ["10000002"]})

    sync.run()

    assert waits == [43, 43]
    assert azure.queries


def test_a_failed_window_is_reported_and_the_rest_still_saved(fake_api):
    azure = FakeAzure()
    azure.fail_windows = {"2024-10"}
    store, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Fabrikam", "accounts": ["20000001"]})

    sync.run()

    entry = store.account("20000001")
    assert "2024-10..2025-09" in entry["errors"]
    assert "actual" not in entry["months"].get("2024-10", {})  # no cost for the failed window; its balance may be there
    assert entry["months"]["2026-09"]["actual"]["service"] == {"VM": 900, "Storage": 100}
    assert sync.status()["errors"]


def test_reading_a_customer_never_calls_azure_and_merges_its_enrollments(fake_api):
    azure = FakeAzure()
    _, book, sync, service, _ = build(fake_api, azure)
    book.save(None, {"name": "Fabrikam", "accounts": ["20000001", "20000002"]})
    sync.run()
    azure.queries.clear()

    result = service.analysis("fabrikam")
    by_enrollment = service.consumption("fabrikam", "2026-09", "2026-09", "account", "actual")

    assert azure.queries == []
    september = result["months"][-2]
    # Two EA enrollments, each billed 1000 usage + 50 Marketplace - 30 credit.
    assert (september["month"], september["actual"], september["cost_management"]) == ("2026-09", 2040.0, 2000.0)
    assert (september["usage"], september["marketplace"], september["credits"]) == (2000.0, 100.0, 60.0)
    assert {row["name"] for row in by_enrollment["rows"]} == {"Fabrikam Energy (20000001)",
                                                              "Fabrikam  Energy (20000002)"}
    assert result["forecast"]["months"][1] == {"month": "2026-11", "cost": 1900, "source": "azure"}


def test_removing_a_customer_keeps_its_invoice_totals_and_marketplace(fake_api):
    _, book, sync, *_ = build(fake_api, FakeAzure())
    book.save(None, {"name": "Contoso", "accounts": ["10000002"]})
    sync.run()

    book.delete("contoso")

    entry = json.loads(fake_api.files[CONSUMPTION_CACHE_FILE])["accounts"]["10000002"]
    assert entry["light"] is True
    assert set(entry["months"]["2026-09"]) == {"balance", "marketplace"}


def test_profiles_sync_every_other_billing_profile_lightly(fake_api):
    azure = FakeAzure()
    store, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Fabrikam", "accounts": ["20000001", "20000002"]})

    sync.run_profiles()

    # The two Contoso enrollments are no customer's: invoice totals and Marketplace, no Cost Management.
    assert {account for account, *_ in azure.queries} == set()
    assert {account for account, _ in azure.marketplace} == {"10000001", "10000002"}
    entry = store.account("10000002")
    assert entry["light"] is True and entry["display_name"] == "Contoso Oil-10000001-PrivateSaaS"
    assert entry["group_key"] == "contoso oil"


def test_windows_split_on_gaps_and_at_twelve_months():
    wanted = [f"2025-{m:02d}" for m in range(1, 13)] + ["2026-01", "2026-03"]

    assert [(w[0], w[-1]) for w in _windows(wanted)] == [("2025-01", "2025-12"), ("2026-01", "2026-01"),
                                                         ("2026-03", "2026-03")]


def test_one_enrollment_failing_unexpectedly_does_not_stop_the_others(fake_api):
    class Broken(FakeAzure):
        def query_monthly_cost(self, account_name, cost_type, first_month, last_month):
            if account_name == "10000002":
                raise ConnectionResetError("[WinError 10054] An existing connection was forcibly closed")
            return super().query_monthly_cost(account_name, cost_type, first_month, last_month)

    azure = Broken()
    store, book, sync, *_ = build(fake_api, azure)
    book.save(None, {"name": "Contoso", "accounts": ["10000002", "20000001"]})

    sync.run()

    assert store.account("20000001").get("synced_at")
    assert [error["account"] for error in sync.status()["errors"]] == ["10000002"]


def test_a_forecasts_only_sync_stores_the_whole_bill_and_the_usage_forecast(fake_api):
    """2026-10-25: the first run stopped at once -- its progress was a name, not a step."""
    from backend.consumption_store import ConsumptionStore
    from backend.consumption_sync import ConsumptionSync
    from backend.customers import AccountDirectory

    class Azure:
        def forecast_monthly(self, account, first, last, azure_only=False):
            return [{"month": "2026-12", "cost": 3500.0 if azure_only else 15000.0}]

    store = ConsumptionStore(fake_api)
    store.save_account("1", {"months": {"2026-10": {"actual": {"service": {"VM": 10.0}}}}})
    sync = ConsumptionSync(store, AccountDirectory(lambda: []), lambda: Azure(),
                           customers=lambda: [{"id": "c", "accounts": ["1"]}], today=lambda: date(2026, 10, 25))

    sync.run_forecasts()

    entry = store.account("1")
    assert entry["forecast"] == [{"month": "2026-12", "cost": 15000.0}]
    assert entry["forecast_usage"] == [{"month": "2026-12", "cost": 3500.0}]
