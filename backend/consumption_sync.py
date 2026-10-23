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
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from . import months, tags
from .azure_token import AzureSignInError
from .billing_client import COST_TYPES, AzureApiError, AzureThrottled, BillingClient
from .consumption_store import SETTLING_DAYS, ConsumptionStore, is_settled
from .customers import AccountDirectory
from .sync_log import SyncLog

WINDOW_MONTHS = 12
# Without a known term, how far back a first sync reaches.
DEFAULT_HISTORY_MONTHS = 12
# A term start further back than this is cut, so a typo cannot ask for decades.
LONGEST_HISTORY_MONTHS = 72
THROTTLE_WAITS_PER_QUERY = 12
# FinOps reads a year of closed months plus the current one; amortized meter
# detail older than that would cost queries and be read by nothing.
FINOPS_MONTHS = 13
# Cost by tag: the last six closed months and the current one. Each tag spelling is
# a query on the throttling budget, so it reaches no further back than its reports read.
TAG_MONTHS = 6
TAG_KEYS_FRESH_FOR = timedelta(days=7)
# What each subscription is used for (solution patterns) is read from the last
# closed months by service, meter and resource group, fetched with the tags and
# again only when another month closes. Each subscription keeps its largest few.
FOOTPRINT_MONTHS = 3
FOOTPRINT_DIMENSIONS = {"services": "ServiceName", "meters": "MeterSubCategory",
                        "resource_groups": "ResourceGroupName"}
FOOTPRINT_KEEP = 40
THIS_MONTH_TAG_DIMENSIONS = ("Project", "Owner", "Environment")
# A sync cut off by a backend restart starts again this long after the plugin loads --
# once the restart has settled -- unless that many runs of it in a row were cut off
# before they asked Azure anything.
RESUME_AFTER_SECONDS = 20
RESUMES_IN_A_ROW = 10
# A Refresh this month asks again for this many days before the last day it has:
# Azure lags a day or two and revises recent days for about as long as a month settles.
DAILY_REFETCH_DAYS = SETTLING_DAYS
# A sync of everyone skips an enrollment synced this recently: a restart resumes,
# and the weekly job and the Sync button still bring every enrollment's delta.
RESYNC_AFTER = timedelta(hours=20)
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


