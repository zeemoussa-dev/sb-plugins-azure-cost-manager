"""Bringing customers' consumption from Azure into local data.

One account at a time, month by month, at most twelve months per query (Cost
Management's limit), saving after every window so a stopped sync resumes where
it left off. Cost Management throttles per sign-in, so the sync waits out
whatever Azure asks for; nothing else in the plugin queries cost at all.

Runs in a background thread: the weekly Hermes job and the Sync buttons only
start it, and read its progress from `status()`.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Callable

from . import months
from .billing_client import COST_TYPES, AzureApiError, AzureThrottled, BillingClient
from .consumption_store import ConsumptionStore
from .customers import AccountDirectory

WINDOW_MONTHS = 12
# Without a known term, how far back a first sync reaches.
DEFAULT_HISTORY_MONTHS = 12
# A term start further back than this is cut, so a typo cannot ask for decades.
LONGEST_HISTORY_MONTHS = 72
THROTTLE_WAITS_PER_QUERY = 12
# FinOps reads a year of closed months plus the current one; amortized meter
# detail older than that would cost queries and be read by nothing.
FINOPS_MONTHS = 13
ENTERPRISE_AGREEMENT = "EnterpriseAgreement"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aggregate(rows: list[dict]) -> dict[str, dict]:
    """Rows of month x service x subscription into, per month, two name -> cost
    maps. The cross product itself is not kept: over three years of a large
    customer it runs to megabytes, and nothing on screen reads it."""
    by_month: dict[str, dict] = {}
    for row in rows:
        month = by_month.setdefault(row["month"], {"service": {}, "subscription": {}, "currency": None})
        for key in ("service", "subscription"):
            month[key][row[key]] = month[key].get(row[key], 0.0) + row["cost"]
        month["currency"] = month["currency"] or row.get("currency")
    for month in by_month.values():
        for key in ("service", "subscription"):
            month[key] = {name: round(cost, 2) for name, cost in month[key].items() if round(cost, 2) != 0}
    return by_month


def _aggregate_meters(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Per month, `"<meter subcategory>|<pricing model>"` -> cost."""
    by_month: dict[str, dict[str, float]] = {}
    for row in rows:
        key = f"{row['meter_subcategory']}|{row['pricing_model']}"
        month = by_month.setdefault(row["month"], {})
        month[key] = month.get(key, 0.0) + row["cost"]
    return {month: {key: round(cost, 2) for key, cost in meters.items() if round(cost, 2) != 0}
            for month, meters in by_month.items()}


def _aggregate_marketplace(charges: list[dict]) -> list[dict]:
    """One month's charges by publisher, offer, plan, subscription and kind: a
    metered VM image bills a line per hour, which nobody reads one at a time."""
    grouped: dict[tuple, dict] = {}
    for charge in charges:
        key = (charge["publisher"], charge["offer"], charge["plan"], charge["subscription"], charge["recurring"])
        item = grouped.setdefault(key, {"publisher": key[0], "offer": key[1], "plan": key[2], "subscription": key[3],
                                        "recurring": key[4], "cost": 0.0, "quantity": 0.0, "unit": charge["unit"],
                                        "lines": 0})
        item["cost"] += charge["cost"]
        item["quantity"] += charge["quantity"]
        item["lines"] += 1
    return [{**item, "cost": round(item["cost"], 2), "quantity": round(item["quantity"], 4)}
            for item in grouped.values()]


def _windows(wanted: list[str]) -> list[list[str]]:
    """Consecutive runs of months, each at most a query's length."""
    runs: list[list[str]] = []
    for month in wanted:
        if runs and months.shift(runs[-1][-1], 1) == month and len(runs[-1]) < WINDOW_MONTHS:
            runs[-1].append(month)
        else:
            runs.append([month])
    return runs


