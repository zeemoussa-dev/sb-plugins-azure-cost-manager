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
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Callable

from . import months

CUSTOMERS_FILE = "Azure-Cost-Manager/Customers.json"
CONSUMPTION_CACHE_FILE = "Azure-Cost-Manager/Consumption-Cache.json"
# Offers the operator marked as not counting toward a MACC -- Azure does not say.
MARKETPLACE_SETTINGS_FILE = "Azure-Cost-Manager/Marketplace-Settings.json"
# 0.1.x tracked single accounts; read once to carry them over as customers.
LEGACY_TRACKED_ACCOUNTS_FILE = "Azure-Cost-Manager/Tracked-Accounts.json"
# FinOps: the pricing region and the Retail Prices discounts per meter (`pricing`).
FINOPS_FILE = "Azure-Cost-Manager/FinOps.json"
# The operator's own service -> solution play choices, over `solution_plays`' defaults.
SOLUTION_PLAYS_FILE = "Azure-Cost-Manager/Solution-Plays.json"
# The seller's baseline (start, months), fiscal year and quota -- one for everyone.
QUOTA_FILE = "Azure-Cost-Manager/Quota.json"
DATA_FILES = (CUSTOMERS_FILE, CONSUMPTION_CACHE_FILE, MARKETPLACE_SETTINGS_FILE, LEGACY_TRACKED_ACCOUNTS_FILE,
              FINOPS_FILE, SOLUTION_PLAYS_FILE, QUOTA_FILE)

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


def _write_json(api, path: str, value, compact: bool = False) -> None:
    # The cache is compact: indentation added a quarter to a file nobody reads by hand.
    text = (json.dumps(value, separators=(",", ":"), sort_keys=True) if compact
            else json.dumps(value, indent=1, sort_keys=True))
    api.data.write_text(path, text)


