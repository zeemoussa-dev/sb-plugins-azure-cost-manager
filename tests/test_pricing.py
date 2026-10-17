"""Pricing steady candidates from the Retail Prices API.

Worth pinning: how a meter subcategory is found in the price list; that a
reservation's term price is spread over its hours; that a Windows meter saves
only on compute; and that the price book refreshes monthly, not per view.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from backend import finops, pricing

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


def item(sku, kind, price, term=None, savings_plan=None, sku_name=None, product="Virtual Machines Ddsv5 Series"):
    return {"armSkuName": sku, "skuName": sku_name or sku, "type": kind, "unitPrice": price, "unitOfMeasure": "1 Hour",
            "reservationTerm": term, "productName": product,
            "savingsPlan": [{"term": t, "unitPrice": p} for t, p in (savings_plan or {}).items()]}


LINUX = [item("D8ds_v5", "Consumption", 1.0, savings_plan={"1 Year": 0.75, "3 Years": 0.5}),
         item("D8ds_v5", "Reservation", 0.6 * 8760, term="1 Year"),
         item("D8ds_v5", "Reservation", 0.4 * 26280, term="3 Years"),
         item("D8ds_v5", "Consumption", 0.1, sku_name="D8ds_v5 Spot")]
WINDOWS = [item("D8ds_v5", "Consumption", 2.0, product="Virtual Machines Ddsv5 Series Windows")]


def test_a_meter_subcategory_is_found_as_the_price_lists_product():
    assert pricing.product_names("Ddsv5 Series") == (["Virtual Machines Ddsv5 Series"], False)
    assert pricing.product_names("Dlsv5 Series Linux") == (["Virtual Machines Dlsv5 Series"], False)
    assert pricing.product_names("Dv3/DSv3 Series Windows") == (
        ["Virtual Machines Dv3 Series", "Virtual Machines DSv3 Series"], True)
    assert pricing.product_names("NVadsA10_v5 Linux") == (["Virtual Machines NVadsA10v5 Series"], False)
    assert pricing.product_names("DCadsv5-series Windows") == (["Virtual Machines DCadsv5 Series"], True)


def test_discounts_spread_a_reservation_over_its_hours_and_ignore_spot():
    assert pricing.series_discounts(LINUX) == {"sp_1y": 0.25, "sp_3y": 0.5, "ri_1y": 0.4, "ri_3y": 0.6}


def test_a_windows_meter_saves_only_on_compute():
    # The licence stays at pay-as-you-go: saving 0.6 of the 1.0 compute out of 2.0 billed.
    assert pricing.series_discounts(LINUX, WINDOWS)["ri_3y"] == 0.3


def fake_prices(products: dict[str, list[dict]]):
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        expression = request.url.params["$filter"]
        asked.append(expression)
        found = next((items for name, items in products.items() if f"productName eq '{name}'" in expression), [])
        return httpx.Response(200, text=json.dumps({"Items": found, "NextPageLink": None}))

    return pricing.RetailPrices(transport=httpx.MockTransport(handler)), asked


def test_the_price_book_prices_once_a_month():
    state: dict = {}
    book = pricing.PriceBook(lambda: state, lambda saved: state.update(saved), now=lambda: NOW)
    prices, asked = fake_prices({"Virtual Machines Ddsv5 Series": LINUX})

    first = book.refresh(prices, ["Ddsv5 Series", "Gone Series"])
    again = book.refresh(prices, ["Ddsv5 Series", "Gone Series"])
    later = pricing.PriceBook(lambda: state, lambda saved: state.update(saved), now=lambda: NOW + timedelta(days=31))

    assert (first["priced"], again["priced"]) == (2, 0)
    assert book.discounts()["Ddsv5 Series"]["discounts"]["ri_3y"] == 0.6
    assert "not in the price list" in book.discounts()["Gone Series"]["reason"]
    assert later.stale(["Ddsv5 Series"]) == ["Ddsv5 Series"]
    assert all("uaenorth" in expression for expression in asked)


def test_a_candidate_gets_a_saving_per_option_or_says_why_not():
    candidates = [{"meter": "Ddsv5 Series", "family": "Virtual machines", "monthly_on_demand": 10_000},
                  {"meter": "Premium Files", "family": "Other reservable services", "monthly_on_demand": 5_000},
                  {"meter": "Esv5 Series", "family": "Virtual machines", "monthly_on_demand": 1_000}]
    prices = {"Ddsv5 Series": {"product": "Virtual Machines Ddsv5 Series", "discounts": {"sp_1y": 0.25, "ri_3y": 0.6}}}

    priced = finops.with_savings(candidates, prices)

    assert priced[0]["savings"] == {"sp_1y": 2_500, "ri_3y": 6_000}
    assert "next phase" in priced[1]["not_priced"]
    assert "next sync" in priced[2]["not_priced"]
