"""Drilling into a service, a subscription, a play or a month.

Worth pinning: a service opens into the subscriptions that run it and a
subscription into its services (from the kept pairs), a month into its parts,
months synced before the pairs were kept say so, "SaaS" names the Marketplace
products behind it, and a service finds its Technology note under its billed name.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from backend import drill
from backend.consumption_analysis import merge
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook
from backend.technology_notes import TechnologyNotes


def month(services: dict[str, dict[str, float]] | None, marketplace: list[dict] | None = None) -> dict:
    """`services`: subscription -> service -> cost; None for a month synced before the pairs."""
    pairs = services or {}
    by_service: dict[str, float] = {}
    for found in pairs.values():
        for name, cost in found.items():
            by_service[name] = by_service.get(name, 0.0) + cost
    actual = {"service": by_service, "subscription": {sub: sum(found.values()) for sub, found in pairs.items()}}
    if services is not None:
        actual["pairs"] = pairs
    return {"actual": actual, "meters": {}, **({"marketplace": {"items": marketplace}} if marketplace else {})}


ENTRY = {"months": {
    "2026-07": month({"Prod": {"VM": 300.0, "SQL": 30.0}, "Dev": {"VM": 30.0}}),
    "2026-08": month({"Prod": {"VM": 300.0, "SQL": 60.0}, "Dev": {"VM": 60.0}}),
    "2026-09": month({"Prod": {"VM": 300.0, "SaaS": 900.0}, "Dev": {"VM": 90.0}},
                     [{"publisher": "Fortinet", "offer": "FortiFlex", "plan": "usage", "subscription": "Prod",
                       "cost": 900.0, "recurring": False}]),
    "2026-10": month({"Prod": {"VM": 10.0}}),
}}


def test_a_service_opens_into_its_subscriptions_and_a_subscription_into_its_services():
    merged, _ = merge({"1": ENTRY})
    vm = drill.analyse(merged, "service", "VM", "2026-10", {})
    prod = drill.analyse(merged, "subscription", "Prod", "2026-10", {}, {"rg-app": 40.0})

    assert [(row["name"], row["monthly"]) for row in vm["parts"]] == [("Prod", 300.0), ("Dev", 60.0)]
    assert vm["trend"][-1] == {"month": "2026-10", "cost": 10.0} and not vm["pairs_missing"]
    assert {row["name"]: row["monthly"] for row in prod["parts"]} == {"VM": 300.0, "SaaS": 300.0, "SQL": 30.0}
    assert prod["parts"][-1]["name"] == "SQL"
    assert prod["resource_groups"] == [{"name": "rg-app", "monthly": 40.0}]


def test_a_month_opens_into_its_parts_and_older_months_say_the_pairs_are_missing():
    merged, _ = merge({"1": {"months": {**ENTRY["months"], "2026-06": month(None)}}})
    sep = drill.analyse(merged, "month", "2026-09", "2026-10", {})
    assert sep["total"] == 1290.0 and sep["parts"][0] == {"name": "SaaS", "cost": 900.0, "before": 0.0}

    merged_old, _ = merge({"1": {"months": {"2026-06": {"actual": {"service": {"VM": 5.0}, "subscription": {"Prod": 5.0}}}}}})
    assert drill.analyse(merged_old, "service", "VM", "2026-10", {})["pairs_missing"]


def test_saas_names_the_marketplace_products_behind_it(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    store.save_account("1", ENTRY)
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc))
    customer_id = book.list()[0]["id"]

    saas = service.drill(customer_id, "service", "SaaS")

    assert saas["marketplace"] == [{"publisher": "Fortinet", "offer": "FortiFlex", "plan": "usage",
                                    "subscriptions": ["Prod"], "recurring": False, "monthly": 300.0}]


def test_a_billed_service_finds_its_technology_note():
    vault = SimpleNamespace(entries=lambda: [
        {"stem": "Azure OpenAI Service", "frontmatter": {"type": "AzureDoc", "title": "Azure OpenAI Service"}},
        {"stem": "Azure Kubernetes Service", "frontmatter": {"type": "AzureDoc", "title": "Azure Kubernetes Service"}},
        {"stem": "Microsoft Sentinel", "frontmatter": {"type": "AzureDoc", "title": "Microsoft Sentinel"}},
        {"stem": "Some meeting", "frontmatter": {"type": "Meeting"}}])
    notes = TechnologyNotes(SimpleNamespace(vault=vault))

    assert notes.note_for("Foundry Models") == "Azure OpenAI Service"           # alias
    assert notes.note_for("Kubernetes Service") == "Azure Kubernetes Service"  # without the prefix
    assert notes.note_for("Sentinel") == "Microsoft Sentinel"
    assert notes.note_for("Some meeting") is None


def test_without_pairs_a_drill_reads_the_footprint():
    entries = {"1": {"footprint": {"months": 3, "subscriptions": {
        "Prod": {"services": {"Foundry Models": 900.0, "VM": 300.0}}, "Dev": {"services": {"Foundry Models": 90.0}}}}}}
    assert drill.from_footprints(entries, "service", "Foundry Models") == [
        {"name": "Prod", "monthly": 300.0, "last_12": None}, {"name": "Dev", "monthly": 30.0, "last_12": None}]
    assert [row["name"] for row in drill.from_footprints(entries, "subscription", "Prod")] == ["Foundry Models", "VM"]



def test_the_guide_lists_services_with_their_customers_and_unbilled_notes(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    store.save_account("1", ENTRY)
    vault = SimpleNamespace(entries=lambda: [
        {"stem": "Virtual Machines", "path": "vm", "frontmatter": {"type": "AzureDoc", "title": "Virtual Machines"}},
        {"stem": "Azure Bastion", "path": "b", "frontmatter": {"type": "AzureDoc", "title": "Azure Bastion"}},
        {"stem": "GenAI play", "path": "p", "frontmatter": {"type": "Playbook", "name": "GenAI play", "solutions": ["genai"]}}],
        read_section=lambda path, header: "A playbook.")
    from backend.solution_notes import SolutionNotes
    api = SimpleNamespace(vault=vault)
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc),
                                 solution_notes=SolutionNotes(api), technology_notes=TechnologyNotes(api))

    guide = service.guide()

    vm = next(row for row in guide["services"] if row["name"] == "VM")
    assert vm["customers"][0]["name"] == "Contoso" and vm["monthly"] == 360.0
    assert any(row["name"] == "Azure Bastion" and row["note"] == "Azure Bastion" for row in guide["services"])
    assert guide["playbooks"] == [{"stem": "GenAI play", "name": "GenAI play", "play": None, "status": None,
                                   "solutions": ["genai"], "summary": "A playbook."}]
    assert len(guide["solutions"]) > 20