def is_settled(month: str, fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    fetched_on = datetime.fromisoformat(fetched_at).date()
    return fetched_on >= months.last_day(month) + timedelta(days=SETTLING_DAYS)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "customer"


# Writing the whole cache costs about a second at 27 MB, and OneDrive uploads every
# write; while a sync holds writes (`holding_writes`), a save reaches the file at most
# this often -- and at once on `flush()`, which the sync calls as each enrollment
# finishes. Pages read the cache in memory, so they see a save at once either way.
CACHE_WRITE_EVERY_SECONDS = 30.0


class ConsumptionStore:
    def __init__(self, api, clock: Callable[[], float] = time.monotonic) -> None:
        self._api = api
        self._clock = clock
        self._lock = threading.RLock()
        self._cache: dict | None = None
        self._unwritten = False
        self._written_at: float | None = None
        self._holding = 0

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

    def finops_state(self) -> dict:
        with self._lock:
            return _read_json(self._api, FINOPS_FILE, {})

    def save_finops_state(self, state: dict) -> None:
        with self._lock:
            _write_json(self._api, FINOPS_FILE, state)

    def read_files(self) -> dict[str, str | None]:
        """Every data file as it is on disk, for an export; the cache as last written."""
        self.flush()
        with self._lock:
            found = {}
            for path in DATA_FILES:
                try:
                    found[path] = self._api.data.read_text(path)
                except Exception:
                    found[path] = None
            return found

    def replace_files(self, files: dict[str, str]) -> None:
        """An import: these files replace the ones here, and the cache is read afresh."""
        with self._lock:
            for path, text in files.items():
                if path not in DATA_FILES:
                    raise ValueError(f"not a data file of this plugin: {path}")
                self._api.data.write_text(path, text)
            self._cache = None
            self._unwritten = False
            self._written_at = None

    def quota_state(self) -> dict:
        with self._lock:
            return dict(_read_json(self._api, QUOTA_FILE, {}))

    def save_quota_state(self, state: dict) -> None:
        with self._lock:
            _write_json(self._api, QUOTA_FILE, state)

    def solution_play_overrides(self) -> dict[str, str]:
        with self._lock:
            return dict(_read_json(self._api, SOLUTION_PLAYS_FILE, {}).get("services") or {})

    def save_solution_play_overrides(self, overrides: dict[str, str]) -> None:
        with self._lock:
            _write_json(self._api, SOLUTION_PLAYS_FILE, {"services": overrides})

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
        # A billing profile's months hold only invoice totals and Marketplace, and are kept.
        entry["months"] = {month: data for month, data in (entry.get("months") or {}).items()
                           if isinstance(data.get("actual"), dict) or "actual" not in data}
        return entry

    def account_status(self, account_name: str) -> dict:
        """`{synced_at, errors}` of one account, without copying its months: the
        customer list reads these for every account on every request, and a deep
        copy of each (15 MB of months on this install) cost a second a list."""
        with self._lock:
            entry = self._loaded()["accounts"].get(account_name) or {}
            return {"synced_at": entry.get("synced_at"), "errors": dict(entry.get("errors") or {})}

    def profile_accounts(self, excluded: set[str]) -> dict[str, dict]:
        """Every cached account outside `excluded` (the customers' accounts): the
        billing profiles synced lightly, or left behind by a removed customer."""
        with self._lock:
            return {name: json.loads(json.dumps(entry)) for name, entry in self._loaded()["accounts"].items()
                    if name not in excluded}

    def save_account(self, account_name: str, entry: dict) -> None:
        with self._lock:
            self._loaded()["accounts"][account_name] = entry
            self._unwritten = True
            if (not self._holding or self._written_at is None
                    or self._clock() - self._written_at >= CACHE_WRITE_EVERY_SECONDS):
                self._write_cache()

    @contextmanager
    def holding_writes(self):
        """Saves inside reach the file at most every `CACHE_WRITE_EVERY_SECONDS`;
        everything held is written on the way out."""
        with self._lock:
            self._holding += 1
        try:
            yield
        finally:
            with self._lock:
                self._holding -= 1
            self.flush()

    def flush(self) -> None:
        """Writes what `save_account` has held back. A restart before it loses at
        most that much, which the next sync fetches again."""
        with self._lock:
            if self._unwritten:
                self._write_cache()

    def _write_cache(self) -> None:
        _write_json(self._api, CONSUMPTION_CACHE_FILE, self._cache, compact=True)
        self._unwritten = False
        self._written_at = self._clock()

    def forget_accounts_except(self, kept: set[str]) -> None:
        """An account no customer holds drops back to a billing profile: its Cost
        Management breakdowns go, its invoice totals and Marketplace charges stay --
        the cross-customer Marketplace covers every profile, customer or not."""
        light_keys = ("balance", "marketplace")
        with self._lock:
            cache = self._loaded()
            changed = False
            for name, entry in cache["accounts"].items():
                if name in kept or entry.get("light"):
                    continue
                entry["months"] = {month: {key: data[key] for key in light_keys if key in data}
                                   for month, data in (entry.get("months") or {}).items()
                                   if any(key in data for key in light_keys)}
                for key in ("forecast", "synced_at"):
                    entry.pop(key, None)
                entry["light"] = True
                changed = True
            if changed:
                self._write_cache()

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
    def amortized_meters_to_fetch(entry: dict, wanted: list[str]) -> list[str]:
        """The wanted months with cost data whose amortized meter detail is missing
        or not yet settled -- FinOps' coverage reads it (0.12.0)."""
        return [month for month in wanted
                if "actual" in (entry["months"].get(month) or {})
                and not is_settled(month, ((entry["months"].get(month) or {}).get("meters_amortized") or {})
                                   .get("fetched_at"))]

    @staticmethod
    def balances_to_fetch(entry: dict, wanted: list[str]) -> list[str]:
        """The wanted billing periods whose balance is missing or not yet settled."""
        return [month for month in wanted
                if not is_settled(month, ((entry["months"].get(month) or {}).get("balance") or {}).get("fetched_at"))]
