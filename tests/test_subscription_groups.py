"""Subscription groups: a customer's named groups of subscriptions, matched by name."""
from __future__ import annotations

import pytest

from backend import subscription_groups
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook, CustomerError

GENOME = [{"name": "Genome programme", "match": ["EGP", "genom"]}, {"name": "Bioinformatics", "match": ["BIX"]}]


def month_with(pairs: dict[str, dict[str, float]]) -> dict:
    return {"actual": {"pairs": pairs}}


def test_a_subscription_falls_in_the_first_group_one_of_whose_fragments_its_name_contains():
    assert subscription_groups.group_of("EGP Data(631892e7-4148)", GENOME) == "Genome programme"
    assert subscription_groups.group_of("Labware Genome Storage(b1a6)", GENOME) == "Genome programme"
    assert subscription_groups.group_of("BIX Secondary Analysis Prod(b520)", GENOME) == "Bioinformatics"
    assert subscription_groups.group_of("Labware Prod(080a)", GENOME) is None


def test_the_subscription_id_never_matches_a_fragment():
    assert subscription_groups.group_of("Labware Prod(0bix0000-egp)", GENOME) is None


def test_the_report_adds_up_each_group_and_its_subscriptions_on_one_service_or_all():
    merged = {
        "2026-08": month_with({"EGP Data(1)": {"Storage": 800.0, "Virtual Machines": 50.0},
                               "Public Genome Data(2)": {"Storage": 70.0},
                               "BIX Common Prod(3)": {"Storage": 15.0}, "Labware Prod(4)": {"Storage": 9.0}}),
        "2026-09": month_with({"EGP Data(1)": {"Storage": 850.0}}),
    }
    found = subscription_groups.report(merged, GENOME, "Storage")
    assert found["months"] == ["2026-08", "2026-09"]
    genome = found["groups"][0]
    assert genome["monthly"] == {"2026-08": 870.0, "2026-09": 850.0}
    assert [row["name"] for row in genome["subscriptions"]] == ["EGP Data(1)", "Public Genome Data(2)"]
    assert found["groups"][1]["monthly"] == {"2026-08": 15.0}
    assert found["services"] == ["Storage", "Virtual Machines"]
    assert subscription_groups.report(merged, GENOME)["groups"][0]["monthly"]["2026-08"] == 920.0


def test_groups_are_validated():
    assert subscription_groups.validated([{"name": " Genome ", "match": ["EGP", " ", "EGP"]}]) == \
        [{"name": "Genome", "match": ["EGP"]}]
    for bad in ([{"name": "", "match": ["x"]}], [{"name": "A", "match": []}],
                [{"name": "A", "match": ["x"]}, {"name": "a", "match": ["y"]}], "nope"):
        with pytest.raises(ValueError):
            subscription_groups.validated(bad)


def test_groups_are_kept_on_the_customer_and_survive_its_other_edits(fake_api):
    fake_api.get_service = lambda name: None
    book = CustomerBook(ConsumptionStore(fake_api), AccountDirectory(
        lambda: [{"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    book.set_subscription_groups("contoso", GENOME)
    book.save("contoso", {"name": "Contoso Ltd", "accounts": ["1"]})
    assert book.records()[0]["subscription_groups"] == GENOME
    with pytest.raises(CustomerError):
        book.set_subscription_groups("nobody", GENOME)