def _aggregate_daily(rows: list[dict], keys: tuple[str, ...]) -> dict[str, dict[str, dict[str, float]]]:
    """Per key (`service`, `subscription`, `resource_group`): day -> name -> cost."""
    found: dict[str, dict[str, dict[str, float]]] = {key: {} for key in keys}
    for row in rows:
        for key in keys:
            day = found[key].setdefault(row["day"], {})
            day[row[key]] = day.get(row[key], 0.0) + row["cost"]
    return {key: {day: {name: round(cost, 2) for name, cost in names.items() if round(cost, 2) != 0}
                  for day, names in days.items()} for key, days in found.items()}


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
                 after_customers: Callable[[], dict] | None = None, log: SyncLog | None = None) -> None:
        self._store = store
        self._log = log
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
                              "scope": None, "current": None, "step_started_at": None,
                              "accounts_done": 0, "accounts_total": 0, "errors": []}

    def status(self) -> dict:
        with self._lock:
            found = {**self._status, "errors": list(self._status["errors"])}
        return {**found, "in_flight": self._log.in_flight() if self._log else None}

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
        if self._log:
            self._log.begin(self._status["scope"])
        threading.Thread(target=self._run_and_finish, args=(customer_id, profiles), daemon=True,
                         name="azure-cost-manager-sync").start()
        return {"started": True, **self.status()}

    def start_tags(self, customer_id: str | None = None) -> dict:
        """Cost by tag only, in the background -- without waiting for a full sync."""
        with self._lock:
            if self._status["running"]:
                return {"started": False, "reason": "a sync is already running", **self._status}
            self._status.update(running=True, started_at=self._now().isoformat(), finished_at=None,
                                scope=f"{customer_id or 'all'}:tags", current=None, accounts_done=0,
                                accounts_total=0, errors=[])
        if self._log:
            self._log.begin(self._status["scope"])
        threading.Thread(target=self._run_and_finish, args=(customer_id, "tags"), daemon=True,
                         name="azure-cost-manager-tags").start()
        return {"started": True, **self.status()}

    def start_this_month(self, customer_id: str | None = None) -> dict:
        """This month and last, by day, in the background -- only when asked
        (operator, 2026-10-18: on demand, no scheduled job)."""
        with self._lock:
            if self._status["running"]:
                return {"started": False, "reason": "a sync is already running", **self._status}
            self._status.update(running=True, started_at=self._now().isoformat(), finished_at=None,
                                scope=f"{customer_id or 'all'}:this-month", current=None, accounts_done=0,
                                accounts_total=0, errors=[])
        if self._log:
            self._log.begin(self._status["scope"])
        threading.Thread(target=self._run_and_finish, args=(customer_id, "month"), daemon=True,
                         name="azure-cost-manager-this-month").start()
        return {"started": True, **self.status()}

    def resume_interrupted(self) -> dict | None:
        """Starts again the sync a backend restart cut off (operator, 2026-10-18: "when
        the plugin loads and the last sync was interrupted by a restart, start it again
        automatically"). It resumes rather than restarts: settled months, recently
        synced enrollments and stored days are never fetched again."""
        scope = self._log.interrupted_scope() if self._log else None
        if not scope or self._log.fruitless_in_a_row(scope) > RESUMES_IN_A_ROW:
            return None
        started = self._start_scope(scope)
        if started.get("started") and self._log:
            self._log.note("started again automatically: the backend restarted during the last run")
        return started

    def _start_scope(self, scope: str) -> dict:
        """The start call a status `scope` came from."""
        base, _, kind = scope.partition(":")
        customer_id = None if base in ("all", "profiles") else base
        if kind == "tags":
            return self.start_tags(customer_id)
        if kind == "this-month":
            return self.start_this_month(customer_id)
        if scope == "profiles":
            return self.start(None, "only")
        if base.endswith("+profiles"):
            customer = base[:-len("+profiles")]
            return self.start(None if customer == "all" else customer, "also")
        return self.start(customer_id)

    def run_this_month(self, customer_id: str | None = None) -> None:
        """Only the delta (operator, 2026-10-18: "why no marker, and fetch only after
        that?"). Each enrollment remembers the last day it was fetched to; a refresh
        asks again from `DAILY_REFETCH_DAYS` before that marker -- Azure keeps revising
        the latest days for that long -- and keeps every earlier day as stored. An
        enrollment never fetched gets last month and this one, and goes first."""
        everyone = self._customers()
        customers = [customer for customer in everyone if not customer_id
                     or customer["id"] == customer_id or customer.get("parent") == customer_id]
        accounts = sorted({name for customer in customers for name in customer["accounts"]})
        today = self._today()
        first_day = months.first_day(months.shift(months.month_of(today), -1)).isoformat()
        if not accounts:
            # A refresh once ended "0 of 0" with nothing to say why (2026-10-18).
            self._record_error(None, f"this month: no enrollments found for {customer_id or 'any customer'} "
                                     f"among {len(everyone)} customers")
        kept_by_account = {account: self._store.account(account).get("daily") or {} for account in accounts}
        order = sorted(accounts, key=lambda name: (kept_by_account[name].get("fetched_at") or "", name))
        self._set(accounts_done=0, accounts_total=len(order))
        client = self._client_factory()
        for done, account in enumerate(order, start=1):
            kept = kept_by_account[account]
            marker = kept.get("last_day") if (kept.get("first_day") or "9999") <= first_day else None
            refetch_from = (max(first_day, (date.fromisoformat(marker) - timedelta(days=DAILY_REFETCH_DAYS)).isoformat())
                            if marker else first_day)

            def since(key: str) -> str:
                return refetch_from if key in kept else first_day

            if self._log and marker:
                self._log.note(f"{account}: fetched by day to {marker}; asking again from {refetch_from}", account)
            self._set(current={**self._named(account), "this_month": True})
            try:
                by_service = self._query(lambda: client.query_daily(
                    account, since("service"), today.isoformat(),
                    {"service": "ServiceName", "subscription": "SubscriptionName"}), account)
                by_group = self._query(lambda: client.query_daily(
                    account, since("resource_group"), today.isoformat(), {"resource_group": "ResourceGroupName"}),
                    account)
            except AzureApiError as exc:
                self._record_error(account, f"this month: {exc}")
                self._set(accounts_done=done)
                continue
            entry = self._store.account(account)
            fetched = {**_aggregate_daily(by_service, ("service", "subscription")),
                       **_aggregate_daily(by_group, ("resource_group",))}
            # By tag too: a new Project or Owner value is often the clearest sign of a
            # new initiative (operator, 2026-10-18). One query per dimension, on the
            # spelling this enrollment uses most plainly -- known once tags have synced.
            found = tags.spellings((entry.get("tags") or {}).get("keys") or [])
            for dimension in THIS_MONTH_TAG_DIMENSIONS:
                if not found.get(dimension):
                    continue
                key, name = found[dimension][0], f"tag:{dimension}"
                try:
                    rows = self._query(lambda key=key, name=name: client.query_daily_by_tag(
                        account, since(name), today.isoformat(), key), account)
                except AzureApiError as exc:
                    self._record_error(account, f"this month, tag {key}: {exc}")
                    continue
                fetched[name] = _aggregate_daily(rows, ("value",))["value"]
            # Stored days before the refetch stay; days before last month drop out.
            merged = {name: {day: values for day, values in (kept.get(name) or {}).items()
                             if first_day <= day < since(name)} | days
                      for name, days in fetched.items()}
            entry["daily"] = {"first_day": first_day, "last_day": today.isoformat(),
                              "fetched_at": self._now().isoformat(), **merged}
            self._store.save_account(account, entry)
            self._store.flush()
            self._set(accounts_done=done)

    def _run_and_finish(self, customer_id: str | None, profiles: str = "none") -> None:
        stopped = False
        try:
            with self._store.holding_writes():
                self._run(customer_id, profiles)
        except Exception as exc:  # the thread must always clear `running`
            stopped = True
            self._record_error(None, f"sync stopped: {exc}")
        finally:
            with self._lock:
                self._status.update(running=False, current=None, step_started_at=None,
                                    finished_at=self._now().isoformat())
            if self._log:
                self._log.end("stopped" if stopped else "finished")

    def _run(self, customer_id: str | None, profiles: str) -> None:
        if profiles == "month":
            self.run_this_month(customer_id)
            return
        if profiles == "tags":
            self.run_tags(customer_id)
            return
        if profiles != "only":
            self.run(customer_id)
            self._price_candidates()
            self.run_tags(customer_id)
        if profiles != "none":
            self.run_profiles()

    def run_tags(self, customer_id: str | None = None) -> None:
        """Cost by tag for the customers' enrollments: each enrollment's tag keys
        (weekly), then, per business dimension, one query per spelling it uses, for
        the months FinOps reads. A settled month is never fetched again."""
        everyone = self._customers()
        customers = [customer for customer in everyone if not customer_id
                     or customer["id"] == customer_id or customer.get("parent") == customer_id]
        accounts = sorted({name for customer in customers for name in customer["accounts"]})
        self._set(accounts_done=0, accounts_total=len(accounts))
        client = self._client_factory()
        wanted = months.span(months.shift(months.month_of(self._today()), -TAG_MONTHS), months.month_of(self._today()))
        tags_synced = {account: (self._store.account(account).get("tags") or {}).get("synced_at") for account in accounts}
        tags_due = {account for account in accounts if customer_id or not self._recent(tags_synced[account])}
        footprint_due = {account for account in accounts if customer_id or self._footprint_stale(account)}
        due = [account for account in sorted(accounts, key=lambda name: (tags_synced[name] or "", name))
               if account in tags_due or account in footprint_due]
        self._note_skipped(len(accounts) - len(due), "tags and solutions")
        self._set(accounts_done=0, accounts_total=len(due))
        for done, account in enumerate(due, start=1):
            if account in tags_due:
                self._one_enrollment(account, lambda: self._sync_account_tags(client, account, wanted))
            if account in footprint_due:
                self._one_enrollment(account, lambda: self._sync_footprint(client, account))
            self._store.flush()
            self._set(accounts_done=done)

    def _footprint_window(self) -> tuple[str, str]:
        last = months.shift(months.month_of(self._today()), -1)
        return months.shift(last, -(FOOTPRINT_MONTHS - 1)), last

    def _footprint_stale(self, account: str) -> bool:
        return (self._store.account(account).get("footprint") or {}).get("last_month") != self._footprint_window()[1]

    def _sync_footprint(self, client: BillingClient, account: str) -> None:
        """Each subscription's last closed months by service, meter and resource group:
        what solution patterns read (operator, 2026-10-23)."""
        first, last = self._footprint_window()
        self._set(current={**self._named(account), "footprint": True, "first_month": first, "last_month": last})
        subscriptions: dict[str, dict[str, dict[str, float]]] = {}
        for key, dimension in FOOTPRINT_DIMENSIONS.items():
            try:
                rows = self._query(lambda dimension=dimension: client.query_by_subscription(
                    account, first, last, dimension), account)
            except AzureApiError as exc:
                self._record_error(account, f"solutions ({key}): {exc}")
                return
            for row in rows:
                found = subscriptions.setdefault(row.get("subscription") or "Unassigned",
                                                 {name: {} for name in FOOTPRINT_DIMENSIONS})[key]
                name = row.get("name") or "Unassigned"
                found[name] = found.get(name, 0.0) + row["cost"]
        for found in subscriptions.values():
            for key, costs in found.items():
                kept = sorted(((name, round(cost, 2)) for name, cost in costs.items() if round(cost, 2) != 0),
                              key=lambda item: -item[1])[:FOOTPRINT_KEEP]
                found[key] = dict(kept)
        entry = self._store.account(account)
        entry["footprint"] = {"first_month": first, "last_month": last, "months": FOOTPRINT_MONTHS,
                              "fetched_at": self._now().isoformat(), "subscriptions": subscriptions}
        self._store.save_account(account, entry)

    def _sync_account_tags(self, client: BillingClient, account: str, wanted: list[str]) -> None:
        entry = self._store.account(account)
        state = entry.setdefault("tags", {})
        self._set(current={**self._named(account), "tags": True})
        fetched = state.get("keys_fetched_at")
        if not fetched or self._now() - datetime.fromisoformat(fetched) > TAG_KEYS_FRESH_FOR:
            try:
                state["keys"] = self._query(lambda: client.list_tag_keys(account), account)
                state["keys_fetched_at"] = self._now().isoformat()
            except AzureApiError as exc:
                self._record_error(account, f"tag keys: {exc}")
                return
        by_key = state.setdefault("by_key", {})
        for dimension, keys in tags.spellings(state.get("keys") or []).items():
            for key in keys:
                spelled = by_key.setdefault(key, {"dimension": dimension, "months": {}, "fetched": {}})
                spelled["dimension"] = dimension
                pending = [month for month in wanted
                           if not is_settled(month, (spelled.get("fetched") or {}).get(month))]
                for window in _windows(pending):
                    self._set(current={**self._named(account), "tags": True, "tag": key,
                                       "first_month": window[0], "last_month": window[-1]})
                    try:
                        rows = self._query(lambda: client.query_monthly_by_tag(account, key, window[0], window[-1]),
                                           account)
                    except AzureApiError as exc:
                        self._record_error(account, f"tag {key} {window[0]}..{window[-1]}: {exc}")
                        continue
                    fetched_at = self._now().isoformat()
                    for month in window:
                        values: dict[str, float] = {}
                        for row in rows:
                            if row["month"] == month:
                                values[row["value"]] = round(values.get(row["value"], 0.0) + row["cost"], 2)
                        spelled["months"][month] = values
                        spelled["fetched"][month] = fetched_at
                    self._store.save_account(account, entry)
        state["synced_at"] = self._now().isoformat()
        self._store.save_account(account, entry)

    def _one_enrollment(self, account: str, sync_it: Callable[[], None]) -> None:
        """One enrollment's unexpected failure is recorded and the sync goes on to the
        next; it used to end the whole run. A lost sign-in still ends it, since every
        enrollment after would fail the same way."""
        try:
            sync_it()
        except AzureSignInError:
            raise
        except Exception as exc:
            self._record_error(account, f"stopped on this enrollment: {exc}")

    def _note_skipped(self, skipped: int, what: str) -> None:
        if skipped and self._log:
            self._log.note(f"{what}: {skipped} enrollment(s) synced within {RESYNC_AFTER} skipped")

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
        if self._log:
            self._log.error(account, message)

    def _set(self, **fields) -> None:
        with self._lock:
            # A wait updates the step it is in; only a different step restarts the clock.
            stepped = "current" in fields and fields["current"] is not None and                 {key: value for key, value in fields["current"].items() if key != "waiting_seconds"} !=                 {key: value for key, value in (self._status["current"] or {}).items() if key != "waiting_seconds"}
            if stepped:
                fields["step_started_at"] = self._now().isoformat()
            self._status.update(fields)
        if stepped and self._log:
            self._log.step(fields["current"])

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
        # A sync of everyone resumes rather than restarts (operator, 2026-10-17: "it should
        # sync the ones that didn't sync yet and add the delta for the rest"): never-synced
        # enrollments first, then the longest ago, and one synced within the day is
        # skipped. Syncing one customer always refreshes it.
        synced_at = {name: self._store.account(name).get("synced_at") for name in first_month_by_account}
        order = sorted(first_month_by_account, key=lambda name: (synced_at[name] or "", name))
        # The progress counts only what will be fetched: "1 of 112" with 59 to skip read
        # as a sync that fetches everything again (operator, 2026-10-18).
        due = [name for name in order if customer_id or not self._recent(synced_at[name])]
        self._note_skipped(len(order) - len(due), "consumption")
        self._set(accounts_done=0, accounts_total=len(due))
        client = self._client_factory()
        for done, name in enumerate(due, start=1):
            self._one_enrollment(name, lambda: self._sync_account(client, name, first_month_by_account[name],
                                                                  visible.get(name) or {}))
            self._store.flush()
            self._set(accounts_done=done)

    def _recent(self, synced_at: str | None) -> bool:
        return bool(synced_at) and self._now() - datetime.fromisoformat(synced_at) < RESYNC_AFTER

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
            self._one_enrollment(account["name"], lambda: self._sync_profile(client, account))
            self._store.flush()
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
                current = {key: value for key, value in (self.status()["current"] or {}).items()
                           if key != "waiting_seconds"}
                self._set(current={**current, "waiting_seconds": exc.retry_after_seconds})
                if self._log:
                    self._log.wait(exc.retry_after_seconds + 1, account)
                self._sleep(exc.retry_after_seconds + 1)
                self._set(current=current)
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
