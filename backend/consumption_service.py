"""Answering for a customer from local data. Nothing here calls Azure: the sync
is the only thing that does (`consumption_sync`)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from . import consumption_analysis, export_xlsx, finops, marketplace, months, pricing
from .consumption_store import ConsumptionStore
from .customers import CustomerBook
from .pipeline import Pipeline, PipelineUnavailable, by_month

# The weekly job keeps data at most a week old; past this the page says it is stale.
STALE_AFTER = timedelta(days=8)
# Who an analysis or a workbook is for: the operator, or the customer it is about.
VIEWS = ("account", "customer")
# The customer list's trend line: the last half-year of closed months.
RECENT_MONTHS = 6
# Running out this many months before the term ends is worth a renewal conversation.
EARLY_EXHAUSTION_MONTHS = 3


def _status(burn: dict | None, synced_at: str | None) -> str:
    if not synced_at:
        return "not-synced"
    if not burn:
        return "no-macc"
    if burn["remaining"] <= 0:
        return "consumed"
    if burn["projected_shortfall"] > 0:
        return "behind"
    exhaustion, end_month = burn["projected_exhaustion"], burn["end"][:7]
    if exhaustion and len(months.span(exhaustion, end_month)) - 1 >= EARLY_EXHAUSTION_MONTHS:
        return "early"
    return "on-track"


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
        self.prices = pricing.PriceBook(store.finops_state, store.save_finops_state, now)
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
        merged, currency = consumption_analysis.merge(entries, labels, self._not_eligible())
        return merged, currency, entries

    def _not_eligible(self) -> set[str]:
        return marketplace.not_eligible_keys(self._store.not_macc_eligible())

    def _period(self, first: str | None, last: str | None) -> tuple[str | None, str]:
        """The last twelve months unless asked otherwise; `first="start"` is everything
        synced, from the first month there is data for."""
        default_first, default_last = marketplace.default_period(self._today().strftime("%Y-%m"))
        if first == "start":
            return None, last or default_last
        return first or default_first, last or default_last

    def marketplace(self, customer_id: str, first: str | None = None, last: str | None = None) -> dict:
        """The customer's (a group's: with its affiliates') Marketplace solutions."""
        customer = self._customer(customer_id)
        accounts = {account["name"]: account for member in self._group(customer) for account in member["accounts"]}
        entries = {name: self._store.account(name) for name in accounts}
        labels = {name: f"{account['display_name']} ({name})" for name, account in accounts.items()}
        first, last = self._period(first, last)
        return {"customer": {"id": customer["id"], "name": customer["name"]},
                **marketplace.customer_report(entries, labels, self._not_eligible(), first, last)}

    def marketplace_across(self, first: str | None = None, last: str | None = None) -> dict:
        """Every partner solution across every customer, each enrollment counted once."""
        first, last = self._period(first, last)
        everyone = self._book.list()
        # Affiliates before parents, so an affiliate's enrollment is credited to the affiliate.
        ordered = sorted(everyone, key=lambda customer: 0 if customer.get("parent") else 1)
        customers = [(customer, {account["name"]: self._store.account(account["name"])
                                 for account in customer["accounts"]}) for customer in ordered]
        in_customers = {account["name"] for customer in everyone for account in customer["accounts"]}
        profiles = marketplace.profile_groups(self._store.profile_accounts(in_customers))
        return marketplace.across_customers(customers + profiles, self._not_eligible(), first, last)

    def not_macc_eligible(self) -> list[dict]:
        return self._store.not_macc_eligible()

    def set_macc_eligible(self, publisher: str, offer: str, eligible: bool) -> list[dict]:
        """Marks one offer as counting toward MACCs or not, for every customer."""
        if not publisher or not offer:
            raise ValueError("an offer is named by its publisher and its offer")
        current = [item for item in self._store.not_macc_eligible()
                   if (item["publisher"], item["offer"]) != (publisher, offer)]
        if not eligible:
            current.append({"publisher": publisher, "offer": offer})
        self._store.save_not_macc_eligible(current)
        return current

    def export_marketplace(self, first: str | None = None, last: str | None = None) -> tuple[str, bytes]:
        report = self.marketplace_across(first, last)
        workbook = export_xlsx.build_marketplace(report, self._today())
        return f"Azure Marketplace - all customers - {self._today().isoformat()}.xlsx", workbook

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
                          "currency": (record.get("commitment") or {}).get("currency"),
                          "entity_customer": record.get("entity_customer")}
        return {"parent": parent,
                "affiliates": [{"id": member["id"], "name": member["name"]} for member in members[1:]],
                "accounts": [{**account, "member": member["name"]} for member in members for account in member["accounts"]]}

    def analysis(self, customer_id: str, measure: dict | None = None, view: str = "account") -> dict:
        if view not in VIEWS:
            raise ValueError("view is account or customer")
        found = self._analysis(customer_id, measure)
        if view == "customer":
            # Left out on the server, so nothing the Customer view hides reaches the browser.
            return {**found, "scenarios": None, "customer": {**found["customer"], "scenario": None},
                    "customer_view": True}
        return found

    def _analysis(self, customer_id: str, measure: dict | None = None) -> dict:
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

    def _finops_of(self, customer: dict) -> dict:
        members = self._group(customer)
        merged, currency, entries = self._merged(customer)
        current_month = months.month_of(self._today())
        commitment = customer.get("commitment")
        trend = consumption_analysis.monthly_totals(merged, current_month,
                                                    consumption_analysis.commitment_measure(commitment or {}))
        outlook = consumption_analysis.forecast(trend, consumption_analysis.merge_forecasts(entries), self._today())
        this_month = next((row["cost"] for row in outlook["months"] if row["month"] == current_month), None)
        return {"customer": {"id": customer["id"], "name": customer["name"], "parent": customer.get("parent"),
                             "affiliates": [member["id"] for member in members[1:]],
                             # Where "Create opportunity" files a finding: the linked Customer note.
                             "entity_customer": customer.get("entity_customer")},
                # The Consumption API pads the currency code ("USD  ").
                "currency": (currency or "").strip() or None,
                **finops.analyse(entries, merged, trend, commitment, customer.get("budget_monthly"), this_month,
                                 self._today(), self.prices.discounts()),
                "pricing_region": self.prices.region()}

    def finops(self, customer_id: str) -> dict:
        """The FinOps findings for one customer (a group: with its affiliates). The
        Customer view shows the same findings: nothing here is internal."""
        return self._finops_of(self._customer(customer_id))

    def finops_across(self) -> list[dict]:
        """Every top-level customer's FinOps at a glance, the largest steady
        on-demand spend first -- where the savings conversations are."""
        everyone = self._book.list()
        rows = []
        for customer in everyone:
            if customer.get("parent"):
                continue
            found = self._finops_of(customer)
            latest = found["coverage"]["latest"]
            rows.append({"id": customer["id"], "name": customer["name"], "affiliates": found["customer"]["affiliates"],
                         "currency": found["currency"], "has_meters": found["has_meters"],
                         "coverage_pct": latest["coverage_pct"] if latest else None,
                         "on_demand": latest["on_demand"] if latest else None,
                         "coverage_month": latest["month"] if latest else None,
                         "candidates": len(found["candidates"]), "candidates_monthly": found["candidates_monthly"],
                         "top_candidate": found["candidates"][0]["meter"] if found["candidates"] else None,
                         "savings_monthly": found["savings_monthly"],
                         "budget": found["budget"]})
        return sorted(rows, key=lambda row: (-row["candidates_monthly"], row["name"].lower()))

    def finops_digest(self, top: int = 5) -> dict:
        """The week's FinOps in a few lines, for a Hermes job to send: who is over
        budget, and where the largest savings are. Text, not a page."""
        rows = self.finops_across()
        over = [row for row in rows if (row["budget"] or {}).get("status") in ("over", "forecast-over")]
        priced = sorted((row for row in rows if (row["savings_monthly"] or {}).get("ri_3y")),
                        key=lambda row: -row["savings_monthly"]["ri_3y"])

        def money(value: float) -> str:
            return f"${value / 1_000_000:.2f}M" if value >= 1_000_000 else f"${value / 1_000:.0f}k"

        lines = [f"Azure FinOps – week of {self._today().isoformat()}"]
        if priced:
            total = sum(row["savings_monthly"]["ri_3y"] for row in priced)
            lines += ["", f"Estimated savings on steady on-demand spend: {money(total)} a month on 3-year reservations."]
            lines += [f"• {row['name']}: {money(row['savings_monthly']['ri_3y'])}/mo "
                      f"({row['candidates']} meters, largest {row['top_candidate']})" for row in priced[:top]]
        if over:
            lines += ["", "Over budget:"]
            lines += [f"• {row['name']}: {money(row['budget']['last_month_actual'] or 0)} in {row['budget']['last_month']} "
                      f"against {money(row['budget']['amount'])}"
                      + (" (forecast over this month)" if row['budget']['status'] == "forecast-over" else "")
                      for row in over[:top]]
        if len(lines) == 1:
            lines += ["", "Nothing to flag this week."]
        return {"text": "\n".join(lines), "customers": len(rows), "over_budget": len(over), "with_savings": len(priced)}

    def meters_to_price(self) -> list[str]:
        """Every VM and GPU meter that is a steady candidate for some customer."""
        return sorted({candidate["meter"] for customer in self._book.list() if not customer.get("parent")
                       for candidate in self._finops_of(customer)["candidates"]
                       if candidate["family"] in finops.PRICED_FAMILIES})

    def refresh_prices(self, retail: pricing.RetailPrices | None = None) -> dict:
        """Prices every candidate meter not priced this month (Retail Prices API,
        no sign-in). Run by the sync after customers, or on demand."""
        return self.prices.refresh(retail or pricing.RetailPrices(), self.meters_to_price())

    def set_pricing_region(self, region: str) -> dict:
        """Where steady candidates are priced; existing prices for other regions stay."""
        region = region.strip().lower()
        if not re.fullmatch(r"[a-z0-9]{3,30}", region):
            raise ValueError("a region is an Azure region name, e.g. uaenorth")
        state = self._store.finops_state()
        state["pricing_region"] = region
        self._store.save_finops_state(state)
        return {"pricing_region": region}

    def portfolio(self) -> list[dict]:
        """Every customer at a glance -- burn, last month, recent trend, status -- for
        the customer list. A parent rolls up its affiliates, as its report does."""
        everyone = self._book.list()
        today = self._today()
        current_month = months.month_of(today)
        cached: dict[str, dict] = {}

        def entry(account: str) -> dict:
            if account not in cached:
                cached[account] = self._store.account(account)
            return cached[account]

        not_eligible = self._not_eligible()
        rows = []
        for customer in everyone:
            members = [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]]
            accounts = [account["name"] for member in members for account in member["accounts"]]
            merged, currency = consumption_analysis.merge({name: entry(name) for name in accounts},
                                                          None, not_eligible)
            commitment = customer.get("commitment")
            measure = consumption_analysis.commitment_measure(commitment or {})
            trend = consumption_analysis.monthly_totals(merged, current_month, measure)
            closed = [month for month in trend if not month["partial"]]
            burn = consumption_analysis.burn_down(commitment, trend, today) if commitment else None
            # A group whose affiliates are mid-sync still has something to show: its
            # oldest synced enrollment dates it, and the rest are counted.
            synced = [account["synced_at"] for member in members for account in member["accounts"]
                      if account.get("synced_at")]
            synced_at = min(synced) if synced else None
            rows.append({
                "id": customer["id"],
                "name": customer["name"],
                "parent": customer.get("parent"),
                "affiliates": [member["id"] for member in members[1:]],
                "enrollments": len(accounts),
                # The Consumption API pads the currency code ("USD  ").
                "currency": ((commitment or {}).get("currency") or currency or "").strip() or None,
                "signed": (commitment or {}).get("amount"),
                "allocated": round(sum((member.get("commitment") or {}).get("amount", 0.0) for member in members[1:]), 2)
                if len(members) > 1 else None,
                "burn": None if not burn else {key: burn[key] for key in (
                    "consumed", "remaining", "consumed_pct", "elapsed_pct", "projected_at_end",
                    "projected_shortfall", "projected_exhaustion", "end")},
                "last_month": closed[-1] if closed else None,
                "recent": [{"month": month["month"], "actual": month["actual"]} for month in closed[-RECENT_MONTHS:]],
                "status": _status(burn, synced_at),
                "synced_at": synced_at,
                "unsynced_enrollments": len(accounts) - len(synced),
                "stale": not synced_at or self._now() - datetime.fromisoformat(synced_at) > STALE_AFTER,
            })
        return rows

    def export(self, customer_id: str, measure: dict | None = None, view: str = "account") -> tuple[str, bytes]:
        """`(file name, .xlsx bytes)` for one customer. `view="customer"` is the workbook handed
        to the customer: everything but the forecast scenarios (operator, 2026-10-17)."""
        if view not in VIEWS:
            raise ValueError("view is account or customer")
        analysis = {**self.analysis(customer_id, measure), "finops": self.finops(customer_id)}
        if view == "customer":
            analysis = {**analysis, "customer_view": True, "scenarios": None}
        merged, _, entries = self._merged(analysis["customer"])
        # A parent's workbook covers its affiliates' enrollments too.
        exported = {**analysis["customer"], "accounts": analysis["group"]["accounts"]}
        analysis = {**analysis, "marketplace": self.marketplace(customer_id, "start", None)}
        workbook = export_xlsx.build(exported, analysis, merged, self._today(), entries)
        audience = " - for the customer" if view == "customer" else ""
        return f"Azure consumption - {analysis['customer']['name']}{audience} - {self._today().isoformat()}.xlsx", workbook

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
