"""A customer's pipeline: its Opportunity notes, through the Entities plugin.

The Entities plugin owns the `opportunity` Template and writes those notes; this
plugin only asks, through the `entities.opportunities` service (contract in
`PLAN.md`), at the moment it needs to -- plugins load in install order, so the
service may not exist yet at `register`. Without it the pipeline is simply
empty and says why; every other view works.
"""
from __future__ import annotations

SERVICE = "entities.opportunities"
# An opportunity that is still expected to land. Lost, disengaged and paused ones
# add nothing to a forecast.
COUNTED_STATUSES = {"Open", "Won"}


class PipelineUnavailable(RuntimeError):
    pass


class Pipeline:
    def __init__(self, api) -> None:
        self._api = api

    def _service(self):
        service = self._api.get_service(SERVICE)
        if service is None:
            raise PipelineUnavailable("The pipeline needs the Entities plugin (1.1 or later), which owns "
                                      "Opportunity notes. Install or update it to plan opportunities here.")
        return service

    def available(self) -> bool:
        return self._api.get_service(SERVICE) is not None

    def entity_customers(self) -> list[dict]:
        """The notes a customer can be linked to. Entities 1.5 adds Partners (and
        affiliates at any depth) through `hubs()`, each with a `kind`; before it,
        Customers only."""
        service = self._service()
        if hasattr(service, "hubs"):
            return list(service.hubs())
        return [{**customer, "kind": "customer"} for customer in service.customers()]

    def opportunities(self, customer: dict) -> list[dict]:
        if not customer.get("entity_customer"):
            return []
        return list(self._service().list_for_customer(customer["entity_customer"], include_affiliates=True))

    def create(self, customer: dict, owner_stem: str, title: str, fields: dict, plan: list[dict],
               sections: dict[str, str] | None = None) -> dict:
        if not customer.get("entity_customer"):
            raise ValueError("link this customer to its Customer note before adding opportunities")
        if not sections:
            return self._service().create(owner_stem, title, fields, plan)
        try:
            return self._service().create(owner_stem, title, fields, plan, sections)
        except TypeError as exc:
            # Entities before 1.14 writes no sections on create.
            raise PipelineUnavailable("Writing the opportunity's summary needs the Entities plugin 1.14 or later.") from exc

    def update(self, opportunity_id: str, fields: dict, plan: list[dict] | None) -> dict:
        return self._service().update(opportunity_id, fields, plan)

    def create_affiliate(self, customer_stem: str, name: str) -> dict:
        """An affiliate note under a Customer (Entities ≥ 1.2), for an affiliate the
        vault does not know yet -- Azure often has more of them than the vault."""
        if not name:
            raise ValueError("an affiliate needs a name")
        service = self._service()
        if not hasattr(service, "create_affiliate"):
            raise PipelineUnavailable("Creating an affiliate note needs the Entities plugin 1.2 or later.")
        return service.create_affiliate(customer_stem, name)


def by_month(opportunities: list[dict]) -> dict[str, float]:
    """The expected monthly $ of every opportunity still expected to land."""
    totals: dict[str, float] = {}
    for opportunity in opportunities:
        if opportunity.get("status") not in COUNTED_STATUSES:
            continue
        for row in opportunity.get("plan") or []:
            totals[row["month"]] = totals.get(row["month"], 0.0) + float(row.get("usd") or 0)
    return totals
