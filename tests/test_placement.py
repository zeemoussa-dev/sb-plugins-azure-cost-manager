"""Compass places the subscriptions the rules could not.

Worth pinning: an answer is checked (an unknown solution is dropped, a proposed
pattern is validated); a subscription is asked about once, and again only when
what it runs changes; a proposal becomes a Solution note the vault reader accepts.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from backend import placement, solution_notes, solutions
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

CATALOG = solutions.patterns(None)
PROPOSAL = {"name": "Digital twin", "play": "Data & Analytics", "description": "Plant models fed by telemetry.",
            "requires": [["service:Azure Digital Twins"]], "supports": [], "names": ["twin"],
            "pitches": [{"missing": ["service:Microsoft Fabric"], "pitch": "Analytics on the twin's data"}]}


def items():
    return [{"key": "c|twin-prod", "customer": "Contoso", "subscription": "twin-prod", "monthly": 9000,
             "environment": "Production", "services": ["Azure Digital Twins $6000/mo"], "meters": [],
             "resource_groups": ["rg-twin"]},
            {"key": "c|mystery", "customer": "Contoso", "subscription": "mystery", "monthly": 300,
             "environment": None, "services": ["Bandwidth $300/mo"], "meters": [], "resource_groups": []}]


def test_an_answer_is_checked_before_it_is_kept():
    reply = "Here you go:\n```json\n" + json.dumps([
        {"key": "c|twin-prod", "solution_id": None, "new_solution": PROPOSAL, "confidence": "high", "reason": "Digital Twins"},
        {"key": "c|mystery", "solution_id": "not-a-solution", "confidence": "sure", "reason": "?"},
        {"key": "someone-else", "solution_id": "genai"}]) + "\n```"

    found = placement.parse(reply, items(), CATALOG)

    assert set(found) == {"c|twin-prod", "c|mystery"}
    assert found["c|twin-prod"]["proposal"]["valid"] and found["c|twin-prod"]["proposal"]["id"] == "digital-twin"
    assert found["c|mystery"]["solution_id"] is None and found["c|mystery"]["confidence"] == "low"

    broken = placement.parse(json.dumps([{"key": "c|twin-prod", "new_solution": {**PROPOSAL, "requires": [["vm:x"]]}}]),
                             items(), CATALOG)
    assert broken["c|twin-prod"]["proposal"]["valid"] is False


def test_a_proposal_becomes_a_solution_note_the_vault_reader_accepts():
    found = placement.parse(json.dumps([{"key": "c|twin-prod", "new_solution": PROPOSAL}]), items(), CATALOG)
    note = placement.solution_note(found["c|twin-prod"]["proposal"], "2026-10-23")

    pattern_section = re.search(r"## Pattern\n(.*?)## Sources", note, re.DOTALL).group(1)
    pattern = solution_notes.parse_pattern(pattern_section)
    assert solutions.validated([{**pattern, "id": "digital-twin", "name": "Digital twin", "play": "Data & Analytics"}])
    assert 'type: "Solution"' in note and 'status: "draft"' in note


class FakeLlm:
    def __init__(self) -> None:
        self.asked: list = []

    def available(self) -> bool:
        return True

    def complete(self, messages, *, timeout):
        self.asked.append(messages)
        keys = re.findall(r'"key": "([^"]+)"', messages[1]["content"])
        return json.dumps([{"key": key, "solution_id": "iaas", "confidence": "medium", "reason": "VMs"} for key in keys])


def test_a_subscription_is_asked_about_once_and_again_when_it_changes(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    footprint = {"first_month": "2026-07", "last_month": "2026-09", "months": 3, "fetched_at": "x",
                 "subscriptions": {"odd-sub": {"services": {"Bandwidth": 3000.0}, "meters": {}, "resource_groups": {}}}}
    store.save_account("1", {"months": {}, "footprint": footprint})
    llm = FakeLlm()
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc), llm=llm)
    customer_id = book.list()[0]["id"]

    first = service.place(customer_id)
    again = service.place(customer_id)

    assert len(llm.asked) == 1 and list(first["suggestions"].values())[0]["solution"] == "Virtual machines (IaaS)"
    assert again["pending"] == []
    footprint["subscriptions"]["odd-sub"]["services"]["Notification Hubs"] = 900.0     # no pattern knows it
    store.save_account("1", {"months": {}, "footprint": footprint})
    assert len(service.placements(customer_id)["pending"]) == 1          # it runs something new: ask again