class ConsumptionSync:
    def __init__(self, store: ConsumptionStore, directory: AccountDirectory,
                 client_factory: Callable[[], BillingClient], today: Callable[[], date] = date.today,
                 now: Callable[[], datetime] = _now, sleep: Callable[[float], None] = time.sleep,
                 customers: Callable[[], list[dict]] | None = None,
                 after_customers: Callable[[], dict] | None = None) -> None:
        self._store = store
        # Run once the customers are synced: FinOps prices their steady candidates.
        self._after_customers = after_customers
        # The customer book's view: a linked customer's signed value is on its Customer note.
        self._customers = customers or store.customers
        self._directory = directory
        self._client_factory = client_factory
        self._today = today
        self._now = now
        self._sleep = sleep
        self._lock = threading.Lock()
        self._status: dict = {"running": False, "started_at": None, "finished_at": None,
                              "scope": None, "current": None, "accounts_done": 0, "accounts_total": 0,
                              "errors": []}

    def status(self) -> dict:
        with self._lock:
            return {**self._status, "errors": list(self._status["errors"])}

    def start(self, customer_id: str | None = None, profiles: str = "none") -> dict:
        """Starts a sync in the background unless one is running already.
        `profiles`: "none" (customers only), "also" (customers, then every other
        billing profile, lightly) or "only" (just the other profiles)."""
        if profiles not in ("none", "also", "only"):
            raise ValueError("profiles is none, also or only")
        scope = "profiles" if profiles == "only" else (customer_id or "all") + ("+profiles" if profiles == "also" else "")
        with self._lock:
            if self._status["running"]:
                return {"started": False, "reason": "a sync is already running", **self._status}
            self._status.update(running=True, started_at=self._now().isoformat(), finished_at=None,
                                scope=scope, current=None, accounts_done=0,
                                accounts_total=0, errors=[])
        threading.Thread(target=self._run_and_finish, args=(customer_id, profiles), daemon=True,
                         name="azure-cost-manager-sync").start()
        return {"started": True, **self.status()}

    def _run_and_finish(self, customer_id: str | None, profiles: str = "none") -> None:
        try:
            if profiles != "only":
                self.run(customer_id)
                self._price_candidates()
            if profiles != "none":
                self.run_profiles()
        except Exception as exc:  # the thread must always clear `running`
            self._record_error(None, f"sync stopped: {exc}")
        finally:
            with self._lock:
                self._status.update(running=False, current=None, finished_at=self._now().isoformat())

    def _price_candidates(self) -> None:
        if not self._after_customers:
            return
        self._set(current={"account": None, "pricing": True})
        try:
            for failure in self._after_customers().get("failed") or []:
                self._record_error(None, f"pricing {failure}")
        except Exception as exc:  # pricing is an extra: it never fails the sync
            self._record_error(None, f"pricing stopped: {exc}")

    def _record_error(self, account: str | None, message: str) -> None:
        with self._lock:
            self._status["errors"].append({"account": account, "message": message})

    def _set(self, **fields) -> None:
        with self._lock:
            self._status.update(fields)

    def _named(self, account: str) -> dict:
        """The account being synced, keeping the name the status already shows for it."""
        current = self.status()["current"] or {}
        name = current.get("display_name") if current.get("account") == account else None
        return {"account": account, **({"display_name": name} if name else {})}

    def run(self, customer_id: str | None = None) -> None:
        everyone = self._customers()
        starts = {customer["id"]: (customer.get("commitment") or {}).get("start") for customer in everyone}
        customers = everyone
        if customer_id:
            # A parent's sync brings its affiliates: their consumption is part of its MACC.
            customers = [customer for customer in everyone
                         if customer["id"] == customer_id or customer.get("parent") == customer_id]
        visible = self._directory.by_name()
        # An account in two customers is fetched once, reaching as far back as either needs.
        first_month_by_account: dict[str, str] = {}
        for customer in customers:
            # An affiliate's dollars count against its parent's MACC from the parent's start.
            own_and_parent = [day for day in (starts.get(customer["id"]), starts.get(customer.get("parent"))) if day]
            commitment_start = min(own_and_parent) if own_and_parent else None
            for name in customer["accounts"]:
                first = self._first_month(visible.get(name) or {}, commitment_start)
                first_month_by_account[name] = min(first, first_month_by_account.get(name, first))
        self._set(accounts_total=len(first_month_by_account))
        client = self._client_factory()
        for done, (name, first_month) in enumerate(sorted(first_month_by_account.items()), start=1):
            self._sync_account(client, name, first_month, visible.get(name) or {})
            self._set(accounts_done=done)

    def run_profiles(self) -> None:
        """Every billing profile that is in no customer, lightly: each month's
        invoice totals and Marketplace charges -- the Consumption API's budget, not
        Cost Management's, which throttles per sign-in. One profile at a time, from
        its term start, so the cross-customer Marketplace covers everyone who
        bought, customer or not (operator, 2026-10-17)."""
        in_customers = {name for customer in self._store.customers() for name in customer["accounts"]}
        visible = self._directory.accounts(fresh=True)
        profiles = [account for account in visible
                    if account["name"] not in in_customers and account.get("agreement_type") == ENTERPRISE_AGREEMENT]
        self._set(accounts_done=0, accounts_total=len(profiles))
        client = self._client_factory()
        for done, account in enumerate(sorted(profiles, key=lambda a: a["display_name"].lower()), start=1):
            self._sync_profile(client, account)
            self._set(accounts_done=done)

    def _sync_profile(self, client: BillingClient, account: dict) -> None:
        name = account["name"]
        entry = self._store.account(name)
        entry.setdefault("months", {})
        errors: dict[str, str] = {}
        wanted = months.span(self._first_month(account, None), months.month_of(self._today()))
        self._set(current={"account": name, "display_name": account["display_name"],
                           "first_month": wanted[0], "last_month": wanted[0]})
        self._sync_balances(client, name, entry, wanted, errors)
        self._sync_marketplace(client, name, entry, wanted, errors)
        # Kept with the data, so a report can name the profile without asking Azure.
        entry.update(display_name=account["display_name"], group_key=account.get("group_key"),
                     light=True, profile_synced_at=self._now().isoformat(), errors=errors)
        self._store.save_account(name, entry)

    def _first_month(self, account: dict, commitment_start: str | None) -> str:
        current = months.month_of(self._today())
        candidates = [day[:7] for day in (account.get("term_start"), commitment_start) if day]
        first = min(candidates) if candidates else months.shift(current, -(DEFAULT_HISTORY_MONTHS - 1))
        return max(first, months.shift(current, -(LONGEST_HISTORY_MONTHS - 1)))

    def _query(self, call: Callable[[], list[dict]], account: str) -> list[dict]:
        for _ in range(THROTTLE_WAITS_PER_QUERY):
            try:
                return call()
            except AzureThrottled as exc:
                self._set(current={**(self.status()["current"] or {}), "waiting_seconds": exc.retry_after_seconds})
                self._sleep(exc.retry_after_seconds + 1)
        raise AzureApiError(429, f"still throttled after {THROTTLE_WAITS_PER_QUERY} waits")

    def _sync_account(self, client: BillingClient, account: str, first_month: str, known: dict) -> None:
        current_month = months.month_of(self._today())
        entry = self._store.account(account)
        entry.setdefault("months", {})
        errors: dict[str, str] = {}
        wanted = months.span(first_month, current_month)
        for window in _windows(self._store.months_to_fetch(entry, wanted)):
            self._set(current={"account": account, "first_month": window[0], "last_month": window[-1]})
            try:
                by_type = {cost_type: _aggregate(self._query(
                    lambda cost_type=cost_type: client.query_monthly_cost(account, cost_type, window[0], window[-1]),
                    account)) for cost_type in COST_TYPES}
                meters = _aggregate_meters(self._query(
                    lambda: client.query_monthly_meters(account, window[0], window[-1]), account))
            except AzureApiError as exc:
                errors[f"{window[0]}..{window[-1]}"] = str(exc)
                self._record_error(account, f"{window[0]}..{window[-1]}: {exc}")
                continue
            fetched_at = self._now().isoformat()
            for month in window:
                actual = by_type["ActualCost"].get(month) or {}
                amortized = by_type["AmortizedCost"].get(month) or {}
                kept_balance = (entry["months"].get(month) or {}).get("balance")
                entry["months"][month] = {
                    "fetched_at": fetched_at,
                    "currency": actual.get("currency") or amortized.get("currency"),
                    "actual": {"service": actual.get("service", {}), "subscription": actual.get("subscription", {})},
                    "amortized": {"service": amortized.get("service", {}),
                                  "subscription": amortized.get("subscription", {})},
                    "meters": meters.get(month, {}),
                    **({"balance": kept_balance} if kept_balance else {}),
                }
            # Saved per window: a sync stopped by a restart resumes from here.
            self._store.save_account(account, entry)

        self._sync_amortized_meters(client, account, entry, wanted[-FINOPS_MONTHS:], errors)
        if known.get("agreement_type") == ENTERPRISE_AGREEMENT:
            self._sync_balances(client, account, entry, wanted, errors)
            self._sync_marketplace(client, account, entry, wanted, errors)

        entry["forecast"] = self._forecast(client, account, entry, current_month, errors)
        entry["synced_at"] = self._now().isoformat()
        entry["light"] = False  # a customer's account now: fully synced
        entry["errors"] = errors
        self._store.save_account(account, entry)

    def _sync_amortized_meters(self, client: BillingClient, account: str, entry: dict, wanted: list[str],
                               errors: dict[str, str]) -> None:
        """The meter detail again, amortized: under actual cost a reservation is its
        purchase and the usage it covers costs nothing, so only the amortized view
        says how much of a month was covered by commitments (FinOps)."""
        for window in _windows(self._store.amortized_meters_to_fetch(entry, wanted)):
            self._set(current={**self._named(account), "first_month": window[0], "last_month": window[-1],
                               "amortized_meters": True})
            try:
                meters = _aggregate_meters(self._query(
                    lambda: client.query_monthly_meters(account, window[0], window[-1], "AmortizedCost"), account))
            except AzureApiError as exc:
                errors[f"amortized meters {window[0]}..{window[-1]}"] = str(exc)
                self._record_error(account, f"amortized meters {window[0]}..{window[-1]}: {exc}")
                continue
            fetched_at = self._now().isoformat()
            for month in window:
                entry["months"][month]["meters_amortized"] = {"by": meters.get(month, {}), "fetched_at": fetched_at}
            self._store.save_account(account, entry)

    def _sync_balances(self, client: BillingClient, account: str, entry: dict, wanted: list[str],
                       errors: dict[str, str]) -> None:
        """Each billing period's usage, Marketplace and credits -- the figures the
        partner export and the customer's invoice use. A period before the
        enrollment existed answers with an error; it is kept as empty so a settled
        one is not asked for again."""
        pending = self._store.balances_to_fetch(entry, wanted)
        for index, month in enumerate(pending, start=1):
            self._set(current={**self._named(account), "first_month": month, "last_month": month, "balances": True})
            fetched_at = self._now().isoformat()
            try:
                balance = self._query(lambda: client.billing_period_balance(account, month), account)
            except AzureApiError as exc:
                if exc.status in (400, 404):
                    balance = {"usage": 0.0, "marketplace": 0.0, "credits": 0.0, "credit_details": [],
                               "billed_separately": 0.0, "currency": None, "missing": True}
                else:
                    errors[f"balance {month}"] = str(exc)
                    self._record_error(account, f"balance {month}: {exc}")
                    continue
            entry["months"].setdefault(month, {})["balance"] = {**balance, "fetched_at": fetched_at}
            if index % 6 == 0:
                self._store.save_account(account, entry)
        self._store.save_account(account, entry)

    def _sync_marketplace(self, client: BillingClient, account: str, entry: dict, wanted: list[str],
                          errors: dict[str, str]) -> None:
        """Each billing period's Marketplace charges, by solution and subscription.
        A period the enrollment did not exist in (its balance says so) is skipped."""
        def exists(month: str) -> bool:
            balance = (entry["months"].get(month) or {}).get("balance") or {}
            return bool(balance) and not balance.get("missing")

        pending = [month for month in self._store.marketplace_to_fetch(entry, wanted) if exists(month)]
        for index, month in enumerate(pending, start=1):
            self._set(current={**self._named(account), "first_month": month, "last_month": month, "marketplace": True})
            fetched_at = self._now().isoformat()
            try:
                charges = self._query(lambda: client.marketplace_charges(account, month), account)
            except AzureApiError as exc:
                errors[f"marketplace {month}"] = str(exc)
                self._record_error(account, f"marketplace {month}: {exc}")
                continue
            entry["months"].setdefault(month, {})["marketplace"] = {"items": _aggregate_marketplace(charges),
                                                                    "fetched_at": fetched_at}
            if index % 6 == 0:
                self._store.save_account(account, entry)
        self._store.save_account(account, entry)

    def _forecast(self, client: BillingClient, account: str, entry: dict, current_month: str,
                  errors: dict[str, str]) -> list[dict] | None:
        recent = [months.shift(current_month, -offset) for offset in range(0, 4)]
        if not any((entry["months"].get(month) or {}).get("actual", {}).get("service") for month in recent):
            return None  # an enrollment that stopped billing has nothing to forecast from
        try:
            return self._query(lambda: client.forecast_monthly(account, current_month,
                                                               f"{self._today().year:04d}-12"), account)
        except AzureApiError as exc:
            errors["forecast"] = str(exc)
            return None
