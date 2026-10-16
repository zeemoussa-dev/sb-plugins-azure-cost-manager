"""Customers: named groups of billing accounts, and the value each signed for.

A customer is rarely one enrollment. A parent enrollment has linked ones
(`Contoso-10000001-ContosoSaaS`), and a renewal starts a new enrollment while
the old one stops billing -- read alone, the old one says consumption fell to
zero. Settings suggests the related enrollments; the operator decides.
"""
from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .consumption_store import ConsumptionStore, slug
from .forecasting import DEFAULT_SCENARIO

COMMITMENT_TYPES = ("MACC", "EA commitment", "Azure Prepayment", "Other")

# `<parent display name>-<parent account number>-<linked enrollment name>`, the way
# a linked enrollment is named under its parent.
_LINKED_ENROLLMENT = re.compile(r"^(?P<parent_name>.+?)-(?P<parent>\d{5,})-(?P<child>.+)$")
_DIRECTORY_TTL = timedelta(hours=1)


class CustomerError(ValueError):
    pass


def group_key(account: dict, by_name: dict[str, dict]) -> str:
    """Accounts sharing a key are probably one customer: the same name (a
    renewal), or linked under the same parent enrollment."""
    name = account.get("display_name") or account["name"]
    linked = _LINKED_ENROLLMENT.match(name)
    if linked:
        parent = by_name.get(linked.group("parent"))
        name = parent["display_name"] if parent else linked.group("parent_name")
    return re.sub(r"\s+", " ", name).strip().lower()


