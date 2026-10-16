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

    def _merged(self, customer: dict) -> tuple[dict, str | None, dict[str, dict]]:
        entries = {account["name"]: self._store.account(account["name"]) for account in customer["accounts"]}
        labels = {account["name"]: f"{account['display_name']} ({account['name']})"
                  for account in customer["accounts"]}
        merged, currency = consumption_analysis.merge(entries, labels)
        return merged, currency, entries

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

    def analysis(self, customer_id: str, measure: dict | None = None) -> dict:
        customer = self._customer(customer_id)
        merged, currency, entries = self._merged(customer)
        synced_at = customer.get("synced_at")
        pipeline = self.pipeline(customer_id)
        return {
            "customer": customer,
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
        workbook = export_xlsx.build(analysis["customer"], analysis, merged, self._today(), entries)
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
