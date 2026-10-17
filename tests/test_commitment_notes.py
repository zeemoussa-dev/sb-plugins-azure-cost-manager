"""A linked customer's signed value lives on its Customer note.

Worth pinning: the note wins and is where a save goes; values held here move to
their notes once; an incomplete hand edit is reported, never counted; and
without Entities 1.3 everything stays in this plugin's own data.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.commitment_notes import CommitmentNotes
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook, CustomerError

ACCOUNTS = [{"name": name, "display_name": name, "agreement_type": "EnterpriseAgreement",
             "term_start": "2026-01-01", "term_end": "2028-12-31"} for name in ("1", "2")]
SIGNED = {"type": "MACC", "amount": 125_000_000, "currency": "USD", "start": "2024-01-01", "end": "2028-12-31"}


class FakeCustomers:
    """Entities' `entities.customers` service as of 1.3: one note per stem."""

    def __init__(self, notes: dict[str, dict | None]) -> None:
        self.notes = notes
        self.writes: list[tuple[str, dict | None]] = []

    def commitment(self, stem: str):
        if stem not in self.notes:
            raise ValueError(f"no Customer {stem!r}")
        return self.notes[stem]

    def set_commitment(self, stem: str, commitment):
        if stem not in self.notes:
            raise ValueError(f"no Customer {stem!r}")
        if commitment and commitment["amount"] < 0:
            raise ValueError("amount must not be negative")
        self.writes.append((stem, commitment))
        self.notes[stem] = commitment
        return commitment


def book(fake_api, service, customers: list[dict]) -> tuple[CustomerBook, ConsumptionStore]:
    fake_api.get_service = lambda name: service if name == "entities.customers" else None
    store = ConsumptionStore(fake_api)
    store.save_customers(customers)
    return CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]), CommitmentNotes(fake_api)), store


def linked(commitment=None, stem="ADNOC") -> dict:
    return {"id": "adnoc", "name": "ADNOC", "accounts": ["1"], "commitment": commitment, "entity_customer": stem}


def test_a_linked_customers_signed_value_is_read_from_its_note(fake_api):
    customers, _ = book(fake_api, FakeCustomers({"ADNOC": dict(SIGNED)}), [linked()])

    listed = customers.list()[0]

    assert listed["commitment"]["amount"] == 125_000_000
    assert listed["commitment_source"] == "note"


def test_a_save_writes_the_note_and_keeps_nothing_here(fake_api):
    service = FakeCustomers({"ADNOC": None})
    customers, store = book(fake_api, service, [linked()])

    customers.save("adnoc", {"name": "ADNOC", "accounts": ["1"], "commitment": {**SIGNED, "amount": 130_000_000}})

    assert service.notes["ADNOC"]["amount"] == 130_000_000
    assert store.customers()[0]["commitment"] is None
    assert customers.list()[0]["commitment"]["amount"] == 130_000_000


def test_a_value_the_note_refuses_is_not_saved_anywhere(fake_api):
    service = FakeCustomers({"ADNOC": dict(SIGNED)})
    customers, _ = book(fake_api, service, [linked()])
    service.set_commitment = lambda stem, commitment: (_ for _ in ()).throw(ValueError("currency must be 3 letters"))

    with pytest.raises(CustomerError, match="currency must be 3 letters"):
        customers.save("adnoc", {"name": "ADNOC", "accounts": ["1"], "commitment": SIGNED})


def test_values_held_here_move_to_their_notes_once_and_a_note_with_one_wins(fake_api):
    service = FakeCustomers({"ADNOC": None, "TAQA": {**SIGNED, "amount": 20_000_000}})
    customers, store = book(fake_api, service, [
        linked(SIGNED),
        {"id": "taqa", "name": "TAQA", "accounts": ["2"], "commitment": {**SIGNED, "amount": 1}, "entity_customer": "TAQA"},
    ])

    by_id = {customer["id"]: customer for customer in customers.list()}

    assert service.notes["ADNOC"] == SIGNED
    assert by_id["adnoc"]["commitment"]["amount"] == 125_000_000
    assert by_id["taqa"]["commitment"]["amount"] == 20_000_000
    assert [customer["commitment"] for customer in store.customers()] == [None, None]
    customers.list()
    assert service.writes == [("ADNOC", SIGNED)]


def test_linking_to_a_note_that_has_a_signed_value_keeps_the_notes(fake_api):
    service = FakeCustomers({"ADNOC": dict(SIGNED)})
    customers, store = book(fake_api, service, [{**linked(), "entity_customer": None, "commitment": None}])
    store.save_customers([{**linked(), "entity_customer": None, "commitment": {**SIGNED, "amount": 1}}])

    saved = customers.save("adnoc", {"name": "ADNOC", "accounts": ["1"], "entity_customer": "ADNOC",
                                     "commitment": {**SIGNED, "amount": 1}})

    assert saved["commitment"]["amount"] == 125_000_000
    assert service.writes == []
    assert store.customers()[0]["commitment"] is None


def test_an_incomplete_hand_edit_is_reported_and_counts_nothing(fake_api):
    edited = {**SIGNED, "end": ""}
    customers, _ = book(fake_api, FakeCustomers({"ADNOC": edited}), [linked()])

    listed = customers.list()[0]

    assert listed["commitment"] is None
    assert "term start and end" in listed["commitment_problem"]


def test_a_missing_note_is_reported(fake_api):
    customers, _ = book(fake_api, FakeCustomers({}), [linked(stem="Gone")])

    assert "'Gone' was not found" in customers.list()[0]["commitment_problem"]


def test_without_entities_1_3_everything_stays_here(fake_api):
    class Entities12:
        def customers(self):
            return []

    customers, store = book(fake_api, Entities12(), [linked(SIGNED)])

    listed = customers.list()[0]
    customers.save("adnoc", {"name": "ADNOC", "accounts": ["1"], "commitment": {**SIGNED, "amount": 5}})

    assert listed["commitment_source"] == "settings"
    assert listed["commitment"]["amount"] == 125_000_000
    assert store.customers()[0]["commitment"]["amount"] == 5


def test_an_unlinked_customer_keeps_its_value_here(fake_api):
    service = FakeCustomers({})
    customers, store = book(fake_api, service, [{**linked(SIGNED), "entity_customer": None}])

    assert customers.list()[0]["commitment_source"] == "settings"
    assert store.customers()[0]["commitment"] == SIGNED
    assert service.writes == []


def test_the_sync_reads_the_term_start_from_the_note(fake_api):
    customers, _ = book(fake_api, FakeCustomers({"ADNOC": dict(SIGNED)}), [linked()])

    record = customers.records()[0]

    assert record["accounts"] == ["1"]
    assert record["commitment"]["start"] == "2024-01-01"
    assert date.fromisoformat(record["commitment"]["start"]).year == 2024
