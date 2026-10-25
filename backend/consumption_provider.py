"""`azure-cost-manager.consumption`: a Customer note's own monthly consumption,
for plugins that bill on it (Core42 Insight, 2026-10-18).

Read-only and local: a page load asks it, so it never calls Azure. A parent's
figures are its own enrollments only -- Insight rolls affiliates up itself,
since each affiliate has its own terms. The forecast is the run rate the MACC
burn-down uses (the average of the last three closed months), carried to the
MACC term's end, or to the year's end without one, so the two never disagree.
"""
from __future__ import annotations

import time
from urllib.parse import urlencode

from . import consumption_analysis, months
from .consumption_service import ConsumptionService
from .customers import CustomerBook

SERVICE = "azure-cost-manager.consumption"
REPORT_PATH = "/azure-cost-manager/report"
LIST_REUSED_FOR = 10.0


def _route(customer_id: str) -> str:
    return f"{REPORT_PATH}?{urlencode({'report': 'Overview', 'customer': customer_id})}"


class ConsumptionProvider:
    def __init__(self, service: ConsumptionService, book: CustomerBook, today=None,
                 clock=time.monotonic) -> None:
        self._service = service
        self._book = book
        self._today = today or service._today
        self._clock = clock
        self._listed: tuple[float, list[dict]] | None = None

    def _everyone(self) -> list[dict]:
        """The customer list, reused for a few seconds: Insight asks for every
        customer's months in one go, and listing customers per call made a 99-
        customer page cost a hundred listings (2026-10-18)."""
        if self._listed is None or self._clock() - self._listed[0] > LIST_REUSED_FOR:
            self._listed = (self._clock(), self._book.list())
        return self._listed[1]

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
        return self._speakers(self._everyone()).get(customer_stem)

    def linked(self) -> list[dict]:
        """Every customer here linked to a Customer note."""
        everyone = self._everyone()
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

    def customers(self) -> list[dict]:
        """Every customer here, linked to a note or not -- a parent's terms can cover
        affiliates that have no note of their own (Insight, 2026-10-18)."""
        everyone = self._everyone()
        return sorted(({"id": customer["id"], "name": customer["name"], "parent_id": customer.get("parent"),
                        "customer_stem": customer.get("entity_customer") or None,
                        "currency": ((customer.get("commitment") or {}).get("currency") or "USD").strip() or "USD",
                        # Whether this parent's affiliates roll up into its MACC or signed their own.
                        "affiliates": "own" if not consumption_analysis.affiliates_roll_up(customer.get("commitment"))
                        else "roll up",
                        "route": _route(customer["id"])} for customer in everyone),
                      key=lambda row: row["name"].lower())

    def monthly_of(self, customer_id: str, include_marketplace: bool | str = True,
                   subtract_credits: bool = True) -> dict | None:
        """`monthly()` for a customer named by its id here; None for an unknown id."""
        customer = next((listed for listed in self._everyone() if listed["id"] == customer_id), None)
        return self._monthly(customer, include_marketplace, subtract_credits) if customer else None

    def monthly(self, customer_stem: str, include_marketplace: bool | str = True,
                subtract_credits: bool = True) -> dict | None:
        customer = self._speaker(customer_stem)
        return self._monthly(customer, include_marketplace, subtract_credits) if customer else None

    def _monthly(self, customer: dict, include_marketplace: bool | str, subtract_credits: bool) -> dict:
        """`include_marketplace="core42"` counts only Core42's own Marketplace offers, so
        `total` is Core42's revenue; every month also carries `core42_revenue` beside it."""
        marketplace = "core42" if include_marketplace == "core42" else bool(include_marketplace)
        measure = {"marketplace": marketplace, "credits": bool(subtract_credits)}
        trend, currency, commitment = self._service.own_monthly(customer, measure)
        today = self._today()
        current = months.month_of(today)
        until = commitment["end"][:7] if commitment else f"{today.year:04d}-12"
        # The plugin's one forecast (`consumption_analysis.forecast`), as the Overview shows it.
        projected = self._service.standard_forecast(trend, self._service.own_entries(customer), until)
        forecast = [{"month": month, "total": cost} for month, cost in projected.items()]
        return {
            "currency": currency or "USD",
            "months": [{"month": row["month"], "usage": row["usage"], "marketplace": row["marketplace"],
                        "credits": row["credits"], "total": row["actual"], "closed": not row["partial"],
                        "core42_marketplace": row["marketplace_core42"], "core42_revenue": row["core42_revenue"]}
                       for row in trend],
            "forecast": forecast,
            "commitment": {key: commitment[key] for key in ("amount", "start", "end")} if commitment else None,
            "route": _route(customer["id"]),
        }
