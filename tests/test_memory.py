"""What the seller told Compass about a customer.

Worth pinning: a line is kept and can be removed; the brief is handed it (and the
brief goes stale when it changes); an answer given in Explain this lands in the
customer's memory, so the brief hears it too; the memory travels with an export.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend.consumption_service import ConsumptionService
from backend.consumption_store import CUSTOMER_MEMORY_FILE, DATA_FILES, ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook


class FakeLlm:
    def __init__(self) -> None:
        self.asked: list = []

    def available(self) -> bool:
        return True

    def complete(self, messages, *, timeout):
        self.asked.append(messages)
        return "## Headline\nWritten."


def service_with(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    months = {month: {"actual": {"service": {"VM": cost}, "subscription": {"Prod": cost},
                                 "pairs": {"Prod": {"VM": cost}}}, "meters": {}}
              for month, cost in (("2026-08", 100.0), ("2026-09", 120.0))}
    store.save_account("1", {"months": months})
    llm = FakeLlm()
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc), llm=llm)
    return service, llm, book.list()[0]["id"]


def test_a_line_is_kept_and_can_be_removed(fake_api):
    service, _, customer_id = service_with(fake_api)
    kept = service.memory.add(customer_id, "  The MACC was renewed at $150M in September  ")
    assert kept[0]["said"] == "The MACC was renewed at $150M in September" and kept[0]["on"] == "2026-10-23"
    assert service.memory.remove(customer_id, kept[0]["id"]) == []
    with pytest.raises(ValueError):
        service.memory.add(customer_id, "   ")


def test_the_brief_hears_the_memory_and_goes_stale_when_it_changes(fake_api):
    service, llm, customer_id = service_with(fake_api)
    service.customer_brief(customer_id, write=True)

    service.memory.add(customer_id, "They are moving SAP from on-premises this quarter")
    assert service.customer_brief(customer_id)["stale"]
    service.customer_brief(customer_id, write=True)

    sent = json.loads(llm.asked[-1][1]["content"].split("```json\n", 1)[1].rsplit("\n```", 1)[0])
    assert sent["seller_says"][0]["said"] == "They are moving SAP from on-premises this quarter"
    assert "(you said)" in llm.asked[-1][0]["content"]


def test_an_explain_answer_lands_in_the_customers_memory(fake_api):
    from backend import compass
    from backend.advisor_service import Advisor
    service, llm, customer_id = service_with(fake_api)
    state: dict = {}
    advisor = Advisor(service, compass.Answers(lambda: state, state.update, lambda: datetime(2026, 10, 23)), llm)

    advisor.explain(customer_id, "service", "VM", note="A one-off data migration in September")

    assert service.memory.of(customer_id)[0]["source"] == "explain: service VM"
    assert service.brief_facts(customer_id)["seller_says"][0]["said"] == "A one-off data migration in September"


def test_the_memory_travels_with_an_export():
    assert CUSTOMER_MEMORY_FILE in DATA_FILES
