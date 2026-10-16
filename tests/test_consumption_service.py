"""Tracking and refreshing, against a fake Azure: a settled month is never asked
for twice, and a missing commitment or forecast does not fail a refresh."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend import register
from backend.billing_client import AzureApiError
from backend.consumption_service import AccountNotTracked, ConsumptionService
from backend.consumption_store import CONSUMPTION_CACHE_FILE, ConsumptionStore
from conftest import cost_row


class FakeAzure:
    def __init__(self, agreement_type="MicrosoftCustomerAgreement") -> None:
        self.agreement_type = agreement_type
        self.queries: list[tuple] = []
        self.forecast_fails = False

    def list_billing_accounts(self):
        return [{"name": "acct-1", "display_name": "Contoso Ltd", "agreement_type": self.agreement_type,
                 "account_type": "Enterprise"}]

    def query_monthly_cost(self, account_name, cost_type, first_month, last_month):
        self.queries.append((cost_type, first_month, last_month))
        return [cost_row("2026-09", 900), cost_row("2026-10", 300)]

    def forecast_monthly(self, account_name, first_month, last_month):
        if self.forecast_fails:
            raise AzureApiError(400, "Forecast is not supported for this scope")
        return [{"month": "2026-11", "cost": 950}]

    def consumption_commitment_lots(self, account_name):
        return []

    def enterprise_agreement_balance(self, account_name):
        raise AzureApiError(403, "no access to balances")


def service_on(fake_api, azure, today=date(2026, 10, 16),
               now=datetime(2026, 10, 16, 9, tzinfo=timezone.utc)) -> ConsumptionService:
    return ConsumptionService(ConsumptionStore(fake_api), lambda: azure, today=lambda: today, now=lambda: now)


def test_register_declares_its_data_files_and_one_router(fake_api):
    register(fake_api)

    assert len(fake_api.seed_data_files) == 2
    assert len(fake_api.routers) == 1


def test_only_accounts_the_sign_in_can_see_can_be_tracked(fake_api):
    service = service_on(fake_api, FakeAzure())

    with pytest.raises(AccountNotTracked):
        service.set_tracked(["someone-else"])
    tracked = service.set_tracked(["acct-1"])

    assert tracked[0]["display_name"] == "Contoso Ltd"
    assert tracked[0]["stale"] is True


def test_a_settled_month_is_not_queried_again(fake_api):
    azure = FakeAzure()
    service_on(fake_api, azure).set_tracked(["acct-1"])
    service_on(fake_api, azure).refresh("acct-1")
    assert azure.queries[0][1:] == ("2025-11", "2026-10")

    later = datetime(2026, 10, 20, tzinfo=timezone.utc)
    service_on(fake_api, azure, now=later).refresh("acct-1")

    # Fetched on 16 Oct, September had settled (30 Sep + 5 days); only October is asked for.
    assert azure.queries[-1][1:] == ("2026-10", "2026-10")


def test_a_failing_forecast_or_commitment_is_reported_not_fatal(fake_api):
    azure = FakeAzure(agreement_type="EnterpriseAgreement")
    azure.forecast_fails = True
    service = service_on(fake_api, azure)
    service.set_tracked(["acct-1"])

    result = service.refresh("acct-1")

    assert set(result["errors"]) == {"forecast", "commitment"}
    assert result["forecast"]["source"] == "run-rate"
    assert result["months"][-1] == {"month": "2026-10", "actual": 300.0, "amortized": 300.0,
                                    "mom_pct": None, "partial": True}


def test_untracking_an_account_drops_its_cache(fake_api):
    azure = FakeAzure()
    service = service_on(fake_api, azure)
    service.set_tracked(["acct-1"])
    service.refresh("acct-1")

    service.set_tracked([])

    assert json.loads(fake_api.files[CONSUMPTION_CACHE_FILE])["accounts"] == {}


def test_consumption_groups_by_subscription(fake_api):
    service = service_on(fake_api, FakeAzure())
    service.set_tracked(["acct-1"])
    service.refresh("acct-1")

    result = service.consumption("acct-1", "2026-09", "2026-09", "subscription", "actual")

    assert result["rows"] == [{"month": "2026-09", "subscription": "Prod", "cost": 900.0}]
