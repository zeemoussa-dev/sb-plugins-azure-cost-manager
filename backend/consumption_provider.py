"""`azure-cost-manager.consumption`: a Customer note's own monthly consumption,
for plugins that bill on it (Core42 Insight, 2026-10-18).

Read-only and local: a page load asks it, so it never calls Azure. A parent's
figures are its own enrollments only -- Insight rolls affiliates up itself,
since each affiliate has its own terms. The forecast is the run rate the MACC
burn-down uses (the average of the last three closed months), carried to the
MACC term's end, or to the year's end without one, so the two never disagree.
"""
from __future__ import annotations

from urllib.parse import urlencode

from . import consumption_analysis, months
from .consumption_service import ConsumptionService
from .customers import CustomerBook

SERVICE = "azure-cost-manager.consumption"
REPORT_PATH = "/azure-cost-manager/report"


def _route(customer_id: str) -> str:
    return f"{REPORT_PATH}?{urlencode({'report': 'Overview', 'customer': customer_id})}"


class ConsumptionProvider:
    def __init__(self, service: ConsumptionService, book: CustomerBook, today=None) -> None:
        self._service = service
        self._book = book
        self._today = today or service._today

    @staticmethod
    def _speakers(everyone: list[dict]) -> dict[str, dict]:
        """Per Customer note, the customer that speaks for it: with two on one note,
        the top-level one, as in `for_entity`."""
        speakers: dict[str, dict] = {}
        for customer in sorted(everyone, key=lambda c: (bool(c.get("parent")), c["name"].lower())):
            if customer.get("entity_customer"):
                speakers.setdefault(customer["entity_customer"], customer)
        return speakers

    def _speaker(self, customer_stem: str) -> dict | None:
        return self._speakers(self._book.list()).get(customer_stem)

    def linked(self) -> list[dict]:
        """Every customer here linked to a Customer note."""
        everyone = self._book.list()
        speakers = self._speakers(everyone)
        notes = {customer["id"]: customer.get("entity_customer") for customer in everyone}
        rows = []
        for customer in everyone:
            stem = customer.get("entity_customer")
            if not stem or speakers[stem]["id"] != customer["id"]:
                continue
            commitment = customer.get("commitment") or {}
            rows.append({"customer_stem": stem, "name": customer["name"],
                         "parent_stem": notes.get(customer.get("parent")) if customer.get("parent") else None,
                         "currency": (commitment.get("currency") or "USD").strip() or "USD",
                         "route": _route(customer["id"])})
        return sorted(rows, key=lambda row: row["name"].lower())

    def monthly(self, customer_stem: str, include_marketplace: bool = True,
                subtract_credits: bool = True) -> dict | None:
        customer = self._speaker(customer_stem)
        if customer is None:
            return None
        measure = {"marketplace": bool(include_marketplace), "credits": bool(subtract_credits)}
        trend, currency, commitment = self._service.own_monthly(customer["id"], measure)
        today = self._today()
        current = months.month_of(today)
        rate = consumption_analysis.run_rate(trend)
        until = commitment["end"][:7] if commitment else f"{today.year:04d}-12"
        forecast = [{"month": month, "total": rate} for month in months.span(current, until)] if rate is not None else []
        return {
            "currency": currency or "USD",
            "months": [{"month": row["month"], "usage": row["usage"], "marketplace": row["marketplace"],
                        "credits": row["credits"], "total": row["actual"], "closed": not row["partial"]}
                       for row in trend],
            "forecast": forecast,
            "commitment": {key: commitment[key] for key in ("amount", "start", "end")} if commitment else None,
            "route": _route(customer["id"]),
        }
