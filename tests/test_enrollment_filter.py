"""Every customer report can be limited to some of the group's enrollments (operator,
2026-10-23: "some reports I can filter enrollments and others I can't").

Worth pinning: each report that used to read the whole group reads only the
enrollments chosen, and one outside the customer is refused.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

ACCOUNTS = [{"name": name, "display_name": f"Contoso {name}", "agreement_type": "EnterpriseAgreement",
             "term_start": "2026-01-01", "term_end": "2028-12-31"} for name in ("1", "2")]


def entry(subscription: str, cost: float) -> dict:
    months = {month: {"actual": {"service": {"VM": cost}, "subscription": {subscription: cost},
                                 "pairs": {subscription: {"VM": cost}}},
                      "amortized": {"service": {"VM": cost}, "subscription": {subscription: cost}}, "meters": {}}
              for month in ("2026-07", "2026-08", "2026-09")}
    footprint = {"first_month": "2026-07", "last_month": "2026-09", "months": 3, "fetched_at": "x",
                 "subscriptions": {subscription: {"services": {"Virtual Machines": cost * 3}, "meters": {},
                                                  "resource_groups": {}}}}
    return {"months": months, "footprint": footprint}


@pytest.fixture
def contoso(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [dict(account) for account in ACCOUNTS]))
    book.save(None, {"name": "Contoso", "accounts": ["1", "2"]})
    store.save_account("1", entry("sub-one", 1000.0))
    store.save_account("2", entry("sub-two", 50.0))
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc))
    return service, book.list()[0]["id"]


def test_each_report_reads_only_the_enrollments_chosen(contoso):
    service, customer_id = contoso

    assert [row["subscription"] for row in service.solutions_of(customer_id, ["2"])["subscriptions"]] == ["sub-two"]
    assert len(service.solutions_of(customer_id)["subscriptions"]) == 2
    assert service.tags(customer_id, ["1"])["customer"]["name"] == "Contoso"
    assert service.this_month(customer_id, ["2"])["customer"]["id"] == customer_id
    assert service.finops(customer_id, ["1"])["customer"]["id"] == customer_id
    assert service.marketplace(customer_id, "start", None, ["1"])["customer"]["id"] == customer_id
    def consumed(found: dict) -> float:
        return sum(month.get("consumption") or 0 for month in found["months"])

    assert 0 < consumed(service.quota_customer(customer_id, None, ["2"])) < consumed(service.quota_customer(customer_id))


def test_an_enrollment_outside_the_customer_is_refused(contoso):
    service, customer_id = contoso
    with pytest.raises(ValueError, match="none of those enrollments"):
        service.finops(customer_id, ["999"])
