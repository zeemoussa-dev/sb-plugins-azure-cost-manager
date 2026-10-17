"""Answering for a customer from local data. Nothing here calls Azure: the sync
is the only thing that does (`consumption_sync`)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable

from . import consumption_analysis, export_xlsx
from .consumption_store import ConsumptionStore
from .customers import CustomerBook
from .pipeline import Pipeline, PipelineUnavailable, by_month

# The weekly job keeps data at most a week old; past this the page says it is stale.
STALE_AFTER = timedelta(days=8)


class CustomerNotFound(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConsumptionService:
    def __init__(self, store: ConsumptionStore, book: CustomerBook,
                 today: Callable[[], date] = date.today, now: Callable[[], datetime] = _now,
                 pipeline: Pipeline | None = None) -> None:
        self._store = store
        self._book = book
        self._pipeline = pipeline
        self._today = today
        self._now = now

    def customer(self, customer_id: str) -> dict:
        return self._customer(customer_id)

    def _customer(self, customer_id: str) -> dict:
        customer = next((listed for listed in self._book.list() if listed["id"] == customer_id), None)
        if customer is None:
            raise CustomerNotFound(f"no customer {customer_id!r}")
        return customer

    def _group(self, customer: dict) -> list[dict]:
        """The customer and, for a parent, its affiliates: everything its MACC covers."""
        affiliates = [listed for listed in self._book.list() if listed.get("parent") == customer["id"]]
        return [customer] + affiliates

    def _merged(self, customer: dict, rolled_up: bool = True) -> tuple[dict, str | None, dict[str, dict]]:
        accounts = {account["name"]: account for member in (self._group(customer) if rolled_up else [customer])
                    for account in member["accounts"]}
        entries = {name: self._store.account(name) for name in accounts}
        labels = {name: f"{account['display_name']} ({name})" for name, account in accounts.items()}
        merged, currency = consumption_analysis.merge(entries, labels)
        return merged, currency, entries

    def _allocations(self, parent: dict, affiliates: list[dict]) -> dict | None:
        """How the parent's MACC is carved up: each affiliate against its own MACC,
        and the unallocated rest against the parent's own enrollments."""
        commitment = parent.get("commitment")
        if not affiliates:
            return None
        current_month = self._today().strftime("%Y-%m")

        def burn_of(member: dict, signed: dict | None) -> tuple[dict | None, float]:
            merged, _, _ = self._merged(member, rolled_up=False)
            measure = consumption_analysis.commitment_measure(signed or commitment or {})
            trend = consumption_analysis.monthly_totals(merged, current_month, measure)
            burn = consumption_analysis.burn_down(signed, trend, self._today()) if signed else None
            within = trend
            if commitment:
                first, last = commitment["start"][:7], commitment["end"][:7]
                within = [month for month in trend if first <= month["month"] <= last]
            return burn, round(sum(month["actual"] for month in within), 2)

        rows = []
        for affiliate in affiliates:
            burn, against_parent = burn_of(affiliate, affiliate.get("commitment"))
            rows.append({"id": affiliate["id"], "name": affiliate["name"], "commitment": affiliate.get("commitment"),
                         "burn": burn, "consumed_against_parent": against_parent})
        allocated = sum((row["commitment"] or {}).get("amount", 0.0) for row in rows)
        _, own_consumed = burn_of(parent, None)
        amount = (commitment or {}).get("amount")
        unallocated = None if amount is None else amount - allocated
        return {
            "parent_amount": amount,
            "allocated": round(allocated, 2),
            "unallocated": None if unallocated is None else round(unallocated, 2),
            "over_allocated": bool(amount is not None and allocated > amount),
            "own": {"consumed": own_consumed,
                    "remaining": None if unallocated is None else round(unallocated - own_consumed, 2)},
            "affiliates": rows,
            "consumed_total": round(own_consumed + sum(row["consumed_against_parent"] for row in rows), 2),
        }

    def pipeline(self, customer_id: str) -> dict:
        """The customer's opportunities and what they add by month, or why there are none."""
        customer = self._customer(customer_id)
        if self._pipeline is None:
            return {"available": False, "reason": "no pipeline source", "opportunities": [], "by_month": {}}
        try:
            opportunities = self._pipeline.opportunities(customer)
        except PipelineUnavailable as exc:
            return {"available": False, "reason": str(exc), "opportunities": [], "by_month": {}}
        reason = None if customer.get("entity_customer") else \
            "Link this customer to its Customer note to see and plan its opportunities."
        return {"available": True, "reason": reason, "linked": bool(customer.get("entity_customer")),
                "opportunities": opportunities, "by_month": by_month(opportunities)}

    def _group_info(self, customer: dict, members: list[dict]) -> dict:
        parent = None
        if customer.get("parent"):
            record = next((listed for listed in self._book.list() if listed["id"] == customer["parent"]), None)
            if record:
                parent = {"id": record["id"], "name": record["name"],
                          "amount": (record.get("commitment") or {}).get("amount"),
                          "currency": (record.get("commitment") or {}).get("currency")}
        return {"parent": parent,
                "affiliates": [{"id": member["id"], "name": member["name"]} for member in members[1:]],
                "accounts": [{**account, "member": member["name"]} for member in members for account in member["accounts"]]}

    def analysis(self, customer_id: str, measure: dict | None = None) -> dict:
        customer = self._customer(customer_id)
        members = self._group(customer)
        merged, currency, entries = self._merged(customer)
        synced = [account["synced_at"] for member in members for account in member["accounts"]]
        synced_at = min(synced) if synced and all(synced) else None
        pipeline = self.pipeline(customer_id)
        return {
            "customer": customer,
            "group": self._group_info(customer, members),
            "allocations": self._allocations(customer, members[1:]),
            "synced_at": synced_at,
            "stale": not synced_at or self._now() - datetime.fromisoformat(synced_at) > STALE_AFTER,
            "errors": {account: entry.get("errors") for account, entry in entries.items() if entry.get("errors")},
            "pipeline": pipeline,
            **consumption_analysis.analyse(merged, currency, customer.get("commitment"),
                                           consumption_analysis.merge_forecasts(entries), self._today(),
                                           measure=measure, scenario=customer.get("scenario"),
                                           pipeline=pipeline["by_month"]),
        }

    def export(self, customer_id: str, measure: dict | None = None) -> tuple[str, bytes]:
        """`(file name, .xlsx bytes)` for one customer."""
        analysis = self.analysis(customer_id, measure)
        merged, _, entries = self._merged(analysis["customer"])
        # A parent's workbook covers its affiliates' enrollments too.
        exported = {**analysis["customer"], "accounts": analysis["group"]["accounts"]}
        workbook = export_xlsx.build(exported, analysis, merged, self._today(), entries)
        return f"Azure consumption - {analysis['customer']['name']} - {self._today().isoformat()}.xlsx", workbook

    def consumption(self, customer_id: str, first_month: str | None, last_month: str | None,
                    group_by: str, cost_kind: str) -> dict:
        """Spend per month per `service`, `subscription` or `account` (enrollment)."""
        if group_by not in ("service", "subscription", "account"):
            raise ValueError("group must be 'service', 'subscription' or 'account'")
        if cost_kind not in consumption_analysis.COST_KINDS:
            raise ValueError("cost must be 'actual' or 'amortized'")
        merged, _, _ = self._merged(self._customer(customer_id))
        rows = []
        for month in sorted(merged):
            if (first_month and month < first_month) or (last_month and month > last_month):
                continue
            spend = merged[month][cost_kind][group_by]
            rows.extend({"month": month, "name": name, "cost": round(cost, 2)}
                        for name, cost in sorted(spend.items(), key=lambda item: -item[1]))
        return {"customer": customer_id, "group": group_by, "cost": cost_kind, "rows": rows}
