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

from . import subscription_groups
from .commitment_notes import CommitmentNotes
from .consumption_store import ConsumptionStore, slug
from .forecasting import DEFAULT_SCENARIO

COMMITMENT_TYPES = ("MACC", "EA commitment", "Azure Prepayment", "Other")

# `<parent display name>-<parent account number>-<linked enrollment name>`, the way
# a linked enrollment is named under its parent.
_LINKED_ENROLLMENT = re.compile(r"^(?P<parent_name>.+?)-(?P<parent>\d{5,})-(?P<child>.+)$")


def short_name(display_name: str) -> str:
    """A linked enrollment's own part: "<parent>-<number>-Masdar" reads "Masdar"."""
    linked = _LINKED_ENROLLMENT.match(display_name or "")
    return " ".join(linked.group("child").split()) if linked else display_name
_DIRECTORY_TTL = timedelta(hours=1)
_RETRY_AFTER_FAILURE = timedelta(minutes=5)


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
                try:
                    listed = self._list_accounts()
                except Exception:
                    # An hourly refresh that fails (throttled, `az` busy with the sync)
                    # keeps the last good list: emptying Settings would stop the operator
                    # from linking a customer until the next hour (operator, 2026-10-17).
                    if self._accounts is None:
                        raise
                    self._fetched_at = self._now() - _DIRECTORY_TTL + _RETRY_AFTER_FAILURE
                    return list(self._accounts)
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
            "subtract_credits": bool(commitment.get("subtract_credits", True)),
            # A parent's affiliates: "roll up" into this commitment, or each signed its "own".
            "affiliates": "own" if commitment.get("affiliates") == "own" else "roll up"}


