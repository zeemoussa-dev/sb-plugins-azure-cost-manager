"""This plugin's two data files, through the Plugin API's `api.data`.

`Tracked-Accounts.json` is the operator's choice of billing accounts.
`Consumption-Cache.json` holds the rows Azure returned, per account per month,
with when each month was fetched -- so a month Azure has finished settling is
never queried again (Cost Management throttles per scope).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import months

TRACKED_ACCOUNTS_FILE = "Azure-Cost-Manager/Tracked-Accounts.json"
CONSUMPTION_CACHE_FILE = "Azure-Cost-Manager/Consumption-Cache.json"
DATA_FILES = (TRACKED_ACCOUNTS_FILE, CONSUMPTION_CACHE_FILE)

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
    api.data.write_text(path, json.dumps(value, indent=2, sort_keys=True))


def is_settled(month: str, fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    fetched_on = datetime.fromisoformat(fetched_at).date()
    return fetched_on >= months.last_day(month) + timedelta(days=SETTLING_DAYS)


class ConsumptionStore:
    def __init__(self, api) -> None:
        self._api = api

    def tracked_accounts(self) -> list[dict]:
        return list(_read_json(self._api, TRACKED_ACCOUNTS_FILE, {"accounts": []}).get("accounts") or [])

    def save_tracked_accounts(self, accounts: list[dict]) -> None:
        _write_json(self._api, TRACKED_ACCOUNTS_FILE, {"accounts": accounts})

    def tracked_account(self, account_name: str) -> dict | None:
        return next((account for account in self.tracked_accounts()
                     if account["name"] == account_name), None)

    def _cache(self) -> dict:
        return _read_json(self._api, CONSUMPTION_CACHE_FILE, {"accounts": {}})

    def cached(self, account_name: str) -> dict:
        """`{months: {YYYY-MM: {fetched_at, actual, amortized}}, commitment, forecast, fetched_at, errors}`."""
        return self._cache()["accounts"].get(account_name) or {"months": {}}

    def save_cached(self, account_name: str, entry: dict) -> None:
        cache = self._cache()
        cache["accounts"][account_name] = entry
        _write_json(self._api, CONSUMPTION_CACHE_FILE, cache)

    def forget_untracked(self, tracked_names: set[str]) -> None:
        cache = self._cache()
        kept = {name: entry for name, entry in cache["accounts"].items() if name in tracked_names}
        if len(kept) != len(cache["accounts"]):
            _write_json(self._api, CONSUMPTION_CACHE_FILE, {"accounts": kept})

    @staticmethod
    def months_to_fetch(entry: dict, wanted: list[str]) -> list[str]:
        """The wanted months that are missing or not yet settled, as one
        contiguous run ending at the last wanted month -- one query, not many."""
        unsettled = [month for month in wanted
                     if not is_settled(month, (entry["months"].get(month) or {}).get("fetched_at"))]
        if not unsettled:
            return []
        return months.span(min(unsettled), wanted[-1])
