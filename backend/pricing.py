"""What committing would save, from Azure's public Retail Prices API.

The meter detail names a VM *series* ("Ddsv5 Series", "Dv3/DSv3 Series Windows"),
not a size or a region, so a series is priced as the average discount across its
sizes in the pricing region -- an estimate, and every screen says so:

- a 1- or 3-year reservation: the term's price over its hours, against pay-as-you-go;
- a 1- or 3-year savings plan: its hourly price, against pay-as-you-go.

A reservation covers compute only, never a Windows licence, so for a Windows
meter the Linux saving is taken against the Windows hourly price.

The API needs no sign-in and is not Cost Management, so it does not touch the
per-sign-in throttling budget; prices still come from the sync and a cache,
never from a page view.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Callable

import httpx

RETAIL_PRICES = "https://prices.azure.com/api/retail/prices"
RETAIL_API_VERSION = "2023-01-01-preview"  # the first version that carries savings plan prices
DEFAULT_REGION = "uaenorth"
PRICES_FRESH_FOR = timedelta(days=30)
RATE_LIMIT_ATTEMPTS = 5
HOURS = {"1 Year": 8760, "3 Years": 26280}
OPTIONS = ("sp_1y", "sp_3y", "ri_1y", "ri_3y")
OPTION_LABELS = {"sp_1y": "1-year savings plan", "sp_3y": "3-year savings plan",
                 "ri_1y": "1-year reservation", "ri_3y": "3-year reservation"}


def product_names(meter_subcategory: str) -> tuple[list[str], bool]:
    """The price list's product names a meter subcategory may be sold as, most
    likely first, and whether the meter is Windows. Checked against the price
    list on 2026-10-17: "Dlsv5 Series Linux" is "Dlsv5 Series", "Dv3/DSv3 Series"
    is sold as both halves, "NVadsA10_v5" is "NVadsA10v5 Series"."""
    name = meter_subcategory.strip()
    windows = name.endswith(" Windows")
    name = re.sub(r" (Windows|Linux)$", "", name)
    name = re.sub(r"[- ]series$", " Series", name, flags=re.IGNORECASE)
    if not name.endswith(" Series"):
        name = f"{name.replace('_', '')} Series"
    stem = name[: -len(" Series")]
    halves = stem.split("/") if "/" in stem else [stem]
    return [f"Virtual Machines {half.strip()} Series" for half in halves], windows


class RetailPrices:
    def __init__(self, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._http = httpx.Client(timeout=60, transport=transport)
        self._sleep = sleep

    def _get(self, url: str, params: dict | None) -> httpx.Response:
        # The price list rate-limits a burst of queries (seen 2026-10-17, ~70 in a row).
        for attempt in range(RATE_LIMIT_ATTEMPTS):
            response = self._http.get(url, params=params)
            if response.status_code != 429 or attempt == RATE_LIMIT_ATTEMPTS - 1:
                return response
            self._sleep(float(response.headers.get("Retry-After") or 2 ** (attempt + 1)))
        return response

    def items(self, filter_expression: str) -> list[dict]:
        url, params, found = RETAIL_PRICES, {"api-version": RETAIL_API_VERSION, "$filter": filter_expression}, []
        while url:
            response = self._get(url, params)
            response.raise_for_status()
            page = response.json()
            found.extend(page.get("Items") or [])
            url, params = page.get("NextPageLink"), None
        return found


def _sizes(items: list[dict]) -> dict[str, dict]:
    """Per size: its pay-as-you-go hourly price, savings plan hourly prices and
    reservation hourly prices -- spot and low-priority left out."""
    sizes: dict[str, dict] = {}
    for item in items:
        sku = item.get("armSkuName") or ""
        if not sku or re.search(r"Spot|Low Priority", item.get("skuName") or ""):
            continue
        size = sizes.setdefault(sku, {})
        if item.get("type") == "Consumption" and item.get("unitOfMeasure") == "1 Hour":
            size["payg"] = item["unitPrice"]
            for plan in item.get("savingsPlan") or []:
                key = {"1 Year": "sp_1y", "3 Years": "sp_3y"}.get(plan.get("term"))
                if key:
                    size[key] = plan["unitPrice"]
        elif item.get("type") == "Reservation" and item.get("reservationTerm") in HOURS:
            key = "ri_1y" if item["reservationTerm"] == "1 Year" else "ri_3y"
            size[key] = item["unitPrice"] / HOURS[item["reservationTerm"]]
    return sizes


def series_discounts(linux: list[dict], windows: list[dict] | None = None) -> dict | None:
    """The average saving per option across a series' sizes, as a fraction of
    what the meter is billed at (for Windows, of the Windows hourly price)."""
    sizes, windows_sizes = _sizes(linux), _sizes(windows or [])
    savings: dict[str, list[float]] = {option: [] for option in OPTIONS}
    for sku, size in sizes.items():
        payg = size.get("payg")
        billed = windows_sizes.get(sku, {}).get("payg") if windows is not None else payg
        if not payg or not billed:
            continue
        for option in OPTIONS:
            if size.get(option):
                savings[option].append((payg - size[option]) / billed)
    averaged = {option: round(mean(values), 4) for option, values in savings.items() if values}
    return averaged or None


def price_meter(prices: RetailPrices, region: str, meter_subcategory: str) -> dict:
    """The discounts for one meter subcategory, or why there are none."""
    names, windows = product_names(meter_subcategory)
    for product in names:
        quoted = product.replace("'", "''")
        linux = prices.items(f"armRegionName eq '{region}' and productName eq '{quoted}'")
        if not linux:
            continue
        windows_items = prices.items(f"armRegionName eq '{region}' and productName eq '{quoted} Windows'") \
            if windows else None
        discounts = series_discounts(linux, windows_items)
        return {"product": product, "windows": windows, "discounts": discounts,
                "reason": None if discounts else "no reservation or savings plan price for its sizes"}
    return {"product": None, "windows": windows, "discounts": None,
            "reason": f"not in the price list for {region} as {' or '.join(names)}"}


class PriceBook:
    """Discounts per meter subcategory and region, kept in this plugin's data and
    refreshed monthly -- prices move rarely, and pages read only this."""

    def __init__(self, load: Callable[[], dict], save: Callable[[dict], None],
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._load = load
        self._save = save
        self._now = now

    def region(self) -> str:
        return self._load().get("pricing_region") or DEFAULT_REGION

    def discounts(self) -> dict[str, dict]:
        """`meter subcategory -> priced entry` for the pricing region."""
        state = self._load()
        return (state.get("prices") or {}).get(self.region()) or {}

    def stale(self, meters: list[str]) -> list[str]:
        known = self.discounts()
        cutoff = self._now() - PRICES_FRESH_FOR
        return [meter for meter in meters
                if meter not in known or datetime.fromisoformat(known[meter]["priced_at"]) < cutoff]

    def refresh(self, prices: RetailPrices, meters: list[str]) -> dict:
        """Prices every meter not priced this month; returns `{priced, failed}`."""
        state = self._load()
        region = state.get("pricing_region") or DEFAULT_REGION
        book = state.setdefault("prices", {}).setdefault(region, {})
        priced, failed = 0, []
        for meter in self.stale(meters):
            try:
                book[meter] = {**price_meter(prices, region, meter), "priced_at": self._now().isoformat()}
                priced += 1
            except httpx.HTTPError as exc:
                failed.append(f"{meter}: {exc}")
        self._save(state)
        return {"priced": priced, "failed": failed}