class AccountDirectory:
    """The billing accounts this sign-in can see, asked of Azure at most hourly:
    Settings lists all of them, and the sync needs each one's term."""

    def __init__(self, list_accounts: Callable[[], list[dict]],
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._list_accounts = list_accounts
        self._now = now
        self._lock = threading.Lock()
        self._accounts: list[dict] | None = None
        self._fetched_at: datetime | None = None

    def accounts(self, fresh: bool = False) -> list[dict]:
        with self._lock:
            if fresh or self._accounts is None or self._now() - self._fetched_at > _DIRECTORY_TTL:
                listed = self._list_accounts()
                by_name = {account["name"]: account for account in listed}
                self._accounts = [{**account, "group_key": group_key(account, by_name)} for account in listed]
                self._fetched_at = self._now()
            return list(self._accounts)

    def by_name(self) -> dict[str, dict]:
        return {account["name"]: account for account in self.accounts()}


def _valid_day(value, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise CustomerError(f"{field} must be a date (YYYY-MM-DD)") from exc


def _valid_commitment(commitment: dict | None) -> dict | None:
    if not commitment or commitment.get("amount") in (None, ""):
        return None
    try:
        amount = float(commitment["amount"])
    except (TypeError, ValueError) as exc:
        raise CustomerError("the signed amount must be a number") from exc
    if amount <= 0:
        raise CustomerError("the signed amount must be above zero")
    kind = commitment.get("type") or "Other"
    if kind not in COMMITMENT_TYPES:
        raise CustomerError(f"commitment type must be one of {', '.join(COMMITMENT_TYPES)}")
    start = _valid_day(commitment.get("start"), "term start")
    end = _valid_day(commitment.get("end"), "term end")
    if not start or not end:
        raise CustomerError("a signed value needs its term start and end")
    if end <= start:
        raise CustomerError("the term must end after it starts")
    return {"type": kind, "amount": amount, "currency": (commitment.get("currency") or "USD").upper(),
            "start": start, "end": end, "note": (commitment.get("note") or "").strip(),
            # Marketplace burns a MACC; a credit lowers what was billed against it.
            "include_marketplace": bool(commitment.get("include_marketplace", True)),
            "subtract_credits": bool(commitment.get("subtract_credits", True))}


def _valid_scenario(settings: dict) -> dict:
    growth = settings.get("growth") or {}
    try:
        cleaned_growth = {name: float(growth.get(name, default))
                          for name, default in DEFAULT_SCENARIO["growth"].items()}
        uplift = float(settings.get("uplift_usd") or 0)
    except (TypeError, ValueError) as exc:
        raise CustomerError("growth rates and the uplift must be numbers") from exc
    if any(abs(rate) > 1 for rate in cleaned_growth.values()):
        raise CustomerError("a monthly growth rate is a fraction, e.g. 0.02 for 2%")
    active = settings.get("active") or "Base"
    if active not in DEFAULT_SCENARIO["growth"]:
        raise CustomerError("the active scenario must be Base, Upside or Downside")
    uplift_from = settings.get("uplift_from") or None
    if uplift_from and not re.fullmatch(r"\d{4}-\d{2}", uplift_from):
        raise CustomerError("the uplift starts from a month, YYYY-MM")
    return {"growth": cleaned_growth, "seasonality": bool(settings.get("seasonality", True)),
            "active": active, "uplift_usd": uplift, "uplift_from": uplift_from}


class CustomerBook:
    def __init__(self, store: ConsumptionStore, directory: AccountDirectory) -> None:
        self._store = store
        self._directory = directory

    def list(self) -> list[dict]:
        # Customers and their local data are readable without Azure; names and
        # terms simply go missing while the sign-in is.
        try:
            visible = self._directory.by_name()
        except Exception:
            visible = {}
        listed = []
        for customer in self._store.customers():
            accounts = []
            for name in customer["accounts"]:
                cached = self._store.account(name)
                known = visible.get(name) or {}
                accounts.append({"name": name, "display_name": known.get("display_name", name),
                                 "agreement_type": known.get("agreement_type"),
                                 "term_start": known.get("term_start"), "term_end": known.get("term_end"),
                                 "synced_at": cached.get("synced_at"), "errors": cached.get("errors") or {}})
            synced = [account["synced_at"] for account in accounts]
            listed.append({**customer, "accounts": accounts,
                           "synced_at": min(synced) if synced and all(synced) else None})
        return listed

    def save(self, customer_id: str | None, submitted: dict) -> dict:
        if not isinstance(submitted.get("name", ""), str):
            raise CustomerError("a customer's name is text")
        if not isinstance(submitted.get("accounts", []), list) or \
                not all(isinstance(account, str) for account in submitted.get("accounts", [])):
            raise CustomerError("accounts is a list of billing account numbers")
        name = (submitted.get("name") or "").strip()
        if not name:
            raise CustomerError("a customer needs a name")
        account_names = list(dict.fromkeys(submitted.get("accounts") or []))
        if not account_names:
            raise CustomerError("a customer needs at least one billing account")
        visible = self._directory.by_name()
        unknown = [account for account in account_names if account not in visible]
        if unknown:
            raise CustomerError(f"not a billing account this sign-in can see: {', '.join(unknown)}")
        customers = self._store.customers()
        if not customer_id:
            customer_id, taken = slug(name), {customer["id"] for customer in customers}
            while customer_id in taken:
                customer_id += "-2"
        existing = next((customer for customer in customers if customer["id"] == customer_id), {})
        saved = {"id": customer_id, "name": name, "accounts": account_names,
                 "commitment": _valid_commitment(submitted.get("commitment")),
                 # The Entities Customer hub this customer's Opportunity notes sit under.
                 "entity_customer": (submitted["entity_customer"] or None) if "entity_customer" in submitted
                 else existing.get("entity_customer"),
                 "scenario": existing.get("scenario")}
        replaced = [saved if customer["id"] == customer_id else customer for customer in customers]
        if not any(customer["id"] == customer_id for customer in customers):
            replaced.append(saved)
        self._store.save_customers(replaced)
        self._forget_unused_accounts(replaced)
        return saved

    def set_scenario(self, customer_id: str, settings: dict) -> dict:
        customers = self._store.customers()
        customer = next((candidate for candidate in customers if candidate["id"] == customer_id), None)
        if customer is None:
            raise CustomerError(f"no customer {customer_id!r}")
        customer["scenario"] = _valid_scenario(settings)
        self._store.save_customers(customers)
        return customer["scenario"]

    def delete(self, customer_id: str) -> None:
        customers = [customer for customer in self._store.customers() if customer["id"] != customer_id]
        self._store.save_customers(customers)
        self._forget_unused_accounts(customers)

    def _forget_unused_accounts(self, customers: list[dict]) -> None:
        self._store.forget_accounts_except({name for customer in customers for name in customer["accounts"]})