def _valid_budget(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        budget = float(value)
    except (TypeError, ValueError) as exc:
        raise CustomerError("the monthly budget must be a number") from exc
    if budget <= 0:
        raise CustomerError("the monthly budget must be above zero")
    return budget


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
    def __init__(self, store: ConsumptionStore, directory: AccountDirectory,
                 notes: CommitmentNotes | None = None) -> None:
        self._store = store
        self._directory = directory
        self._notes = notes
        self._moved_to_notes = False

    def _notes_in_use(self) -> bool:
        return self._notes is not None and self._notes.available()

    def commitments_on_notes(self) -> bool:
        """Whether a linked customer's signed value is kept on its Customer note (Entities 1.3+)."""
        return self._notes_in_use()

    def _commitment_of(self, customer: dict) -> tuple[dict | None, str, str | None]:
        """`(commitment, where it lives, why it cannot be used)`. A linked customer's
        is its Customer note's, even when the note has none."""
        if not (customer.get("entity_customer") and self._notes_in_use()):
            return customer.get("commitment"), "settings", None
        if customer.get("commitment"):
            # Not moved to its note yet (see `_move_commitments_to_notes`): until it
            # is, the value held here is the one that counts.
            return customer["commitment"], "settings", None
        try:
            on_note = self._notes.read(customer["entity_customer"])
        except ValueError:
            return None, "note", f"The Customer note {customer['entity_customer']!r} was not found in the vault."
        if not on_note or not any(on_note.get(field) not in (None, "") for field in ("amount", "start", "end")):
            return None, "note", None
        try:
            return _valid_commitment(on_note), "note", None
        except CustomerError as exc:
            # Edited by hand in Obsidian and left incomplete: say so, count nothing.
            return None, "note", f"The signed value on the Customer note is incomplete: {exc}."

    def _move_commitments_to_notes(self) -> None:
        """Once per run: a linked customer's signed value still held here moves to
        its Customer note -- unless the note already has one, which wins."""
        if self._moved_to_notes or not self._notes_in_use():
            return
        customers = self._store.customers()
        changed = left_behind = False
        for customer in customers:
            if not (customer.get("entity_customer") and customer.get("commitment")):
                continue
            try:
                if not self._notes.read(customer["entity_customer"]):
                    self._notes.write(customer["entity_customer"], customer["commitment"])
            except ValueError:
                # Its note is gone, refuses it, or is not indexed yet -- right after
                # a restart the vault index is empty and every note reads as
                # missing. The value stays here and the move is tried again.
                left_behind = True
                continue
            customer["commitment"] = None
            changed = True
        if changed:
            self._store.save_customers(customers)
        self._moved_to_notes = not left_behind

    def records(self) -> list[dict]:
        """The stored customers as they are -- accounts by number -- with each one's
        signed value from wherever it lives."""
        self._move_commitments_to_notes()
        return [{**customer, "commitment": self._commitment_of(customer)[0]} for customer in self._store.customers()]

    def list(self) -> list[dict]:
        self._move_commitments_to_notes()
        # Customers and their local data are readable without Azure; names and
        # terms simply go missing while the sign-in is.
        try:
            visible = self._directory.by_name()
        except Exception:
            visible = {}
        listed = []
        for customer in self._store.customers():
            commitment, source, problem = self._commitment_of(customer)
            customer = {**customer, "commitment": commitment, "commitment_source": source,
                        "commitment_problem": problem}
            accounts = []
            for name in customer["accounts"]:
                cached = self._store.account_status(name)
                known = visible.get(name) or {}
                accounts.append({"name": name, "display_name": known.get("display_name", name),
                                 "agreement_type": known.get("agreement_type"),
                                 "term_start": known.get("term_start"), "term_end": known.get("term_end"),
                                 "synced_at": cached.get("synced_at"), "errors": cached.get("errors") or {}})
            synced = [account["synced_at"] for account in accounts]
            listed.append({**customer, "accounts": accounts, "parent": customer.get("parent"),
                           "synced_at": min(synced) if synced and all(synced) else None})
        for customer in listed:
            customer["affiliates"] = [other["id"] for other in listed if other["parent"] == customer["id"]]
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
        parent = (submitted.get("parent") or None) if "parent" in submitted else existing.get("parent")
        self._check_parent(customer_id, parent, customers)
        commitment = _valid_commitment(submitted.get("commitment"))
        # The Entities Customer hub this customer's Opportunity notes sit under.
        entity_customer = (submitted["entity_customer"] or None) if "entity_customer" in submitted \
            else existing.get("entity_customer")
        on_note = bool(entity_customer and self._notes_in_use())
        newly_linked = on_note and entity_customer != existing.get("entity_customer")
        try:
            if newly_linked and self._notes.read(entity_customer):
                # Linking to a note that already says what was signed: the note wins.
                commitment = self._commitment_of({"entity_customer": entity_customer})[0]
            elif on_note:
                # Written first: if the note refuses it, nothing is saved here either.
                self._notes.write(entity_customer, commitment)
        except ValueError as exc:
            raise CustomerError(f"the Customer note did not take the signed value: {exc}") from exc
        saved = {"id": customer_id, "name": name, "accounts": account_names,
                 "commitment": None if on_note else commitment,
                 # Overrides the FinOps budget, which is otherwise the MACC spread over its term.
                 "budget_monthly": _valid_budget(submitted["budget_monthly"]) if "budget_monthly" in submitted
                 else existing.get("budget_monthly"),
                 "entity_customer": entity_customer,
                 # The group this customer is an affiliate of: its MACC is carved out of the parent's.
                 "parent": parent,
                 "scenario": existing.get("scenario"),
                 "subscription_groups": existing.get("subscription_groups") or []}
        replaced = [saved if customer["id"] == customer_id else customer for customer in customers]
        if not any(customer["id"] == customer_id for customer in customers):
            replaced.append(saved)
        self._store.save_customers(replaced)
        self._forget_unused_accounts(replaced)
        return {**saved, "commitment": commitment, "commitment_source": "note" if on_note else "settings"}

    def set_scenario(self, customer_id: str, settings: dict) -> dict:
        customers = self._store.customers()
        customer = next((candidate for candidate in customers if candidate["id"] == customer_id), None)
        if customer is None:
            raise CustomerError(f"no customer {customer_id!r}")
        customer["scenario"] = _valid_scenario(settings)
        self._store.save_customers(customers)
        return customer["scenario"]

    def set_subscription_groups(self, customer_id: str, groups) -> list[dict]:
        customers = self._store.customers()
        customer = next((candidate for candidate in customers if candidate["id"] == customer_id), None)
        if customer is None:
            raise CustomerError(f"no customer {customer_id!r}")
        customer["subscription_groups"] = subscription_groups.validated(groups)
        self._store.save_customers(customers)
        return customer["subscription_groups"]

    @staticmethod
    def _check_parent(customer_id: str, parent: str | None, customers: list[dict]) -> None:
        """Groups are one level deep: a parent is a top-level customer, and a
        customer with affiliates of its own cannot become someone's affiliate."""
        if not parent:
            return
        if parent == customer_id:
            raise CustomerError("a customer cannot be its own parent")
        parent_record = next((customer for customer in customers if customer["id"] == parent), None)
        if parent_record is None:
            raise CustomerError(f"no customer {parent!r} to be part of")
        if parent_record.get("parent"):
            raise CustomerError(f"{parent_record['name']} is itself an affiliate; groups are one level deep")
        if any(customer.get("parent") == customer_id for customer in customers):
            raise CustomerError("this customer has affiliates of its own, so it cannot be an affiliate")

    def delete(self, customer_id: str) -> None:
        if any(customer.get("parent") == customer_id for customer in self._store.customers()):
            raise CustomerError("remove its affiliates, or move them to another parent, first")
        customers = [customer for customer in self._store.customers() if customer["id"] != customer_id]
        self._store.save_customers(customers)
        self._forget_unused_accounts(customers)

    def _forget_unused_accounts(self, customers: list[dict]) -> None:
        self._store.forget_accounts_except({name for customer in customers for name in customer["accounts"]})
