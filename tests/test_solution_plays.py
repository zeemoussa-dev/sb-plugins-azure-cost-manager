"""Spend by solution play.

Worth pinning: the defaults follow the operator's examples (GPU is AI & ML,
Databricks and Fabric are Data, VNET is Infra); GPU virtual machines move from
Infra to AI & ML, never more than the VM service cost; the operator's choices
override the defaults and a reset drops them; a service nothing maps is
Unassigned and listed as unmapped.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend import solution_plays as plays
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook


def test_the_defaults_follow_the_operators_examples():
    mapping = plays.mapping(None)

    assert plays.play_of("Azure Databricks", mapping) == plays.DATA
    assert plays.play_of("Microsoft Fabric", mapping) == plays.DATA
    assert plays.play_of("Virtual Network", mapping) == plays.INFRA
    assert plays.play_of("Foundry Models", mapping) == plays.AI
    assert plays.play_of("Sentinel", mapping) == plays.SECURITY
    assert plays.play_of("SaaS", mapping) == plays.MARKETPLACE
    assert plays.play_of("Something New", mapping) == plays.UNASSIGNED


def test_gpu_virtual_machines_move_from_infra_to_ai():
    services = {"Virtual Machines": 1000.0, "Virtual Network": 50.0, "Azure Databricks": 200.0}
    meters = {"NDsr H100 v5 Series|Reservation": 600.0, "Dsv5 Series Windows|OnDemand": 400.0}

    split = plays.split(services, meters, plays.mapping(None))

    assert split == {plays.INFRA: 450.0, plays.AI: 600.0, plays.DATA: 200.0}


def test_the_gpu_share_never_exceeds_the_vm_service():
    split = plays.split({"Virtual Machines": 100.0}, {"NCads H100 v5|OnDemand": 500.0}, plays.mapping(None))

    assert split == {plays.AI: 100.0}


def test_the_operators_choice_overrides_and_a_reset_drops_it(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "MicrosoftCustomerAgreement",
                                                          "term_start": "2026-01-01", "term_end": "2028-12-31"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    spend = {"service": {"Redis Cache": 30.0, "Brand New Service": 5.0}, "subscription": {"Prod": 35.0}}
    store.save_account("1", {"months": {"2026-09": {"fetched_at": "2026-10-10T00:00:00+00:00", "currency": "USD",
                                                    "actual": spend, "amortized": spend, "meters": {}}}})
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 18))

    view = service.set_solution_play("Redis Cache", plays.APPS)
    redis = next(row for row in view["services"] if row["service"] == "Redis Cache")
    assert (redis["play"], redis["default"], redis["changed"]) == (plays.APPS, plays.DATA, True)
    assert view["unmapped"] == ["Brand New Service"]
    by_play = service.consumption("contoso", None, None, "play", "actual")["rows"]
    assert {row["name"]: row["cost"] for row in by_play} == {plays.APPS: 30.0, plays.UNASSIGNED: 5.0}

    reset = service.set_solution_play("Redis Cache", None)
    assert next(row for row in reset["services"] if row["service"] == "Redis Cache")["play"] == plays.DATA
    with pytest.raises(ValueError):
        service.set_solution_play("Redis Cache", "Not A Play")


def test_an_ea_months_marketplace_comes_from_the_invoice():
    split = plays.split({"Virtual Machines": 1000.0, "SaaS": 28.0}, {}, plays.mapping(None), marketplace=373_000.0)

    assert split[plays.MARKETPLACE] == 373_000.0 and split[plays.INFRA] == 1000.0
    assert plays.split({"SaaS": 50.0}, {}, plays.mapping(None), marketplace=0.0)[plays.MARKETPLACE] == 50.0
