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


def test_third_party_licenses_are_marketplace_once_and_microsofts_stay():
    """FAB, Apr-Sep 2026: $10.44M of VM licenses, $10.2M of it Fortinet FortiFlex, which the
    invoice's $12.68M Marketplace already holds beside $2.48M of SaaS."""
    mapping = plays.mapping(None)
    services = {"Virtual Machine Licenses": 10_441_886.0, "SaaS": 2_484_005.0, "Virtual Machines": 5_000_000.0}
    meters = {"Fortinet FortiFlex Usage-based Licensing|Reservation": 10_199_127.0, "Windows Server|OnDemand": 240_000.0}
    offers = {"Fortinet FortiFlex Usage-based Licensing-Fortinet FortiFlex (Enterprise)": 10_199_127.0,
              "Dataiku for Enterprise AI-FAB": 366_667.0}

    found = plays.split(services, meters, mapping, marketplace=12_683_606.0, offers=offers)

    assert found[plays.MARKETPLACE] == 12_683_606.0
    assert found[plays.INFRA] == round(5_000_000.0 + 10_441_886.0 - 10_199_127.0, 2)   # Windows stays Infra
    assert sum(found.values()) == round(5_000_000.0 + 10_441_886.0 - 10_199_127.0 + 12_683_606.0, 2)


def test_microsoft_licenses_with_no_matching_offer_stay_put():
    mapping = plays.mapping(None)
    found = plays.split({"Virtual Machine Licenses": 1000.0}, {"SQL Server Enterprise|OnDemand": 1000.0}, mapping,
                        marketplace=500.0, offers={"Dataiku for Enterprise AI": 500.0})
    assert found[plays.INFRA] == 1000.0 and found[plays.MARKETPLACE] == 500.0


def test_plays_read_amortized_so_a_commitment_lands_where_it_is_used():
    month = {"actual": {"service": {"Unassigned": 900.0, "Virtual Machines": 100.0}},
             "amortized": {"service": {"Virtual Machines": 400.0, "Foundry Models": 600.0}},
             "measured": {"marketplace": 0.0}}
    found = plays.split_month(month, plays.mapping(None))
    assert plays.UNASSIGNED not in found and found[plays.INFRA] == 400.0 and found[plays.AI] == 600.0

