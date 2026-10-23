"""The seller's Compass features beyond the brief.

Worth pinning: a figure a seller sees is the plugin's, never the model's (an
action's value is the Solution note's sizing, a draft's value the size chosen,
a sizing the bill times the factor); an answer about an unknown customer, report
or block is dropped; an explanation is kept per item and data; a question is
answered only from the reports Compass chose to read.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend import advisor, compass
from backend.advisor_service import Advisor
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

SIZING = {"rows": [{"block": "Models", "service": "Azure OpenAI", "small": 100.0, "medium": 1000.0, "large": 5000.0,
                    "basis": "tokens"},
                   {"block": "Search", "service": "AI Search", "small": 50.0, "medium": 250.0, "large": 1000.0,
                    "basis": "S1"}],
          "totals": {"small": 150.0, "medium": 1250.0, "large": 6000.0}}


def test_an_action_keeps_only_known_customers_and_the_notes_sizing():
    facts = {"customers": [{"customer_id": "c", "customer": "Contoso", "last_month": 9000,
                            "pitches": [{"pitch": "Use Compass", "solution": "GenAI", "sized_monthly": [150, 1250, 6000]}]}]}
    reply = json.dumps([{"customer_id": "c", "action": "Pitch Compass", "why": "GenAI without Compass", "urgency": "now",
                         "pitch": "Use Compass", "value": 99999999},
                        {"customer_id": "ghost", "action": "x"}])

    found = advisor.check_actions(reply, facts)

    assert len(found) == 1 and found[0]["sized_monthly"] == [150, 1250, 6000] and "value" not in found[0]


def test_a_draft_takes_its_value_from_the_size_chosen():
    reply = json.dumps({"title": "Contoso GenAI", "summary": "s", "size": "large", "next_steps": ["a"],
                        "email_subject": "Hi", "email_body": "Body", "expected_monthly": 1})
    found = advisor.check_draft(reply, {"sizing": SIZING, "pitch": "p"})
    assert found["expected_monthly"] == 6000.0 and found["size"] == "large"


def test_a_sizing_is_the_bill_times_the_factor_whatever_the_model_says():
    reply = json.dumps({"blocks": [{"block": "Models", "size": "large", "factor": 2, "reason": "2x users"},
                                   {"block": "Search", "size": "huge", "factor": 999}, {"block": "Ghost", "size": "small"}],
                        "assumptions": ["500 users"], "questions": ["How many documents?"]})
    found = advisor.check_sizing(reply, SIZING)
    assert [(row["block"], row["size"], row["factor"], row["monthly"]) for row in found["rows"]] == [
        ("Models", "large", 2.0, 10000.0), ("Search", "medium", 10.0, 2500.0)]
    assert found["total"] == 12500.0


def test_a_plan_keeps_only_known_reports():
    reply = '```json\n{"calls": [{"tool": "growth", "args": {"direction": "declining"}}, {"tool": "rm -rf", "args": {}}]}\n```'
    assert advisor.check_plan(reply) == [{"tool": "growth", "args": {"direction": "declining"}}]


def test_a_marketplace_answer_is_kept_only_for_products_asked_about():
    reply = json.dumps([{"key": "a", "category": "Security", "what": "A firewall", "compass_alternative": False},
                        {"key": "b", "category": "Nonsense"}, {"key": "z", "category": "Security"}])
    assert advisor.check_marketplace(reply, {"a", "b"}) == {
        "a": {"category": "Security", "what": "A firewall", "compass_alternative": False},
        "b": {"category": "Other", "what": "", "compass_alternative": False}}


class FakeLlm:
    def __init__(self, replies) -> None:
        self.replies = list(replies)
        self.asked: list = []

    def available(self) -> bool:
        return True

    def complete(self, messages, *, timeout):
        self.asked.append(messages)
        return self.replies.pop(0)


def advisor_with(fake_api, replies):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    months = {month: {"actual": {"service": {"VM": cost, "SQL": 50.0}, "subscription": {"Prod": cost + 50},
                                 "pairs": {"Prod": {"VM": cost, "SQL": 50.0}}}, "meters": {}}
              for month, cost in (("2026-07", 100.0), ("2026-08", 110.0), ("2026-09", 300.0))}
    store.save_account("1", {"months": months})
    llm = FakeLlm(replies)
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc), llm=llm)
    state: dict = {}
    answers = compass.Answers(lambda: state, state.update, lambda: datetime(2026, 10, 23, tzinfo=timezone.utc))
    return Advisor(service, answers, llm), llm, book.list()[0]["id"]


def test_an_explanation_is_kept_for_the_item_and_its_data(fake_api):
    found, llm, customer_id = advisor_with(fake_api, ["VM tripled in Prod. **Is it a migration?**"])

    assert found.explain(customer_id, "service", "VM")["kept"] is False
    written = found.explain(customer_id, "service", "VM", write=True)
    assert written["value"].startswith("VM tripled") and not written["stale"]
    facts = json.loads(llm.asked[0][1]["content"].split("```json\n", 1)[1].rsplit("\n```", 1)[0])
    assert facts["by_month"][-1] == {"month": "2026-09", "cost": 300.0} and facts["made_of"][0]["name"] == "Prod"
    assert found.explain(customer_id, "service", "VM")["value"] == written["value"] and len(llm.asked) == 1


def test_a_question_is_answered_from_the_reports_compass_chose(fake_api):
    plan = json.dumps({"calls": [{"tool": "customers_with_but_without", "args": {"has": "VM", "lacks": "Sentinel"}}]})
    found, llm, _ = advisor_with(fake_api, [plan, "Contoso runs VMs without Sentinel."])

    answered = found.ask("Who runs VMs but not Sentinel?")

    assert answered["calls"][0]["rows"] == ["Contoso"] and answered["answer"].startswith("Contoso")
    assert "Contoso" in llm.asked[1][1]["content"]                      # the answer was written from the rows


def test_without_compass_a_feature_says_why(fake_api):
    found, _, customer_id = advisor_with(fake_api, [])
    found._llm = None
    with pytest.raises(compass.CompassUnavailable, match="api.llm"):
        found.explain(customer_id, "service", "VM", write=True)
