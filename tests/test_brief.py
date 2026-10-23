"""The one-click customer brief.

Worth pinning: the model is handed facts the reports computed and told to use
nothing else; a brief is kept and written again only when its facts change or
when asked; without Compass for plugins the brief says what is missing; the
vault part is the Customer note and the notes linking to it, newest first.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from backend import brief
from backend.consumption_service import BriefUnavailable, ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customer_context import CustomerContext
from backend.customers import AccountDirectory, CustomerBook

ENTRY = {"months": {month: {"actual": {"service": {"VM": cost}, "subscription": {"Prod": cost},
                                       "pairs": {"Prod": {"VM": cost}}}, "meters": {}}
                    for month, cost in (("2026-07", 100.0), ("2026-08", 110.0), ("2026-09", 121.0))}}


class FakeLlm:
    def __init__(self) -> None:
        self.asked: list = []

    def available(self) -> bool:
        return True

    def complete(self, messages, *, timeout):
        self.asked.append(messages)
        return f"## Headline\nBrief {len(self.asked)}"


def service_with(fake_api, llm=None, context=None):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    store.save_account("1", ENTRY)
    found = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                               now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc), llm=llm, customer_context=context)
    return found, store, book.list()[0]["id"]


def test_the_model_gets_the_reports_figures_and_is_told_to_use_nothing_else(fake_api):
    llm = FakeLlm()
    service, store, customer_id = service_with(fake_api, llm)

    written = service.customer_brief(customer_id, write=True)

    system, user = llm.asked[0]
    assert "ONLY the facts" in system["content"] and "Never invent a number" in system["content"]
    sent = json.loads(user["content"].split("```json\n", 1)[1].rsplit("\n```", 1)[0])
    assert sent["customer"] == "Contoso" and sent["consumption"]["by_month"][-1] == {"month": "2026-09", "total": 121}
    assert written["markdown"].startswith("## Headline") and written["kept"] and not written["stale"]


def test_a_brief_is_kept_and_written_again_only_when_asked(fake_api):
    llm = FakeLlm()
    service, store, customer_id = service_with(fake_api, llm)
    service.customer_brief(customer_id, write=True)

    kept = service.customer_brief(customer_id)
    assert kept["markdown"].endswith("Brief 1") and not kept["stale"] and len(llm.asked) == 1

    store.save_account("1", {"months": {**ENTRY["months"], "2026-09": {"actual": {"service": {"VM": 500.0},
                                                                                  "subscription": {}}, "meters": {}}}})
    assert service.customer_brief(customer_id)["stale"]                  # the data moved: say so, do not rewrite
    assert service.customer_brief(customer_id, write=True)["markdown"].endswith("Brief 2")


def test_without_compass_for_plugins_the_brief_says_what_is_missing(fake_api):
    service, _, customer_id = service_with(fake_api, llm=None)
    assert service.customer_brief(customer_id)["available"] is False
    with pytest.raises(BriefUnavailable, match="api.llm"):
        service.customer_brief(customer_id, write=True)


def test_the_vault_part_is_the_customer_note_and_the_latest_notes_linking_to_it():
    notes = {
        "Contoso": ({"type": "Customer"}, [], "## Summary\nOil and gas.", "Oil and gas."),
        "Old meeting": ({"type": "Meeting", "date": "2026-05-01"}, ["Contoso"], "", "Talked MACC."),
        "New thread": ({"type": "Thread", "date": "2026-10-20"}, ["contoso"], "Asked  about\nGPUs.", ""),
        "Solution": ({"type": "Solution"}, ["Contoso"], "", "Not a conversation."),
        "Elsewhere": ({"type": "Meeting", "date": "2026-10-22"}, ["Fabrikam"], "", "Other customer."),
    }
    vault = SimpleNamespace(
        entries=lambda: [{"stem": stem, "path": stem, "frontmatter": front, "outgoing_wikilinks": links}
                         for stem, (front, links, _, _) in notes.items()],
        read_section=lambda path, header: notes[path][3],
        read_note=lambda path: (notes[path][0], notes[path][2]))

    found = CustomerContext(SimpleNamespace(vault=vault)).about("Contoso")

    assert found["customer_note"] == "Oil and gas."
    assert [note["note"] for note in found["recent"]] == ["New thread", "Old meeting"]
    assert found["recent"][0]["summary"] == "Asked about GPUs."          # no Summary: the start of its text


def test_the_fingerprint_ignores_the_day_it_was_asked():
    one = {"customer": "Contoso", "as_of": "2026-10-23", "x": 1}
    assert brief.fingerprint(one) == brief.fingerprint({**one, "as_of": "2026-10-24"})
    assert brief.fingerprint(one) != brief.fingerprint({**one, "x": 2})


def test_a_thread_without_a_summary_speaks_through_its_latest_messages():
    notes = {
        "Contoso": ({"type": "Customer"}, [], "", "Oil and gas."),
        "Skilling": ({"type": "Thread", "date": "2026-10-20"}, ["Contoso"], "## Summary", ""),
        "m1": ({"type": "RawMessage", "sender": "Sally", "received": "2026-10-19 10:00"}, ["Skilling"],
               "[CAUTION-EXTERNAL] Be careful.\nFirst ask.", ""),
        "m2": ({"type": "RawMessage", "sender": "Karim", "received": "2026-10-20 09:00"}, ["Skilling"], "Budget approved.", ""),
        "Columbus": ({"type": "Partner"}, ["Contoso"], "", "A partner hub."),
    }
    vault = SimpleNamespace(
        entries=lambda: [{"stem": stem, "path": stem, "frontmatter": front, "outgoing_wikilinks": links}
                         for stem, (front, links, _, _) in notes.items()],
        read_section=lambda path, header: notes[path][3],
        read_note=lambda path: (notes[path][0], notes[path][2]))

    found = CustomerContext(SimpleNamespace(vault=vault)).about("Contoso")

    assert [note["note"] for note in found["recent"]] == ["Skilling"]                 # no partner hub
    assert found["recent"][0]["summary"] == "Karim (2026-10-20): Budget approved. | Sally (2026-10-19): First ask."
