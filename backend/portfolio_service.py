"""`azure-cost-manager.portfolio`: what this plugin knows about one Customer note,
for other plugins to show (Entities' customer page, 2026-10-17).

Read-only and local: a page load asks it, so it never calls Azure. Other plugins
get it with `api.get_service` at call time and treat None as "not installed".
"""
from __future__ import annotations

from urllib.parse import urlencode

from .consumption_service import ConsumptionService
from .customers import CustomerBook

SERVICE = "azure-cost-manager.portfolio"
REPORT_PATH = "/azure-cost-manager/report"


class PortfolioService:
    def __init__(self, service: ConsumptionService, book: CustomerBook) -> None:
        self._service = service
        self._book = book

    def for_entity(self, customer_stem: str) -> dict | None:
        """The portfolio row of the customer linked to `customer_stem` (a Customer or
        affiliate note's stem) -- burn, last month, trend, status -- plus `route`, its
        page here. None when no customer here is linked to that note."""
        linked = [customer for customer in self._book.list() if customer.get("entity_customer") == customer_stem]
        if not linked:
            return None
        # Two customers on one note: the top-level one speaks for the note.
        customer = min(linked, key=lambda candidate: (bool(candidate.get("parent")), candidate["name"].lower()))
        rows = self._service.portfolio(only=customer["id"])
        if not rows:
            return None
        return {**rows[0], "route": f"{REPORT_PATH}?{urlencode({'report': 'Overview', 'customer': customer['id']})}"}
