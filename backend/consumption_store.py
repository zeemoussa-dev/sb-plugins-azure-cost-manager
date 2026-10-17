"""This plugin's local data, through the Plugin API's `api.data`.

`Customers.json` is the operator's own: each customer is a named group of
billing accounts (enrollments) with the value they signed for.
`Consumption-Cache.json` is what the sync brought back from Azure, per account
per month: spend by service and by subscription, actual and amortized, as
name -> cost maps, with when each month was fetched -- so a month Azure has
finished settling is never asked for again.

The cache is held in memory once read and written through: the sync writes it
from a background thread while pages read it, and a reader must never see a
half-written file.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta

from . import months

CUSTOMERS_FILE = "Azure-Cost-Manager/Customers.json"
CONSUMPTION_CACHE_FILE = "Azure-Cost-Manager/Consumption-Cache.json"
# Offers the operator marked as not counting toward a MACC -- Azure does not say.
MARKETPLACE_SETTINGS_FILE = "Azure-Cost-Manager/Marketplace-Settings.json"
# 0.1.x tracked single accounts; read once to carry them over as customers.
LEGACY_TRACKED_ACCOUNTS_FILE = "Azure-Cost-Manager/Tracked-Accounts.json"
DATA_FILES = (CUSTOMERS_FILE, CONSUMPTION_CACHE_FILE, MARKETPLACE_SETTINGS_FILE, LEGACY_TRACKED_ACCOUNTS_FILE)

# Azure keeps adjusting a month's usage for a few days after it ends; a month
# fetched before then is fetched again.
SETTLING_DAYS = 5


def _read_json(api, path: str, empty):
    try:
        text = api.data.read_text(path)
    except Exception:
        return empty
    if not text:
        return empty
    try:
        return json.loads(text)
    except ValueError:
        return empty


def _write_json(api, path: str, value) -> None:
    api.data.write_text(path, json.dumps(value, indent=1, sort_keys=True))


def is_settled(month: str, fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    fetched_on = datetime.fromisoformat(fetched_at).date()
    return fetched_on >= months.last_day(month) + timedelta(days=SETTLING_DAYS)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "customer"


class ConsumptionStore:
    def __init__(self, api) -> None:
        self._api = api
        self._lock = threading.RLock()
        self._cache: dict | None = None

    # -- customers --------------------------------------------------------

    def customers(self) -> list[dict]:
        with self._lock:
            stored = _read_json(self._api, CUSTOMERS_FILE, None)
            if stored is None:
                return self._carried_over_from_tracked_accounts()
            return list(stored.get("customers") or [])

    def _carried_over_from_tracked_accounts(self) -> list[dict]:
        tracked = _read_json(self._api, LEGACY_TRACKED_ACCOUNTS_FILE, {"accounts": []}).get("accounts") or []
        customers, taken = [], set()
        for account in tracked:
            customer_id = slug(account.get("display_name") or account["name"])
            while customer_id in taken:
                customer_id += "-2"
            taken.add(customer_id)
            customers.append({"id": customer_id, "name": account.get("display_name") or account["name"],
                              "accounts": [account["name"]], "commitment": None})
        if customers:
            self.save_customers(customers)
        return customers

    def save_customers(self, customers: list[dict]) -> None:
        with self._lock:
            _write_json(self._api, CUSTOMERS_FILE, {"customers": customers})

    def customer(self, customer_id: str) -> dict | None:
        return next((customer for customer in self.customers() if customer["id"] == customer_id), None)

    # -- consumption cache --------------------------------------------------

    def _loaded(self) -> dict:
        if self._cache is None:
            self._cache = _read_json(self._api, CONSUMPTION_CACHE_FILE, {"accounts": {}})
            self._cache.setdefault("accounts", {})
        return self._cache

    def account(self, account_name: str) -> dict:
        """`{months: {YYYY-MM: {fetched_at, currency, actual: {service: {}, subscription: {}},
        amortized: {...}}}, forecast, synced_at, errors}` -- a deep copy."""
        with self._lock:
            entry = json.loads(json.dumps(self._loaded()["accounts"].get(account_name) or {"months": {}}))
        # 0.1.x cached raw row lists; such a month is dropped, so the sync fetches it again.
        entry["months"] = {month: data for month, data in (entry.get("months") or {}).items()
                           if isinstance(data.get("actual"), dict)}
        return entry

    def save_account(self, account_name: str, entry: dict) -> None:
        with self._lock:
            self._loaded()["accounts"][account_name] = entry
            _write_json(self._api, CONSUMPTION_CACHE_FILE, self._cache)

    def forget_accounts_except(self, kept: set[str]) -> None:
        with self._lock:
            cache = self._loaded()
            dropped = [name for name in cache["accounts"] if name not in kept]
            for name in dropped:
                del cache["accounts"][name]
            if dropped:
                _write_json(self._api, CONSUMPTION_CACHE_FILE, cache)

    @staticmethod
    def months_to_fetch(entry: dict, wanted: list[str]) -> list[str]:
        """The wanted months that are missing or not yet settled, oldest first.
        A month synced before meter detail was kept (0.2.0) is fetched once more."""
        def complete(month: str) -> bool:
            data = entry["months"].get(month) or {}
            return "meters" in data and is_settled(month, data.get("fetched_at"))
        return [month for month in wanted if not complete(month)]

    def not_macc_eligible(self) -> list[dict]:
        """`[{publisher, offer}]` the operator marked as not counting toward a MACC."""
        with self._lock:
            settings = _read_json(self._api, MARKETPLACE_SETTINGS_FILE, {})
            return list(settings.get("not_macc_eligible") or [])

    def save_not_macc_eligible(self, offers: list[dict]) -> None:
        with self._lock:
            settings = _read_json(self._api, MARKETPLACE_SETTINGS_FILE, {})
            settings["not_macc_eligible"] = offers
            _write_json(self._api, MARKETPLACE_SETTINGS_FILE, settings)

    @staticmethod
    def marketplace_to_fetch(entry: dict, wanted: list[str]) -> list[str]:
        """The wanted billing periods whose Marketplace charges are missing or not yet settled."""
        return [month for month in wanted
                if not is_settled(month, ((entry["months"].get(month) or {}).get("marketplace") or {}).get("fetched_at"))]

    @staticmethod
    def balances_to_fetch(entry: dict, wanted: list[str]) -> list[str]:
        """The wanted billing periods whose balance is missing or not yet settled."""
        return [month for month in wanted
                if not is_settled(month, ((entry["months"].get(month) or {}).get("balance") or {}).get("fetched_at"))]
